from __future__ import annotations

import json
from typing import Any

from agent.context_pv.schema import ContextPVPlan, ContextPVPolicy, PV_TIERS


def _labels(plan: ContextPVPlan) -> dict[str, str]:
    return {
        "app.kubernetes.io/part-of": "software-production-agent",
        "app.kubernetes.io/component": "context-pv",
        "context.agent/tenant": plan.policy.tenant,
        "context.agent/manifest": plan.manifest.manifest_id,
    }


def _storage_class(tier: str, policy: ContextPVPolicy) -> dict[str, Any]:
    return {
        "apiVersion": "storage.k8s.io/v1",
        "kind": "StorageClass",
        "metadata": {"name": policy.storage_classes[tier]},
        # Placeholder CSI provisioner. Real deployments should replace this
        # with local-path, Longhorn, Ceph RBD, EBS, OSS/S3 CSI, etc.
        "provisioner": f"context-pv.example.com/{tier}",
        "allowVolumeExpansion": True,
        "reclaimPolicy": "Retain",
        "volumeBindingMode": "WaitForFirstConsumer",
        "parameters": {
            "tier": tier,
            "encrypted": str(policy.encryption_required).lower(),
        },
    }


def _pvc(name: str, tier: str, policy: ContextPVPolicy, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": name, "namespace": policy.namespace, "labels": {**labels, "context.agent/tier": tier}},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": policy.storage_classes[tier],
            "resources": {"requests": {"storage": policy.pvc_capacity[tier]}},
        },
    }


def render_context_pv_bundle(plan: ContextPVPlan, *, include_storage_classes: bool = True) -> list[dict[str, Any]]:
    policy = plan.policy.normalized()
    labels = _labels(plan)
    docs: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": policy.namespace, "labels": {"context.agent/tenant": policy.tenant}},
        },
        {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "context-pv-quota", "namespace": policy.namespace},
            "spec": {
                "hard": {
                    "requests.storage": policy.quota_storage_limit,
                    "limits.cpu": policy.quota_cpu_limit,
                    "limits.memory": policy.quota_memory_limit,
                    "persistentvolumeclaims": str(sum(policy.pvc_count_per_tier.values()) + 2),
                }
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": "context-pv-loader", "namespace": policy.namespace, "labels": labels},
            "automountServiceAccountToken": False,
        },
    ]
    if include_storage_classes:
        docs.extend(_storage_class(tier, policy) for tier in PV_TIERS)

    planned_pvcs: dict[str, str] = {}
    for placement in plan.manifest.placements:
        planned_pvcs.setdefault(placement.pvc_name, placement.pv_tier)
        for replica_name in placement.replica_pvc_names:
            planned_pvcs.setdefault(replica_name, "hot" if "-hot-" in replica_name else placement.pv_tier)
    for name, tier in sorted(planned_pvcs.items()):
        docs.append(_pvc(name, tier, policy, labels))

    docs.append(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "context-pv-index", "namespace": policy.namespace, "labels": labels},
            "data": {
                "manifest.json": json.dumps(plan.manifest.to_dict(include_text=False), ensure_ascii=False, indent=2),
                "load-plan.json": json.dumps(plan.load_plan, ensure_ascii=False, indent=2),
            },
        }
    )
    docs.append(
        {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "context-pv-loader", "namespace": policy.namespace, "labels": labels},
            "spec": {
                "backoffLimit": 1,
                "ttlSecondsAfterFinished": 1800,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "serviceAccountName": "context-pv-loader",
                        "automountServiceAccountToken": False,
                        "restartPolicy": "Never",
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 10001,
                            "runAsGroup": 10001,
                            "fsGroup": 10001,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "initContainers": [
                            {
                                "name": "verify-manifest",
                                "image": "python:3.12-slim",
                                "command": ["python", "-c"],
                                "args": [
                                    "import json, pathlib; "
                                    "p=pathlib.Path('/index/manifest.json'); "
                                    "m=json.loads(p.read_text()); "
                                    "assert m['merkle_root']; "
                                    "print('manifest', m['manifest_id'], 'ok')"
                                ],
                                "volumeMounts": [{"name": "index", "mountPath": "/index"}],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            }
                        ],
                        "containers": [
                            {
                                "name": "loader",
                                "image": "python:3.12-slim",
                                "command": ["/bin/sh", "-lc"],
                                "args": [
                                    "echo loading context slices with WAL/checksum discipline; "
                                    "cat /index/load-plan.json | head -c 1024"
                                ],
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                },
                                "volumeMounts": [{"name": "index", "mountPath": "/index"}],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            },
                            {
                                "name": "slice-metrics-sidecar",
                                "image": "python:3.12-slim",
                                "command": ["/bin/sh", "-lc"],
                                "args": [
                                    "echo context_pv_loader_sidecar=1; "
                                    "echo expose Prometheus counters in real deployment; "
                                    "sleep 1"
                                ],
                                "resources": {
                                    "requests": {"cpu": "25m", "memory": "32Mi"},
                                    "limits": {"cpu": "100m", "memory": "64Mi"},
                                },
                                "volumeMounts": [{"name": "index", "mountPath": "/index"}],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            },
                        ],
                        "volumes": [{"name": "index", "configMap": {"name": "context-pv-index"}}],
                    },
                },
            },
        }
    )
    docs.append(
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "context-pv-default-deny", "namespace": policy.namespace},
            "spec": {
                "podSelector": {"matchLabels": {"app.kubernetes.io/component": "context-pv"}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],
                "egress": [],
            },
        }
    )
    return docs


def manifest_to_jsonl(docs: list[dict[str, Any]]) -> str:
    return "\n---\n".join(json.dumps(doc, ensure_ascii=False, indent=2) for doc in docs) + "\n"
