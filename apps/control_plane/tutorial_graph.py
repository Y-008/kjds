"""Governed deterministic TutorialGraph compilation (BAS-187 first slice).

Compiles software feature nodes into a deterministic, masked TutorialGraph and
a synthetic capture manifest. Real Windows desktop capture (``windows_agent``)
is not admitted in this slice: the workspace never performs external capture,
credential capture, or external writes, and never grants listing eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

TUTORIAL_CONTRACT = "kjds-tutorial-graph-v1"
TUTORIAL_VERSION = "1.0.0"
CAPTURE_CONTRACT = "kjds-tutorial-capture-manifest-v1"
CAPTURE_VERSION = "1.0.0"

INTERNAL_TUTORIAL_PROVIDER = "kjds_internal_tutorial_compiler"
WINDOWS_AGENT_PROVIDER = "windows_agent"

WINDOWS_CAPTURE_ADMITTED = False

ALLOWED_OPERATIONS = frozenset({"click", "type", "navigate", "observe", "screenshot", "scroll"})

SENSITIVE_REGION_LABELS = frozenset({"credential_input", "browser_profile", "local_storage", "payment_input"})

SAFE_OUTCOME_STATUSES = frozenset({"COMPILED", "PROPOSAL_ONLY", "BLOCKED", "INVALIDATED", "STALE"})

READBACK_STATES = frozenset({"PENDING", "VERIFIED", "INVALIDATED", "STALE"})

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

SECRET_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "sk-",
)


class TutorialGraphError(ValueError):
    """The tutorial compile input or provider contract is invalid or blocked."""


@dataclass(frozen=True)
class TutorialProviderDescriptor:
    provider: str
    connector_ref: str
    binding_sha256: str
    protocol_version: str
    capabilities: frozenset[str]
    deterministic: bool
    external_call: bool
    credential_required: bool
    admitted: bool


@dataclass(frozen=True)
class TutorialStep:
    step_id: str
    feature_id: str
    operation: str
    ui_anchor: str
    narration: str
    screenshot_placeholder: str
    sensitive_regions: tuple[str, ...]
    masked_regions: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class TutorialGraphOutcome:
    status: str
    reason_code: str
    tutorial_graph_version: str
    capture_manifest_sha256: str
    capture_admitted: bool
    external_write_allowed: bool
    listing_eligible: bool
    steps: tuple[TutorialStep, ...]


@dataclass(frozen=True)
class TutorialReadback:
    step_id: str
    feature_id: str
    operation: str
    screenshot_placeholder: str
    readback_state: str
    integrity_ok: bool


def _text(value: Any, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value:
        raise TutorialGraphError(f"{name}_invalid")
    if len(value) > maximum:
        raise TutorialGraphError(f"{name}_too_long")
    return value


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise TutorialGraphError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise TutorialGraphError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_VALUE_MARKERS):
            raise TutorialGraphError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TutorialGraphError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise TutorialGraphError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class TutorialLecture:
    language: str
    content: str
    lecture_sha256: str
    step_count: int


class GovernedTutorialGraphWorkspace:
    """Deterministic, masked tutorial graph compiler for BAS-187."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self.internal_compiler = self._admit_internal_compiler()
        self.windows_agent = self._admit_windows_agent()

    def _admit_internal_compiler(self) -> TutorialProviderDescriptor:
        return TutorialProviderDescriptor(
            provider=INTERNAL_TUTORIAL_PROVIDER,
            connector_ref="internal://tutorial-graph-compiler-v1",
            binding_sha256=_hash(
                {
                    "provider": INTERNAL_TUTORIAL_PROVIDER,
                    "protocol": "kjds-internal-tutorial-compiler/1",
                }
            ),
            protocol_version="kjds-internal-tutorial-compiler/1",
            capabilities=frozenset({"tutorial_graph", "structured_output"}),
            deterministic=True,
            external_call=False,
            credential_required=False,
            admitted=True,
        )

    def _admit_windows_agent(self) -> TutorialProviderDescriptor:
        return TutorialProviderDescriptor(
            provider=WINDOWS_AGENT_PROVIDER,
            connector_ref="windows://desktop-agent-v1",
            binding_sha256=_hash({"provider": WINDOWS_AGENT_PROVIDER, "protocol": "kjds-windows-agent/1"}),
            protocol_version="kjds-windows-agent/1",
            capabilities=frozenset({"windows_capture"}),
            deterministic=False,
            external_call=True,
            credential_required=False,
            admitted=WINDOWS_CAPTURE_ADMITTED,
        )

    def _validate_nodes(self, feature_nodes: Any) -> list[dict[str, Any]]:
        if not isinstance(feature_nodes, list) or not feature_nodes:
            raise TutorialGraphError("feature_nodes_invalid")
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in feature_nodes:
            if not isinstance(raw, Mapping):
                raise TutorialGraphError("feature_node_invalid")
            node_id = _text(raw.get("id"), "node_id", maximum=120)
            if node_id in seen:
                raise TutorialGraphError("duplicate_node_id")
            seen.add(node_id)
            _text(raw.get("label"), "node_label", maximum=300)
            operation = _text(raw.get("operation"), "operation", maximum=40)
            if operation not in ALLOWED_OPERATIONS:
                raise TutorialGraphError("operation_not_allowed")
            _text(raw.get("ui_anchor"), "ui_anchor", maximum=500)
            _text(raw.get("narration"), "narration", maximum=1000)
            sensitive_regions = raw.get("sensitive_regions", [])
            if not isinstance(sensitive_regions, list):
                raise TutorialGraphError("sensitive_regions_invalid")
            normalized_regions: list[str] = []
            for region in sensitive_regions:
                text = _text(region, "sensitive_region", maximum=80)
                if text not in SENSITIVE_REGION_LABELS:
                    raise TutorialGraphError("sensitive_region_not_recognized")
                if text not in normalized_regions:
                    normalized_regions.append(text)
            depends_on = raw.get("depends_on", [])
            if not isinstance(depends_on, list):
                raise TutorialGraphError("depends_on_invalid")
            normalized_deps: list[str] = []
            for dep in depends_on:
                text = _text(dep, "depends_on", maximum=120)
                if text not in normalized_deps:
                    normalized_deps.append(text)
            nodes.append(
                {
                    "id": node_id,
                    "label": raw["label"],
                    "operation": operation,
                    "ui_anchor": raw["ui_anchor"],
                    "narration": raw["narration"],
                    "sensitive_regions": normalized_regions,
                    "depends_on": normalized_deps,
                }
            )
        return nodes

    def _topological_order(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {node["id"]: node for node in nodes}
        indegree = {node["id"]: 0 for node in nodes}
        children: dict[str, list[str]] = {node["id"]: [] for node in nodes}
        for node in nodes:
            for dep in node["depends_on"]:
                if dep == node["id"]:
                    raise TutorialGraphError("self_dependency")
                if dep not in by_id:
                    raise TutorialGraphError("dependency_unknown")
                children[dep].append(node["id"])
                indegree[node["id"]] += 1
        available = sorted(nid for nid, degree in indegree.items() if degree == 0)
        order: list[dict[str, Any]] = []
        while available:
            nid = available.pop(0)
            order.append(by_id[nid])
            for child in sorted(children[nid]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    available.append(child)
                    available.sort()
        if len(order) != len(nodes):
            raise TutorialGraphError("dependency_cycle")
        return order

    def _build_steps(
        self,
        nodes: list[dict[str, Any]],
        capture_policy: Mapping[str, Any],
    ) -> tuple[list[TutorialStep], list[dict[str, Any]]]:
        mask_by_default = capture_policy.get("mask_by_default")
        if not isinstance(mask_by_default, bool):
            raise TutorialGraphError("capture_policy_mask_by_default_invalid")
        max_steps = capture_policy.get("max_steps")
        if max_steps is not None and (not isinstance(max_steps, int) or max_steps < 1):
            raise TutorialGraphError("capture_policy_max_steps_invalid")
        if max_steps is not None and len(nodes) > max_steps:
            raise TutorialGraphError("capture_policy_step_budget_exceeded")
        steps: list[TutorialStep] = []
        manifest_steps: list[dict[str, Any]] = []
        for node in nodes:
            sensitive = tuple(sorted(node["sensitive_regions"]))
            if sensitive and not mask_by_default:
                raise TutorialGraphError("sensitive_region_unmasked")
            masked = sensitive if mask_by_default else ()
            placeholder = _hash(
                {
                    "contract": CAPTURE_CONTRACT,
                    "feature_id": node["id"],
                    "ui_anchor": node["ui_anchor"],
                    "masked_regions": list(masked),
                }
            )
            step = TutorialStep(
                step_id=f"step-{node['id']}",
                feature_id=node["id"],
                operation=node["operation"],
                ui_anchor=node["ui_anchor"],
                narration=node["narration"],
                screenshot_placeholder=placeholder,
                sensitive_regions=sensitive,
                masked_regions=masked,
                depends_on=tuple(sorted(node["depends_on"])),
            )
            steps.append(step)
            manifest_steps.append(
                {
                    "step_id": step.step_id,
                    "operation": step.operation,
                    "ui_anchor": step.ui_anchor,
                    "screenshot_placeholder": step.screenshot_placeholder,
                    "masked_regions": list(masked),
                }
            )
        return steps, manifest_steps

    def compile(
        self,
        *,
        application_ref: str,
        feature_nodes: list[dict[str, Any]],
        capture_policy: Mapping[str, Any],
        narration_profile: Mapping[str, Any],
        idempotency_key: str,
    ) -> TutorialGraphOutcome:
        _text(application_ref, "application_ref", maximum=300)
        key = _text(idempotency_key, "idempotency_key", maximum=160)
        if not IDEMPOTENCY_PATTERN.match(key):
            raise TutorialGraphError("idempotency_key_invalid")
        if not isinstance(narration_profile, Mapping):
            raise TutorialGraphError("narration_profile_invalid")
        if not isinstance(capture_policy, Mapping):
            raise TutorialGraphError("capture_policy_invalid")

        _safe_tree(
            {
                "application_ref": application_ref,
                "feature_nodes": feature_nodes,
                "capture_policy": capture_policy,
                "narration_profile": narration_profile,
                "idempotency_key": idempotency_key,
            }
        )

        nodes = self._validate_nodes(feature_nodes)
        ordered = self._topological_order(nodes)
        steps, manifest_steps = self._build_steps(ordered, capture_policy)

        graph_document = {
            "contract_id": TUTORIAL_CONTRACT,
            "contract_version": TUTORIAL_VERSION,
            "application_ref": application_ref,
            "narration_profile": narration_profile,
            "steps": [
                {
                    "step_id": step.step_id,
                    "operation": step.operation,
                    "ui_anchor": step.ui_anchor,
                    "narration": step.narration,
                    "sensitive_regions": list(step.sensitive_regions),
                    "masked_regions": list(step.masked_regions),
                    "depends_on": list(step.depends_on),
                }
                for step in steps
            ],
        }
        tutorial_graph_version = _hash(graph_document)

        capture_manifest = {
            "contract_id": CAPTURE_CONTRACT,
            "contract_version": CAPTURE_VERSION,
            "tutorial_graph_version": tutorial_graph_version,
            "capture_admitted": self.windows_agent.admitted,
            "steps": manifest_steps,
        }
        capture_manifest_sha256 = _hash(capture_manifest)

        status = "COMPILED"
        reason_code = "windows_capture_not_admitted" if not self.windows_agent.admitted else "compiled"

        return TutorialGraphOutcome(
            status=status,
            reason_code=reason_code,
            tutorial_graph_version=tutorial_graph_version,
            capture_manifest_sha256=capture_manifest_sha256,
            capture_admitted=self.windows_agent.admitted,
            external_write_allowed=False,
            listing_eligible=False,
            steps=tuple(steps),
        )

    def _step(self, outcome: TutorialGraphOutcome, feature_id: str) -> TutorialStep:
        for step in outcome.steps:
            if step.feature_id == feature_id:
                return step
        raise TutorialGraphError("step_not_found")

    def readback(
        self,
        outcome: TutorialGraphOutcome,
        feature_id: str,
        *,
        observed_placeholder: str | None = None,
    ) -> TutorialReadback:
        step = self._step(outcome, feature_id)
        if observed_placeholder is None:
            return TutorialReadback(
                step_id=step.step_id,
                feature_id=step.feature_id,
                operation=step.operation,
                screenshot_placeholder=step.screenshot_placeholder,
                readback_state="PENDING",
                integrity_ok=True,
            )
        observed = _hex64(observed_placeholder, "observed_placeholder")
        integrity_ok = observed == step.screenshot_placeholder
        return TutorialReadback(
            step_id=step.step_id,
            feature_id=step.feature_id,
            operation=step.operation,
            screenshot_placeholder=step.screenshot_placeholder,
            readback_state="VERIFIED" if integrity_ok else "INVALIDATED",
            integrity_ok=integrity_ok,
        )

    def invalidate(
        self,
        outcome: TutorialGraphOutcome,
        *,
        reason: str,
    ) -> TutorialGraphOutcome:
        _text(reason, "invalidation_reason", maximum=200)
        return TutorialGraphOutcome(
            status="INVALIDATED",
            reason_code=reason,
            tutorial_graph_version=outcome.tutorial_graph_version,
            capture_manifest_sha256=outcome.capture_manifest_sha256,
            capture_admitted=outcome.capture_admitted,
            external_write_allowed=outcome.external_write_allowed,
            listing_eligible=outcome.listing_eligible,
            steps=outcome.steps,
        )

    def mark_stale(
        self,
        outcome: TutorialGraphOutcome,
        *,
        reason: str,
    ) -> TutorialGraphOutcome:
        _text(reason, "stale_reason", maximum=200)
        return TutorialGraphOutcome(
            status="STALE",
            reason_code=reason,
            tutorial_graph_version=outcome.tutorial_graph_version,
            capture_manifest_sha256=outcome.capture_manifest_sha256,
            capture_admitted=outcome.capture_admitted,
            external_write_allowed=outcome.external_write_allowed,
            listing_eligible=outcome.listing_eligible,
            steps=outcome.steps,
        )

    def assemble_lecture(
        self,
        outcome: TutorialGraphOutcome,
        *,
        language: str = "zh-CN",
    ) -> TutorialLecture:
        _text(language, "language", maximum=40)
        lines = [f"# Tutorial ({language})", ""]
        for index, step in enumerate(outcome.steps, start=1):
            masked = "、".join(step.masked_regions) if step.masked_regions else "无"
            lines.append(f"## 步骤 {index}")
            lines.append(f"- 操作: {step.operation}")
            lines.append(f"- 界面: {step.ui_anchor}")
            lines.append(f"- 说明: {step.narration}")
            lines.append(f"- 遮蔽: {masked}")
            lines.append("")
        content = "\n".join(lines).rstrip() + "\n"
        return TutorialLecture(
            language=language,
            content=content,
            lecture_sha256=_hash({"language": language, "content": content}),
            step_count=len(outcome.steps),
        )
