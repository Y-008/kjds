from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .action_policies import ActionPolicyRegistry


class WritePathRegistryError(ValueError):
    """Raised when a governed write path is missing or contradicts policy."""


class WritePathRegistry:
    """Machine-readable inventory of every implemented or closed L1-L4 action."""

    def __init__(
        self,
        registry_path: str | Path | None = None,
        *,
        action_policies: ActionPolicyRegistry | None = None,
    ) -> None:
        self.registry_path = Path(registry_path) if registry_path else self._default_path()
        self.action_policies = action_policies or ActionPolicyRegistry()
        self.registry = self._load()
        self._paths = self._validate(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "write_path_registry.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WritePathRegistryError(
                f"Unable to load write-path registry: {self.registry_path}"
            ) from exc
        if not isinstance(value, dict) or value.get("status") != "active":
            raise WritePathRegistryError("Write-path registry must be an active object")
        return value

    def _validate(self, registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
        governed = {
            item["id"]: item
            for item in self.action_policies.snapshot()["actions"]
            if item["risk_tier"] != "L0"
        }
        paths: dict[str, dict[str, Any]] = {}
        for item in registry.get("actions", []):
            action_id = str(item.get("action_id", "")).strip()
            if not action_id or action_id in paths:
                raise WritePathRegistryError("Write-path action ids must be present and unique")
            policy = governed.get(action_id)
            if policy is None:
                raise WritePathRegistryError(f"Write path has no L1-L4 policy: {action_id}")
            if item.get("risk_tier") != policy["risk_tier"]:
                raise WritePathRegistryError(f"Write-path risk tier drifted: {action_id}")
            for key in ("request_revalidation", "execution_revalidation"):
                if item.get(key) is not policy[key]:
                    raise WritePathRegistryError(f"Write-path policy drifted: {action_id}.{key}")
            if item.get("limit_keys") != policy["limit_keys"]:
                raise WritePathRegistryError(f"Write-path limits drifted: {action_id}")

            availability = item.get("availability")
            if availability not in {"enabled", "policy_only"}:
                raise WritePathRegistryError(f"Unknown write-path availability: {action_id}")
            if availability == "enabled":
                for key in ("request_entries", "formal_fact_writes", "audit_codes"):
                    if not isinstance(item.get(key), list) or not item[key]:
                        raise WritePathRegistryError(f"Enabled write path requires {key}: {action_id}")
                if not item.get("service_entry"):
                    raise WritePathRegistryError(f"Enabled write path requires a service entry: {action_id}")
                if policy["idempotency_required"] and not item.get("idempotency"):
                    raise WritePathRegistryError(f"Write path requires idempotency: {action_id}")
                if policy["readback_required"] and not item.get("readback"):
                    raise WritePathRegistryError(f"Write path requires readback: {action_id}")
                if policy["external_business_side_effect"] and not item.get("external_calls"):
                    raise WritePathRegistryError(f"External action has no declared call: {action_id}")
            elif not item.get("activation_blocker"):
                raise WritePathRegistryError(f"Policy-only path needs an activation blocker: {action_id}")

            if policy["risk_tier"] in {"L3", "L4"}:
                if item.get("single_use_permit") is not True:
                    raise WritePathRegistryError(f"High-risk path requires a single-use permit: {action_id}")
                if availability == "enabled" and item.get("delivery", {}).get("kind") != "lease_worker":
                    raise WritePathRegistryError(f"High-risk path requires a lease worker: {action_id}")
            paths[action_id] = item

        if set(paths) != set(governed):
            missing = sorted(set(governed) - set(paths))
            extra = sorted(set(paths) - set(governed))
            raise WritePathRegistryError(
                f"Write-path registry must exactly cover L1-L4 actions; missing={missing}, extra={extra}"
            )
        return paths

    def get(self, action_id: str) -> dict[str, Any]:
        try:
            return json.loads(json.dumps(self._paths[action_id]))
        except KeyError as exc:
            raise WritePathRegistryError(f"Unknown write path: {action_id}") from exc

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.registry))


def validate_repository_write_paths(root: Path) -> None:
    """Fail CI when execution adapters or outbound HTTP escape the registry."""
    registry = WritePathRegistry()
    snapshot = registry.snapshot()
    adapters = _literal_assignment(
        root / "apps" / "control_plane" / "execution_plans.py",
        "ADAPTERS",
    )
    for adapter_id, adapter in adapters.items():
        path = registry.get(str(adapter["action_id"]))
        if adapter.get("live_execution_supported"):
            if path["availability"] != "enabled":
                raise WritePathRegistryError(
                    f"Live adapter maps to a closed write path: {adapter_id}"
                )
            if path["delivery"]["kind"] != "lease_worker":
                raise WritePathRegistryError(
                    f"Live adapter bypasses the lease-worker boundary: {adapter_id}"
                )

    allowed_http = set(snapshot["outbound_http_modules"])
    actual_http: set[str] = set()
    for source in (root / "apps" / "control_plane").rglob("*.py"):
        module = source.relative_to(root).as_posix()
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        if any(_is_http_import(node) for node in ast.walk(tree)):
            actual_http.add(module)
    if actual_http != allowed_http:
        raise WritePathRegistryError(
            "Outbound HTTP modules drifted; "
            f"undeclared={sorted(actual_http - allowed_http)}, stale={sorted(allowed_http - actual_http)}"
        )

    python_sources = list((root / "apps").rglob("*.py"))
    for boundary in snapshot["exclusive_external_literals"]:
        literal = boundary["literal"]
        allowed = set(boundary["allowed_modules"])
        matches = {
            source.relative_to(root).as_posix()
            for source in python_sources
            if literal in source.read_text(encoding="utf-8")
        }
        if not matches or not matches <= allowed:
            raise WritePathRegistryError(
                f"External call boundary drifted for {literal}; matches={sorted(matches)}"
            )


def _literal_assignment(path: Path, name: str) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                return value
    raise WritePathRegistryError(f"Literal assignment not found: {path}:{name}")


def _is_http_import(node: ast.AST) -> bool:
    clients = {"httpx", "requests", "aiohttp", "urllib.request", "http.client"}
    if isinstance(node, ast.Import):
        return any(alias.name in clients for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        if node.module in clients:
            return True
        if node.module in {"urllib", "http"}:
            return any(f"{node.module}.{alias.name}" in clients for alias in node.names)
    return False
