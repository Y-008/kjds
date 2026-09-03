from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.enterprise_control import (
    BackupManifest,
    CashLink,
    CashState,
    DataAsset,
    DataClassification,
    ExactScope,
    FiveLinkSettlementLedger,
    FulfillmentEpisode,
    FulfillmentMode,
    FulfillmentState,
    InMemoryBackupRepository,
    InMemoryBillingMeter,
    InMemoryDataLifecycle,
    InMemoryRestoreCoordinator,
    InMemorySecretProvider,
    InMemoryTenantBoundary,
    InMemoryWriteFreeze,
    InventoryReservation,
    LandedCostSnapshot,
    PayloadClassifier,
    ProviderFailoverRouter,
    ProviderSnapshot,
    ProviderState,
    RecoveryVerifier,
    ReturnCase,
    ReturnState,
    SupplierQuote,
    WriteFrozenError,
    safe_export_payload,
)

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
OTHER_SCOPE = ExactScope("tenant-a", "entity-a", "ozon-secondary")
NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _sha(value: bytes = b"evidence") -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def test_exact_scope_boundary_rejects_cross_store_reads():
    boundary = InMemoryTenantBoundary()
    boundary.assert_access(SCOPE, SCOPE)
    with pytest.raises(Exception, match="outside"):
        boundary.assert_access(OTHER_SCOPE, SCOPE)


def test_classifier_and_safe_export_never_emit_sensitive_payload():
    classifier = PayloadClassifier()
    assert classifier.classify({"customer_email": "a@example.com"}) is DataClassification.PERSONAL
    assert classifier.classify({"notes": "contact a@example.com"}) is DataClassification.PERSONAL
    assert classifier.classify({"api_key": "secret"}) is DataClassification.SECRET
    assert classifier.classify({"notes": "Authorization: Bearer abcdefghijklmnop"}) is DataClassification.SECRET
    projection = safe_export_payload({"bank_account": "123", "amount": "10"}, classifier)
    assert "bank_account" not in str(projection)
    assert "payload_sha256" in projection


def test_retention_export_and_deletion_are_scope_bound_and_irreversible():
    asset = DataAsset(
        "customer-1-chat",
        SCOPE,
        DataClassification.PERSONAL,
        _sha(),
        "customer_pii",
        NOW - timedelta(days=10),
        NOW - timedelta(days=1),
    )
    lifecycle = InMemoryDataLifecycle([asset])
    assert lifecycle.export("customer-1", SCOPE)["assets"][0]["asset_ref"] == asset.asset_ref
    assert lifecycle.export("customer-1", OTHER_SCOPE)["assets"] == []
    planned = lifecycle.plan([asset], as_of=NOW)
    receipt = lifecycle.execute(planned, actor_id="privacy-owner")
    assert receipt["asset_refs"] == (asset.asset_ref,)
    assert lifecycle.export("customer-1", SCOPE)["assets"] == []
    with pytest.raises(Exception, match="unknown asset"):
        lifecycle.execute([asset], actor_id="privacy-owner")


def test_legal_hold_blocks_retention_deletion():
    asset = DataAsset(
        "customer-1-legal",
        SCOPE,
        DataClassification.CONFIDENTIAL,
        _sha(b"legal"),
        "legal",
        NOW - timedelta(days=30),
        NOW - timedelta(days=1),
        legal_hold=True,
    )
    lifecycle = InMemoryDataLifecycle([asset])
    with pytest.raises(Exception, match="legal-hold"):
        lifecycle.plan([asset], as_of=NOW)


def test_backup_manifest_and_restore_guard():
    repo = InMemoryBackupRepository()
    manifest = repo.create_manifest(scope=SCOPE, archive=b"pg_dump", alembic_head="20260809_0098", created_at=NOW)
    assert isinstance(manifest, BackupManifest)
    assert repo.get(manifest.backup_ref).archive_sha256 == manifest.archive_sha256
    restore = InMemoryRestoreCoordinator().restore(manifest, target_database="pilot_restore", dry_run=True)
    assert restore.dry_run is True
    with pytest.raises(Exception, match="production"):
        InMemoryRestoreCoordinator().restore(manifest, target_database="production", dry_run=False)


def test_recovery_verifier_reports_rpo_and_rto_result():
    report = RecoveryVerifier().check(
        backup_created_at=NOW - timedelta(minutes=5),
        restored_at=NOW - timedelta(minutes=4),
        rpo=timedelta(minutes=15),
        rto=timedelta(minutes=30),
        as_of=NOW,
    )
    assert report.status == "PASS"
    assert len(report.report_sha256) == 64


def test_kill_switch_freezes_and_releases_external_writes():
    freeze = InMemoryWriteFreeze()
    freeze.ensure_writes_allowed()
    paused = freeze.freeze(reason="provider drift", actor_id="risk-owner", as_of=NOW)
    assert paused.mode.value == "paused"
    with pytest.raises(WriteFrozenError):
        freeze.ensure_writes_allowed()
    resumed = freeze.release(reason="readback passed", actor_id="admin", as_of=NOW + timedelta(minutes=1))
    assert resumed.mode.value == "running"
    freeze.ensure_writes_allowed()


