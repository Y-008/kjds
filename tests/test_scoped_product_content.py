from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.batch_opportunity import BatchOpportunityWorkspace
from apps.control_plane.domain import (
    ContentAsset,
    ContentStatus,
    ContentType,
    Passport,
    PassportType,
    Product,
)
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.media_jobs import (
    EDITING_TARGET_CHANNELS,
    FFMPEG_RENDER_PROFILE_SHA256,
    MediaJobScope,
    MediaJobWorkerInputProjection,
    canonical_json,
    sha256_bytes,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_product_content import (
    ScopedProductContentAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.sql_repository import (
    Base,
    ProductRow,
    SqlAlchemyRepository,
)

AS_OF = datetime(2026, 7, 28, 10, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute(
            "PRAGMA foreign_keys=ON"
        ),
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
    authority_sha256: str = "a" * 64,
) -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority_sha256,
    }


class Catalog:
    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.calls = 0

    def latest(self, **_):
        self.calls += 1
        return {
            "contract_id": "kjds-scoped-marketplace-catalog-v1",
            "status": "ready" if self.items else "no_data",
            "items": self.items,
            "source_gaps": [] if self.items else ["catalog_not_available"],
            "blockers": [],
            "snapshot_sha256": "c" * 64,
        }


class Evidence:
    def __init__(self, *, blocked: set[str] | None = None):
        self.blocked = blocked or set()

    def project_targets(self, *, evidence_ids, **_):
        invalid = sorted(set(evidence_ids) & self.blocked)
        records = [
            {
                "evidence_id": evidence_id,
                "sha256": evidence_id[-1:] * 64,
                "scope_binding": {
                    "status": (
                        "blocked"
                        if evidence_id in self.blocked
                        else "ready"
                    ),
                    "reasons": (
                        ["tenant_ref_mismatch"]
                        if evidence_id in self.blocked
                        else []
                    ),
                },
            }
            for evidence_id in evidence_ids
        ]
        return {
            "status": "blocked" if invalid else "ready",
            "records": records,
            "invalid_evidence_ids": invalid,
            "binding_authority_sha256": "e" * 64,
            "source_gaps": (
                ["evidence_scope_conflict"] if invalid else []
            ),
            "blockers": [],
        }


class Sourcing:
    def __init__(self):
        self.store = SimpleNamespace(
            get_offer=self._missing,
            get_scenario=self._missing,
        )
        self.approvals_created = 0

    @staticmethod
    def _missing(_):
        raise KeyError("not found")

    @staticmethod
    def require_release_ready(_):
        raise AssertionError("missing scenario cannot be release ready")


def authority(
    repo,
    *,
    catalog: Catalog | None = None,
    evidence: Evidence | None = None,
):
    source = catalog or Catalog()
    return (
        source,
        ScopedProductContentAuthority(
            repository=repo,
            scoped_catalog=source,
            scoped_evidence=evidence or Evidence(),
            sourcing=Sourcing(),
        ),
    )


def native_product(
    *,
    sku: str,
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    product_id: str | None = None,
) -> Product:
    values = {
        "sku": sku,
        "name": f"Product {sku}",
        "created_at": "2026-07-28T01:00:00+00:00",
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
        "scope_grant_authority_sha256": "a" * 64,
        "scope_as_of": "2026-07-28T01:00:00+00:00",
        "created_by": "operator-a",
    }
    if product_id:
        values["id"] = product_id
    return Product(**values)


def approved_facts(kind: PassportType) -> dict:
    values = {
        PassportType.PRODUCT: {
            "material": "steel",
            "intended_use": "storage",
            "country_of_origin": "CN",
            "weight_kg": "1",
            "dimensions_cm": "10x10x10",
        },
        PassportType.COMPLIANCE: {
            "hs_code": "0000",
            "eaeu_rules": "checked",
            "eac_requirement": "not_applicable",
            "chestny_znak_requirement": "not_applicable",
            "russian_labeling": "required",
            "ip_status": "cleared",
            "transport_restrictions": "none",
            "sellability": "allowed",
        },
        PassportType.QUALITY: {
            "golden_sample_ref": "sample-1",
            "inspection_plan": "plan-1",
            "packaging_test": "passed",
        },
    }[kind]
    return {"decision": "approved", **values}


def _editing_source_authority(
    *,
    rights_status: str = "approved",
    blocked_subtitle: bool = False,
    noncanonical_analysis: bool = False,
):
    engine = database()
    repo = SqlAlchemyRepository(engine)
    product = repo.add_product(
        native_product(sku="editing-source", product_id="product-editing")
    )
    evidence_service = EvidenceService(engine)
    campaign_record = evidence_service.capture(
        content=b"campaign artifact",
        filename="campaign.jpg",
        content_type="image/jpeg",
        source="https://example.test/campaign",
        source_ref="campaign-artifact",
        grade=EvidenceGrade.B,
        effective_at=AS_OF.isoformat(),
        effective_until=None,
        created_by="operator-a",
        metadata={"rights_status": rights_status},
    )
    subtitle_record = evidence_service.capture(
        content=b"1\n00:00:00,000 --> 00:00:03,000\nBAS-186\n",
        filename="subtitle.srt",
        content_type="application/x-subrip",
        source="https://example.test/subtitle",
        source_ref="editing-subtitle",
        grade=EvidenceGrade.B,
        effective_at=AS_OF.isoformat(),
        effective_until=None,
        created_by="operator-a",
        metadata={"rights_status": rights_status},
    )
    caption_record = evidence_service.capture(
        content=b"1\n00:00:00,000 --> 00:00:03,000\nScene caption\n",
        filename="caption.srt",
        content_type="application/x-subrip",
        source="https://example.test/caption",
        source_ref="editing-caption",
        grade=EvidenceGrade.B,
        effective_at=AS_OF.isoformat(),
        effective_until=None,
        created_by="operator-a",
        metadata={"rights_status": rights_status},
    )
    video_record = evidence_service.capture(
        content=b"\x00\x00\x00\x18ftypisomgoverned-video",
        filename="reference.mp4",
        content_type="video/mp4",
        source="https://example.test/reference-video",
        source_ref="reference-video",
        grade=EvidenceGrade.B,
        effective_at=AS_OF.isoformat(),
        effective_until=None,
        created_by="operator-a",
        metadata={"rights_status": rights_status},
    )
    audio_record = evidence_service.capture(
        content=b"RIFF\x04\x00\x00\x00WAVE",
        filename="audio.wav",
        content_type="audio/wav",
        source="https://example.test/audio",
        source_ref="editing-audio",
        grade=EvidenceGrade.B,
        effective_at=AS_OF.isoformat(),
        effective_until=None,
        created_by="operator-a",
        metadata={"rights_status": rights_status},
    )
    source_video_artifacts = [
        {
            "content_asset_ref": "content-asset://reference-video",
            "evidence_ref": f"evidence://{video_record.id}",
            "evidence_sha256": video_record.sha256,
        }
    ]
    analysis_run_ref = "analysis-editing-source"
    analysis = {
        "contract_id": "kjds-reference-video-analysis-v1",
        "schema_version": "1.0.0",
        "analysis_run_ref": analysis_run_ref,
        "observed_at": AS_OF.isoformat(),
        "source_video_artifacts": source_video_artifacts,
        "scenes": [
            {
                "scene_id": "scene-1",
                "source_asset_ref": "content-asset://reference-video",
                "source_start_ms": 0,
                "source_end_ms": 3000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 3000,
                "transition": "cut",
                "caption_ref": f"evidence://{caption_record.id}",
            }
        ],
        "target_channels": list(EDITING_TARGET_CHANNELS),
        "subtitle_asset_ref": f"evidence://{subtitle_record.id}",
    }
    canonical_analysis_bytes = canonical_json(analysis)
    analysis_bytes = (
        json.dumps(analysis, ensure_ascii=False, indent=2).encode()
        if noncanonical_analysis
        else canonical_analysis_bytes
    )
    analysis_sha256 = sha256_bytes(canonical_analysis_bytes)
    with Session(engine) as session, session.begin():
        analysis_record = evidence_service.capture_media_job_evidence(
            content=analysis_bytes,
            filename="analysis.json",
            content_type="application/json",
            source="governed-reference-video-analysis",
            source_ref=f"reference-analysis://{analysis_run_ref}/{analysis_sha256}",
            grade=EvidenceGrade.B,
            effective_at=AS_OF.isoformat(),
            recorded_at=AS_OF.isoformat(),
            created_by="operator-a",
            metadata={
            "rights_status": rights_status,
            "contract_id": "kjds-reference-video-analysis-v1",
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "scope_grant_authority_sha256": "a" * 64,
            "subject_actor_id": "operator-a",
            "analysis_run_ref": analysis_run_ref,
            "analysis_contract_sha256": analysis_sha256,
            "source_video_artifacts_sha256": sha256_bytes(
                canonical_json(source_video_artifacts)
            ),
            "schema_version": "1.0.0",
            "observed_at": AS_OF.isoformat(),
            },
            session=session,
        )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="ozon",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref=campaign_record.id,
            id="campaign-asset",
            created_at=AS_OF.isoformat(),
        )
    )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.VIDEO,
            locale="ru-RU",
            channel="ozon",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref=video_record.id,
            id="reference-video",
            created_at=AS_OF.isoformat(),
        )
    )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.COPY,
            locale="ru-RU",
            channel="ozon",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref=audio_record.id,
            id="audio-asset",
            created_at=AS_OF.isoformat(),
        )
    )
    worker = MediaJobWorkerInputProjection(
        job_ref="media-job-editing",
        tool_name="media.video_blueprint",
        tool_version="1.0.0",
        payload={
            "campaign_content_asset_refs": [
                "content-asset://campaign-asset"
            ],
            "reference_asset_refs": [
                "content-asset://reference-video"
            ],
            "source_asset_refs": [],
            "audio_asset_refs": ["content-asset://audio-asset"],
            "editing_blueprint_ref": None,
            "analysis_evidence_ref": f"evidence://{analysis_record.id}",
            "analysis_contract_sha256": analysis_sha256,
            "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
            "target_channels": list(EDITING_TARGET_CHANNELS),
        },
        worker_input_sha256="b" * 64,
        evidence_id="worker-input-evidence",
        recorded_at=AS_OF.isoformat(),
    )

    class Jobs:
        def current_scope(self, **_):
            return MediaJobScope(
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="store-a",
                authority_sha256="a" * 64,
                subject_actor_id="operator-a",
            )

        def read_worker_input(self, **_):
            return worker

    scoped = ScopedProductContentAuthority(
        repository=repo,
        scoped_catalog=Catalog(),
        scoped_evidence=Evidence(
            blocked={subtitle_record.id} if blocked_subtitle else set()
        ),
        sourcing=Sourcing(),
        evidence=evidence_service,
        media_jobs=Jobs(),
    )
    scope = MediaJobScope(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_sha256="a" * 64,
        subject_actor_id="operator-a",
    )
    return scoped, scope


