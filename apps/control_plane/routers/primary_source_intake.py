from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..api_contracts import current_principal, ensure_role, run
from ..primary_source_intake import CONTRACT_ID, PrimarySourceConflictError
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

SourcePack = Literal[
    "operating_cash_truth",
    "marketplace_demand_and_catalog",
    "unit_economics_supply_and_logistics",
    "global_trade_lead_intelligence",
    "customer_product_and_revenue",
    "ai_technology_and_cost_benchmark",
    "competitor_enterprise_and_capital",
    "risk_legal_security_and_compliance",
]
AcquisitionMode = Literal[
    "official_api",
    "account_owner_export",
    "licensed_dataset",
    "terms_permitted_public_business_observation",
    "consented_first_party_crm_import",
]
DataClassification = Literal[
    "business_public",
    "business_confidential",
    "financial_restricted",
    "personal_professional",
    "security_restricted",
]
CrossBorderClassification = Literal[
    "not_applicable", "domestic_only", "approved_transfer", "restricted"
]
RetentionClass = Literal[
    "operational", "financial", "compliance", "experiment", "security"
]
EntityType = Literal[
    "seller_account",
    "supplier_entity",
    "prospect_account",
    "buyer_signal",
    "verified_contact_point",
    "qualified_opportunity",
]
ContactPurposeBasis = Literal[
    "not_applicable",
    "consent",
    "existing_customer",
    "contractual_necessity",
    "documented_legitimate_business_interest",
]
DncStatus = Literal["unknown", "clear", "do_not_contact", "withdrawn"]


class PaginationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_pages: int = Field(ge=1, le=100_000)
    received_pages: int = Field(ge=0, le=100_000)
    failed_page_refs: list[str] = Field(default_factory=list, max_length=10_000)
    checkpoint_ref: str | None = Field(default=None, max_length=500)


class IntegrityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_blob_reverified: Literal[True]
    verifier_id: str = Field(min_length=1, max_length=160)
    verifier_version: str = Field(min_length=1, max_length=160)
    verified_at: datetime


class ConservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_total: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)


class SourceEnvelopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_pack_id: SourcePack
    source_contract_id: str = Field(min_length=1, max_length=160)
    source_contract_version: str = Field(min_length=1, max_length=80)
    subject_ref: str = Field(min_length=1, max_length=500)
    source_locator_ref: str = Field(min_length=1, max_length=500)
    blob_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    mime_type: str = Field(min_length=3, max_length=120)
    captured_at: datetime
    effective_at: datetime
    acquisition_mode: AcquisitionMode
    license_or_terms_basis: str = Field(min_length=1, max_length=500)
    allowed_purpose: str = Field(min_length=1, max_length=500)
    jurisdiction: str = Field(min_length=1, max_length=80)
    retention_class: RetentionClass
    data_classification: DataClassification
    cross_border_transfer_classification: CrossBorderClassification
    parser_version: str = Field(min_length=1, max_length=80)
    field_count: int = Field(gt=0)
    pagination: PaginationInput
    integrity: IntegrityInput
    conservation: ConservationInput
    review_due_at: datetime


class LeadRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_family: str = Field(min_length=1, max_length=100)
    marketplace_or_site: str = Field(min_length=1, max_length=160)
    business_entity_name: str = Field(min_length=1, max_length=240)
    country_or_region: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=160)
    public_business_url: str | None = Field(default=None, max_length=1000)
    entity_type: EntityType
    signal_type: str = Field(min_length=1, max_length=80)
    signal_observed_at: datetime
    license_or_terms_basis: str = Field(min_length=1, max_length=500)
    contact_ref: str | None = Field(default=None, max_length=160)
    contact_purpose_basis: ContactPurposeBasis
    jurisdiction: str = Field(min_length=1, max_length=80)
    do_not_contact_status: DncStatus
    confidence_bps: int = Field(ge=0, le=10_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class PrimarySourceAdmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_ref: str = Field(min_length=1, max_length=160)
    as_of: datetime
    envelope: SourceEnvelopeInput
    records: list[LeadRecordInput] = Field(default_factory=list, max_length=500)


class VerifierOutput(BaseModel):
    id: str
    version: str
    raw_blob_reverified: bool
    verified_at: datetime


class CountsOutput(BaseModel):
    source_total: int
    accepted: int
    suppressed: int
    quarantined: int
    duplicate: int


class PaginationOutput(BaseModel):
    expected_pages: int
    received_pages: int
    failed_page_count: int
    failed_page_sha256: list[str]
    checkpoint_sha256: str


class QualityOutput(BaseModel):
    completeness: str
    uniqueness: str
    validity: str
    consistency: str
    timeliness: str
    accuracy: str
    conservation: str


class EvidenceRefOutput(BaseModel):
    id: str
    sha256: str


class PrimarySourceDescriptorOutput(BaseModel):
    intake_ref: str
    store_ref: str
    scope_binding_sha256: str
    source_pack_id: SourcePack
    source_contract_id: str
    source_contract_version: str
    subject_ref_sha256: str
    source_locator_sha256: str
    blob_sha256: str
    byte_count: int
    mime_type: str
    acquisition_mode: AcquisitionMode
    admission_grade: Literal["B", "C"]
    license_or_terms_basis: str
    allowed_purpose: str
    jurisdiction: str
    retention_class: RetentionClass
    data_classification: DataClassification
    cross_border_transfer_classification: CrossBorderClassification
    parser_version: str
    verifier: VerifierOutput
    captured_at: datetime
    effective_at: datetime
    as_of: datetime
    review_due_at: datetime
    counts: CountsOutput
    pagination: PaginationOutput
    quality: QualityOutput
    status: Literal["complete", "partial"]
    evidence: EvidenceRefOutput
    request_sha256: str
    idempotent_replay: bool
    raw_source_retained: Literal[False]
    personal_contact_retained: Literal[False]
    formal_fact_promoted: Literal[False]
    finance_entry_created: Literal[False]
    approval_created: Literal[False]
    permit_created: Literal[False]
    external_write_allowed: Literal[False]
    created_by: str
    created_at: datetime


class LeadRecordOutput(BaseModel):
    record_ref: str
    ordinal: int
    source_record_sha256: str
    source_family: str
    marketplace_or_site: str
    entity_type: EntityType
    business_entity_name: str
    country_or_region: str
    category: str
    public_business_url: str | None
    signal_type: str
    signal_observed_at: datetime
    license_or_terms_basis: str
    contact_ref: str | None
    contact_purpose_basis: ContactPurposeBasis
    jurisdiction: str
    do_not_contact_status: DncStatus
    confidence_bps: int
    evidence_refs: list[str]
    disposition: Literal["accepted", "suppressed"]
    lead_stage: Literal[
        "observed",
        "entity_resolved",
        "icp_matched",
        "contact_basis_verified",
        "qualified_opportunity",
    ]


class PrimarySourceAdmissionOutput(BaseModel):
    contract_id: Literal[CONTRACT_ID]
    intake: PrimarySourceDescriptorOutput
    records: list[LeadRecordOutput]


class PrimarySourceListOutput(BaseModel):
    contract_id: Literal[CONTRACT_ID]
    items: list[PrimarySourceDescriptorOutput]
    next_cursor: str | None


def _idempotency_key(
    value: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=160,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
        ),
    ],
) -> str:
    return value


def _execute(call):
    try:
        return run(call)
    except PrimarySourceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/v1/primary-source-intakes",
    status_code=201,
    response_model=PrimarySourceAdmissionOutput,
)
def admit_primary_source(
    body: PrimarySourceAdmissionInput,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
):
    ensure_role(principal, "operator", "admin")
    return _execute(
        lambda: runtime.primary_source_intake.admit(
            principal=principal,
            store_ref=body.store_ref,
            as_of=body.as_of,
            idempotency_key=idempotency_key,
            envelope=body.envelope.model_dump(),
            records=[record.model_dump() for record in body.records],
        )
    )


@router.get(
    "/v1/primary-source-intakes",
    response_model=PrimarySourceListOutput,
)
def list_primary_sources(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime,
    source_pack_id: SourcePack | None = None,
    status: Literal["complete", "partial"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
):
    ensure_role(
        principal, "operator", "reviewer", "compliance", "monitor", "admin"
    )
    return _execute(
        lambda: runtime.primary_source_intake.list(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            source_pack_id=source_pack_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(
    "/v1/primary-source-intakes/{intake_ref}",
    response_model=PrimarySourceAdmissionOutput,
)
def get_primary_source(
    intake_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime,
):
    ensure_role(
        principal, "operator", "reviewer", "compliance", "monitor", "admin"
    )
    return _execute(
        lambda: runtime.primary_source_intake.get(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            intake_ref=intake_ref,
        )
    )
