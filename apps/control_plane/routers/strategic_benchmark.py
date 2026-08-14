from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role
from ..security import Principal
from ..strategic_benchmark import StrategicBenchmarkConflictError

router = APIRouter()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategicBenchmarkSnapshotInput(StrictModel):
    store_ref: str = Field(min_length=1, max_length=160)
    as_of: datetime
    evidence_refs: list[str] = Field(min_length=1, max_length=5_000)

    @field_validator("evidence_refs")
    @classmethod
    def unique_bounded_refs(cls, value: list[str]) -> list[str]:
        refs = [item.strip() for item in value]
        if any(not item or len(item) > 160 for item in refs):
            raise ValueError("evidence_refs must contain bounded identifiers")
        if len(refs) != len(set(refs)):
            raise ValueError("evidence_refs must be unique")
        return refs


class CitationResponse(StrictModel):
    token: str
    sha256: str
    grade: str


class WithheldValueProjectionResponse(StrictModel):
    mode: Literal["withheld"]


class PublicExactValueProjectionResponse(StrictModel):
    mode: Literal["public_exact"]
    value: str
    lower: str
    upper: str


class InternalBandValueProjectionResponse(StrictModel):
    mode: Literal["internal_band"]
    lower: str
    upper: str


ValueProjectionResponse = Annotated[
    WithheldValueProjectionResponse
    | PublicExactValueProjectionResponse
    | InternalBandValueProjectionResponse,
    Field(discriminator="mode"),
]


class ObservationResponse(StrictModel):
    observation_ref: str
    ordinal: int
    subject_token: str
    subject_class: Literal["kjds_current", "peer", "frontier_candidate"]
    value_projection: ValueProjectionResponse
    confidence_bps: int
    sample_size: int
    source_grade: str
    citations: list[CitationResponse]
    evidence_snapshot_sha256: str
    observed_at: datetime
    freshness_due_at: datetime
    eligibility_state: Literal[
        "eligible",
        "ineligible_grade",
        "stale",
        "invalidated_source",
        "ineligible_confidence",
        "ineligible_sample",
    ]
    observation_sha256: str


class WindowResponse(StrictModel):
    start: datetime
    end: datetime


class MethodologyResponse(StrictModel):
    id: str
    version: str
    sha256: str
    sample_definition_sha256: str


class SourceContractResponse(StrictModel):
    id: str
    version: str
    sha256: str
    kind: str


class CountsResponse(StrictModel):
    observations: int
    comparable: int
    ineligible: int
    leaders: int


class GroupResponse(StrictModel):
    group_ref: str
    ordinal: int
    domain: str
    metric_id: str
    direction: Literal["higher_is_better", "lower_is_better"]
    unit: str
    minimum_source_grade: Literal["A", "B"]
    freshness_days: int
    minimum_confidence_bps: int
    minimum_sample_size: int
    cohort_ref: str
    market: str
    window: WindowResponse
    methodology: MethodologyResponse
    source_contract: SourceContractResponse
    comparison_state: Literal[
        "comparable",
        "partial",
        "not_comparable",
        "no_data",
        "stale",
        "invalidated",
    ]
    leader_label: Literal[
        "metric_leader", "frontier_candidate", "best_feasible_for_kjds"
    ] | None
    leader_observation_refs: list[str]
    reason_code: str
    counts: CountsResponse
    group_sha256: str
    result_sha256: str
    observations: list[ObservationResponse]
    global_top1_claim: Literal[False]


class SnapshotResponse(StrictModel):
    snapshot_ref: str
    store_ref: str
    registry_schema: str
    registry_sha256: str
    as_of: datetime
    group_count: int
    observation_count: int
    snapshot_citation: CitationResponse
    request_sha256: str
    idempotent_replay: bool
    global_top1_claim: Literal[False]
    formal_fact_created: Literal[False]
    finance_entry_created: Literal[False]
    approval_created: Literal[False]
    permit_created: Literal[False]
    external_write_allowed: Literal[False]
    created_at: datetime


class StrategicBenchmarkResponse(StrictModel):
    contract_id: str
    snapshot: SnapshotResponse
    groups: list[GroupResponse]


class StrategicBenchmarkListResponse(StrictModel):
    contract_id: str
    items: list[SnapshotResponse]
    next_cursor: str | None


class ComparisonItemResponse(StrictModel):
    domain: str
    metric_id: str
    cohort_ref: str
    market: str
    direction: Literal["higher_is_better", "lower_is_better"]
    unit: str
    current_group_ref: str
    baseline_group_ref: str | None
    state: Literal["comparable", "not_comparable", "stale", "invalidated"]
    reason_code: str
    current_label: str | None = None
    baseline_label: str | None = None
    current_leader_observation_refs: list[str] | None = None
    baseline_leader_observation_refs: list[str] | None = None
    current_leader_subject_tokens: list[str] | None = None
    baseline_leader_subject_tokens: list[str] | None = None
    leader_changed: bool | None = None


class StrategicBenchmarkComparisonResponse(StrictModel):
    contract_id: str
    snapshot_ref: str
    baseline_snapshot_ref: str
    as_of: datetime
    comparisons: list[ComparisonItemResponse]
    global_top1_claim: Literal[False]
    formal_fact_created: Literal[False]
    finance_entry_created: Literal[False]
    approval_created: Literal[False]
    permit_created: Literal[False]
    external_write_allowed: Literal[False]


def _runtime_services():
    from ..runtime import runtime

    return runtime


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
        return call()
    except StrategicBenchmarkConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, PermissionError) as exc:
        raise HTTPException(
            status_code=404,
            detail="Strategic benchmark resource not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/v1/strategic-benchmark-snapshots",
    status_code=201,
    response_model=StrategicBenchmarkResponse,
)
def build_strategic_benchmark_snapshot(
    body: StrategicBenchmarkSnapshotInput,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
):
    ensure_role(principal, "operator", "admin")
    return _execute(
        lambda: _runtime_services().strategic_benchmark.build_snapshot(
            principal=principal,
            store_ref=body.store_ref,
            as_of=body.as_of,
            idempotency_key=idempotency_key,
            evidence_refs=body.evidence_refs,
        )
    )


@router.get(
    "/v1/strategic-benchmark-snapshots",
    response_model=StrategicBenchmarkListResponse,
)
def list_strategic_benchmark_snapshots(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime,
    domain: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    metric_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    comparison_state: Annotated[
        Literal[
            "comparable",
            "partial",
            "not_comparable",
            "no_data",
            "stale",
            "invalidated",
        ]
        | None,
        Query(),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    return _execute(
        lambda: _runtime_services().strategic_benchmark.list(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            domain=domain,
            metric_id=metric_id,
            comparison_state=comparison_state,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(
    "/v1/strategic-benchmark-snapshots/{snapshot_ref}",
    response_model=StrategicBenchmarkResponse,
)
def get_strategic_benchmark_snapshot(
    snapshot_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    return _execute(
        lambda: _runtime_services().strategic_benchmark.get(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            snapshot_ref=snapshot_ref,
        )
    )


@router.get(
    "/v1/strategic-benchmark-snapshots/{snapshot_ref}/compare",
    response_model=StrategicBenchmarkComparisonResponse,
    response_model_exclude_none=True,
)
def compare_strategic_benchmark_snapshots(
    snapshot_ref: str,
    baseline_snapshot_ref: Annotated[str, Query(min_length=1, max_length=64)],
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)],
    as_of: datetime,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    return _execute(
        lambda: _runtime_services().strategic_benchmark.compare(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            snapshot_ref=snapshot_ref,
            baseline_snapshot_ref=baseline_snapshot_ref,
        )
    )