def test_editing_source_is_server_built_from_scoped_approved_assets():
    scoped, current_scope = _editing_source_authority()

    source = scoped.read_editing_source(
        principal=principal(),
        store_ref="store-a",
        job_ref="media-job-editing",
        scope=current_scope,
        as_of=AS_OF,
    )

    assert source["product_id"] == "product-editing"
    assert source["rights_status"] == "approved"
    assert source["reference_asset_refs"] == [
        "content-asset://reference-video"
    ]
    assert source["scope"]["authority_sha256"] == "a" * 64
    assert len(source["analysis_receipt"]["source_snapshot_sha256"]) == 64
    assert len(source["source_snapshot_sha256"]) == 64
    assert (
        source["analysis_receipt"]["semantic_sha256"]
        == source["analysis_receipt"]["evidence_sha256"]
    )


def test_editing_source_rejects_rights_or_current_scope_drift():
    scoped, current_scope = _editing_source_authority(rights_status="unknown")
    with pytest.raises(ValueError, match="rights"):
        scoped.read_editing_source(
            principal=principal(),
            store_ref="store-a",
            job_ref="media-job-editing",
            scope=current_scope,
            as_of=AS_OF,
        )


def test_editing_source_rejects_subtitle_outside_current_scope():
    scoped, current_scope = _editing_source_authority(blocked_subtitle=True)

    with pytest.raises(ValueError, match="exact tenant/entity/store scope"):
        scoped.read_editing_source(
            principal=principal(),
            store_ref="store-a",
            job_ref="media-job-editing",
            scope=current_scope,
            as_of=AS_OF,
        )


