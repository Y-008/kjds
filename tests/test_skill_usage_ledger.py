from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.control_plane.skill_usage_ledger import SkillUsageEvent, SkillUsageLedger


def _event(key: str, event_id: str = "e1") -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id=event_id,
        idempotency_key=key,
        tenant_id="t1",
        customer_id="c1",
        skill_id="image.generate",
        units=Decimal("2"),
        unit_cost=Decimal("0.25"),
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_usage_is_idempotent_and_invoice_is_reproducible():
    ledger = SkillUsageLedger()
    first = ledger.record(_event("k1"))
    assert ledger.record(_event("k1", event_id="different")) == first
    assert ledger.total_cost(tenant_id="t1", customer_id="c1") == Decimal("0.50")
    assert ledger.invoice_preview(tenant_id="t1", customer_id="c1")["event_count"] == 1


def test_conflicting_idempotency_and_mixed_currency_fail_closed():
    ledger = SkillUsageLedger()
    ledger.record(_event("k1"))
    conflicting = replace(_event("k1", event_id="e2"), units=Decimal("3"))
    with pytest.raises(ValueError, match="idempotency"):
        ledger.record(conflicting)
    ledger.record(replace(_event("k2", event_id="e3"), currency="CNY"))
    with pytest.raises(ValueError, match="mixed currencies"):
        ledger.total_cost(tenant_id="t1", customer_id="c1")


def test_idempotency_keys_are_scoped_to_tenant():
    ledger = SkillUsageLedger()
    ledger.record(_event("shared"))
    other = replace(_event("shared", event_id="e2"), tenant_id="t2")
    assert ledger.record(other) == other
