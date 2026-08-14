"""BAS-178 campaign authority contract tests (campaign authority slice)."""

from __future__ import annotations

import pytest

from apps.control_plane.campaign_authority import (
    CampaignAuthorityError,
    CampaignGrant,
    GovernedCampaignAuthority,
)


def _authority() -> GovernedCampaignAuthority:
    return GovernedCampaignAuthority()


def _grant(**overrides) -> dict:
    grant = {
        "grant_id": "grant-001",
        "grantor": "human-operator-alice",
        "account_ref": "account-xhs-1",
        "authorized_actions": ["publish", "comment", "reply"],
        "purpose": "spring skincare campaign",
        "audience": "verified followers",
        "budget": {"volume": 100, "cost_limit": "CNY:5000"},
        "stop_conditions": ["negative_ratio_gt_0.2", "budget_exhausted"],
        "not_before": "2026-08-14T00:00:00Z",
        "expiry": "2026-08-21T00:00:00Z",
        "revoked": False,
        "kill_switched": False,
    }
    grant.update(overrides)
    return grant


def _issued(**overrides) -> CampaignGrant:
    return _authority().issue(_grant(**overrides))


def test_issue_valid_grant():
    grant = _issued()
    assert grant.grant_id == "grant-001"
    assert grant.authorized_actions == ("publish", "comment", "reply")
    assert len(grant.grant_sha256) == 64
    assert grant.revoked is False
    assert grant.kill_switched is False


def test_status_active_within_window():
    status = _authority().status(_issued(), now="2026-08-15T12:00:00Z")
    assert status.status == "ACTIVE"
    assert status.authorization_ok is True


def test_status_not_yet_active():
    status = _authority().status(_issued(), now="2026-08-13T00:00:00Z")
    assert status.status == "NOT_YET_ACTIVE"
    assert status.authorization_ok is False
    assert "grant_not_yet_active" in status.reasons


def test_status_expired():
    status = _authority().status(_issued(), now="2026-08-21T00:00:01Z")
    assert status.status == "EXPIRED"
    assert status.authorization_ok is False
    assert "grant_expired" in status.reasons


def test_status_revoked():
    status = _authority().status(_issued(revoked=True), now="2026-08-15T00:00:00Z")
    assert status.status == "REVOKED"
    assert status.authorization_ok is False
    assert "grant_revoked" in status.reasons


def test_status_kill_switched():
    status = _authority().status(_issued(kill_switched=True), now="2026-08-15T00:00:00Z")
    assert status.status == "KILL_SWITCHED"
    assert status.authorization_ok is False
    assert "grant_kill_switched" in status.reasons


def test_authorize_action_in_scope():
    decision = _authority().authorize(_issued(), "publish", now="2026-08-15T00:00:00Z")
    assert decision.authorized is True
    assert decision.status == "ACTIVE"


def test_authorize_action_out_of_scope():
    decision = _authority().authorize(_issued(), "delete", now="2026-08-15T00:00:00Z")
    assert decision.authorized is False
    assert "action_not_authorized" in decision.reasons


def test_authorize_expired_grant():
    decision = _authority().authorize(_issued(), "publish", now="2026-08-22T00:00:00Z")
    assert decision.authorized is False
    assert decision.status == "EXPIRED"


def test_replay_identity():
    first = _issued()
    second = _issued()
    assert first.grant_sha256 == second.grant_sha256


def test_expiry_not_after_not_before_rejected():
    with pytest.raises(CampaignAuthorityError) as exc:
        _issued(not_before="2026-08-20T00:00:00Z", expiry="2026-08-15T00:00:00Z")
    assert "expiry_not_after_not_before" in str(exc.value)


def test_unknown_action_rejected():
    with pytest.raises(CampaignAuthorityError) as exc:
        _issued(authorized_actions=["publish", "hack"])
    assert "action_not_recognized" in str(exc.value)


def test_sensitive_value_rejected():
    with pytest.raises(CampaignAuthorityError) as exc:
        _issued(budget={"volume": "api_key=secret"})
    assert "sensitive_value_rejected" in str(exc.value)


def test_empty_authorized_actions_rejected():
    with pytest.raises(CampaignAuthorityError):
        _issued(authorized_actions=[])


def test_readback_states():
    authority = _authority()
    grant = _issued()
    status = authority.status(grant, now="2026-08-15T00:00:00Z")
    decision = authority.authorize(grant, "publish", now="2026-08-15T00:00:00Z")

    assert authority.readback(grant)["readback_state"] == "PENDING"
    assert authority.readback(grant, observed=grant.grant_sha256)["readback_state"] == "VERIFIED"
    assert authority.readback(status, observed=status.status_sha256)["readback_state"] == "VERIFIED"
    assert authority.readback(decision, observed=decision.decision_sha256)["readback_state"] == "VERIFIED"

    invalidated = authority.readback(grant, observed="0" * 64)
    assert invalidated["readback_state"] == "INVALIDATED"
    assert invalidated["integrity_ok"] is False


def test_zero_authority_all_false():
    flags = _authority().zero_authority()
    assert flags
    assert all(not value for value in flags.values())
    assert flags["external_write"] is False
    assert flags["pilot"] is False
    assert flags["approval"] is False