def test_editing_source_rejects_jointly_resealed_noncanonical_analysis_bytes():
    with pytest.raises(ValueError, match="Evidence canonical JSON"):
        _editing_source_authority(noncanonical_analysis=True)

    scoped, current_scope = _editing_source_authority()
    drifted = MediaJobScope(
        tenant_ref=current_scope.tenant_ref,
        entity_ref=current_scope.entity_ref,
        store_ref=current_scope.store_ref,
        authority_sha256="f" * 64,
        subject_actor_id=current_scope.subject_actor_id,
    )
    with pytest.raises(PermissionError, match="scope_binding"):
        scoped.read_editing_source(
            principal=principal(),
            store_ref="store-a",
            job_ref="media-job-editing",
            scope=drifted,
            as_of=AS_OF,
        )


def test_missing_entity_scope_performs_no_raw_product_or_catalog_read():
    class RawMustNotRun:
        def __getattr__(self, _):
            raise AssertionError("raw Product/content must not be read")

    result = ScopedProductContentAuthority(
        repository=RawMustNotRun(),
        scoped_catalog=RawMustNotRun(),
        scoped_evidence=RawMustNotRun(),
        sourcing=RawMustNotRun(),
    ).project(
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
    assert result["products"] == []
    assert result["control_envelope"]["raw_product_content_read"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_native_product_scope_excludes_other_tenant_and_store():
    repo = SqlAlchemyRepository(database())
    allowed = repo.add_product(native_product(sku="same-sku"))
    repo.add_product(
        native_product(
            sku="same-sku",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )
    catalog, scoped = authority(repo)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "partial"
    assert [item["product"]["id"] for item in result["products"]] == [
        allowed.id
    ]
    assert result["products"][0]["scope_authority"] == (
        "native_product_scope"
    )
    assert catalog.calls == 1


def test_batch_candidate_source_lineage_survives_in_pim_projection():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="source-lineage"))
    repo.append_event(
        "product.created_from_batch_opportunity",
        product.id,
        {
            "references": {
                "competitive_market_url": "https://www.ozon.ru/product/1/",
                "primary_supplier_url": (
                    "https://detail.1688.com/offer/1.html"
                ),
                "backup_supplier_urls": [
                    "https://www.yiwugo.com/product/detail/1.html"
                ],
            }
        },
        actor_id="operator-a",
        source_evidence_id="evd-batch-source",
    )
    _, scoped = authority(repo)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=datetime(2030, 1, 1, tzinfo=UTC),
        product_id=product.id,
    )

    lineage = result["products"][0]["source_lineage"]
    assert lineage == {
        "status": "observed",
        "competitive_market_url": "https://www.ozon.ru/product/1/",
        "primary_supplier_url": "https://detail.1688.com/offer/1.html",
        "backup_supplier_urls": [
            "https://www.yiwugo.com/product/detail/1.html"
        ],
        "source_evidence_id": "evd-batch-source",
        "authority": "product_event_ledger",
        "links_are_observations_not_orders": True,
        "external_sync_performed": False,
    }


