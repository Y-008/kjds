from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.primary_source_intake import (
    CONTRACT_ID,
    EVIDENCE_SOURCE,
    LEAD_SOURCE_FAMILIES,
    SOURCE_FAMILY_ALIASES,
    PrimarySourceConflictError,
    PrimarySourceIntake,
    PrimarySourceIntakeRow,
    PrimarySourceRecordRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


class FakeScopeGrants:
    def __init__(self) -> None:
        self.ready = True
        self.entity_suffix = "entity"
        self.authority_suffix = "v1"

    def current(self, *, principal, store_ref, as_of):
        assert as_of.tzinfo is not None
        if not self.ready:
            return {
                "status": "no_data",
                "reason": "entity_scope_authority_missing",
            }
        entity_ref = f"{self.entity_suffix}-{principal.tenant_ref}"
        authority_sha256 = hashlib.sha256(
            (
                f"{principal.tenant_ref}|{entity_ref}|{store_ref}|"
                f"{principal.actor_id}|{self.authority_suffix}"
            ).encode()
        ).hexdigest()
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority_sha256,
        }


class FakeScopedEvidence:
    def __init__(self) -> None:
        self.status = "ready"

    def project(self, **kwargs):
        return {
            "status": self.status,
            "evidence_ids": kwargs["evidence_ids"],
        }


def principal(tenant: str = "tenant-a", actor: str = "operator-a", *roles: str):
    return Principal(
        actor_id=actor,
        roles=frozenset(roles or ("operator",)),
        tenant_ref=tenant,
        store_refs=frozenset({"store-a"}),
    )


@pytest.fixture
def intake_runtime():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            EvidenceBlobRow.__table__,
            EvidenceRecordRow.__table__,
            PrimarySourceIntakeRow.__table__,
            PrimarySourceRecordRow.__table__,
        ],
    )
    scope = FakeScopeGrants()
    scoped_evidence = FakeScopedEvidence()
    service = PrimarySourceIntake(
        engine=engine,
        evidence=EvidenceService(engine),
        scope_grants=scope,
        scoped_evidence=scoped_evidence,
        clock=lambda: NOW,
    )
    return service, engine, scope, scoped_evidence


def record(**overrides):
    value = {
        "source_family": "amazon",
        "marketplace_or_site": "amazon.com",
        "business_entity_name": "Acme Trading LLC",
        "country_or_region": "US",
        "category": "home-and-kitchen",
        "public_business_url": "https://seller.example/store/acme",
        "entity_type": "seller_account",
        "signal_type": "seller_presence",
        "signal_observed_at": NOW - timedelta(hours=2),
        "license_or_terms_basis": "official public business page terms v3",
        "contact_ref": None,
        "contact_purpose_basis": "not_applicable",
        "jurisdiction": "US",
        "do_not_contact_status": "unknown",
        "confidence_bps": 8700,
        "evidence_refs": [],
    }
    value.update(overrides)
    return value


def envelope(*, source_total: int, **overrides):
    value = {
        "source_pack_id": "global_trade_lead_intelligence",
        "source_contract_id": "amazon-seller-export",
        "source_contract_version": "2026-08-03",
        "subject_ref": "subject://lead-batch-a",
        "source_locator_ref": "customer-vault://exports/lead-batch-a",
        "blob_sha256": "a" * 64,
        "byte_count": 4096,
        "mime_type": "application/json",
        "captured_at": NOW - timedelta(hours=3),
        "effective_at": NOW - timedelta(hours=3),
        "acquisition_mode": "account_owner_export",
        "license_or_terms_basis": "account owner export terms v2",
        "allowed_purpose": "B2B market research and proposed outreach review",
        "jurisdiction": "US",
        "retention_class": "operational",
        "data_classification": "business_public",
        "cross_border_transfer_classification": "domestic_only",
        "parser_version": "lead-normalizer-1",
        "field_count": 16,
        "pagination": {
            "expected_pages": 1,
            "received_pages": 1,
            "failed_page_refs": [],
            "checkpoint_ref": None,
        },
        "integrity": {
            "raw_blob_reverified": True,
            "verifier_id": "sha256-byte-verifier",
            "verifier_version": "1",
            "verified_at": NOW - timedelta(hours=1),
        },
        "conservation": {
            "source_total": source_total,
            "quarantined_count": 0,
            "duplicate_count": 0,
        },
        "review_due_at": NOW + timedelta(days=30),
    }
    value.update(overrides)
    return value


def admit(service, records, *, key="lead-batch-a", body=None, actor=None):
    return service.admit(
        principal=actor or principal(),
        store_ref="store-a",
        as_of=NOW,
        idempotency_key=key,
        envelope=body or envelope(source_total=len(records)),
        records=records,
    )


