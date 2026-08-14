from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.control_plane.batch_opportunity import BatchOpportunityCandidateRow, BatchOpportunityRunRow
from apps.control_plane.evidence import EvidenceBlobRow, EvidenceRecordRow
from apps.control_plane.profit_erp_sync import (
    DisabledErpItemConnector,
    ProfitErpItemSyncRow,
    ProfitQualifiedErpSync,
)


class EvidenceStub:
    def require_valid(self, evidence_ids: list[str]) -> None:
        if "evd_bad" in evidence_ids:
            raise ValueError("invalid Evidence")


class RepositoryStub:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def append_event(self, *args, **kwargs) -> None:
        self.events.append((args, kwargs))

    def get_product(self, product_id: str):
        if product_id != "prd-1":
            raise KeyError(product_id)
        return SimpleNamespace(id="prd-1", sku="SKU-1", name="利润测试商品")


class ConnectorStub:
    configured = True

    def __init__(self, *, mismatch: bool = False) -> None:
        self.payloads: list[dict] = []
        self.mismatch = mismatch

    def write_draft_and_readback(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "name": payload["item_code"],
            "item_code": payload["item_code"],
            "docstatus": 1 if self.mismatch else 0,
            "custom_kjds_product_id": payload["custom_kjds_product_id"],
            "opening_stock": 0,
        }


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EvidenceBlobRow.__table__.create(engine)
    EvidenceRecordRow.__table__.create(engine)
    BatchOpportunityRunRow.__table__.create(engine)
    BatchOpportunityCandidateRow.__table__.create(engine)
    ProfitErpItemSyncRow.__table__.create(engine)
    return engine


def seed(database, *, qualified: bool = True, invalid_evidence: bool = False):
    now = datetime.now(UTC)
    run = BatchOpportunityRunRow(
        id="bor-1",
        store_ref="ozon-primary",
        idempotency_key="run-1",
        policy_id="cn-ozon-observed-cost-v1",
        contract_version="batch-opportunity/1.3.0",
        snapshot_sha256="a" * 64,
        evidence_id="evd_run",
        as_of=now,
        created_by="operator",
        created_at=now,
        counts_json={},
        policy_json={},
        blockers_json=[],
        payload_json={"limits": {"cm3_floor_cny": "0.00"}},
        task_id=None,
    )
    payload = {
        "canonical_product_id": "prd-1",
        "identity_match": {"status": "exact"},
        "economics": {
            "cost_evidence_complete": qualified,
            "downside": {
                "cm3_cny": "88.00" if qualified else None,
                "conservation_delta_cny": "0.00" if qualified else None,
            },
        },
        "evidence_ids": ["evd_bad" if invalid_evidence else "evd_cost"],
        "invalid_evidence_ids": ["evd_bad"] if invalid_evidence else [],
    }
    candidate = BatchOpportunityCandidateRow(
        id="boc-1",
        run_id=run.id,
        candidate_key="b" * 64,
        fingerprint="c" * 64,
        rank=1,
        state="evaluate",
        strategy="controlled_distribution",
        pilot_ready=False,
        payload_json=payload,
        evidence_id="evd_candidate",
    )
    with Session(database) as session, session.begin():
        session.add_all([run, candidate])


def service(database, connector=None):
    return ProfitQualifiedErpSync(
        engine=database,
        evidence=EvidenceStub(),
        repository=RepositoryStub(),
        connector=connector or DisabledErpItemConnector(),
    )


def test_no_profit_candidate_creates_no_sync_row(database):
    seed(database, qualified=False)
    result = service(database).workspace(tenant_ref="tenant-a", store_ref="ozon-primary")
    assert result["state"] == "no_data"
    assert result["counts"]["profit_qualified"] == 0
    assert result["counts"]["sync_records"] == 0
    with pytest.raises(ValueError, match="not profit-qualified"):
        service(database).prepare(
            tenant_ref="tenant-a",
            store_ref="ozon-primary",
            run_id="bor-1",
            candidate_id="boc-1",
            idempotency_key="erp-1",
            actor_id="operator",
        )