def test_legacy_product_requires_scoped_catalog_canonical_binding():
    repo = SqlAlchemyRepository(database())
    legacy = repo.add_product(
        Product(
            sku="legacy",
            name="Legacy",
            created_at="2026-07-28T01:00:00+00:00",
        )
    )
    catalog = Catalog(
        [
            {
                "canonical_product_id": legacy.id,
                "offer_id": "offer-1",
            }
        ]
    )
    _, scoped = authority(repo, catalog=catalog)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=legacy.id,
    )

    assert result["products"][0]["scope_authority"] == (
        "scoped_catalog_canonical_binding"
    )
    assert result["scope"]["tenant_ref"] == "tenant-a"


def test_passport_and_asset_evidence_conflict_blocks_content_readiness():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="blocked"))
    for index, kind in enumerate(PassportType, start=1):
        repo.add_passport(
            Passport(
                product_id=product.id,
                kind=kind,
                version=1,
                facts=approved_facts(kind),
                evidence=[f"evd-{index}"],
                approved_by="reviewer",
                created_at="2026-07-28T02:00:00+00:00",
            )
        )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={"source_asset_evidence_ids": ["evd-image-source"]},
            source_facts={"evidence_ids": ["evd-image-source"]},
            status=ContentStatus.APPROVED,
            artifact_ref="evd-bad-artifact",
            created_at="2026-07-28T03:00:00+00:00",
        )
    )
    _, scoped = authority(
        repo,
        evidence=Evidence(blocked={"evd-bad-artifact"}),
    )

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=product.id,
    )

    item = result["products"][0]
    assert result["status"] == "blocked"
    assert item["readiness"]["passport_approved"] is True
    assert item["readiness"]["media_qa_ready"] is False
    assert item["readiness"]["listing_draft_allowed"] is False
    assert item["readiness"]["external_write_allowed"] is False


