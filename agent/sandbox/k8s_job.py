from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class K8sSandboxResources:
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "128Mi"
    memory_limit: str = "512Mi"

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": {"cpu": self.cpu_request, "memory": self.memory_request},
            "limits": {"cpu": self.cpu_limit, "memory": self.memory_limit},
        }


@dataclass(slots=True)
class K8sSandboxSpec:
    namespace: str = "agent-sandbox"
    image: str = "python:3.12-slim"
    service_account_name: str = "agent-sandbox-runner"
    ttl_seconds_after_finished: int = 600
    active_deadline_seconds: int = 300
    backoff_limit: int = 0
    network: str = "none"
    resources: K8sSandboxResources = field(default_factory=K8sSandboxResources)
    labels: dict[str, str] = field(default_factory=lambda: {"app.kubernetes.io/part-of": "software-production-agent"})

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["resources"] = self.resources.to_dict()
        return data


def stable_job_name(action_name: str, command: str, *, prefix: str = "agent-sandbox") -> str:
    token = hashlib.sha1(f"{action_name}:{command}".encode("utf-8")).hexdigest()[:10]
    base = re.sub(r"[^a-z0-9-]+", "-", prefix.lower()).strip("-") or "agent-sandbox"
    return f"{base}-{token}"[:63].rstrip("-")


def render_sandbox_job_manifest(
    action_obj: dict[str, Any],
    *,
    spec: K8sSandboxSpec | None = None,
    job_name: str = "",
) -> dict[str, Any]:
    sandbox_spec = spec or K8sSandboxSpec()
    action_name = str(action_obj.get("action", "run_command"))
    args = action_obj.get("args") if isinstance(action_obj.get("args"), dict) else {}
    command = str(args.get("command", "python -V") or "python -V")
    name = job_name or stable_job_name(action_name, command)
    labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/component": "sandbox-job",
        **sandbox_spec.labels,
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": sandbox_spec.namespace, "labels": labels},
        "spec": {
            "backoffLimit": sandbox_spec.backoff_limit,
            "ttlSecondsAfterFinished": sandbox_spec.ttl_seconds_after_finished,
            "activeDeadlineSeconds": sandbox_spec.active_deadline_seconds,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": sandbox_spec.service_account_name,
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "fsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "sandbox",
                            "image": sandbox_spec.image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["/bin/sh", "-lc"],
                            "args": [command],
                            "workingDir": "/workspace",
                            "env": [
                                {"name": "AGENT_SANDBOX", "value": "true"},
                                {"name": "AGENT_ACTION", "value": action_name},
                            ],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": sandbox_spec.resources.to_dict(),
                            "volumeMounts": [
                                {"name": "workspace", "mountPath": "/workspace"},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "workspace", "emptyDir": {"sizeLimit": "512Mi"}},
                        {"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}},
                    ],
                },
            },
        },
    }


def render_default_deny_network_policy(namespace: str = "agent-sandbox", *, name: str = "sandbox-default-deny") -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/component": "sandbox-job"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [],
        },
    }


def render_sandbox_bundle(action_obj: dict[str, Any], *, spec: K8sSandboxSpec | None = None) -> list[dict[str, Any]]:
    sandbox_spec = spec or K8sSandboxSpec()
    docs: list[dict[str, Any]] = [render_sandbox_job_manifest(action_obj, spec=sandbox_spec)]
    if sandbox_spec.network == "none":
        docs.append(render_default_deny_network_policy(sandbox_spec.namespace))
    return docs


def manifest_to_jsonl(docs: list[dict[str, Any]]) -> str:
    return "\n---\n".join(json.dumps(doc, ensure_ascii=False, indent=2) for doc in docs) + "\n"