def test_runtime_source_families_and_aliases_match_machine_registry():
    registry = json.loads(
        (ROOT / "docs/project/registries/primary_source_intake.json").read_text(
            encoding="utf-8"
        )
    )
    pack = next(
        item
        for item in registry["source_packs"]
        if item["id"] == "global_trade_lead_intelligence"
    )
    registered_families = {
        family
        for group in pack["source_families"].values()
        for family in group
    }
    assert registered_families == set(LEAD_SOURCE_FAMILIES)
    assert pack["alias_normalization"] == SOURCE_FAMILY_ALIASES


def test_admits_normalized_leads_with_quality_conservation_and_suppression(
    intake_runtime,
):
    service, _engine, _scope, _scoped = intake_runtime
    records = [
        record(source_family="tk"),
        record(
            source_family="customs_data",
            business_entity_name="Northstar Imports Inc",
            marketplace_or_site="customs-data",
            entity_type="buyer_signal",
            signal_type="customs_import_activity",
            public_business_url=None,
            confidence_bps=7900,
        ),
        record(
            source_family="linkedin_company_and_public_professional_data",
            business_entity_name="Northstar Imports Inc",
            marketplace_or_site="linkedin-company",
            entity_type="verified_contact_point",
            signal_type="public_professional_role",
            contact_ref="vault://contacts/northstar-buyer-1",
            contact_purpose_basis="documented_legitimate_business_interest",
            do_not_contact_status="withdrawn",
            public_business_url="https://www.linkedin.com/company/northstar-imports",
        ),
    ]

    result = admit(service, records)

    assert result["contract_id"] == CONTRACT_ID
    descriptor = result["intake"]
    assert descriptor["counts"] == {
        "source_total": 3,
        "accepted": 2,
        "suppressed": 1,
        "quarantined": 0,
        "duplicate": 0,
    }
    assert descriptor["quality"] == {
        "completeness": "passed",
        "uniqueness": "passed",
        "validity": "passed",
        "consistency": "passed",
        "timeliness": "passed",
        "accuracy": "pending_independent_review",
        "conservation": "passed",
    }
    assert descriptor["admission_grade"] == "B"
    assert descriptor["formal_fact_promoted"] is False
    assert descriptor["finance_entry_created"] is False
    assert descriptor["external_write_allowed"] is False
    assert result["records"][0]["source_family"] == "tiktok_shop"
    assert result["records"][2]["disposition"] == "suppressed"
    assert result["records"][2]["lead_stage"] == "contact_basis_verified"


def test_only_hash_manifest_is_evidence_and_raw_locator_is_not_retained(
    intake_runtime,
):
    service, engine, _scope, _scoped = intake_runtime
    result = admit(service, [record()])
    evidence_id = result["intake"]["evidence"]["id"]
    content, evidence = service.evidence.content(evidence_id)
    manifest = json.loads(content)

    assert evidence.source == EVIDENCE_SOURCE
    assert manifest["raw_source_retained"] is False
    assert manifest["personal_contact_retained"] is False
    assert manifest["record_hashes"] == [
        result["records"][0]["source_record_sha256"]
    ]
    serialized = content.decode()
    assert "customer-vault://exports/lead-batch-a" not in serialized
    assert "subject://lead-batch-a" not in serialized
    assert "Acme Trading LLC" not in serialized
    with Session(engine) as session:
        row = session.scalar(select(PrimarySourceIntakeRow))
        assert row is not None
        assert row.source_locator_sha256 == hashlib.sha256(
            b"customer-vault://exports/lead-batch-a"
        ).hexdigest()


def test_idempotent_replay_is_exactly_once_and_payload_drift_is_conflict(
    intake_runtime,
):
    service, engine, _scope, _scoped = intake_runtime
    first = admit(service, [record()])
    replay = admit(service, [record()])
    assert replay["intake"]["intake_ref"] == first["intake"]["intake_ref"]
    assert replay["intake"]["idempotent_replay"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PrimarySourceIntakeRow)) == 1
        assert session.scalar(select(func.count()).select_from(PrimarySourceRecordRow)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(EvidenceRecordRow)
                .where(EvidenceRecordRow.source == EVIDENCE_SOURCE)
            )
            == 1
        )
    with pytest.raises(PrimarySourceConflictError):
        admit(
            service,
            [record(confidence_bps=8600)],
            key="lead-batch-a",
        )


def test_cross_scope_and_authority_drift_are_non_enumerable(intake_runtime):
    service, _engine, scope, _scoped = intake_runtime
    created = admit(service, [record()])
    ref = created["intake"]["intake_ref"]
    other = principal("tenant-b", "operator-b")
    with pytest.raises(KeyError, match="authorized scope"):
        service.get(
            principal=other,
            store_ref="store-a",
            as_of=NOW,
            intake_ref=ref,
        )
    scope.authority_suffix = "v2"
    with pytest.raises(KeyError, match="authorized scope"):
        service.get(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            intake_ref=ref,
        )