def test_as_of_excludes_later_passport_and_content_asset():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="as-of"))
    repo.add_passport(
        Passport(
            product_id=product.id,
            kind=PassportType.PRODUCT,
            version=1,
            facts={"decision": "draft"},
            evidence=[],
            created_at="2026-07-28T02:00:00+00:00",
        )
    )
    repo.add_passport(
        Passport(
            product_id=product.id,
            kind=PassportType.PRODUCT,
            version=2,
            facts=approved_facts(PassportType.PRODUCT),
            evidence=["evd-future"],
            approved_by="reviewer",
            created_at="2026-07-28T12:00:00+00:00",
        )
    )
    repo.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref="evd-future-asset",
            created_at="2026-07-28T12:00:00+00:00",
        )
    )
    _, scoped = authority(repo)

    result = scoped.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        product_id=product.id,
    )

    item = result["products"][0]
    assert item["passports"][0]["version"] == 1
    assert item["content_assets"] == []


def test_listing_plan_is_deterministic_and_creates_no_approval_or_permit():
    repo = SqlAlchemyRepository(database())
    product = repo.add_product(native_product(sku="plan"))
    _, scoped = authority(repo)
    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
        "product_id": product.id,
        "offer_id": "offer-missing",
        "scenario_id": "scenario-missing",
        "content_asset_ids": ["asset-missing"],
        "listing_data": {
            "title": "Товар",
            "description": "Описание",
            "category_id": "1",
            "attributes": {},
            "images": [],
        },
    }

    first = scoped.listing_approval_plan(**values)
    second = scoped.listing_approval_plan(**values)
    changed = scoped.listing_approval_plan(
        **{
            **values,
            "listing_data": {
                **values["listing_data"],
                "title": "Другой товар",
            },
        }
    )

    assert first == second
    assert first["allowed"] is False
    assert first["approval_plan_sha256"] != changed[
        "approval_plan_sha256"
    ]
    assert first["control_envelope"] == {
        "read_only_plan": True,
        "listing_draft_created": False,
        "approval_created": False,
        "permit_created": False,
        "pilot_started": False,
        "external_write_allowed": False,
    }


