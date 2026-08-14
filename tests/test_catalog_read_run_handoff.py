from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.catalog_read_run_handoff import (
    CatalogReadRunHandoffRow,
    CatalogReadRunHandoffService,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import Base

AS_OF = datetime(2026, 7, 28, 8, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def principal(
    *,
    tenant_ref: str = "tenant-a",
    stores: frozenset[str] = frozenset({"store-a"}),
) -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=stores,
    )


def entity_scope(
    *,
    entity_ref: str = "entity-a",
    authority: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority,
    }


def source_contract(
    *,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    grant_hash: str = "a" * 64,
) -> dict:
    frozen = {
        "registry_sha256": "b" * 64,
        "adapter": {
            "adapter_id": "ozon-seller-api-product-read-v1",
            "adapter_version": "1.0.0",
            "max_source_grade": "A",
            "semantic_authority": "own_listing_catalog_fact",
        },
        "scope": {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": "store-a",
            "scope_grant_authority_sha256": grant_hash,
        },
        "as_of": AS_OF.isoformat(),
    }
    return {
        **frozen,
        "adapter_contract_sha256": "c" * 64,
        "import_allowed": True,
        "external_write_allowed": False,
    }


class PilotRuns:
    def __init__(self, *, run: dict | None = None):
        self.run = run or {
            "id": "ror-1",
            "operation": "ozon.product.read",
            "status": "completed",
            "outcome": "succeeded",
            "raw_response_stored": True,
            "raw_response_verified": True,
            "raw_response_evidence_id": "evd-raw-1",
        }
        self.verified = []

    def get(self, run_id):
        return {**self.run, "id": run_id}

    def verified_product_response_bundle(self, evidence_id):
        self.verified.append(evidence_id)
        return b"verified", object()


class ScopedPilots:
    def __init__(self, pilot_runs):
        self.pilot_runs = pilot_runs
        self.calls = []

    def require_run(self, run_id, **values):
        self.calls.append({"run_id": run_id, **values})
        return self.pilot_runs.get(run_id)


class ScopedCatalog:
    def __init__(self):
        self.calls = []

    def require_import_evidence(self, **values):
        self.calls.append(values)
        return {
            "status": "ready",
            "evidence_ids": values["evidence_ids"],
            "evidence_authority_sha256": "d" * 64,
        }


class SourceAdapters:
    def catalog_contract(self, **values):
        scope = values["entity_scope"]
        return source_contract(
            tenant_ref=values["principal"].tenant_ref,
            entity_ref=scope["entity_ref"],
            grant_hash=scope["authority_sha256"],
        )


class MutableSourceAdapters(SourceAdapters):
    def __init__(self):
        self.registry_sha256 = "b" * 64

    def catalog_contract(self, **values):
        contract = super().catalog_contract(**values)
        return {
            **contract,
            "registry_sha256": self.registry_sha256,
        }


class Catalog:
    def __init__(self, failures: list[Exception] | None = None):
        self.calls = []
        self.failures = list(failures or [])

    def import_ozon_evidence(self, **values):
        self.calls.append(values)
        if self.failures:
            raise self.failures.pop(0)
        suffix = values["scope_authority"]["tenant_ref"]
        return {
            "id": f"mcs-{suffix}",
            "snapshot_hash": (
                "e" if suffix == "tenant-a" else "f"
            )
            * 64,
        }


def service(
    *,
    engine=None,
    pilot_runs=None,
    scoped_pilots=None,
    scoped_catalog=None,
    source_adapters=None,
    catalog=None,
):
    runs = pilot_runs or PilotRuns()
    return CatalogReadRunHandoffService(
        engine=engine or database(),
        pilot_runs=runs,
        scoped_pilots=scoped_pilots or ScopedPilots(runs),
        scoped_catalog=scoped_catalog or ScopedCatalog(),
        source_adapters=source_adapters or SourceAdapters(),
        catalog=catalog or Catalog(),
    )


def request(
    handoffs,
    *,
    principal_value=None,
    entity_scope_value=None,
    run_id="ror-1",
    idempotency_key="handoff-1",
    as_of=AS_OF,
):
    return handoffs.import_run(
        principal=principal_value or principal(),
        entity_scope=entity_scope_value or entity_scope(),
        store_ref="store-a",
        as_of=as_of,
        run_id=run_id,
        idempotency_key=idempotency_key,
        imported_by="operator-a",
    )


def test_successful_handoff_replays_one_catalog_snapshot():
    catalog = Catalog()
    pilots = PilotRuns()
    handoffs = service(catalog=catalog, pilot_runs=pilots)

    first = request(handoffs)
    replay = request(handoffs)

    assert first == replay
    assert first["status"] == "completed"
    assert first["catalog_snapshot_id"] == "mcs-tenant-a"
    assert first["scope"]["tenant_ref"] == "tenant-a"
    assert first["scope"]["entity_ref"] == "entity-a"
    assert first["source_adapter"]["adapter_id"] == (
        "ozon-seller-api-product-read-v1"
    )
    assert first["external_write_allowed"] is False
    assert first["automatic_product_binding"] is False
    assert len(catalog.calls) == 1
    assert catalog.calls[0]["idempotency_key"].startswith("read-run:crh_")
    assert catalog.calls[0]["evidence_ids"] == ["evd-raw-1"]
    assert pilots.verified == ["evd-raw-1", "evd-raw-1"]


def test_scoped_idempotency_conflicts_on_changed_run_and_isolates_tenants():
    handoffs = service()
    tenant_a = request(handoffs)

    with pytest.raises(ValueError, match="idempotency conflict"):
        request(handoffs, run_id="ror-2")

    tenant_b = request(
        handoffs,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_scope_value=entity_scope(
            entity_ref="entity-b",
            authority="9" * 64,
        ),
    )

    assert tenant_b["id"] != tenant_a["id"]
    assert tenant_b["catalog_snapshot_id"] == "mcs-tenant-b"


@pytest.mark.parametrize(
    "run",
    [
        {
            "operation": "ozon.finance.read",
            "status": "completed",
            "outcome": "succeeded",
            "raw_response_stored": True,
            "raw_response_verified": True,
            "raw_response_evidence_id": "evd-finance",
        },
        {
            "operation": "ozon.product.read",
            "status": "completed",
            "outcome": "failed",
            "raw_response_stored": False,
            "raw_response_verified": False,
            "raw_response_evidence_id": None,
        },
    ],
)
def test_non_product_or_failed_run_creates_no_handoff(run):
    engine = database()
    handoffs = service(engine=engine, pilot_runs=PilotRuns(run=run))

    with pytest.raises(ValueError, match="verified successful"):
        request(handoffs)

    with Session(engine) as session:
        assert session.scalars(
            select(CatalogReadRunHandoffRow)
        ).all() == []


def test_missing_entity_stops_before_read_run_or_catalog():
    class MustNotRead:
        def get(self, _):
            raise AssertionError("run must not be read without entity scope")

    class MustNotScope:
        def require_run(self, *_args, **_values):
            raise AssertionError(
                "run must not be scoped without entity authority"
            )

    handoffs = service(
        pilot_runs=MustNotRead(),
        scoped_pilots=MustNotScope(),
    )

    with pytest.raises(ValueError, match="entity scope grant"):
        request(
            handoffs,
            entity_scope_value={
                "status": "no_data",
                "entity_ref": None,
                "authority_sha256": None,
            },
        )


def test_deterministic_catalog_rejection_is_audited_blocked():
    catalog = Catalog(failures=[ValueError("bad immutable bundle")])
    handoffs = service(catalog=catalog)

    blocked = request(handoffs)
    replay = request(handoffs)

    assert blocked == replay
    assert blocked["status"] == "blocked"
    assert blocked["error_code"] == "CATALOG_IMPORT_REJECTED"
    assert blocked["catalog_snapshot_id"] is None
    assert len(catalog.calls) == 1


def test_infrastructure_failure_leaves_prepared_and_retry_completes():
    catalog = Catalog(failures=[RuntimeError("temporary database outage")])
    engine = database()
    handoffs = service(engine=engine, catalog=catalog)

    with pytest.raises(RuntimeError, match="temporary database outage"):
        request(handoffs)
    with Session(engine) as session:
        row = session.scalar(select(CatalogReadRunHandoffRow))
        assert row is not None
        assert row.status == "prepared"

    completed = request(
        handoffs,
        as_of=datetime(2026, 7, 28, 9, tzinfo=UTC),
    )

    assert completed["status"] == "completed"
    assert len(catalog.calls) == 2


def test_prepared_retry_rejects_changed_adapter_registry_under_same_key():
    catalog = Catalog(failures=[RuntimeError("temporary database outage")])
    adapters = MutableSourceAdapters()
    handoffs = service(catalog=catalog, source_adapters=adapters)

    with pytest.raises(RuntimeError, match="temporary database outage"):
        request(handoffs)

    adapters.registry_sha256 = "8" * 64
    with pytest.raises(ValueError, match="idempotency conflict"):
        request(handoffs)

    assert len(catalog.calls) == 1


def test_prepared_retry_rejects_changed_scope_grant_under_same_key():
    catalog = Catalog(failures=[RuntimeError("temporary database outage")])
    handoffs = service(catalog=catalog)

    with pytest.raises(RuntimeError, match="temporary database outage"):
        request(handoffs)

    with pytest.raises(ValueError, match="idempotency conflict"):
        request(
            handoffs,
            entity_scope_value=entity_scope(authority="7" * 64),
        )

    assert len(catalog.calls) == 1


def test_list_get_and_database_state_are_exact_scope():
    engine = database()
    handoffs = service(engine=engine)
    created = request(handoffs)
    request(
        handoffs,
        principal_value=principal(tenant_ref="tenant-b"),
        entity_scope_value=entity_scope(
            entity_ref="entity-b",
            authority="9" * 64,
        ),
    )

    listing = handoffs.list_scoped(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )
    found = handoffs.get_scoped(
        handoff_id=created["id"],
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime.now(UTC),
    )

    assert listing["counts"] == {
        "total": 1,
        "prepared": 0,
        "completed": 1,
        "blocked": 0,
    }
    assert found["id"] == created["id"]
    with pytest.raises(KeyError, match="authorized scope"):
        handoffs.get_scoped(
            handoff_id=created["id"],
            principal=principal(tenant_ref="tenant-b"),
            entity_scope=entity_scope(
                entity_ref="entity-b",
                authority="9" * 64,
            ),
            store_ref="store-a",
            as_of=datetime.now(UTC),
        )
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.execute(
            update(CatalogReadRunHandoffRow)
            .where(CatalogReadRunHandoffRow.id == created["id"])
            .values(
                status="prepared",
                catalog_snapshot_id=None,
                catalog_snapshot_hash=None,
            )
        )


def test_missing_entity_list_is_no_data_without_database_read():
    class EngineMustNotRun:
        def connect(self):
            raise AssertionError("database must not be read")

    handoffs = service()
    handoffs.engine = EngineMustNotRun()
    result = handoffs.list_scoped(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["items"] == []
    assert result["source_gaps"] == [
        "entity_scope_authority_missing"
    ]
    assert result["external_write_allowed"] is False


def test_handoff_routes_require_auth_scope_and_pass_server_authority(
    monkeypatch,
):
    captured = {}
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: entity_scope(),
    )

    def fake_import(**values):
        captured.update(values)
        return {
            "id": "crh-api",
            "status": "completed",
            "external_write_allowed": False,
        }

    monkeypatch.setattr(
        runtime.catalog_read_run_handoffs,
        "import_run",
        fake_import,
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}
    created = client.post(
        "/v1/marketplace-catalog/ozon/import-read-run",
        json={
            "run_id": "ror-api",
            "store_ref": "store-a",
            "idempotency_key": "handoff-api",
        },
        headers=headers,
    )
    forbidden = client.get(
        "/v1/marketplace-catalog/ozon/read-run-handoffs",
        params={"store_ref": "store-b"},
        headers=headers,
    )

    assert created.status_code == 201
    assert captured["principal"].tenant_ref == "tenant-a"
    assert captured["entity_scope"]["entity_ref"] == "entity-a"
    assert captured["store_ref"] == "store-a"
    assert captured["run_id"] == "ror-api"
    assert created.json()["external_write_allowed"] is False
    assert forbidden.status_code == 403
    schema = app.openapi()
    assert schema["paths"][
        "/v1/marketplace-catalog/ozon/import-read-run"
    ]["post"]["security"] == [{"KjdsApiKey": []}]
    assert schema["paths"][
        "/v1/marketplace-catalog/ozon/read-run-handoffs"
    ]["get"]["security"] == [{"KjdsApiKey": []}]


def test_handoff_routes_reject_anonymous(monkeypatch):
    def reject(_):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    client = TestClient(app)

    assert (
        client.post(
            "/v1/marketplace-catalog/ozon/import-read-run",
            json={
                "run_id": "ror-api",
                "store_ref": "store-a",
                "idempotency_key": "handoff-api",
            },
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/v1/marketplace-catalog/ozon/read-run-handoffs",
            params={"store_ref": "store-a"},
        ).status_code
        == 401
    )
