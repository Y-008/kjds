from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .security import Principal
from .sql_repository import Base

CONTRACT_ID = "kjds-primary-source-intake-v1"
EVIDENCE_SOURCE = "primary-source-intake"
MAX_RECORDS_PER_INTAKE = 500
ZERO_SHA256 = "0" * 64

SOURCE_PACKS = frozenset(
    {
        "operating_cash_truth",
        "marketplace_demand_and_catalog",
        "unit_economics_supply_and_logistics",
        "global_trade_lead_intelligence",
        "customer_product_and_revenue",
        "ai_technology_and_cost_benchmark",
        "competitor_enterprise_and_capital",
        "risk_legal_security_and_compliance",
    }
)
ACQUISITION_MODES = frozenset(
    {
        "official_api",
        "account_owner_export",
        "licensed_dataset",
        "terms_permitted_public_business_observation",
        "consented_first_party_crm_import",
    }
)
LEAD_SOURCE_FAMILIES = frozenset(
    {
        "amazon",
        "alibaba_com",
        "aliexpress",
        "shopee",
        "tiktok_shop",
        "temu",
        "mercado_libre",
        "wildberries",
        "ozon",
        "ebay",
        "lazada",
        "rakuten",
        "yahoo_shopping",
        "walmart_marketplace",
        "global_sources",
        "made_in_china",
        "world_factory",
        "yiwugo",
        "1688",
        "global_huapin",
        "baobaoniu",
        "17zwd",
        "souk",
        "eelly",
        "toybaba",
        "meizhuang",
        "zhiai_muying",
        "shipinwang",
        "91jiafang",
        "gongpinhui",
        "global_shoes",
        "independent_storefront",
        "customs_data",
        "linkedin_company_and_public_professional_data",
    }
)
SOURCE_FAMILY_ALIASES = {
    "tk": "tiktok_shop",
    "wb": "wildberries",
    "美客多": "mercado_libre",
    "阿里巴巴国际站": "alibaba_com",
    "速卖通": "aliexpress",
    "虾皮": "shopee",
    "环球资源网": "global_sources",
    "中国制造网": "made_in_china",
    "义乌购": "yiwugo",
    "1688拿货网": "1688",
    "搜款网": "souk",
}
LEAD_ENTITY_TYPES = frozenset(
    {
        "seller_account",
        "supplier_entity",
        "prospect_account",
        "buyer_signal",
        "verified_contact_point",
        "qualified_opportunity",
    }
)
BUYER_SIGNAL_TYPES = frozenset(
    {
        "rfq_posted",
        "purchase_request",
        "replenishment_need",
        "sourcing_inquiry",
        "customs_import_activity",
        "first_party_need_verified",
    }
)
DNC_STATUSES = frozenset({"unknown", "clear", "do_not_contact", "withdrawn"})
CONTACT_PURPOSE_BASES = frozenset(
    {
        "not_applicable",
        "consent",
        "existing_customer",
        "contractual_necessity",
        "documented_legitimate_business_interest",
    }
)
DATA_CLASSIFICATIONS = frozenset(
    {
        "business_public",
        "business_confidential",
        "financial_restricted",
        "personal_professional",
        "security_restricted",
    }
)
CROSS_BORDER_CLASSES = frozenset(
    {"not_applicable", "domestic_only", "approved_transfer", "restricted"}
)
RETENTION_CLASSES = frozenset(
    {"operational", "financial", "compliance", "experiment", "security"}
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_CONTACT_REF = re.compile(r"^(?:crm|vault|contact)://[A-Za-z0-9._:/-]{1,144}$")
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")
_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"session[_-]?cookie|authorization\s*:\s*bearer|private[_-]?key)"
)


class PrimarySourceConflictError(RuntimeError):
    pass