def test_scoped_batch_content_never_calls_global_passport_or_asset_loader():
    class RawMustNotRun:
        def __getattr__(self, _):
            raise AssertionError("global Product/content loader must not run")

    result = BatchOpportunityWorkspace._content(
        SimpleNamespace(repository=RawMustNotRun()),
        market={
            "title": "Тестовый товар",
            "product_identity": {"color": "black"},
            "target_product_id": "prd-1",
            "media_rights_status": "owned",
        },
        supplier={"media_rights_status": "licensed"},
        scoped_product_content={
            "prd-1": {
                "passports": [
                    {"kind": kind.value, "status": "approved"}
                    for kind in PassportType
                ],
                "content_assets": [
                    {
                        "id": "image-1",
                        "content_type": "image",
                        "status": "approved",
                        "evidence_ready": True,
                    },
                    {
                        "id": "copy-1",
                        "content_type": "copy",
                        "status": "approved",
                        "evidence_ready": True,
                    },
                ],
            }
        },
    )

    assert result["content_authority"] == "scoped_product_content"
    assert result["content_ready"] is True
    assert result["observed_title_not_content_draft"] is True


def test_product_database_scope_check_and_scoped_sku_uniqueness():
    engine = database()
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(
            ProductRow(
                id="bad-partial",
                sku="partial",
                name="bad",
                market="RU",
                channel="OZON",
                status="candidate",
                created_at=AS_OF,
                tenant_ref="tenant-a",
            )
        )
        session.flush()

    repo = SqlAlchemyRepository(engine)
    repo.add_product(native_product(sku="shared"))
    repo.add_product(
        native_product(
            sku="shared",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )
    with pytest.raises(ValueError, match="SKU already exists"):
        repo.add_product(native_product(sku="shared"))


def test_scoped_product_content_api_requires_auth_and_store_scope(
    monkeypatch,
):
    def missing(_):
        raise AuthenticationFailure("missing", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", missing)
    client = TestClient(app)
    assert (
        client.get(
            "/v1/product-content/workspace",
            params={"store_ref": "store-a"},
        ).status_code
        == 401
    )

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    monkeypatch.setattr(
        runtime.kill_switch,
        "ensure_writes_allowed",
        lambda: None,
    )
    assert (
        client.get(
            "/v1/product-content/workspace",
            params={"store_ref": "store-b"},
            headers={"X-KJDS-API-Key": "test"},
        ).status_code
        == 403
    )

    listing_payload = {
        "product_id": "product-a",
        "offer_id": "offer-a",
        "scenario_id": "scenario-a",
        "content_asset_ids": ["asset-a"],
        "listing_data": {
            "title": "Товар",
            "description": "Описание",
            "category_id": "1",
            "attributes": {},
            "images": ["asset-a"],
        },
        "store_ref": "store-b",
    }
    calls = []
    monkeypatch.setattr(
        runtime.scoped_product_content,
        "listing_approval_plan",
        lambda **values: calls.append(values),
    )
    response = client.post(
        "/v1/listings/ozon/approval-plan",
        json=listing_payload,
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 403
    assert calls == []


def test_listing_approval_plan_api_rejects_anonymous(monkeypatch):
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: (_ for _ in ()).throw(
            AuthenticationFailure("missing", 401)
        ),
    )
    response = TestClient(app).post(
        "/v1/listings/ozon/approval-plan",
        json={
            "product_id": "product-a",
            "offer_id": "offer-a",
            "scenario_id": "scenario-a",
            "content_asset_ids": ["asset-a"],
            "listing_data": {
                "title": "Товар",
                "description": "Описание",
                "category_id": "1",
                "attributes": {},
                "images": ["asset-a"],
            },
            "store_ref": "store-a",
        },
    )
    assert response.status_code == 401


def test_product_create_missing_entity_is_409_and_does_not_write(
    monkeypatch,
):
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _: principal(),
    )
    monkeypatch.setattr(
        runtime.kill_switch,
        "ensure_writes_allowed",
        lambda: None,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
            "authority_sha256": None,
        },
    )
    calls = []
    monkeypatch.setattr(
        runtime.commerce,
        "create_product",
        lambda **values: calls.append(values),
    )

    response = TestClient(app).post(
        "/v1/products",
        json={"sku": "never-created", "name": "Never"},
        headers={"X-KJDS-API-Key": "test"},
    )

    assert response.status_code == 409
    assert calls == []
