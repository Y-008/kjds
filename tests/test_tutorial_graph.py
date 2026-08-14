"""BAS-187 TutorialGraph deterministic compiler contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.control_plane.tutorial_graph import (
    ALLOWED_OPERATIONS,
    GovernedTutorialGraphWorkspace,
    TutorialGraphError,
)

ROOT = Path(__file__).resolve().parents[1]


def _workspace() -> GovernedTutorialGraphWorkspace:
    return GovernedTutorialGraphWorkspace()


def _nodes() -> list[dict]:
    return [
        {
            "id": "open_app",
            "label": "Open application",
            "operation": "navigate",
            "ui_anchor": "app://main-window",
            "narration": "Open the application.",
        },
        {
            "id": "sign_in",
            "label": "Sign in",
            "operation": "type",
            "ui_anchor": "form#login .credential-field",
            "narration": "Enter your credentials.",
            "sensitive_regions": ["credential_input"],
            "depends_on": ["open_app"],
        },
        {
            "id": "capture_result",
            "label": "Capture result",
            "operation": "screenshot",
            "ui_anchor": "section#result",
            "narration": "Capture the result.",
            "depends_on": ["sign_in"],
        },
    ]


def _policy(**overrides) -> dict:
    policy = {"mask_by_default": True}
    policy.update(overrides)
    return policy


def test_compile_is_deterministic() -> None:
    workspace = _workspace()
    args = dict(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={"language": "zh-CN", "tone": "calm"},
        idempotency_key="run-1",
    )
    first = workspace.compile(**args)
    second = workspace.compile(**args)
    assert first.tutorial_graph_version == second.tutorial_graph_version
    assert first.capture_manifest_sha256 == second.capture_manifest_sha256
    assert len(first.tutorial_graph_version) == 64


def test_idempotency_key_does_not_change_graph() -> None:
    workspace = _workspace()
    base = dict(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={"language": "zh-CN"},
    )
    first = workspace.compile(idempotency_key="run-1", **base)
    second = workspace.compile(idempotency_key="run-2", **base)
    assert first.tutorial_graph_version == second.tutorial_graph_version


def test_topological_order_stable_and_respects_dependencies() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    ids = [step.feature_id for step in outcome.steps]
    assert ids.index("open_app") < ids.index("sign_in")
    assert ids.index("sign_in") < ids.index("capture_result")


def test_masked_by_default_covers_sensitive_regions() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(mask_by_default=True),
        narration_profile={},
        idempotency_key="run-1",
    )
    sign_in = next(s for s in outcome.steps if s.feature_id == "sign_in")
    assert sign_in.sensitive_regions == ("credential_input",)
    assert sign_in.masked_regions == ("credential_input",)
    assert outcome.capture_admitted is False
    assert outcome.external_write_allowed is False
    assert outcome.listing_eligible is False


def test_sensitive_region_unmasked_is_blocked() -> None:
    workspace = _workspace()
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=_nodes(),
            capture_policy=_policy(mask_by_default=False),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "unmasked" in str(exc.value)


def test_dependency_cycle_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A", "operation": "click", "ui_anchor": "#a", "narration": "a", "depends_on": ["b"]},
        {"id": "b", "label": "B", "operation": "click", "ui_anchor": "#b", "narration": "b", "depends_on": ["a"]},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "cycle" in str(exc.value)


def test_self_dependency_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A", "operation": "click", "ui_anchor": "#a", "narration": "a", "depends_on": ["a"]},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "self_dependency" in str(exc.value)


def test_duplicate_node_id_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A1", "operation": "click", "ui_anchor": "#a", "narration": "a"},
        {"id": "a", "label": "A2", "operation": "click", "ui_anchor": "#a2", "narration": "a2"},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "duplicate" in str(exc.value)


def test_unknown_dependency_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A", "operation": "click", "ui_anchor": "#a", "narration": "a", "depends_on": ["ghost"]},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "dependency_unknown" in str(exc.value)


def test_unknown_operation_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A", "operation": "delete_system", "ui_anchor": "#a", "narration": "a"},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "operation_not_allowed" in str(exc.value)


def test_secret_marker_rejected() -> None:
    workspace = _workspace()
    nodes = [
        {"id": "a", "label": "A", "operation": "click", "ui_anchor": "#a", "narration": "password=hunter2"},
    ]
    with pytest.raises(TutorialGraphError) as exc:
        workspace.compile(
            application_ref="app://demo",
            feature_nodes=nodes,
            capture_policy=_policy(),
            narration_profile={},
            idempotency_key="run-1",
        )
    assert "sensitive_value_rejected" in str(exc.value)


def test_windows_capture_not_admitted() -> None:
    workspace = _workspace()
    assert workspace.windows_agent.provider == "windows_agent"
    assert workspace.windows_agent.admitted is False
    assert workspace.internal_compiler.admitted is True
    assert workspace.internal_compiler.deterministic is True
    assert workspace.internal_compiler.external_call is False


def test_contract_registry_is_consistent() -> None:
    path = ROOT / "docs" / "project" / "registries" / "tutorial_graph_contracts.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    assert contract["schema_version"] == "kjds-tutorial-graph-contracts-v1"
    assert contract["owner_task"] == "BAS-187"
    graph = contract["graph_contract"]
    assert set(graph["allowed_operations"]) == ALLOWED_OPERATIONS
    assert graph["raw_credential_or_blob_allowed"] is False
    capture = contract["capture_contract"]
    assert capture["windows_capture_admitted"] is False
    assert capture["real_desktop_capture"] == "not_admitted"
    assert capture["mask_by_default"] is True


def test_non_ascii_narration_is_stable() -> None:
    workspace = _workspace()
    nodes = _nodes()
    nodes[2]["narration"] = "点击并截取结果，讲解给用户。"
    args = dict(
        application_ref="app://demo",
        feature_nodes=nodes,
        capture_policy=_policy(),
        narration_profile={"language": "zh-CN"},
    )
    first = workspace.compile(idempotency_key="run-1", **args)
    second = workspace.compile(idempotency_key="run-2", **args)
    assert first.tutorial_graph_version == second.tutorial_graph_version
    assert len(first.tutorial_graph_version) == 64


def test_readback_pending_and_verified() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    shot = next(s for s in outcome.steps if s.feature_id == "capture_result")
    pending = workspace.readback(outcome, "capture_result")
    assert pending.readback_state == "PENDING"
    assert pending.integrity_ok is True
    verified = workspace.readback(
        outcome,
        "capture_result",
        observed_placeholder=shot.screenshot_placeholder,
    )
    assert verified.readback_state == "VERIFIED"
    assert verified.integrity_ok is True


def test_readback_mismatch_is_invalidated() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    result = workspace.readback(
        outcome,
        "capture_result",
        observed_placeholder="0" * 64,
    )
    assert result.readback_state == "INVALIDATED"
    assert result.integrity_ok is False


def test_readback_unknown_step_rejected() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    with pytest.raises(TutorialGraphError) as exc:
        workspace.readback(outcome, "ghost")
    assert "step_not_found" in str(exc.value)


def test_readback_placeholder_length_validated() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    with pytest.raises(TutorialGraphError):
        workspace.readback(
            outcome,
            "capture_result",
            observed_placeholder="short",
        )


def test_invalidate_and_stale_transitions() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    invalidated = workspace.invalidate(outcome, reason="source_revoked")
    assert invalidated.status == "INVALIDATED"
    assert invalidated.reason_code == "source_revoked"
    assert invalidated.tutorial_graph_version == outcome.tutorial_graph_version
    stale = workspace.mark_stale(outcome, reason="application_version_changed")
    assert stale.status == "STALE"
    assert stale.tutorial_graph_version == outcome.tutorial_graph_version


def test_lecture_is_deterministic_and_ordered() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={"language": "zh-CN"},
        idempotency_key="run-1",
    )
    first = workspace.assemble_lecture(outcome)
    second = workspace.assemble_lecture(outcome)
    assert first.lecture_sha256 == second.lecture_sha256
    assert first.step_count == 3
    assert len(first.lecture_sha256) == 64
    open_at = first.content.index("## 步骤 1")
    sign_at = first.content.index("## 步骤 2")
    shot_at = first.content.index("## 步骤 3")
    assert open_at < sign_at < shot_at


def test_lecture_reflects_masking_and_narration() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    lecture = workspace.assemble_lecture(outcome)
    assert "credential_input" in lecture.content
    assert "Enter your credentials." in lecture.content
    assert "无" in lecture.content


def test_lecture_language_changes_hash() -> None:
    workspace = _workspace()
    outcome = workspace.compile(
        application_ref="app://demo",
        feature_nodes=_nodes(),
        capture_policy=_policy(),
        narration_profile={},
        idempotency_key="run-1",
    )
    zh = workspace.assemble_lecture(outcome, language="zh-CN")
    en = workspace.assemble_lecture(outcome, language="en-US")
    assert zh.lecture_sha256 != en.lecture_sha256
    assert "zh-CN" in zh.content
    assert "en-US" in en.content
