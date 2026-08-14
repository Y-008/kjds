"""BAS-178 source adoption evaluator contract tests (first slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.source_adoption import (
    GovernedSourceAdoptionEvaluator,
    SourceAdoptionError,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _workspace() -> GovernedSourceAdoptionEvaluator:
    return GovernedSourceAdoptionEvaluator()


def _candidate(**overrides) -> dict:
    candidate = {
        "candidate_ref": "jackwener/xiaohongshu-cli",
        "version": "0.6.4",
        "license_id": "Apache-2.0",
        "commit_sha256": _sha("4d63f3c"),
        "source_rank": "operator_cli_or_browser",
        "decision": "pilot_isolated",
        "authenticated": False,
    }
    candidate.update(overrides)
    return candidate


def test_evaluates_candidate_deterministically():
    decision = _workspace().evaluate(_candidate())
    assert decision.decision == "pilot_isolated"
    assert decision.authenticated is False
    assert decision.external_write_allowed is False
    assert len(decision.decision_sha256) == 64


def test_replay_identity():
    first = _workspace().evaluate(_candidate())
    second = _workspace().evaluate(_candidate())
    assert first.decision_sha256 == second.decision_sha256


def test_unknown_source_rank_rejected():
    with pytest.raises(SourceAdoptionError) as exc:
        _workspace().evaluate(_candidate(source_rank="crawler"))
    assert "source_rank_not_recognized" in str(exc.value)


def test_unknown_decision_rejected():
    with pytest.raises(SourceAdoptionError) as exc:
        _workspace().evaluate(_candidate(decision="install_now"))
    assert "decision_not_recognized" in str(exc.value)


def test_preferred_path_requires_official_api():
    with pytest.raises(SourceAdoptionError) as exc:
        _workspace().evaluate(
            _candidate(source_rank="operator_cli_or_browser", decision="preferred_path")
        )
    assert "preferred_path_requires_official_api" in str(exc.value)


def test_reject_runtime_license_conflict():
    with pytest.raises(SourceAdoptionError) as exc:
        _workspace().evaluate(
            _candidate(license_id="Apache-2.0", decision="reject_runtime")
        )
    assert "reject_runtime_license_conflict" in str(exc.value)


def test_preferred_path_unauthenticated_reason():
    decision = _workspace().evaluate(
        _candidate(
            source_rank="official_authorized_api",
            decision="preferred_path",
            authenticated=False,
        )
    )
    assert "preferred_path_unauthenticated" in decision.reasons


def test_bad_commit_sha256_rejected():
    with pytest.raises(SourceAdoptionError):
        _workspace().evaluate(_candidate(commit_sha256="not-hex"))


def test_sensitive_candidate_rejected():
    with pytest.raises(SourceAdoptionError) as exc:
        _workspace().evaluate(_candidate(version="api_key=secret"))
    assert "sensitive_value_rejected" in str(exc.value)


def test_authenticated_non_bool_rejected():
    with pytest.raises(SourceAdoptionError):
        _workspace().evaluate(_candidate(authenticated="yes"))


def test_readback_states():
    decision = _workspace().evaluate(_candidate())
    pending = _workspace().readback(decision)
    assert pending["readback_state"] == "PENDING"
    assert pending["integrity_ok"] is True

    verified = _workspace().readback(decision, observed=decision.decision_sha256)
    assert verified["readback_state"] == "VERIFIED"

    invalidated = _workspace().readback(decision, observed=_sha("other"))
    assert invalidated["readback_state"] == "INVALIDATED"
    assert invalidated["integrity_ok"] is False


def test_zero_authority_all_false():
    flags = _workspace().zero_authority()
    assert flags
    assert all(not value for value in flags.values())
