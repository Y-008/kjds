from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..api_contracts import current_principal, ensure_role, run
from ..security import Principal
from ..strategic_capital_dashboard import CONTRACT_ID, CONTRACT_VERSION

router = APIRouter()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardDisplayItemResponse(StrictModel):
    item_ref: str
    label: str
    display_text: str


class DashboardCitationResponse(StrictModel):
    token: str = Field(
        pattern=(
            r"^(?:sbc|psc|gdc|gapc|capc|expc|outc|invc)_"
            r"[A-Za-z0-9_-]{16,256}$"
        )
    )
    summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


SectionId = Literal[
    "primary_source_coverage",
    "strategic_benchmark",
    "strategic_gaps",
    "opportunity_portfolio",
    "experiment_portfolio",
    "capital_proposals",
    "verified_outcomes",
    "invalidation_review",
]
SECTION_ORDER: tuple[SectionId, ...] = (
    "primary_source_coverage",
    "strategic_benchmark",
    "strategic_gaps",
    "opportunity_portfolio",
    "experiment_portfolio",
    "capital_proposals",
    "verified_outcomes",
    "invalidation_review",
)


class DashboardSectionEnvelope(StrictModel):
    section_id: SectionId
    display_order: int = Field(ge=0, le=7)
    scope_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_id: str
    source_contract_version: str
    source_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: list[str] = Field(min_length=1)
    global_top1_claim: Literal[False]
    production_admission: Literal[False]
    actionable_proposal: Literal[False]


class CurrentDashboardSectionResponse(DashboardSectionEnvelope):
    status: Literal["ready", "partial"]
    projection_ref: str
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_as_of: datetime
    recorded_at: datetime
    effective_at: datetime
    review_due_at: datetime
    citations: list[DashboardCitationResponse] = Field(min_length=1)
    display_items: list[DashboardDisplayItemResponse] = Field(min_length=1)
    invalidation_conditions: list[str] = Field(min_length=1)


class NonCurrentDashboardSectionResponse(DashboardSectionEnvelope):
    status: Literal["stale", "invalidated"]
    projection_ref: str
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_as_of: datetime
    recorded_at: datetime
    effective_at: datetime
    review_due_at: datetime
    citations: list[DashboardCitationResponse] = Field(min_length=1)
    display_items: list[DashboardDisplayItemResponse] = Field(max_length=0)
    invalidation_conditions: list[str] = Field(min_length=1)


class UnavailableDashboardSectionResponse(DashboardSectionEnvelope):
    status: Literal["no_data", "not_connected", "UNKNOWN"]
    projection_ref: None = None
    projection_sha256: None = None
    data_as_of: None = None
    recorded_at: None = None
    effective_at: None = None
    review_due_at: None = None
    citations: list[DashboardCitationResponse] = Field(max_length=0)
    display_items: list[DashboardDisplayItemResponse] = Field(max_length=0)
    invalidation_conditions: list[str] = Field(max_length=0)


DashboardSectionResponse = Annotated[
    CurrentDashboardSectionResponse
    | NonCurrentDashboardSectionResponse
    | UnavailableDashboardSectionResponse,
    Field(discriminator="status"),
]


class DashboardSideEffectsResponse(StrictModel):
    evidence_writes: Literal[0]
    fact_writes: Literal[0]
    finance_entry_writes: Literal[0]
    graph_writes: Literal[0]
    approval_writes: Literal[0]
    permit_writes: Literal[0]
    pilot_writes: Literal[0]
    outbox_writes: Literal[0]
    external_writes: Literal[0]
    network_writes: Literal[0]


class StrategicCapitalDashboardResponse(StrictModel):
    contract_id: Literal[CONTRACT_ID]
    contract_version: Literal[CONTRACT_VERSION]
    registry_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dashboard_ref: str
    scope_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    store_ref: str
    data_as_of: datetime
    authority_checked_at: datetime
    overall_state: Literal[
        "ready", "partial", "no_data", "stale", "invalidated", "UNKNOWN"
    ]
    reason_codes: list[str]
    sections: list[DashboardSectionResponse] = Field(min_length=8, max_length=8)
    global_top1_claim: Literal[False]
    production_admission: Literal[False]
    budget_authority: Literal[False]
    side_effects: DashboardSideEffectsResponse
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_section_envelope(self):
        if tuple(section.section_id for section in self.sections) != SECTION_ORDER:
            raise ValueError("dashboard sections must match the frozen order")
        if any(
            section.display_order != index
            for index, section in enumerate(self.sections)
        ):
            raise ValueError("dashboard section display order drift")
        if any(
            section.scope_binding_sha256 != self.scope_binding_sha256
            for section in self.sections
        ):
            raise ValueError("dashboard section scope binding drift")
        return self


def _runtime_services():
    from ..runtime import runtime

    return runtime


@router.get(
    "/v1/strategic-capital-dashboard",
    response_model=StrategicCapitalDashboardResponse,
    response_model_exclude_none=False,
)
def get_strategic_capital_dashboard(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "monitor",
        "admin",
    )
    return run(
        lambda: _runtime_services().strategic_capital_dashboard.read(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
        )
    )