def test_five_link_cash_ledger_requires_bank_and_zero_difference():
    ledger = FiveLinkSettlementLedger()
    rows = [
        CashLink(kind, kind, SCOPE, Decimal("0"), "CNY", _sha(kind.encode()))
        for kind in ("order", "posting", "accrual", "payout", "bank")
    ]
    verified = ledger.match(rows)
    assert verified.state is CashState.CASH_VERIFIED
    assert verified.unmatched == ()
    missing_bank = ledger.match(rows[:-1])
    assert missing_bank.state is CashState.CASH_PARTIAL
    assert "BANK_EVIDENCE_MISSING" in missing_bank.unmatched


def test_five_link_cash_ledger_rejects_cross_scope_and_broken_chain():
    ledger = FiveLinkSettlementLedger()
    rows = [
        CashLink("order", "order-1", SCOPE, Decimal("0"), "CNY", _sha(b"order"), "posting-1"),
        CashLink("posting", "posting-1", SCOPE, Decimal("0"), "CNY", _sha(b"posting"), "wrong-accrual"),
        CashLink("accrual", "accrual-1", OTHER_SCOPE, Decimal("0"), "CNY", _sha(b"accrual"), "payout-1"),
        CashLink("payout", "payout-1", SCOPE, Decimal("0"), "CNY", _sha(b"payout"), "bank-1"),
        CashLink("bank", "bank-1", SCOPE, Decimal("0"), "CNY", _sha(b"bank")),
    ]
    result = ledger.match(rows)
    assert result.state is CashState.CASH_PARTIAL
    assert "SCOPE_MISMATCH" in result.unmatched


def test_fulfillment_and_return_state_machines_fail_closed():
    episode = FulfillmentEpisode("episode-1", SCOPE, "order-1", "2021933624", FulfillmentMode.FBS)
    episode = episode.transition(FulfillmentState.RESERVED).transition(FulfillmentState.PACKING)
    with pytest.raises(Exception, match="invalid fulfillment"):
        episode.transition(FulfillmentState.DELIVERED)
    case = ReturnCase("return-1", SCOPE, "order-1", "2021933624", "damaged")
    case = case.transition(ReturnState.REVIEW).transition(ReturnState.APPROVED).transition(ReturnState.REFUNDED)
    assert case.state is ReturnState.REFUNDED
    fbo = FulfillmentEpisode("episode-fbo", SCOPE, "order-2", "2021933624", FulfillmentMode.FBO)
    with pytest.raises(Exception, match="invalid fulfillment"):
        fbo.transition(FulfillmentState.RESERVED).transition(FulfillmentState.PACKING)
    real_fbs = FulfillmentEpisode("episode-real", SCOPE, "order-3", "2021933624", FulfillmentMode.REAL_FBS)
    real_fbs = real_fbs.transition(FulfillmentState.RESERVED).transition(FulfillmentState.PACKING)
    with pytest.raises(Exception, match="invalid fulfillment"):
        real_fbs.transition(FulfillmentState.CANCELLED)


def test_inventory_reservation_and_supplier_quote_rules():
    reservation = InventoryReservation("reservation-1", SCOPE, "2021933624", 2)
    assert reservation.commit().status == "committed"
    with pytest.raises(Exception, match="only reserved"):
        reservation.commit().commit()
    quote = SupplierQuote("quote-1", SCOPE, "2021933624", Decimal("100"), "CNY", NOW + timedelta(hours=1), "supplier-1")
    assert quote.is_current(as_of=NOW)
    assert not quote.is_current(as_of=NOW + timedelta(days=2))


def test_landed_cost_and_reconciliation_owner_rules():
    landed = LandedCostSnapshot(
        "2021933624", "CNY", Decimal("100"), Decimal("5"), Decimal("20"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("1"), NOW, _sha(b"cost")
    )
    assert landed.total_cost == Decimal("134")


def test_billing_meter_enforces_exact_scope_limit():
    meter = InMemoryBillingMeter({(SCOPE.key, "agent_tokens"): Decimal("10")})
    meter.record(scope=SCOPE, metric="agent_tokens", quantity=Decimal("6"), unit="token", occurred_at=NOW)
    assert meter.used(scope=SCOPE, metric="agent_tokens") == Decimal("6")
    with pytest.raises(Exception, match="limit"):
        meter.record(scope=SCOPE, metric="agent_tokens", quantity=Decimal("5"), unit="token", occurred_at=NOW)
    assert meter.used(scope=OTHER_SCOPE, metric="agent_tokens") == Decimal("0")


def test_provider_router_uses_fallback_only_when_primary_unavailable():
    router = ProviderFailoverRouter(primary="cloud", fallback="private")
    router.update(ProviderSnapshot("cloud", ProviderState.UNAVAILABLE, NOW, "429"))
    assert router.require_candidate() == ("private",)
    router.update(ProviderSnapshot("cloud", ProviderState.HEALTHY, NOW, "ok"))
    assert router.require_candidate() == ("cloud", "private")


def test_secret_provider_snapshot_contains_handles_only():
    provider = InMemorySecretProvider()
    provider.put("ozon-key", "opaque-secret")
    assert provider.get("ozon-key") == "opaque-secret"
    assert "opaque-secret" not in str(provider.snapshot())
    provider.revoke("ozon-key")
    with pytest.raises(Exception, match="unavailable"):
        provider.get("ozon-key")
