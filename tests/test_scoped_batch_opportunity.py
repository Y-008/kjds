from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.batch_opportunity import (
    BatchOpportunityRunRow,
    BatchOpportunityWorkspace,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_batch_opportunity import (
    ScopedBatchOpportunityAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal

AS_OF = datetime(2026, 7, 28, 6, tzinfo=UTC)


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
    authority_sha256: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority_sha256,
    }


def observation(
    *,
    marketplace: str,
    currency: str,
    evidence_id: str,
) -> dict:
    return {
        "id": f"obs-{marketplace}",
        "marketplace": marketplace,
        "currency": currency,
        "evidence_id": evidence_id,
    }


class ScopedObservations:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def collect(self, **values):
        self.calls.append(values)
        marketplace = values["marketplace"]
        items = list(self.rows.get(marketplace, []))
        return {
            "status": "ready" if items else "no_data",
            "items": items,
            "source_gaps": [] if items else ["observation_not_available"],
            "blockers": [],
            "snapshot_sha256": (
                ("1" if marketplace == "ozon" else "2") * 64
            ),
            "pagination": {"truncated": False},
        }


class ScopedCatalog:
    def __init__(self, *, status: str = "no_data") -> None:
        self.status = status
        self.calls: list[dict] = []

    def latest(self, **values):
        self.calls.append(values)
        return {
            "status": self.status,
            "items": [],
            "source_gaps": (
                []
                if self.status == "ready"
                else ["catalog_not_available"]
            ),
            "blockers": (
                [{"code": "catalog_evidence_integrity_invalid"}]
                if self.status == "blocked"
                else []
            ),
            "snapshot_sha256": "3" * 64,
        }


class ScopedEvidence:
    def __init__(self, *, status: str = "ready") -> None:
        self.status = status
        self.calls: list[dict] = []

    def project_targets(self, *, evidence_ids, **values):
        self.calls.append(
            {"evidence_ids": list(evidence_ids), **values}
        )
        records = [
            {
                "evidence_id": evidence_id,
                "sha256": "e" * 64,
                "scope_binding": {
                    "status": "ready",
                    "reasons": [],
                },
            }
            for evidence_id in evidence_ids
        ]
        return {
            "status": self.status,
            "records": records if self.status == "ready" else [],
            "invalid_evidence_ids": (
                [] if self.status == "ready" else list(evidence_ids)
            ),
            "binding_authority_sha256": "b" * 64,
            "blockers": (
                []
                if self.status == "ready"
                else [{"code": "evidence_integrity_invalid"}]
            ),
        }


class Finance:
    def __init__(self, rates=None) -> None:
        self.rates = list(rates or [])
        self.calls: list[str] = []

    def list_fx_rates(self, *, base_currency: str):
        self.calls.append(base_currency)
        return [
            item
            for item in self.rates
            if item.base_currency == base_currency
        ]


class Batch:
    def __init__(self, *, finance=None) -> None:
        self.finance = finance or Finance()
        self.prepare_calls: list[dict] = []
        self.latest_calls: list[dict] = []

    def prepare(self, **values):
        self.prepare_calls.append(values)
        return {
            "contract_version": "batch-opportunity/1.3.0",
            "scope": values["scope_authority"],
            "counts": {"observed": len(values["scoped_observations"])},
            "candidates": [{"fingerprint": "candidate-a"}],
            "blockers": [],
            "ozon_global_cn_rule_registry": {
                "source_evidence_gaps": [],
            },
            "snapshot_sha256": "9" * 64,
        }

    def latest_scoped(self, **values):
        self.latest_calls.append(values)
        return None


def authority(
    *,
    batch=None,
    observations=None,
    catalog=None,
    evidence=None,
) -> ScopedBatchOpportunityAuthority:
    return ScopedBatchOpportunityAuthority(
        batch=batch or Batch(),
        scoped_observations=observations
        or ScopedObservations({}),
        scoped_catalog=catalog or ScopedCatalog(),
        scoped_evidence=evidence or ScopedEvidence(),
        rules=object(),
    )


def prepare_values() -> dict:
    return {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
        "policy_id": "cn-ozon-observed-cost-v1",
        "idempotency_key": "scope-run-a",
        "candidate_limit": 100,
        "pilot_limit": 3,
        "target_purchase_quantity": 3,
        "max_age_hours": 72,
        "max_inventory_cash_cny": "3000",
        "cm3_floor_cny": "0",
        "actor_id": "operator-a",
        "full_evaluate_limit": 100,
        "scan_page_size": 100,
        "scan_shard_count": 1,
        "scan_shard_index": 0,
        "max_batch_inventory_cash_cny": "9000",
    }


def test_missing_entity_returns_no_data_without_reading_any_child():
    class MustNotRead:
        def __getattr__(self, _name):
            raise AssertionError("scoped child must not be read")

    service = authority(
        batch=MustNotRead(),
        observations=MustNotRead(),
        catalog=MustNotRead(),
        evidence=MustNotRead(),
    )
    result = service.prepare(
        **{
            **prepare_values(),
            "entity_scope": {
                "status": "no_data",
                "entity_ref": None,
                "reason": "entity_scope_authority_missing",
            },
        }
    )

    assert result["status"] == "no_data"
    assert result["scope"]["entity_ref"] is None
    assert result["candidates"] == []
    assert result["control_envelope"]["external_write_allowed"] is False


def test_cross_store_is_rejected_before_reading_children():
    service = authority()

    with pytest.raises(PermissionError):
        service.prepare(
            **{
                **prepare_values(),
                "store_ref": "store-b",
            }
        )


def test_missing_scoped_fx_returns_no_data_without_creating_run():
    batch = Batch(finance=Finance())
    service = authority(
        batch=batch,
        observations=ScopedObservations(
            {
                "ozon": [
                    observation(
                        marketplace="ozon",
                        currency="RUB",
                        evidence_id="evd-ozon",
                    )
                ],
                "1688": [
                    observation(
                        marketplace="1688",
                        currency="CNY",
                        evidence_id="evd-supplier",
                    )
                ],
            }
        ),
    )

    result = service.prepare(**prepare_values())

    assert result["status"] == "no_data"
    assert "scoped_fx_rate_missing:RUB/CNY" in result["source_gaps"]
    assert batch.prepare_calls == []
    assert result["control_envelope"]["candidate_scoring_allowed"] is False


def test_bad_component_evidence_blocks_before_creating_run():
    batch = Batch()
    service = authority(
        batch=batch,
        observations=ScopedObservations(
            {
                "ozon": [
                    observation(
                        marketplace="ozon",
                        currency="CNY",
                        evidence_id="evd-ozon",
                    )
                ],
                "1688": [
                    observation(
                        marketplace="1688",
                        currency="CNY",
                        evidence_id="evd-supplier",
                    )
                ],
            }
        ),
        evidence=ScopedEvidence(status="blocked"),
    )

    result = service.prepare(**prepare_values())

    assert result["status"] == "blocked"
    assert "scoped_batch_component_evidence_not_ready" in result[
        "source_gaps"
    ]
    assert batch.prepare_calls == []


def test_catalog_integrity_blocker_stops_scoring():
    batch = Batch()
    service = authority(
        batch=batch,
        observations=ScopedObservations(
            {
                "ozon": [
                    observation(
                        marketplace="ozon",
                        currency="CNY",
                        evidence_id="evd-ozon",
                    )
                ],
                "1688": [
                    observation(
                        marketplace="1688",
                        currency="CNY",
                        evidence_id="evd-supplier",
                    )
                ],
            }
        ),
        catalog=ScopedCatalog(status="blocked"),
    )

    result = service.prepare(**prepare_values())

    assert result["status"] == "blocked"
    assert batch.prepare_calls == []


def test_complete_cny_inputs_freeze_scope_and_create_research_run():
    batch = Batch()
    observations = ScopedObservations(
        {
            "ozon": [
                observation(
                    marketplace="ozon",
                    currency="CNY",
                    evidence_id="evd-ozon",
                )
            ],
            "1688": [
                observation(
                    marketplace="1688",
                    currency="CNY",
                    evidence_id="evd-supplier",
                )
            ],
        }
    )
    service = authority(
        batch=batch,
        observations=observations,
        catalog=ScopedCatalog(status="no_data"),
    )

    result = service.prepare(**prepare_values())

    assert result["status"] == "ready_with_constraints"
    call = batch.prepare_calls[0]
    assert call["scope_authority"]["tenant_ref"] == "tenant-a"
    assert call["scope_authority"]["entity_ref"] == "entity-a"
    assert call["scope_authority"]["store_ref"] == "store-a"
    assert len(
        call["scope_authority"]["scoped_economics_snapshot_sha256"]
    ) == 64
    assert call["scoped_fx_rates"] == {}
    assert result["control_envelope"]["internal_research_run_created"] is True
    assert result["control_envelope"]["approval_created"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_fx_snapshot_is_as_of_scoped_and_passed_to_evaluator():
    fx = SimpleNamespace(
        id="fx-rub-cny",
        base_currency="RUB",
        quote_currency="CNY",
        rate="0.081",
        version=2,
        effective_at="2026-07-28T02:00:00+00:00",
        source="central-bank",
        evidence_id="evd-fx",
        created_by="finance-reviewer",
        recorded_at="2026-07-28T03:00:00+00:00",
    )
    batch = Batch(finance=Finance([fx]))
    scoped_evidence = ScopedEvidence()
    service = authority(
        batch=batch,
        observations=ScopedObservations(
            {
                "ozon": [
                    observation(
                        marketplace="ozon",
                        currency="RUB",
                        evidence_id="evd-ozon",
                    )
                ],
                "1688": [
                    observation(
                        marketplace="1688",
                        currency="CNY",
                        evidence_id="evd-supplier",
                    )
                ],
            }
        ),
        evidence=scoped_evidence,
    )

    result = service.prepare(**prepare_values())

    assert result["status"] == "ready_with_constraints"
    call = batch.prepare_calls[0]
    assert call["scoped_fx_rates"]["RUB"]["id"] == "fx-rub-cny"
    assert "evd-fx" in scoped_evidence.calls[0]["evidence_ids"]
    assert result["control_envelope"]["formal_cm3_created"] is False


def test_latest_without_entity_does_not_read_run_table():
    batch = Batch()
    service = authority(batch=batch)

    result = service.latest(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert batch.latest_calls == []


def test_scoped_fx_path_never_falls_back_to_global_finance():
    class MustNotReadFinance:
        @staticmethod
        def list_fx_rates(**_values):
            raise AssertionError("global FX authority must not be read")

    workspace = BatchOpportunityWorkspace(
        engine=object(),
        observations=object(),
        evidence=object(),
        finance=MustNotReadFinance(),
        repository=object(),
        operating_tasks=object(),
    )

    amount, rate = workspace._to_cny(
        amount=Decimal("100"),
        currency="RUB",
        as_of=AS_OF,
        scoped_fx_rates={},
    )

    assert amount is None
    assert rate is None


def test_run_table_rejects_partial_scope_and_scopes_idempotency():
    database = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    BatchOpportunityRunRow.__table__.create(database)
    insert = text(
        """
        INSERT INTO batch_opportunity_runs (
            id, store_ref, tenant_ref, entity_ref,
            scope_grant_authority_sha256,
            scope_evidence_authority_sha256,
            idempotency_key, policy_id, contract_version,
            snapshot_sha256, evidence_id, as_of, created_by, created_at,
            counts_json, policy_json, blockers_json, payload_json, task_id
        ) VALUES (
            :id, 'store-a', :tenant_ref, :entity_ref,
            :grant_hash, :evidence_hash,
            'same-key', 'policy', 'contract',
            :snapshot_hash, 'evd-derived', :as_of, 'actor', :as_of,
            '{}', '{}', '[]', '{}', NULL
        )
        """
    )
    base = {
        "entity_ref": "entity-a",
        "grant_hash": "a" * 64,
        "evidence_hash": "b" * 64,
        "snapshot_hash": "c" * 64,
        "as_of": AS_OF,
    }
    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            insert,
            {
                **base,
                "id": "partial",
                "tenant_ref": "tenant-a",
                "entity_ref": None,
            },
        )
    with database.begin() as connection:
        connection.execute(
            insert,
            {**base, "id": "tenant-a", "tenant_ref": "tenant-a"},
        )
        connection.execute(
            insert,
            {**base, "id": "tenant-b", "tenant_ref": "tenant-b"},
        )
    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            insert,
            {**base, "id": "tenant-a-duplicate", "tenant_ref": "tenant-a"},
        )


def test_batch_routes_require_auth_store_and_entity_scope(monkeypatch):
    def reject_missing_key(_key):
        raise AuthenticationFailure("API key required", 401)

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        reject_missing_key,
    )
    client = TestClient(app)
    assert client.get("/v1/batch-opportunities/latest").status_code == 401
    assert (
        client.post(
            "/v1/batch-market-scans",
            json={"idempotency_key": "anonymous"},
        ).status_code
        == 401
    )

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(),
    )
    headers = {"X-KJDS-API-Key": "test-key"}
    assert (
        client.get(
            "/v1/batch-opportunities/latest",
            params={"store_ref": "store-b"},
            headers=headers,
        ).status_code
        == 403
    )

    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
            "authority_sha256": None,
        },
    )

    class MustNotRead:
        def __getattr__(self, _name):
            raise AssertionError("raw Batch authority must not be read")

    monkeypatch.setattr(
        runtime.scoped_batch_opportunity,
        "batch",
        MustNotRead(),
    )
    response = client.get(
        "/v1/batch-opportunities/latest",
        params={
            "store_ref": "store-a",
            "as_of": AS_OF.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["candidates"] == []
    assert (
        response.json()["control_envelope"]["external_write_allowed"]
        is False
    )

    response = client.post(
        "/v1/batch-market-scans",
        json={
            "store_ref": "store-a",
            "idempotency_key": "missing-entity",
            "as_of": AS_OF.isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 409
