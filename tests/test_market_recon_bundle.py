from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceRecordRow, EvidenceService
from apps.control_plane.market_recon_bundle import (
    BundleContentConflict,
    MarketReconBundleIngestion,
    MarketReconBundleItemRow,
    MarketReconBundleRunRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from scripts.package_market_recon_bundle import DEFAULT_OUTPUT, package_bundle

AS_OF = datetime(2026, 8, 2, 7, tzinfo=UTC)
CORE_SOURCE_TOTAL = 372
CORE_ACCEPTED_TOTAL = 47
CORE_QUARANTINED_TOTAL = 325


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def principal(*, tenant_ref: str = "tenant-a", stores: frozenset[str] = frozenset({"store-a"})) -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=stores,
    )


def entity_scope(*, entity_ref: str = "entity-a") -> dict:
    return {"status": "ready", "entity_ref": entity_ref, "authority_sha256": "a" * 64}


@pytest.fixture(scope="module")
def real_bundle() -> bytes:
    return package_bundle(DEFAULT_OUTPUT).read_bytes()


def test_preflight_counts_every_real_source_record_without_writes(real_bundle: bytes) -> None:
    engine = database()
    ingestion = MarketReconBundleIngestion(engine=engine, evidence=EvidenceService(engine))

    result = ingestion.preflight(
        real_bundle,
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["writes_performed"] is False
    artifact_counts = result["quality"]["artifact_record_counts"]
    browser_capture_count = artifact_counts["browser_capture"]
    assert result["counts"] == {
        "source_total": CORE_SOURCE_TOTAL + browser_capture_count,
        "accepted": CORE_ACCEPTED_TOTAL + browser_capture_count,
        "quarantined": CORE_QUARANTINED_TOTAL,
    }
    assert artifact_counts == {
        "browser_capture": browser_capture_count,
        "ozon_analytics": 2,
        "ozon_catalog": 18,
        "ozon_finance": 12,
        "ozon_product_info": 18,
        "supplier_catalog": 322,
    }
    assert result["quality"]["complete_source_retention"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MarketReconBundleRunRow)) == 0
        assert session.scalar(select(func.count()).select_from(EvidenceRecordRow)) == 0


def test_ingestion_is_conservative_idempotent_and_scope_isolated(real_bundle: bytes) -> None:
    engine = database()
    ingestion = MarketReconBundleIngestion(engine=engine, evidence=EvidenceService(engine))

    first = ingestion.ingest(
        real_bundle,
        filename="market_recon_bundle.zip",
        idempotency_key="real-market-recon-20260802",
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    replay = ingestion.ingest(
        real_bundle,
        filename="market_recon_bundle.zip",
        idempotency_key="real-market-recon-20260802",
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert first["counts"]["accepted"] + first["counts"]["quarantined"] == first["counts"]["source_total"]
    assert replay["bundle_id"] == first["bundle_id"]
    assert replay["idempotent"] is True
    assert ingestion.quality(
        first["bundle_id"],
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )["conservation_passed"] is True

    with Session(engine) as session:
        items = session.scalars(
            select(MarketReconBundleItemRow).where(MarketReconBundleItemRow.bundle_id == first["bundle_id"])
        ).all()
        finance = [item for item in items if item.artifact_kind == "ozon_finance"]
        suppliers = [item for item in items if item.artifact_kind == "supplier_catalog"]
        assert len(items) == first["counts"]["source_total"]
        assert len(finance) == 12
        finance_with_operations = [item for item in finance if item.payload_json.get("operations")]
        empty_finance_windows = [item for item in finance if not item.payload_json.get("operations")]
        assert len(finance_with_operations) == 3
        assert len(empty_finance_windows) == 9
        assert all(item.disposition == "quarantined" for item in finance_with_operations)
        assert all("money_currency_missing" in item.reason_codes_json for item in finance_with_operations)
        assert all(item.disposition == "accepted" for item in empty_finance_windows)
        assert len(suppliers) == 322
        assert all(item.disposition == "quarantined" for item in suppliers)
        assert all("variant_identity_unresolved" in item.reason_codes_json for item in suppliers)

    with pytest.raises(KeyError, match="authorized scope"):
        ingestion.get(
            first["bundle_id"],
            principal=principal(tenant_ref="tenant-b"),
            entity_scope=entity_scope(entity_ref="entity-b"),
            store_ref="store-a",
            as_of=AS_OF,
        )


def test_same_idempotency_key_rejects_content_drift(real_bundle: bytes) -> None:
    engine = database()
    ingestion = MarketReconBundleIngestion(engine=engine, evidence=EvidenceService(engine))
    kwargs = {
        "filename": "market_recon_bundle.zip",
        "idempotency_key": "stable-key",
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
    }
    ingestion.ingest(real_bundle, **kwargs)

    with pytest.raises(BundleContentConflict, match="different immutable content"):
        ingestion.ingest(real_bundle + b"drift", **kwargs)
