from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import PassportType
from apps.control_plane.evidence import EvidenceService
from apps.control_plane.intake import (
    PRODUCT_MEDIA_ROLES,
    PassportEvidencePayload,
    ProductMediaEvidenceService,
    SkuEpisodeIntakeService,
)
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sql_repository import Base

FACTS = {
    PassportType.PRODUCT: {
        "decision": "draft",
        "material": "polypropylene",
        "intended_use": "household storage",
        "country_of_origin": "CN",
        "weight_kg": "0.5",
        "dimensions_cm": {"length": 30, "width": 20, "height": 10},
    },
    PassportType.COMPLIANCE: {
        "decision": "draft",
        "hs_code": "3924.90",
        "eaeu_rules": ["requires reviewer confirmation"],
        "eac_requirement": "unknown",
        "chestny_znak_requirement": "unknown",
        "russian_labeling": "required",
        "ip_status": "review_required",
        "transport_restrictions": "unknown",
        "sellability": "pending_review",
    },
    PassportType.QUALITY: {
        "decision": "draft",
        "golden_sample_ref": "sample://RU-001/golden",
        "inspection_plan": ["dimensions", "material", "appearance"],
        "packaging_test": "pending",
    },
}


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repo = InMemoryRepository()
    commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
    return repo, evidence, SkuEpisodeIntakeService(commerce=commerce, evidence=evidence)


def payloads():
    return [
        PassportEvidencePayload(
            kind=kind,
            facts=FACTS[kind],
            content=f"{kind.value} evidence".encode(),
            filename=f"{kind.value}.txt",
            content_type="text/plain",
        )
        for kind in PassportType
    ]


def test_sku_episode_intake_is_idempotent_and_keeps_drafts_unapproved():
    repo, evidence, intake = make_service()
    first = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    second = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )

    assert second["product"]["id"] == first["product"]["id"]
    latest = repo.latest_passports(first["product"]["id"])
    assert {item.version for item in latest.values()} == {1}
    assert {item["status"] for item in second["readiness"]["passports"]} == {"draft"}
    for record, passport in zip(first["evidence"], first["passports"], strict=True):
        assert any(edge.to_id == passport["id"] for edge in evidence.lineage(record["id"]))


def test_sku_episode_rejects_identity_conflict_on_retry():
    _, _, intake = make_service()
    intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    try:
        intake.ingest(
            sku="RU-001",
            name="Different product",
            effective_at="2026-07-16T00:00:00+08:00",
            payloads=payloads(),
            created_by="operator-1",
        )
    except ValueError as exc:
        assert "different product name" in str(exc)
    else:
        raise AssertionError("Expected SKU identity conflict")


def test_passport_review_queue_and_decision_are_versioned_and_idempotent():
    repo, _, intake = make_service()
    result = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    commerce = intake.commerce
    assert len(commerce.passport_review_queue()) == 3

    reviewed = commerce.review_passport(
        product_id=result["product"]["id"],
        kind=PassportType.PRODUCT,
        expected_version=1,
        decision="approved",
        review_notes="Facts and source file checked",
        reviewed_by="reviewer-1",
    )
    retry = commerce.review_passport(
        product_id=result["product"]["id"],
        kind=PassportType.PRODUCT,
        expected_version=1,
        decision="approved",
        review_notes="Facts and source file checked",
        reviewed_by="reviewer-1",
    )

    assert retry.id == reviewed.id
    assert reviewed.version == 2
    assert reviewed.approved_by == "reviewer-1"
    assert len(commerce.passport_review_queue()) == 2
    assert repo.latest_passports(result["product"]["id"])[PassportType.PRODUCT].facts["decision"] == "approved"


def test_blocking_passport_requires_review_notes():
    _, _, intake = make_service()
    result = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    try:
        intake.commerce.review_passport(
            product_id=result["product"]["id"],
            kind=PassportType.COMPLIANCE,
            expected_version=1,
            decision="blocked",
            review_notes="",
            reviewed_by="reviewer-1",
        )
    except ValueError as exc:
        assert "requires notes" in str(exc)
    else:
        raise AssertionError("Expected review notes requirement")


def test_product_media_requires_real_file_signatures_and_passport_approval():
    repo, evidence, intake = make_service()
    result = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    product_id = result["product"]["id"]
    media = ProductMediaEvidenceService(commerce=intake.commerce, evidence=evidence)

    for role in PRODUCT_MEDIA_ROLES:
        captured = media.ingest(
            product_id=product_id,
            variant_id="base",
            asset_role=role,
            source_kind="sample_photo",
            source_ref=f"sample://RU-001/{role}",
            effective_at="2026-07-18T10:00:00+08:00",
            image_content=b"\x89PNG\r\n\x1a\n" + role.encode(),
            image_filename=f"{role}.png",
            image_content_type="image/png",
            rights_content=b"%PDF-1.7\nsample ownership declaration",
            rights_filename=f"{role}-rights.pdf",
            rights_content_type="application/pdf",
            created_by="operator-1",
        )
        assert captured["media_readiness"]["automatic_generation"] is False

    pending = media.readiness(product_id)
    assert pending["approved_role_count"] == 0
    assert pending["missing_roles"] == []
    assert set(pending["pending_passport_roles"]) == set(PRODUCT_MEDIA_ROLES)
    assert pending["ready_for_full_production"] is False

    for kind in PassportType:
        latest = repo.latest_passports(product_id)[kind]
        intake.commerce.review_passport(
            product_id=product_id,
            kind=kind,
            expected_version=latest.version,
            decision="approved",
            review_notes="Original evidence and facts checked",
            reviewed_by="reviewer-1",
        )

    ready = media.readiness(product_id)
    assert ready["approved_role_count"] == len(PRODUCT_MEDIA_ROLES)
    assert ready["all_passports_approved"] is True
    assert ready["ready_for_full_production"] is True
    assert {item["status"] for item in ready["roles"]} == {"approved"}


def test_product_media_rejects_declared_png_with_non_png_content_before_capture():
    _, evidence, intake = make_service()
    result = intake.ingest(
        sku="RU-001",
        name="Storage box",
        effective_at="2026-07-16T00:00:00+08:00",
        payloads=payloads(),
        created_by="operator-1",
    )
    media = ProductMediaEvidenceService(commerce=intake.commerce, evidence=evidence)
    evidence_count = len(evidence.list())

    try:
        media.ingest(
            product_id=result["product"]["id"],
            variant_id="base",
            asset_role="front_main",
            source_kind="supplier_authorized",
            source_ref="supplier://offer/1",
            effective_at="2026-07-18T10:00:00+08:00",
            image_content=b"not-a-png",
            image_filename="front.png",
            image_content_type="image/png",
            rights_content=b"%PDF-1.7\nlicense",
            rights_filename="license.pdf",
            rights_content_type="application/pdf",
            created_by="operator-1",
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("Expected image signature rejection")
    assert len(evidence.list()) == evidence_count
