from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

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
from scripts.extract_ru002_logistics_evidence import EvidenceHit, structured_records
from scripts.package_market_recon_bundle import (
    DEFAULT_OUTPUT,
    SOURCE_ROOT,
    package_bundle,
)

AS_OF = datetime(2026, 8, 2, 7, tzinfo=UTC)
CORE_SOURCE_TOTAL = 372
CORE_ACCEPTED_TOTAL = 47
CORE_QUARANTINED_TOTAL = 325

pytestmark = pytest.mark.skipif(
    not all(
        (SOURCE_ROOT / name).is_file()
        for name in (
            "full_catalog.json",
            "full_product_info.json",
            "analytics_by_window.json",
            "finance_by_month.json",
            "supply_1688/supply_crawl.json",
        )
    ),
    reason="market-recon business fixtures are not committed",
)


def logistics_record() -> dict[str, object]:
    return structured_records(
        [
            EvidenceHit(
                source_relpath="wuliu/provider.xlsx",
                sha256="b" * 64,
                kind="xlsx",
                location="Rates!A12:F12",
                excerpt="OZON 运费 50元/kg",
                currency="CNY",
            )
        ]
    )[0]


def rehash_observation(record: dict[str, object]) -> None:
    payload = dict(record)
    payload.pop("observation_sha256", None)
    record["observation_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def bundle_member_names(content: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {info.filename for info in archive.infolist() if not info.is_dir()}


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


def test_packager_does_not_implicitly_read_logistics_user_files(
    real_bundle: bytes,
) -> None:
    names = bundle_member_names(real_bundle)

    assert "logistics_evidence_hits.json" not in names
    assert not any(name.startswith("wuliu/") for name in names)


def test_explicit_logistics_artifact_is_retained_idempotently_and_fails_closed(
    tmp_path: Path,
) -> None:
    valid = logistics_record()
    tampered = dict(valid)
    tampered["mapped_cost_legs"] = ["customs"]
    prematurely_bound = dict(valid)
    prematurely_bound["sku_binding"] = "SKU-MUST-NOT-BIND"
    rehash_observation(prematurely_bound)
    extra_field = dict(valid)
    extra_field["fee_amount"] = "50"
    rehash_observation(extra_field)
    authority_overclaim = dict(valid)
    authority_overclaim["evidence_level"] = "reviewed"
    rehash_observation(authority_overclaim)
    records = [
        valid,
        tampered,
        "schema-error",
        prematurely_bound,
        extra_field,
        authority_overclaim,
    ]
    observations_path = tmp_path / "logistics-observations.json"
    observations_path.write_text(
        json.dumps(records, ensure_ascii=False),
        encoding="utf-8",
    )
    content = package_bundle(
        tmp_path / "market-recon-with-logistics.zip",
        logistics_observations_path=observations_path,
    ).read_bytes()
    assert "logistics_evidence_hits.json" in bundle_member_names(content)
    assert not any(
        name.startswith("wuliu/") for name in bundle_member_names(content)
    )

    engine = database()
    ingestion = MarketReconBundleIngestion(
        engine=engine,
        evidence=EvidenceService(engine),
    )
    preflight = ingestion.preflight(
        content,
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    browser_count = preflight["quality"]["artifact_record_counts"][
        "browser_capture"
    ]
    assert preflight["quality"]["artifact_record_counts"][
        "logistics_observation"
    ] == 6
    assert preflight["counts"] == {
        "source_total": CORE_SOURCE_TOTAL + browser_count + 6,
        "accepted": CORE_ACCEPTED_TOTAL + browser_count + 1,
        "quarantined": CORE_QUARANTINED_TOTAL + 5,
    }
    assert preflight["quality"]["reason_counts"][
        "logistics_observation_identity_missing"
    ] == 1
    assert preflight["quality"]["reason_counts"][
        "logistics_observation_premature_binding_or_amount"
    ] == 1
    assert preflight["quality"]["reason_counts"][
        "logistics_observation_schema_invalid"
    ] == 2
    assert preflight["quality"]["reason_counts"][
        "logistics_observation_authority_overclaimed"
    ] == 1

    kwargs = {
        "filename": "market-recon-with-logistics.zip",
        "idempotency_key": "explicit-logistics-v1",
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
    }
    first = ingestion.ingest(content, **kwargs)
    replay = ingestion.ingest(content, **kwargs)
    assert replay["bundle_id"] == first["bundle_id"]
    assert replay["idempotent"] is True

    with Session(engine) as session:
        items = session.scalars(
            select(MarketReconBundleItemRow).where(
                MarketReconBundleItemRow.bundle_id == first["bundle_id"],
                MarketReconBundleItemRow.artifact_kind
                == "logistics_observation",
            )
        ).all()
    assert len(items) == 6
    accepted = [item for item in items if item.disposition == "accepted"]
    assert len(accepted) == 1
    assert accepted[0].record_key == valid["observation_id"]
    assert accepted[0].highest_stage == "normalized_observation"
    assert accepted[0].reason_codes_json == [
        "exact_quantity_missing",
        "independent_cost_review_pending",
        "sku_binding_missing",
        "variant_identity_unresolved",
    ]
    assert ingestion.quality(
        first["bundle_id"],
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )["conservation_passed"] is True


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