def test_missing_authority_and_wrong_roles_write_nothing(intake_runtime):
    service, engine, scope, _scoped = intake_runtime
    scope.ready = False
    with pytest.raises(PermissionError, match="authority_missing"):
        admit(service, [record()])
    scope.ready = True
    with pytest.raises(PermissionError, match="required intake role"):
        admit(
            service,
            [record()],
            actor=principal("tenant-a", "viewer-a", "monitor"),
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PrimarySourceIntakeRow)) == 0


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item.update(business_entity_name="buyer@example.com"),
            "raw personal contact",
        ),
        (
            lambda item: item.update(contact_ref="buyer@example.com"),
            "opaque CRM or vault",
        ),
        (
            lambda item: item.update(
                public_business_url="https://seller.example/store?token=hidden"
            ),
            "query-free URL",
        ),
    ],
)
def test_rejects_raw_contact_secret_or_tracking_url(
    intake_runtime, mutator, message
):
    service, _engine, _scope, _scoped = intake_runtime
    item = record()
    mutator(item)
    with pytest.raises(ValueError, match=message):
        admit(service, [item])


def test_rejects_presence_as_buyer_intent_and_unproven_opportunity(
    intake_runtime,
):
    service, _engine, _scope, _scoped = intake_runtime
    with pytest.raises(ValueError, match="not buyer intent"):
        admit(
            service,
            [record(entity_type="buyer_signal", signal_type="seller_presence")],
        )
    with pytest.raises(ValueError, match="first-party need Evidence"):
        admit(
            service,
            [
                record(
                    entity_type="qualified_opportunity",
                    signal_type="first_party_need_verified",
                )
            ],
        )


def test_qualified_opportunity_requires_exact_scope_evidence(intake_runtime):
    service, _engine, _scope, scoped = intake_runtime
    item = record(
        entity_type="qualified_opportunity",
        signal_type="first_party_need_verified",
        evidence_refs=["evd_first_party_interaction"],
    )
    scoped.status = "blocked"
    with pytest.raises(ValueError, match="exact-scope ready"):
        admit(service, [item])
    scoped.status = "ready"
    result = admit(service, [item], key="qualified-ready")
    assert result["records"][0]["lead_stage"] == "qualified_opportunity"


def test_pagination_and_conservation_fail_closed(intake_runtime):
    service, _engine, _scope, _scoped = intake_runtime
    bad_pagination = envelope(source_total=1)
    bad_pagination["pagination"] = {
        "expected_pages": 3,
        "received_pages": 1,
        "failed_page_refs": ["page://2"],
        "checkpoint_ref": "checkpoint://batch-a",
    }
    with pytest.raises(ValueError, match="must equal expected_pages"):
        admit(service, [record()], body=bad_pagination)

    bad_counts = envelope(source_total=2)
    with pytest.raises(ValueError, match="conservation failed"):
        admit(service, [record()], body=bad_counts)

    partial = envelope(source_total=2)
    partial["pagination"] = {
        "expected_pages": 2,
        "received_pages": 1,
        "failed_page_refs": ["page://2"],
        "checkpoint_ref": "checkpoint://batch-a",
    }
    partial["conservation"] = {
        "source_total": 2,
        "quarantined_count": 1,
        "duplicate_count": 0,
    }
    result = admit(service, [record()], key="partial-a", body=partial)
    assert result["intake"]["status"] == "partial"
    assert result["intake"]["pagination"]["failed_page_count"] == 1


def test_list_is_scoped_filtered_and_cursor_paginated(intake_runtime):
    service, _engine, _scope, _scoped = intake_runtime
    admit(service, [record()], key="batch-1")
    admit(service, [record(business_entity_name="Beta Trading LLC")], key="batch-2")

    page = service.list(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        source_pack_id="global_trade_lead_intelligence",
        status="complete",
        limit=1,
    )
    assert len(page["items"]) == 1
    assert page["next_cursor"] is not None
    second = service.list(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        source_pack_id="global_trade_lead_intelligence",
        status="complete",
        limit=1,
        cursor=page["next_cursor"],
    )
    assert len(second["items"]) == 1
    assert second["items"][0]["intake_ref"] != page["items"][0]["intake_ref"]


def test_non_lead_pack_cannot_smuggle_lead_records(intake_runtime):
    service, _engine, _scope, _scoped = intake_runtime
    body = envelope(
        source_total=1,
        source_pack_id="competitor_enterprise_and_capital",
    )
    with pytest.raises(ValueError, match="require global_trade"):
        admit(service, [record()], body=body)
