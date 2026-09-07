from datetime import UTC, datetime

import pytest

from apps.control_plane.data_fabric_contracts import ScopeRef
from apps.control_plane.decision_ledger import DecisionLedger, DecisionLedgerError

SCOPE = ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-a",))
WHEN = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)


def test_ledger_is_hash_chained_and_idempotent():
    ledger = DecisionLedger()
    first = ledger.append(
        "decision_proposed",
        decision_id="d-1",
        payload={"action": "increase", "delta": "2"},
        actor_id="pm",
        idempotency_key="idem-1",
        scope=SCOPE,
        occurred_at=WHEN,
    )
    retry = ledger.append(
        "decision_proposed",
        decision_id="d-1",
        payload={"action": "increase", "delta": "2"},
        actor_id="pm",
        idempotency_key="idem-1",
        scope=SCOPE,
    )
    assert retry == first
    assert ledger.verify() is True
    assert len(ledger) == 1


def test_ledger_rejects_idempotency_drift_and_preserves_events():
    ledger = DecisionLedger()
    ledger.append("decision_proposed", decision_id="d-1", payload={"delta": "1"}, idempotency_key="idem-1", occurred_at=WHEN)
    with pytest.raises(DecisionLedgerError):
        ledger.append("decision_proposed", decision_id="d-1", payload={"delta": "2"}, idempotency_key="idem-1", occurred_at=WHEN)
    assert ledger.verify() is True


def test_ledger_latest_and_scoped_replay():
    ledger = DecisionLedger()
    ledger.append("decision_proposed", decision_id="d-1", payload={"step": 1}, occurred_at=WHEN)
    ledger.append("decision_readback", decision_id="d-1", payload={"step": 2}, occurred_at=WHEN)
    ledger.append("decision_proposed", decision_id="d-2", payload={"step": 1}, occurred_at=WHEN)
    assert [event.event_type for event in ledger.events(decision_id="d-1")] == ["decision_proposed", "decision_readback"]
    assert ledger.latest(decision_id="d-1").event_type == "decision_readback"
    assert ledger.verify() is True