def test_qualified_candidate_prepares_zero_stock_draft_and_is_idempotent(database):
    seed(database)
    sync = service(database)
    first = sync.prepare(
        tenant_ref="tenant-a",
        store_ref="ozon-primary",
        run_id="bor-1",
        candidate_id="boc-1",
        idempotency_key="erp-1",
        actor_id="operator",
    )
    second = sync.prepare(
        tenant_ref="tenant-a",
        store_ref="ozon-primary",
        run_id="bor-1",
        candidate_id="boc-1",
        idempotency_key="erp-1",
        actor_id="operator",
    )
    assert first == second
    assert first["status"] == "blocked_connector_not_configured"
    assert first["erp_item"] == {"item_code": "SKU-1", "docstatus": 0, "opening_stock": 0}
    assert first["external_effects"]["purchase_order_created"] is False


def test_idempotency_conflict_and_cross_store_fail_closed(database):
    seed(database)
    sync = service(database)
    sync.prepare(
        tenant_ref="tenant-a", store_ref="ozon-primary", run_id="bor-1",
        candidate_id="boc-1", idempotency_key="erp-1", actor_id="operator",
    )
    with pytest.raises(ValueError, match="idempotency conflict"):
        sync.prepare(
            tenant_ref="tenant-a", store_ref="ozon-primary", run_id="bor-1",
            candidate_id="different", idempotency_key="erp-1", actor_id="operator",
        )
    with pytest.raises(KeyError, match="authorized store"):
        sync.prepare(
            tenant_ref="tenant-a", store_ref="other-store", run_id="bor-1",
            candidate_id="boc-1", idempotency_key="erp-2", actor_id="operator",
        )


def test_dispatch_writes_only_item_draft_and_requires_exact_readback(database):
    seed(database)
    connector = ConnectorStub()
    sync = service(database, connector)
    prepared = sync.prepare(
        tenant_ref="tenant-a", store_ref="ozon-primary", run_id="bor-1",
        candidate_id="boc-1", idempotency_key="erp-1", actor_id="operator",
    )
    result = sync.dispatch(
        sync_id=prepared["sync_id"], tenant_ref="tenant-a", store_ref="ozon-primary", actor_id="operator"
    )
    assert result["status"] == "succeeded"
    assert connector.payloads == [
        {
            "docstatus": 0,
            "item_code": "SKU-1",
            "item_name": "利润测试商品",
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "custom_kjds_product_id": "prd-1",
            "opening_stock": 0,
        }
    ]


def test_bad_evidence_and_readback_mismatch_never_report_success(database):
    seed(database, invalid_evidence=True)
    with pytest.raises(ValueError, match="not profit-qualified"):
        service(database).prepare(
            tenant_ref="tenant-a", store_ref="ozon-primary", run_id="bor-1",
            candidate_id="boc-1", idempotency_key="erp-1", actor_id="operator",
        )


def test_readback_mismatch_is_failed_not_success(database):
    seed(database)
    sync = service(database, ConnectorStub(mismatch=True))
    prepared = sync.prepare(
        tenant_ref="tenant-a", store_ref="ozon-primary", run_id="bor-1",
        candidate_id="boc-1", idempotency_key="erp-1", actor_id="operator",
    )
    result = sync.dispatch(
        sync_id=prepared["sync_id"], tenant_ref="tenant-a", store_ref="ozon-primary", actor_id="operator"
    )
    assert result["status"] == "failed_readback"
    assert result["last_error"] == "ERPNext Item readback mismatch"


def test_erp_workspace_rejects_anonymous_and_cross_store(monkeypatch):
    from apps.control_plane.api import app
    from apps.control_plane.runtime import runtime
    from apps.control_plane.security import AuthenticationFailure, Principal

    def reject(_key):
        raise AuthenticationFailure("missing", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    assert TestClient(app).get("/v1/erp/profit-items").status_code == 401

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: Principal(
            "operator-a", frozenset({"operator"}), "tenant-a", frozenset({"store-a"})
        ),
    )
    response = TestClient(app).get("/v1/erp/profit-items?store_ref=store-b")
    assert response.status_code == 403

    monkeypatch.setattr(
        runtime.profit_erp_sync,
        "workspace",
        lambda *, tenant_ref, store_ref: {
            "state": "no_data",
            "tenant_ref": tenant_ref,
            "store_ref": store_ref,
            "counts": {"profit_qualified": 0},
        },
    )
    response = TestClient(app).get("/v1/erp/profit-items?store_ref=store-a")
    assert response.status_code == 200
    assert response.json()["tenant_ref"] == "tenant-a"
