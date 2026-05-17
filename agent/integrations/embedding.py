"""Third-party embedded integration fabric.

The module models external systems as typed, auditable integration manifests.
It does not call vendor APIs. Instead it produces the embed, bridge, permission
and artifact-mapping plan that the platform UI or gateway can enforce.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, urlparse


DEFAULT_SANDBOX = (
    "allow-forms",
    "allow-popups",
    "allow-popups-to-escape-sandbox",
    "allow-same-origin",
    "allow-scripts",
)

BRIDGE_PARENT_TO_CHILD = (
    "host.context.sync",
    "host.selection.request",
    "host.action.result",
    "host.theme.update",
    "host.token.refresh.request",
)

BRIDGE_CHILD_TO_PARENT = (
    "selection.changed",
    "asset.export.requested",
    "action.invoke",
    "event.emit",
    "handoff.create",
)


@dataclass(frozen=True)
class IntegrationManifest:
    id: str
    label: str
    vendor: str
    category: str
    description: str
    homepage: str
    allowed_origins: tuple[str, ...]
    surfaces: tuple[str, ...]
    capabilities: tuple[str, ...]
    required_scopes: tuple[str, ...]
    secret_env: tuple[str, ...]
    events: tuple[str, ...]
    risk_level: str
    data_policy: str
    embed_url_template: str = ""
    deep_link_template: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in (
            "allowed_origins",
            "surfaces",
            "capabilities",
            "required_scopes",
            "secret_env",
            "events",
        ):
            out[key] = list(out[key])
        return out


INTEGRATION_CATALOG: dict[str, IntegrationManifest] = {
    "figma": IntegrationManifest(
        id="figma",
        label="Figma Design Surface",
        vendor="Figma",
        category="design",
        description="Embed design files, capture frame selections and turn design context into frontend tasks.",
        homepage="https://www.figma.com",
        allowed_origins=("https://www.figma.com", "https://figma.com"),
        surfaces=("embed_panel", "resource_picker", "action_bridge", "webhook_event_source", "asset_sync"),
        capabilities=(
            "design_embed",
            "frame_selection",
            "component_inventory",
            "design_token_handoff",
            "comment_context",
            "asset_reference",
        ),
        required_scopes=("files:read", "file_comments:read"),
        secret_env=("FIGMA_ACCESS_TOKEN",),
        events=("selection.changed", "asset.export.requested", "comment.created", "handoff.create"),
        risk_level="medium",
        data_policy="Design metadata and selected asset references are stored; raw private file content stays vendor-side unless explicitly exported.",
        embed_url_template="https://www.figma.com/embed?embed_host=software-production-agent&url={resource_url}",
        deep_link_template="{resource_url}",
    ),
    "github": IntegrationManifest(
        id="github",
        label="GitHub Development Surface",
        vendor="GitHub",
        category="code",
        description="Embed repository, issue and pull-request context for code review, crawler input and solution publishing.",
        homepage="https://github.com",
        allowed_origins=("https://github.com",),
        surfaces=("resource_picker", "action_bridge", "webhook_event_source", "asset_sync"),
        capabilities=(
            "repo_reference",
            "issue_reference",
            "pull_request_reference",
            "code_asset_handoff",
            "webhook_event_ingest",
        ),
        required_scopes=("repo:read", "issues:read", "pull_requests:read"),
        secret_env=("GITHUB_TOKEN",),
        events=("pull_request.opened", "issue.updated", "repository.selected", "handoff.create"),
        risk_level="medium",
        data_policy="Only selected repository references and explicit asset snapshots are imported into local solution or training stores.",
        deep_link_template="{resource_url}",
    ),
    "notion": IntegrationManifest(
        id="notion",
        label="Notion Knowledge Surface",
        vendor="Notion",
        category="knowledge",
        description="Attach product docs, meeting notes and knowledge pages as RAG-ready references.",
        homepage="https://www.notion.so",
        allowed_origins=("https://www.notion.so", "https://notion.so"),
        surfaces=("resource_picker", "action_bridge", "webhook_event_source", "asset_sync"),
        capabilities=("page_reference", "database_reference", "knowledge_card_handoff", "rag_source_sync"),
        required_scopes=("read_content",),
        secret_env=("NOTION_TOKEN",),
        events=("page.updated", "database.selected", "handoff.create"),
        risk_level="medium",
        data_policy="Imported pages are converted into cited knowledge cards with source, owner and sync timestamp.",
        deep_link_template="{resource_url}",
    ),
    "linear": IntegrationManifest(
        id="linear",
        label="Linear Work Surface",
        vendor="Linear",
        category="work",
        description="Bind issues, milestones and delivery state into workflow dry-runs and evidence ledgers.",
        homepage="https://linear.app",
        allowed_origins=("https://linear.app",),
        surfaces=("resource_picker", "action_bridge", "webhook_event_source"),
        capabilities=("issue_reference", "project_reference", "workflow_state_sync", "evidence_event"),
        required_scopes=("read",),
        secret_env=("LINEAR_API_KEY",),
        events=("issue.updated", "project.updated", "handoff.create"),
        risk_level="low",
        data_policy="Issue metadata is stored as delivery evidence; comments and attachments require explicit selection.",
        deep_link_template="{resource_url}",
    ),
    "slack": IntegrationManifest(
        id="slack",
        label="Slack Collaboration Surface",
        vendor="Slack",
        category="collaboration",
        description="Ingest selected discussion context and emit agent handoff notifications.",
        homepage="https://slack.com",
        allowed_origins=("https://app.slack.com", "https://slack.com"),
        surfaces=("resource_picker", "action_bridge", "webhook_event_source"),
        capabilities=("thread_reference", "notification_handoff", "decision_log_capture"),
        required_scopes=("channels:history", "chat:write"),
        secret_env=("SLACK_BOT_TOKEN",),
        events=("thread.selected", "message.action", "handoff.create"),
        risk_level="medium",
        data_policy="Only user-selected threads are copied into evidence or RAG stores; channel-wide sync is disabled by default.",
        deep_link_template="{resource_url}",
    ),
}


def list_integration_catalog(category: str = "") -> dict[str, Any]:
    category_key = category.strip().lower()
    manifests = [
        manifest.to_dict()
        for manifest in INTEGRATION_CATALOG.values()
        if not category_key or manifest.category.lower() == category_key
    ]
    return {
        "schema": "integration_catalog.v1",
        "count": len(manifests),
        "category_filter": category,
        "surfaces": [
            "embed_panel",
            "resource_picker",
            "action_bridge",
            "webhook_event_source",
            "asset_sync",
        ],
        "bridge_schema": "integration_bridge_message.v1",
        "integrations": sorted(manifests, key=lambda row: str(row["id"])),
    }


def build_integration_embed_plan(
    integration_id: str,
    *,
    resource_url: str = "",
    mode: str = "embed_panel",
    workspace_context: str = "",
    requested_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    key = integration_id.strip().lower()
    manifest = INTEGRATION_CATALOG.get(key)
    if manifest is None:
        return _blocked_plan(
            integration_id=integration_id,
            resource_url=resource_url,
            mode=mode,
            reason="unknown_integration",
            remediation="Call integration_catalog first and choose a registered integration id.",
        )

    normalized_mode = (mode or "embed_panel").strip()
    checks = _validate_request(manifest, resource_url, normalized_mode, requested_capabilities)
    embeddable = not checks["blocking_reasons"]
    iframe_url = _build_surface_url(manifest, resource_url, normalized_mode) if embeddable else ""
    deep_link_url = _build_deep_link_url(manifest, resource_url) if embeddable else ""
    selected_capabilities = tuple(requested_capabilities) or manifest.capabilities

    return {
        "schema": "integration_embed_plan.v1",
        "integration": manifest.to_dict(),
        "request": {
            "integration_id": integration_id,
            "resource_url": resource_url,
            "mode": normalized_mode,
            "workspace_context": workspace_context,
            "requested_capabilities": list(requested_capabilities),
        },
        "surface": {
            "mode": normalized_mode,
            "iframe_url": iframe_url,
            "deep_link_url": deep_link_url,
            "sandbox": list(DEFAULT_SANDBOX),
            "allowed_origins": list(manifest.allowed_origins),
            "csp": {
                "frame-src": list(manifest.allowed_origins),
                "connect-src": list(manifest.allowed_origins),
            },
        },
        "bridge_contract": _bridge_contract(manifest),
        "permissions": {
            "required_scopes": list(manifest.required_scopes),
            "secret_env": list(manifest.secret_env),
            "risk_level": manifest.risk_level,
            "requires_user_consent": bool(manifest.required_scopes or manifest.secret_env),
            "data_policy": manifest.data_policy,
        },
        "artifact_mapping": _artifact_mapping(manifest, selected_capabilities),
        "admission": {
            "embeddable": embeddable,
            "reasons": checks["blocking_reasons"],
            "warnings": checks["warnings"],
            "remediation": checks["remediation"],
        },
    }


def _validate_request(
    manifest: IntegrationManifest,
    resource_url: str,
    mode: str,
    requested_capabilities: tuple[str, ...],
) -> dict[str, list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    remediation: list[str] = []

    if mode not in manifest.surfaces:
        blocking.append("unsupported_surface")
        remediation.append(f"Use one of: {', '.join(manifest.surfaces)}.")

    if resource_url:
        url_check = _validate_resource_url(resource_url, manifest.allowed_origins)
        if url_check:
            blocking.append(url_check)
            remediation.append("Use an HTTPS URL from the integration's allowed origins.")
    elif mode == "embed_panel":
        blocking.append("resource_url_required")
        remediation.append("Provide a concrete resource_url before opening an iframe embed panel.")
    else:
        warnings.append("resource_url_not_bound")

    unsupported = sorted(set(requested_capabilities) - set(manifest.capabilities))
    if unsupported:
        blocking.append("unsupported_capability")
        remediation.append(f"Remove unsupported capabilities: {', '.join(unsupported)}.")

    return {"blocking_reasons": blocking, "warnings": warnings, "remediation": remediation}


def _validate_resource_url(resource_url: str, allowed_origins: tuple[str, ...]) -> str:
    parsed = urlparse(resource_url)
    if parsed.scheme not in {"http", "https"}:
        return "blocked_url_scheme"
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return "blocked_url_scheme"
    if not parsed.netloc:
        return "invalid_resource_url"
    origin = _origin(parsed)
    if origin not in {item.lower() for item in allowed_origins}:
        return "origin_not_allowed"
    return ""


def _origin(parsed: Any) -> str:
    port = f":{parsed.port}" if parsed.port else ""
    host = (parsed.hostname or "").lower()
    return f"{parsed.scheme.lower()}://{host}{port}"


def _build_surface_url(manifest: IntegrationManifest, resource_url: str, mode: str) -> str:
    if mode == "embed_panel" and manifest.embed_url_template:
        encoded = quote(resource_url, safe="")
        return manifest.embed_url_template.format(resource_url=encoded)
    return _build_deep_link_url(manifest, resource_url)


def _build_deep_link_url(manifest: IntegrationManifest, resource_url: str) -> str:
    if resource_url:
        template = manifest.deep_link_template or "{resource_url}"
        return template.format(resource_url=resource_url)
    return manifest.homepage


def _bridge_contract(manifest: IntegrationManifest) -> dict[str, Any]:
    child_events = [event for event in BRIDGE_CHILD_TO_PARENT if event in manifest.events or event == "handoff.create"]
    if "action_bridge" in manifest.surfaces and "action.invoke" not in child_events:
        child_events.append("action.invoke")
    if "webhook_event_source" in manifest.surfaces and "event.emit" not in child_events:
        child_events.append("event.emit")
    return {
        "schema": "integration_bridge_contract.v1",
        "message_envelope": {
            "schema": "integration_bridge_message.v1",
            "integration_id": manifest.id,
            "event": "<event_name>",
            "payload": {},
            "nonce": "<host-issued-nonce>",
            "correlation_id": "<trace-id>",
        },
        "parent_to_child": list(BRIDGE_PARENT_TO_CHILD),
        "child_to_parent": child_events,
        "audit_events": [
            "integration.embed.opened",
            "integration.bridge.message_accepted",
            "integration.bridge.message_rejected",
            "integration.asset.handoff_created",
        ],
        "idempotency": "Every action.invoke payload must carry idempotency_key and host-issued nonce.",
    }


def _artifact_mapping(manifest: IntegrationManifest, capabilities: tuple[str, ...]) -> dict[str, Any]:
    mappings: list[dict[str, str]] = []
    if "design_token_handoff" in capabilities:
        mappings.append({"external": "design_tokens", "internal": "frontend_style_spec"})
    if "frame_selection" in capabilities or "asset_reference" in capabilities:
        mappings.append({"external": "selected_frame", "internal": "design_asset_ref"})
    if "repo_reference" in capabilities or "code_asset_handoff" in capabilities:
        mappings.append({"external": "repository_snapshot", "internal": "github_crawl_profile_input"})
    if "knowledge_card_handoff" in capabilities or "rag_source_sync" in capabilities:
        mappings.append({"external": "knowledge_page", "internal": "rag_knowledge_card"})
    if "issue_reference" in capabilities or "workflow_state_sync" in capabilities:
        mappings.append({"external": "work_item", "internal": "workflow_evidence"})
    if not mappings:
        mappings.append({"external": "selected_resource", "internal": "solution_asset_reference"})
    return {
        "schema": "integration_artifact_mapping.v1",
        "integration_id": manifest.id,
        "pipeline": [
            "external_selection",
            "bridge_validation",
            "evidence_ledger",
            "solution_or_training_store",
        ],
        "mappings": mappings,
    }


def _blocked_plan(
    *,
    integration_id: str,
    resource_url: str,
    mode: str,
    reason: str,
    remediation: str,
) -> dict[str, Any]:
    return {
        "schema": "integration_embed_plan.v1",
        "integration": None,
        "request": {
            "integration_id": integration_id,
            "resource_url": resource_url,
            "mode": mode,
            "workspace_context": "",
            "requested_capabilities": [],
        },
        "surface": {
            "mode": mode,
            "iframe_url": "",
            "deep_link_url": "",
            "sandbox": list(DEFAULT_SANDBOX),
            "allowed_origins": [],
            "csp": {"frame-src": [], "connect-src": []},
        },
        "bridge_contract": {"schema": "integration_bridge_contract.v1", "message_envelope": {}},
        "permissions": {
            "required_scopes": [],
            "secret_env": [],
            "risk_level": "unknown",
            "requires_user_consent": True,
            "data_policy": "No data movement is allowed until the integration is registered.",
        },
        "artifact_mapping": {
            "schema": "integration_artifact_mapping.v1",
            "integration_id": integration_id,
            "pipeline": [],
            "mappings": [],
        },
        "admission": {
            "embeddable": False,
            "reasons": [reason],
            "warnings": [],
            "remediation": [remediation],
        },
    }
