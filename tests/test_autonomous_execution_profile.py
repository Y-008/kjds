from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.control_plane.autonomous_execution_profile import (
    AutonomousPermitRequest,
    StandingAutonomousExecutionProfile,
    evaluate_standing_profile,
)
from apps.control_plane.economic_guard_service import (
    EconomicGuardInput,
    evaluate_economic_guard,
)
from apps.control_plane.growth_channel import ChannelCommand, DryRunGrowthChannelAdapter


def _profile(*, enabled: bool = True):
    now = datetime(2026, 9, 6, tzinfo=UTC)
    return StandingAutonomousExecutionProfile(
        profile_id="profile-1",
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_refs=frozenset({"store-a"}),
        allowed_channels=frozenset({"vk"}),
        allowed_operations=frozenset({"publish"}),
        enabled=enabled,
        activated_at=now - timedelta(minutes=1),
        max_permit_ttl_seconds=60,
    )


def _request(**overrides):
    values = dict(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        channel="vk",
        operation="publish",
        idempotency_key="cmd-1",
        attribution_id="attr-1",
        command={"text": "hello"},
        proof_ready=True,
        evidence_fresh=True,
        data_quality_valid=True,
        external_readback_passed=True,
        rollback_available=True,
        economic_guard=evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("10"))),
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )
    values.update(overrides)
    return AutonomousPermitRequest(**values)


def test_profile_issues_command_bound_one_time_permit():
    decision = evaluate_standing_profile(_profile(), _request())
    assert decision.status == "issued"
    assert decision.permit is not None
    command = ChannelCommand(
        idempotency_key="cmd-1",
        operation="publish",
        attribution_id="attr-1",
        payload={"text": "hello"},
    )
    assert decision.permit.command_sha256 == command.fingerprint
    receipt = DryRunGrowthChannelAdapter("vk").dispatch(command, permit=decision.permit, dry_run=True)
    assert receipt["external_write_performed"] is False


def test_profile_fails_closed_on_any_gate_or_scope_mismatch():
    decision = evaluate_standing_profile(
        _profile(),
        _request(data_quality_valid=False, store_ref="store-other"),
    )
    assert decision.status == "blocked"
    assert decision.permit is None
    assert "data_quality_invalid" in decision.reasons
    assert "store_scope_mismatch" in decision.reasons


def test_disabled_profile_cannot_expand_permissions():
    decision = evaluate_standing_profile(_profile(enabled=False), _request())
    assert decision.status == "blocked"
    assert decision.reasons == ("profile_disabled",)