class PrimarySourceIntakeRow(Base):
    __tablename__ = "primary_source_intake_envelopes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_sha256",
            name="uq_primary_source_scope_idempotency",
        ),
        UniqueConstraint(
            "intake_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            name="uq_primary_source_exact_binding",
        ),
        CheckConstraint(
            "source_pack_id IN ("
            "'operating_cash_truth','marketplace_demand_and_catalog',"
            "'unit_economics_supply_and_logistics',"
            "'global_trade_lead_intelligence','customer_product_and_revenue',"
            "'ai_technology_and_cost_benchmark',"
            "'competitor_enterprise_and_capital',"
            "'risk_legal_security_and_compliance')",
            name="ck_primary_source_pack",
        ),
        CheckConstraint(
            "acquisition_mode IN ('official_api','account_owner_export',"
            "'licensed_dataset','terms_permitted_public_business_observation',"
            "'consented_first_party_crm_import')",
            name="ck_primary_source_acquisition_mode",
        ),
        CheckConstraint(
            "admission_grade IN ('B','C')",
            name="ck_primary_source_admission_grade",
        ),
        CheckConstraint(
            "status IN ('complete','partial')",
            name="ck_primary_source_status",
        ),
        CheckConstraint(
            "source_total >= 0 AND accepted_count >= 0 "
            "AND suppressed_count >= 0 AND quarantined_count >= 0 "
            "AND duplicate_count >= 0 "
            "AND accepted_count + suppressed_count + quarantined_count "
            "+ duplicate_count = source_total",
            name="ck_primary_source_conservation",
        ),
        CheckConstraint(
            "field_count > 0 AND expected_pages > 0 AND received_pages >= 0 "
            "AND failed_page_count >= 0 "
            "AND received_pages + failed_page_count = expected_pages",
            name="ck_primary_source_pagination",
        ),
        CheckConstraint(
            "byte_count > 0 AND length(blob_sha256) = 64 "
            "AND length(subject_ref_sha256) = 64 "
            "AND length(source_locator_sha256) = 64 "
            "AND length(scope_authority_sha256) = 64 "
            "AND length(request_sha256) = 64 "
            "AND length(idempotency_sha256) = 64",
            name="ck_primary_source_required_hashes",
        ),
        Index(
            "ix_primary_source_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
            "intake_ref",
        ),
        Index(
            "ix_primary_source_pack_status",
            "tenant_ref",
            "source_pack_id",
            "status",
            "intake_ref",
        ),
    )

    intake_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pack_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_contract_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_ref_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    blob_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    acquisition_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    license_or_terms_basis: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_purpose: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    data_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    cross_border_transfer_classification: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    verifier_id: Mapped[str] = mapped_column(String(120), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(80), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_total: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    field_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    received_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_page_sha256_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    checkpoint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrimarySourceRecordRow(Base):
    __tablename__ = "primary_source_intake_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["intake_ref", "tenant_ref", "entity_ref", "store_ref"],
            [
                "primary_source_intake_envelopes.intake_ref",
                "primary_source_intake_envelopes.tenant_ref",
                "primary_source_intake_envelopes.entity_ref",
                "primary_source_intake_envelopes.store_ref",
            ],
            name="fk_primary_source_record_exact_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "intake_ref", "ordinal", name="uq_primary_source_record_ordinal"
        ),
        UniqueConstraint(
            "intake_ref",
            "source_record_sha256",
            name="uq_primary_source_record_content",
        ),
        CheckConstraint(
            "disposition IN ('accepted','suppressed')",
            name="ck_primary_source_record_disposition",
        ),
        CheckConstraint(
            "entity_type IN ('seller_account','supplier_entity','prospect_account',"
            "'buyer_signal','verified_contact_point','qualified_opportunity')",
            name="ck_primary_source_record_entity_type",
        ),
        CheckConstraint(
            "confidence_bps >= 0 AND confidence_bps <= 10000 "
            "AND ordinal > 0 AND length(source_record_sha256) = 64",
            name="ck_primary_source_record_quality",
        ),
        Index(
            "ix_primary_source_record_lead_search",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_family",
            "entity_type",
            "signal_observed_at",
        ),
        Index(
            "ix_primary_source_record_intake",
            "intake_ref",
            "ordinal",
        ),
    )

    record_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    intake_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_family: Mapped[str] = mapped_column(String(100), nullable=False)
    marketplace_or_site: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    business_entity_name: Mapped[str] = mapped_column(Text, nullable=False)
    country_or_region: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(160), nullable=False)
    public_business_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    signal_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    license_or_terms_basis: Mapped[str] = mapped_column(Text, nullable=False)
    contact_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_purpose_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False)
    do_not_contact_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    disposition: Mapped[str] = mapped_column(String(20), nullable=False)
    lead_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrimarySourceIntake:
    """Admit a hash-addressed source manifest and bounded normalized lead batch."""

    CONTRACT_ID = CONTRACT_ID

    def __init__(
        self,
        *,
        engine,
        evidence,
        scope_grants,
        scoped_evidence=None,
        clock=None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scope_grants = scope_grants
        self.scoped_evidence = scoped_evidence
        self.clock = clock or (lambda: datetime.now(UTC))

    def admit(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        idempotency_key: str,
        envelope: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._require_role(principal, "operator", "admin")
        now = self._aware(self.clock(), "clock")
        as_of = self._aware(as_of, "as_of")
        if as_of > now:
            raise ValueError("as_of cannot be in the future")
        scope = self._scope(principal, store_ref, as_of)
        key = self._token(idempotency_key, "idempotency_key")
        normalized_envelope = self._normalize_envelope(envelope, as_of=as_of)
        normalized_records = self._normalize_records(
            records,
            source_pack_id=normalized_envelope["source_pack_id"],
            as_of=as_of,
            scope=scope,
            principal=principal,
        )
        counts = self._conservation(normalized_envelope, normalized_records)
        idempotency_sha256 = self._hash(
            {
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "idempotency_key": key,
            }
        )
        request = {
            "contract_id": CONTRACT_ID,
            "scope": scope,
            "envelope": normalized_envelope,
            "records": normalized_records,
            "counts": counts,
            "idempotency_sha256": idempotency_sha256,
        }
        request_sha256 = self._hash(request)

        try:
            with Session(self.engine) as session, session.begin():
                existing = session.scalar(
                    select(PrimarySourceIntakeRow).where(
                        PrimarySourceIntakeRow.tenant_ref == scope["tenant_ref"],
                        PrimarySourceIntakeRow.entity_ref == scope["entity_ref"],
                        PrimarySourceIntakeRow.store_ref == scope["store_ref"],
                        PrimarySourceIntakeRow.idempotency_sha256
                        == idempotency_sha256,
                    )
                )
                if existing is not None:
                    self._require_same_request(existing, request_sha256)
                    return self._project(session, existing, include_records=True, replay=True)

                intake_ref = new_id("psi")
                manifest = self._manifest(
                    intake_ref=intake_ref,
                    scope=scope,
                    envelope=normalized_envelope,
                    records=normalized_records,
                    counts=counts,
                    request_sha256=request_sha256,
                )
                manifest_bytes = self._canonical(manifest)
                grade = self._grade(normalized_envelope["acquisition_mode"])
                evidence = self.evidence.capture(
                    content=manifest_bytes,
                    filename=f"{intake_ref}.json",
                    content_type="application/json",
                    source=EVIDENCE_SOURCE,
                    source_ref=f"primary-source-intake://{intake_ref}",
                    grade=grade,
                    effective_at=normalized_envelope["effective_at"].isoformat(),
                    effective_until=normalized_envelope["review_due_at"].isoformat(),
                    created_by=principal.actor_id,
                    metadata={
                        "contract_id": CONTRACT_ID,
                        "tenant_ref": scope["tenant_ref"],
                        "entity_ref": scope["entity_ref"],
                        "store_ref": scope["store_ref"],
                        "scope_grant_authority_sha256": scope[
                            "scope_authority_sha256"
                        ],
                        "source_pack_id": normalized_envelope["source_pack_id"],
                        "request_sha256": request_sha256,
                        "retention_class": normalized_envelope["retention_class"],
                        "raw_source_retained": False,
                        "personal_contact_retained": False,
                        "formal_fact": False,
                        "finance_entry_created": False,
                        "external_write_allowed": False,
                    },
                    _session=session,
                )
                row = self._row(
                    intake_ref=intake_ref,
                    scope=scope,
                    envelope=normalized_envelope,
                    counts=counts,
                    evidence_id=evidence.id,
                    evidence_sha256=evidence.sha256,
                    request_sha256=request_sha256,
                    idempotency_sha256=idempotency_sha256,
                    principal=principal,
                    as_of=as_of,
                    created_at=now,
                )
                session.add(row)
                session.flush()
                for ordinal, record in enumerate(normalized_records, start=1):
                    session.add(
                        self._record_row(
                            intake_ref=intake_ref,
                            scope=scope,
                            ordinal=ordinal,
                            record=record,
                            created_at=now,
                        )
                    )
                session.flush()
                return self._project(session, row, include_records=True, replay=False)
        except IntegrityError:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(PrimarySourceIntakeRow).where(
                        PrimarySourceIntakeRow.tenant_ref == scope["tenant_ref"],
                        PrimarySourceIntakeRow.entity_ref == scope["entity_ref"],
                        PrimarySourceIntakeRow.store_ref == scope["store_ref"],
                        PrimarySourceIntakeRow.idempotency_sha256
                        == idempotency_sha256,
                    )
                )
                if winner is None:
                    raise
                self._require_same_request(winner, request_sha256)
                return self._project(session, winner, include_records=True, replay=True)

    def get(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        intake_ref: str,
        expected_scope_authority_sha256: str | None = None,
    ) -> dict[str, Any]:
        self._require_role(
            principal, "operator", "reviewer", "compliance", "monitor", "admin"
        )
        cutoff = self._aware(as_of, "as_of")
        scope = self._scope(principal, store_ref, cutoff)
        self._require_expected_scope_authority(
            scope=scope,
            expected_scope_authority_sha256=expected_scope_authority_sha256,
        )
        ref = self._intake_ref(intake_ref)
        with Session(self.engine) as session:
            row = self._find(session, scope=scope, intake_ref=ref, as_of=cutoff)
            return self._project(session, row, include_records=True, replay=False)

    def list(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        source_pack_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        expected_scope_authority_sha256: str | None = None,
    ) -> dict[str, Any]:
        self._require_role(
            principal, "operator", "reviewer", "compliance", "monitor", "admin"
        )
        cutoff = self._aware(as_of, "as_of")
        scope = self._scope(principal, store_ref, cutoff)
        self._require_expected_scope_authority(
            scope=scope,
            expected_scope_authority_sha256=expected_scope_authority_sha256,
        )
        if isinstance(limit, bool) or not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        pack = self._source_pack(source_pack_id) if source_pack_id else None
        state = self._choice(status, "status", {"complete", "partial"}) if status else None
        cursor_ref = self._intake_ref(cursor) if cursor else None
        with Session(self.engine) as session:
            query = select(PrimarySourceIntakeRow).where(
                PrimarySourceIntakeRow.tenant_ref == scope["tenant_ref"],
                PrimarySourceIntakeRow.entity_ref == scope["entity_ref"],
                PrimarySourceIntakeRow.store_ref == scope["store_ref"],
                PrimarySourceIntakeRow.scope_authority_sha256
                == scope["scope_authority_sha256"],
                PrimarySourceIntakeRow.as_of <= cutoff,
                PrimarySourceIntakeRow.created_at <= cutoff,
            )
            if pack:
                query = query.where(PrimarySourceIntakeRow.source_pack_id == pack)
            if state:
                query = query.where(PrimarySourceIntakeRow.status == state)
            if cursor_ref:
                query = query.where(PrimarySourceIntakeRow.intake_ref > cursor_ref)
            rows = list(
                session.scalars(
                    query.order_by(PrimarySourceIntakeRow.intake_ref).limit(
                        int(limit) + 1
                    )
                )
            )
            has_more = len(rows) > int(limit)
            rows = rows[: int(limit)]
            return {
                "contract_id": CONTRACT_ID,
                "items": [
                    self._project(session, row, include_records=False, replay=False)[
                        "intake"
                    ]
                    for row in rows
                ],
                "next_cursor": rows[-1].intake_ref if has_more and rows else None,
            }

    def _normalize_envelope(
        self, envelope: dict[str, Any], *, as_of: datetime
    ) -> dict[str, Any]:
        expected = {
            "source_pack_id",
            "source_contract_id",
            "source_contract_version",
            "subject_ref",
            "source_locator_ref",
            "blob_sha256",
            "byte_count",
            "mime_type",
            "captured_at",
            "effective_at",
            "acquisition_mode",
            "license_or_terms_basis",
            "allowed_purpose",
            "jurisdiction",
            "retention_class",
            "data_classification",
            "cross_border_transfer_classification",
            "parser_version",
            "field_count",
            "pagination",
            "integrity",
            "conservation",
            "review_due_at",
        }
        self._exact_keys(envelope, expected, "envelope")
        captured_at = self._aware(envelope["captured_at"], "captured_at")
        effective_at = self._aware(envelope["effective_at"], "effective_at")
        review_due_at = self._aware(envelope["review_due_at"], "review_due_at")
        if captured_at > as_of or effective_at > as_of:
            raise ValueError("captured_at and effective_at cannot be later than as_of")
        if review_due_at <= as_of:
            raise ValueError("review_due_at must be later than as_of")

        pagination = self._pagination(envelope["pagination"])
        integrity = self._integrity(envelope["integrity"], captured_at, as_of)
        conservation = self._conservation_input(envelope["conservation"])
        byte_count = self._integer(envelope["byte_count"], "byte_count", minimum=1)
        field_count = self._integer(envelope["field_count"], "field_count", minimum=1)
        classification = self._choice(
            envelope["data_classification"],
            "data_classification",
            DATA_CLASSIFICATIONS,
        )
        transfer = self._choice(
            envelope["cross_border_transfer_classification"],
            "cross_border_transfer_classification",
            CROSS_BORDER_CLASSES,
        )
        if classification == "personal_professional" and transfer == "not_applicable":
            raise ValueError(
                "personal_professional data requires an explicit transfer classification"
            )
        return {
            "source_pack_id": self._source_pack(envelope["source_pack_id"]),
            "source_contract_id": self._token(
                envelope["source_contract_id"], "source_contract_id"
            ),
            "source_contract_version": self._token(
                envelope["source_contract_version"], "source_contract_version"
            ),
            "subject_ref_sha256": self._opaque_hash(
                envelope["subject_ref"], "subject_ref"
            ),
            "source_locator_sha256": self._opaque_hash(
                envelope["source_locator_ref"], "source_locator_ref"
            ),
            "blob_sha256": self._sha256(envelope["blob_sha256"], "blob_sha256"),
            "byte_count": byte_count,
            "mime_type": self._mime(envelope["mime_type"]),
            "captured_at": captured_at,
            "effective_at": effective_at,
            "acquisition_mode": self._choice(
                envelope["acquisition_mode"], "acquisition_mode", ACQUISITION_MODES
            ),
            "license_or_terms_basis": self._safe_text(
                envelope["license_or_terms_basis"],
                "license_or_terms_basis",
                500,
            ),
            "allowed_purpose": self._safe_text(
                envelope["allowed_purpose"], "allowed_purpose", 500
            ),
            "jurisdiction": self._safe_token(
                envelope["jurisdiction"], "jurisdiction", 80
            ),
            "retention_class": self._choice(
                envelope["retention_class"], "retention_class", RETENTION_CLASSES
            ),
            "data_classification": classification,
            "cross_border_transfer_classification": transfer,
            "parser_version": self._token(
                envelope["parser_version"], "parser_version"
            ),
            "field_count": field_count,
            "pagination": pagination,
            "integrity": integrity,
            "conservation": conservation,
            "review_due_at": review_due_at,
        }

    def _normalize_records(
        self,
        records: list[dict[str, Any]],
        *,
        source_pack_id: str,
        as_of: datetime,
        scope: dict[str, str],
        principal: Principal,
    ) -> list[dict[str, Any]]:
        if not isinstance(records, list) or len(records) > MAX_RECORDS_PER_INTAKE:
            raise ValueError(
                f"records must be a list with at most {MAX_RECORDS_PER_INTAKE} items"
            )
        if records and source_pack_id != "global_trade_lead_intelligence":
            raise ValueError(
                "normalized lead records require global_trade_lead_intelligence"
            )
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        referenced_evidence: set[str] = set()
        for raw in records:
            record = self._normalize_record(raw, as_of=as_of)
            digest = self._hash(record)
            if digest in seen:
                raise ValueError("records contain duplicate canonical content")
            seen.add(digest)
            record["source_record_sha256"] = digest
            referenced_evidence.update(record["evidence_refs"])
            normalized.append(record)
        if referenced_evidence:
            self._verify_evidence_refs(
                evidence_ids=sorted(referenced_evidence),
                principal=principal,
                scope=scope,
                as_of=as_of,
            )
        return normalized

    def _normalize_record(
        self, raw: dict[str, Any], *, as_of: datetime
    ) -> dict[str, Any]:
        expected = {
            "source_family",
            "marketplace_or_site",
            "business_entity_name",
            "country_or_region",
            "category",
            "public_business_url",
            "entity_type",
            "signal_type",
            "signal_observed_at",
            "license_or_terms_basis",
            "contact_ref",
            "contact_purpose_basis",
            "jurisdiction",
            "do_not_contact_status",
            "confidence_bps",
            "evidence_refs",
        }
        self._exact_keys(raw, expected, "record")
        family = self.normalize_source_family(raw["source_family"])
        entity_type = self._choice(
            raw["entity_type"], "entity_type", LEAD_ENTITY_TYPES
        )
        signal_type = self._safe_token(raw["signal_type"], "signal_type", 80)
        signal_observed_at = self._aware(
            raw["signal_observed_at"], "signal_observed_at"
        )
        if signal_observed_at > as_of:
            raise ValueError("signal_observed_at cannot be later than as_of")
        if signal_type in {"presence", "listing_presence", "seller_presence"} and entity_type in {
            "buyer_signal",
            "qualified_opportunity",
        }:
            raise ValueError("seller or product presence is not buyer intent")
        if entity_type == "buyer_signal" and signal_type not in BUYER_SIGNAL_TYPES:
            raise ValueError("buyer_signal requires time-bounded buying semantics")
        evidence_refs = self._evidence_refs(raw["evidence_refs"])
        contact_ref = self._contact_ref(raw["contact_ref"])
        purpose = self._choice(
            raw["contact_purpose_basis"],
            "contact_purpose_basis",
            CONTACT_PURPOSE_BASES,
        )
        dnc = self._choice(
            raw["do_not_contact_status"], "do_not_contact_status", DNC_STATUSES
        )
        if entity_type == "verified_contact_point" and (
            contact_ref is None or purpose == "not_applicable"
        ):
            raise ValueError(
                "verified_contact_point requires an opaque contact_ref and purpose basis"
            )
        if entity_type == "qualified_opportunity" and (
            signal_type != "first_party_need_verified" or not evidence_refs
        ):
            raise ValueError(
                "qualified_opportunity requires first-party need Evidence"
            )
        disposition = "suppressed" if dnc in {"do_not_contact", "withdrawn"} else "accepted"
        stage = {
            "seller_account": "observed",
            "supplier_entity": "entity_resolved",
            "prospect_account": "entity_resolved",
            "buyer_signal": "icp_matched",
            "verified_contact_point": "contact_basis_verified",
            "qualified_opportunity": "qualified_opportunity",
        }[entity_type]
        return {
            "source_family": family,
            "marketplace_or_site": self._safe_token(
                raw["marketplace_or_site"], "marketplace_or_site", 160
            ),
            "business_entity_name": self._safe_text(
                raw["business_entity_name"], "business_entity_name", 240
            ),
            "country_or_region": self._safe_token(
                raw["country_or_region"], "country_or_region", 120
            ),
            "category": self._safe_text(raw["category"], "category", 160),
            "public_business_url": self._business_url(raw["public_business_url"]),
            "entity_type": entity_type,
            "signal_type": signal_type,
            "signal_observed_at": signal_observed_at,
            "license_or_terms_basis": self._safe_text(
                raw["license_or_terms_basis"], "license_or_terms_basis", 500
            ),
            "contact_ref": contact_ref,
            "contact_purpose_basis": purpose,
            "jurisdiction": self._safe_token(
                raw["jurisdiction"], "jurisdiction", 80
            ),
            "do_not_contact_status": dnc,
            "confidence_bps": self._integer(
                raw["confidence_bps"], "confidence_bps", minimum=0, maximum=10000
            ),
            "evidence_refs": evidence_refs,
            "disposition": disposition,
            "lead_stage": stage,
        }

    def _verify_evidence_refs(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        scope: dict[str, str],
        as_of: datetime,
    ) -> None:
        if self.scoped_evidence is None:
            raise ValueError("scoped Evidence authority is required for evidence_refs")
        result = self.scoped_evidence.project(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope={
                "status": "ready",
                "entity_ref": scope["entity_ref"],
            },
            store_ref=scope["store_ref"],
            as_of=as_of,
        )
        if result.get("status") != "ready":
            raise ValueError("evidence_refs are not current and exact-scope ready")

    def _conservation(
        self,
        envelope: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> dict[str, int | str]:
        accepted = sum(record["disposition"] == "accepted" for record in records)
        suppressed = sum(record["disposition"] == "suppressed" for record in records)
        declared = envelope["conservation"]
        total = declared["source_total"]
        quarantined = declared["quarantined_count"]
        duplicate = declared["duplicate_count"]
        if accepted + suppressed + quarantined + duplicate != total:
            raise ValueError(
                "conservation failed: accepted + suppressed + quarantined + duplicate must equal source_total"
            )
        failed = len(envelope["pagination"]["failed_page_sha256"])
        status = "complete" if failed == 0 and quarantined == 0 else "partial"
        return {
            "source_total": total,
            "accepted_count": accepted,
            "suppressed_count": suppressed,
            "quarantined_count": quarantined,
            "duplicate_count": duplicate,
            "status": status,
        }

    def _scope(
        self, principal: Principal, store_ref: str, as_of: datetime
    ) -> dict[str, str]:
        store = self._safe_token(store_ref, "store_ref", 160)
        data_as_of = self._aware(as_of, "as_of")
        authority_checked_at = self._aware(self.clock(), "clock")
        if data_as_of > authority_checked_at:
            raise ValueError("as_of cannot be in the future")
        authority = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=authority_checked_at,
        )
        if authority.get("status") != "ready":
            raise PermissionError(
                str(authority.get("reason") or "exact-scope authority is not ready")
            )
        tenant = self._safe_token(authority.get("tenant_ref"), "tenant_ref", 160)
        entity = self._safe_token(authority.get("entity_ref"), "entity_ref", 160)
        authority_store = self._safe_token(
            authority.get("store_ref"), "authority_store_ref", 160
        )
        digest = self._sha256(
            authority.get("authority_sha256"), "scope_authority_sha256"
        )
        if tenant != principal.tenant_ref or authority_store != store:
            raise PermissionError("scope authority binding mismatch")
        return {
            "tenant_ref": tenant,
            "entity_ref": entity,
            "store_ref": store,
            "scope_authority_sha256": digest,
        }

    def _require_expected_scope_authority(
        self,
        *,
        scope: Mapping[str, str],
        expected_scope_authority_sha256: str | None,
    ) -> None:
        """Bind trusted internal readers without adding a router parameter."""

        if expected_scope_authority_sha256 is None:
            return
        try:
            expected = self._sha256(
                expected_scope_authority_sha256,
                "expected_scope_authority_sha256",
            )
        except ValueError as exc:
            raise KeyError(
                "Primary Source Intake not found in the authorized scope"
            ) from exc
        if not hmac.compare_digest(
            scope["scope_authority_sha256"], expected
        ):
            raise KeyError("Primary Source Intake not found in the authorized scope")

    def _row(
        self,
        *,
        intake_ref: str,
        scope: dict[str, str],
        envelope: dict[str, Any],
        counts: dict[str, Any],
        evidence_id: str,
        evidence_sha256: str,
        request_sha256: str,
        idempotency_sha256: str,
        principal: Principal,
        as_of: datetime,
        created_at: datetime,
    ) -> PrimarySourceIntakeRow:
        pagination = envelope["pagination"]
        integrity = envelope["integrity"]
        return PrimarySourceIntakeRow(
            intake_ref=intake_ref,
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            scope_authority_sha256=scope["scope_authority_sha256"],
            source_pack_id=envelope["source_pack_id"],
            source_contract_id=envelope["source_contract_id"],
            source_contract_version=envelope["source_contract_version"],
            subject_ref_sha256=envelope["subject_ref_sha256"],
            source_locator_sha256=envelope["source_locator_sha256"],
            blob_sha256=envelope["blob_sha256"],
            byte_count=envelope["byte_count"],
            mime_type=envelope["mime_type"],
            acquisition_mode=envelope["acquisition_mode"],
            admission_grade=self._grade(envelope["acquisition_mode"]).value,
            license_or_terms_basis=envelope["license_or_terms_basis"],
            allowed_purpose=envelope["allowed_purpose"],
            jurisdiction=envelope["jurisdiction"],
            retention_class=envelope["retention_class"],
            data_classification=envelope["data_classification"],
            cross_border_transfer_classification=envelope[
                "cross_border_transfer_classification"
            ],
            parser_version=envelope["parser_version"],
            verifier_id=integrity["verifier_id"],
            verifier_version=integrity["verifier_version"],
            captured_at=envelope["captured_at"],
            effective_at=envelope["effective_at"],
            verified_at=integrity["verified_at"],
            as_of=as_of,
            review_due_at=envelope["review_due_at"],
            source_total=counts["source_total"],
            accepted_count=counts["accepted_count"],
            suppressed_count=counts["suppressed_count"],
            quarantined_count=counts["quarantined_count"],
            duplicate_count=counts["duplicate_count"],
            field_count=envelope["field_count"],
            expected_pages=pagination["expected_pages"],
            received_pages=pagination["received_pages"],
            failed_page_count=len(pagination["failed_page_sha256"]),
            failed_page_sha256_json=pagination["failed_page_sha256"],
            checkpoint_sha256=pagination["checkpoint_sha256"],
            status=counts["status"],
            evidence_id=evidence_id,
            evidence_sha256=evidence_sha256,
            request_sha256=request_sha256,
            idempotency_sha256=idempotency_sha256,
            created_by=principal.actor_id,
            created_at=created_at,
        )

    def _record_row(
        self,
        *,
        intake_ref: str,
        scope: dict[str, str],
        ordinal: int,
        record: dict[str, Any],
        created_at: datetime,
    ) -> PrimarySourceRecordRow:
        return PrimarySourceRecordRow(
            record_ref=new_id("psr"),
            intake_ref=intake_ref,
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            ordinal=ordinal,
            source_record_sha256=record["source_record_sha256"],
            source_family=record["source_family"],
            marketplace_or_site=record["marketplace_or_site"],
            entity_type=record["entity_type"],
            business_entity_name=record["business_entity_name"],
            country_or_region=record["country_or_region"],
            category=record["category"],
            public_business_url=record["public_business_url"],
            signal_type=record["signal_type"],
            signal_observed_at=record["signal_observed_at"],
            license_or_terms_basis=record["license_or_terms_basis"],
            contact_ref=record["contact_ref"],
            contact_purpose_basis=record["contact_purpose_basis"],
            jurisdiction=record["jurisdiction"],
            do_not_contact_status=record["do_not_contact_status"],
            confidence_bps=record["confidence_bps"],
            evidence_refs_json=record["evidence_refs"],
            disposition=record["disposition"],
            lead_stage=record["lead_stage"],
            created_at=created_at,
        )

    def _find(
        self,
        session: Session,
        *,
        scope: dict[str, str],
        intake_ref: str,
        as_of: datetime,
    ) -> PrimarySourceIntakeRow:
        row = session.scalar(
            select(PrimarySourceIntakeRow).where(
                PrimarySourceIntakeRow.intake_ref == intake_ref,
                PrimarySourceIntakeRow.tenant_ref == scope["tenant_ref"],
                PrimarySourceIntakeRow.entity_ref == scope["entity_ref"],
                PrimarySourceIntakeRow.store_ref == scope["store_ref"],
                PrimarySourceIntakeRow.as_of <= as_of,
                PrimarySourceIntakeRow.created_at <= as_of,
            )
        )
        if row is None:
            raise KeyError("Primary Source Intake not found in the authorized scope")
        if not hmac.compare_digest(
            row.scope_authority_sha256, scope["scope_authority_sha256"]
        ):
            raise KeyError("Primary Source Intake not found in the authorized scope")
        return row

    def _project(
        self,
        session: Session,
        row: PrimarySourceIntakeRow,
        *,
        include_records: bool,
        replay: bool,
    ) -> dict[str, Any]:
        intake = {
            "intake_ref": row.intake_ref,
            "store_ref": row.store_ref,
            "scope_binding_sha256": row.scope_authority_sha256,
            "source_pack_id": row.source_pack_id,
            "source_contract_id": row.source_contract_id,
            "source_contract_version": row.source_contract_version,
            "subject_ref_sha256": row.subject_ref_sha256,
            "source_locator_sha256": row.source_locator_sha256,
            "blob_sha256": row.blob_sha256,
            "byte_count": row.byte_count,
            "mime_type": row.mime_type,
            "acquisition_mode": row.acquisition_mode,
            "admission_grade": row.admission_grade,
            "license_or_terms_basis": row.license_or_terms_basis,
            "allowed_purpose": row.allowed_purpose,
            "jurisdiction": row.jurisdiction,
            "retention_class": row.retention_class,
            "data_classification": row.data_classification,
            "cross_border_transfer_classification": (
                row.cross_border_transfer_classification
            ),
            "parser_version": row.parser_version,
            "verifier": {
                "id": row.verifier_id,
                "version": row.verifier_version,
                "raw_blob_reverified": True,
                "verified_at": self._database_time(row.verified_at),
            },
            "captured_at": self._database_time(row.captured_at),
            "effective_at": self._database_time(row.effective_at),
            "as_of": self._database_time(row.as_of),
            "review_due_at": self._database_time(row.review_due_at),
            "counts": {
                "source_total": row.source_total,
                "accepted": row.accepted_count,
                "suppressed": row.suppressed_count,
                "quarantined": row.quarantined_count,
                "duplicate": row.duplicate_count,
            },
            "pagination": {
                "expected_pages": row.expected_pages,
                "received_pages": row.received_pages,
                "failed_page_count": row.failed_page_count,
                "failed_page_sha256": list(row.failed_page_sha256_json),
                "checkpoint_sha256": row.checkpoint_sha256,
            },
            "quality": {
                "completeness": "passed",
                "uniqueness": "passed",
                "validity": "passed",
                "consistency": "passed",
                "timeliness": "passed",
                "accuracy": "pending_independent_review",
                "conservation": "passed",
            },
            "status": row.status,
            "evidence": {"id": row.evidence_id, "sha256": row.evidence_sha256},
            "request_sha256": row.request_sha256,
            "idempotent_replay": replay,
            "raw_source_retained": False,
            "personal_contact_retained": False,
            "formal_fact_promoted": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
            "created_by": row.created_by,
            "created_at": self._database_time(row.created_at),
        }
        records: list[dict[str, Any]] = []
        if include_records:
            stored = list(
                session.scalars(
                    select(PrimarySourceRecordRow)
                    .where(
                        PrimarySourceRecordRow.intake_ref == row.intake_ref,
                        PrimarySourceRecordRow.tenant_ref == row.tenant_ref,
                        PrimarySourceRecordRow.entity_ref == row.entity_ref,
                        PrimarySourceRecordRow.store_ref == row.store_ref,
                    )
                    .order_by(PrimarySourceRecordRow.ordinal)
                )
            )
            records = [self._project_record(record) for record in stored]
        return {"contract_id": CONTRACT_ID, "intake": intake, "records": records}

    @staticmethod
    def _project_record(row: PrimarySourceRecordRow) -> dict[str, Any]:
        return {
            "record_ref": row.record_ref,
            "ordinal": row.ordinal,
            "source_record_sha256": row.source_record_sha256,
            "source_family": row.source_family,
            "marketplace_or_site": row.marketplace_or_site,
            "entity_type": row.entity_type,
            "business_entity_name": row.business_entity_name,
            "country_or_region": row.country_or_region,
            "category": row.category,
            "public_business_url": row.public_business_url,
            "signal_type": row.signal_type,
            "signal_observed_at": row.signal_observed_at,
            "license_or_terms_basis": row.license_or_terms_basis,
            "contact_ref": row.contact_ref,
            "contact_purpose_basis": row.contact_purpose_basis,
            "jurisdiction": row.jurisdiction,
            "do_not_contact_status": row.do_not_contact_status,
            "confidence_bps": row.confidence_bps,
            "evidence_refs": list(row.evidence_refs_json),
            "disposition": row.disposition,
            "lead_stage": row.lead_stage,
        }

    @staticmethod
    def _database_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _manifest(
        self,
        *,
        intake_ref: str,
        scope: dict[str, str],
        envelope: dict[str, Any],
        records: list[dict[str, Any]],
        counts: dict[str, Any],
        request_sha256: str,
    ) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID,
            "intake_ref": intake_ref,
            "scope": scope,
            "source": {
                key: self._json_value(value)
                for key, value in envelope.items()
                if key not in {"conservation"}
            },
            "counts": counts,
            "record_hashes": [record["source_record_sha256"] for record in records],
            "request_sha256": request_sha256,
            "raw_source_retained": False,
            "personal_contact_retained": False,
            "formal_fact_promoted": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _grade(acquisition_mode: str) -> EvidenceGrade:
        if acquisition_mode == "terms_permitted_public_business_observation":
            return EvidenceGrade.C
        return EvidenceGrade.B

    def _pagination(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("pagination must be an object")
        self._exact_keys(
            raw,
            {"expected_pages", "received_pages", "failed_page_refs", "checkpoint_ref"},
            "pagination",
        )
        expected = self._integer(raw["expected_pages"], "expected_pages", minimum=1)
        received = self._integer(raw["received_pages"], "received_pages", minimum=0)
        failed_refs = raw["failed_page_refs"]
        if not isinstance(failed_refs, list) or len(failed_refs) > expected:
            raise ValueError("failed_page_refs must be a bounded list")
        failed_sha = [self._opaque_hash(item, "failed_page_ref") for item in failed_refs]
        if len(set(failed_sha)) != len(failed_sha):
            raise ValueError("failed_page_refs contain duplicates")
        if received + len(failed_sha) != expected:
            raise ValueError(
                "received_pages + failed_page_refs must equal expected_pages"
            )
        checkpoint = raw["checkpoint_ref"]
        if expected > 1 and not str(checkpoint or "").strip():
            raise ValueError("checkpoint_ref is required for paged sources")
        checkpoint_sha = (
            self._opaque_hash(checkpoint, "checkpoint_ref")
            if str(checkpoint or "").strip()
            else ZERO_SHA256
        )
        return {
            "expected_pages": expected,
            "received_pages": received,
            "failed_page_sha256": failed_sha,
            "checkpoint_sha256": checkpoint_sha,
        }

    def _integrity(
        self, raw: Any, captured_at: datetime, as_of: datetime
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("integrity must be an object")
        self._exact_keys(
            raw,
            {"raw_blob_reverified", "verifier_id", "verifier_version", "verified_at"},
            "integrity",
        )
        if raw["raw_blob_reverified"] is not True:
            raise ValueError("raw_blob_reverified must be true")
        verified_at = self._aware(raw["verified_at"], "verified_at")
        if verified_at < captured_at or verified_at > as_of:
            raise ValueError("verified_at must be between captured_at and as_of")
        return {
            "raw_blob_reverified": True,
            "verifier_id": self._token(raw["verifier_id"], "verifier_id"),
            "verifier_version": self._token(
                raw["verifier_version"], "verifier_version"
            ),
            "verified_at": verified_at,
        }

    def _conservation_input(self, raw: Any) -> dict[str, int]:
        if not isinstance(raw, dict):
            raise ValueError("conservation must be an object")
        self._exact_keys(
            raw,
            {"source_total", "quarantined_count", "duplicate_count"},
            "conservation",
        )
        return {
            "source_total": self._integer(
                raw["source_total"], "source_total", minimum=0
            ),
            "quarantined_count": self._integer(
                raw["quarantined_count"], "quarantined_count", minimum=0
            ),
            "duplicate_count": self._integer(
                raw["duplicate_count"], "duplicate_count", minimum=0
            ),
        }

    @classmethod
    def normalize_source_family(cls, value: Any) -> str:
        family = str(value or "").strip().lower()
        family = SOURCE_FAMILY_ALIASES.get(str(value or "").strip(), family)
        family = SOURCE_FAMILY_ALIASES.get(family, family)
        if family not in LEAD_SOURCE_FAMILIES:
            raise ValueError("Unsupported global trade lead source family")
        return family

    @staticmethod
    def _require_role(principal: Principal, *roles: str) -> None:
        if not principal.has_any_role(*roles):
            raise PermissionError("Authenticated actor lacks the required intake role")

    @staticmethod
    def _require_same_request(row: PrimarySourceIntakeRow, digest: str) -> None:
        if not hmac.compare_digest(row.request_sha256, digest):
            raise PrimarySourceConflictError(
                "Primary Source Intake idempotency key already has different content"
            )

    @staticmethod
    def _exact_keys(raw: Any, expected: set[str], field: str) -> None:
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ValueError(f"{field} fields do not match the frozen contract")

    @staticmethod
    def _integer(
        value: Any,
        field: str,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{field} must be an integer >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{field} must be <= {maximum}")
        return value

    @staticmethod
    def _choice(value: Any, field: str, allowed: frozenset[str] | set[str]) -> str:
        normalized = str(value or "").strip()
        if normalized not in allowed:
            raise ValueError(f"Unsupported {field}")
        return normalized

    @staticmethod
    def _token(value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not _TOKEN.fullmatch(normalized):
            raise ValueError(f"{field} must be a bounded opaque token")
        if _SECRET.search(normalized):
            raise ValueError(f"{field} contains secret-like material")
        return normalized

    @classmethod
    def _safe_token(cls, value: Any, field: str, maximum: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > maximum or any(ch in normalized for ch in "\r\n\t"):
            raise ValueError(f"{field} must be a bounded value")
        cls._reject_sensitive(normalized, field)
        return normalized

    @classmethod
    def _safe_text(cls, value: Any, field: str, maximum: int) -> str:
        normalized = " ".join(str(value or "").split())
        if not normalized or len(normalized) > maximum:
            raise ValueError(f"{field} must be a bounded non-empty value")
        cls._reject_sensitive(normalized, field)
        return normalized

    @staticmethod
    def _reject_sensitive(value: str, field: str) -> None:
        if _EMAIL.search(value) or _PHONE.search(value) or _SECRET.search(value):
            raise ValueError(f"{field} contains raw personal contact or secret material")

    @classmethod
    def _opaque_hash(cls, value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if (
            not normalized
            or len(normalized) > 500
            or any(ch.isspace() for ch in normalized)
            or any(ch in normalized for ch in "?#@\\")
        ):
            raise ValueError(f"{field} must be a safe opaque reference")
        cls._reject_sensitive(normalized, field)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not _HEX64.fullmatch(normalized):
            raise ValueError(f"{field} must be lowercase SHA-256 hex")
        return normalized

    @staticmethod
    def _mime(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if (
            not normalized
            or len(normalized) > 120
            or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", normalized)
        ):
            raise ValueError("mime_type is invalid")
        return normalized

    @classmethod
    def _business_url(cls, value: Any) -> str | None:
        if value is None or not str(value).strip():
            return None
        raw = str(value).strip()
        if len(raw) > 1000 or _SECRET.search(raw) or _EMAIL.search(raw):
            raise ValueError("public_business_url contains sensitive material")
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("public_business_url must be a public query-free URL")
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                "",
                "",
            )
        )

    @staticmethod
    def _contact_ref(value: Any) -> str | None:
        if value is None or not str(value).strip():
            return None
        normalized = str(value).strip()
        if not _CONTACT_REF.fullmatch(normalized) or "@" in normalized:
            raise ValueError("contact_ref must be an opaque CRM or vault reference")
        return normalized

    @staticmethod
    def _evidence_refs(value: Any) -> list[str]:
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError("evidence_refs must be a bounded list")
        refs = [str(item or "").strip() for item in value]
        if any(not ref or len(ref) > 160 for ref in refs) or len(set(refs)) != len(refs):
            raise ValueError("evidence_refs contain invalid or duplicate values")
        return sorted(refs)

    @staticmethod
    def _aware(value: Any, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _intake_ref(value: Any) -> str:
        normalized = str(value or "").strip()
        if not re.fullmatch(r"psi_[0-9a-f]{32}", normalized):
            raise ValueError("intake_ref is invalid")
        return normalized

    @staticmethod
    def _source_pack(value: Any) -> str:
        normalized = str(value or "").strip()
        if normalized not in SOURCE_PACKS:
            raise ValueError("Unsupported source_pack_id")
        return normalized

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

    @classmethod
    def _canonical(cls, value: Any) -> bytes:
        return json.dumps(
            cls._json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        if isinstance(value, dict):
            return {str(key): cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        return value
