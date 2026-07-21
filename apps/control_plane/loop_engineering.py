from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

LOOP_MODULES = (
    "automations",
    "skills",
    "integrations",
    "subagents",
    "worktrees",
    "memory",
)
LoopModule = Literal[
    "automations",
    "skills",
    "integrations",
    "subagents",
    "worktrees",
    "memory",
]
LoopMode = Literal["proposal", "shadow", "active"]


class LoopRegistryError(ValueError):
    """Raised when the machine-readable loop registry is invalid."""


@dataclass(frozen=True, slots=True)
class LoopValidation:
    module: str
    mode: str
    status: str
    missing_controls: tuple[str, ...]
    required_controls: tuple[str, ...]
    promotion_gate: str
    allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "mode": self.mode,
            "status": self.status,
            "missing_controls": list(self.missing_controls),
            "required_controls": list(self.required_controls),
            "promotion_gate": self.promotion_gate,
            "allowed": self.allowed,
        }


class LoopEngineeringService:
    """Loads and validates the six-module loop contract without side effects.

    This is deliberately a pure control-plane boundary. It does not execute a
    task or promote a skill; it only makes the preconditions explicit so that
    workers, API routes, and future schedulers cannot invent their own gates.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        configured = registry_path or os.getenv("KJDS_LOOP_REGISTRY_PATH")
        self.registry_path = Path(configured) if configured else self._default_path()
        self.registry = self._load()
        self._modules = self._index_modules(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "loop_engineering_registry.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopRegistryError(f"Unable to load loop registry: {self.registry_path}") from exc
        if not isinstance(registry, dict) or registry.get("status") != "active":
            raise LoopRegistryError("Loop registry must be an active object")
        if tuple(item.get("id") for item in registry.get("modules", [])) != LOOP_MODULES:
            raise LoopRegistryError("Loop registry must define the six modules in canonical order")
        if not isinstance(registry.get("loop_contract"), list) or not registry["loop_contract"]:
            raise LoopRegistryError("Loop registry must define a non-empty loop contract")
        return registry

    @staticmethod
    def _index_modules(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for item in registry["modules"]:
            controls = item.get("required_controls")
            if (
                not isinstance(controls, list)
                or not controls
                or any(not str(control).strip() for control in controls)
            ):
                raise LoopRegistryError(f"Module {item.get('id')} must define required controls")
            if item.get("state") not in {"partial", "design_only", "process_only", "ready"}:
                raise LoopRegistryError(f"Module {item.get('id')} has an unknown state")
            indexed[item["id"]] = item
        return indexed

    def registry_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.registry, ensure_ascii=False))

    def validate(
        self,
        *,
        module: str,
        mode: LoopMode,
        controls: dict[str, Any],
    ) -> LoopValidation:
        if module not in self._modules:
            raise LoopRegistryError(f"Unknown loop module: {module}")
        if mode not in {"proposal", "shadow", "active"}:
            raise LoopRegistryError(f"Unknown loop mode: {mode}")
        if not isinstance(controls, dict):
            raise LoopRegistryError("Loop controls must be an object")
        definition = self._modules[module]
        required = tuple(str(item) for item in definition["required_controls"])
        missing = tuple(
            control
            for control in required
            if control not in controls or not self._provided(controls[control])
        )
        state = str(definition["state"])
        if missing:
            status = "missing_controls"
        elif mode == "active" and state != "ready":
            status = "promotion_gate_required"
        elif mode == "shadow":
            status = "shadow_ready"
        else:
            status = "proposal_ready"
        return LoopValidation(
            module=module,
            mode=mode,
            status=status,
            missing_controls=missing,
            required_controls=required,
            promotion_gate=str(definition["promotion_gate"]),
            allowed=not missing and not (mode == "active" and state != "ready"),
        )

    @staticmethod
    def _provided(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True
