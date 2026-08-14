from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.control_plane.fx_evidence_intake import (
    FxEvidenceIntake,
    FxEvidenceScope,
    FxEvidenceSubmission,
    FxSelectionRequest,
)

SCOPE = FxEvidenceScope("tenant-a", "entity-cn", "ozon-store-1")
OTHER_SCOPE = FxEvidenceScope("tenant-a", "entity-cn", "ozon-store-2")
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)
OCCURRED = datetime(2026, 8, 15, tzinfo=UTC)


def submission(
    *,
    source: str = "CNY",
    target: str = "RUB",
    rate: Decimal | str | int | None = "12.5",
    effective_at: datetime | None = START,
    expires_at: datetime | None = END,
    evidence_id: str = "evd-cbr-cny-rub-202608",
    source_type: str = "central_bank_reference",
    authority: str = "Bank of Russia",
    scope: FxEvidenceScope = SCOPE,
    purposes: tuple[str, ...] = ("scenario_profit", "reconciliation"),
    idempotency_key: str = "fx-cny-rub-202608",
) -> FxEvidenceSubmission:
    return FxEvidenceSubmission(
        scope=scope,
        source_currency=source,
        target_currency=target,
        rate=rate,
        effective_at=effective_at,
        expires_at=expires_at,
        evidence_id=evidence_id,
        source_type=source_type,
        authority=authority,
        purposes=purposes,
        idempotency_key=idempotency_key,
    )


def request(
    *,
    source: str = "CNY",
    target: str = "RUB",
    occurred_at: datetime = OCCURRED,
    purpose: str = "scenario_profit",
    as_of: datetime = OCCURRED + timedelta(days=1),
    scope: FxEvidenceScope = SCOPE,
    allow_triangulation: bool = False,
) -> FxSelectionRequest:
    return FxSelectionRequest(
        scope=scope,
        source_currency=source,
        target_currency=target,
        occurred_at=occurred_at,
        purpose=purpose,
        as_of=as_of,
        allow_triangulation=allow_triangulation,
    )


def test_ingest_builds_explicit_fx_record_and_reuses_money_basis_semantics() -> None:
    result = FxEvidenceIntake().ingest([submission()], expected_scope=SCOPE)

    assert result.status == "ready"
    assert not result.blockers
    assert result.records[0].basis.to_dict() == {
        "source_currency": "CNY",
        "target_currency": "RUB",
        "rate": "12.5",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "evidence_id": "evd-cbr-cny-rub-202608",
    }
    assert result.records[0].to_dict()["scope"] == SCOPE.to_dict()
    assert len(result.records[0].content_hash) == 64
    assert len(result.manifest_hash) == 64


@pytest.mark.parametrize("rate", [None, "NaN", "Infinity", "0", "-1", 12.5, True])
def test_ingest_blocks_missing_non_finite_non_positive_and_float_rates(rate: object) -> None:
    result = FxEvidenceIntake().ingest(
        [submission(rate=rate)],  # type: ignore[arg-type]
        expected_scope=SCOPE,
    )

    assert result.status == "blocked"
    assert not result.records
    assert result.blockers[0].code == "invalid_fx_evidence"


def test_ingest_requires_utc_and_a_strict_validity_interval() -> None:
    non_utc = timezone(timedelta(hours=8))
    non_utc_result = FxEvidenceIntake().ingest(
        [submission(effective_at=datetime(2026, 8, 1, tzinfo=non_utc))],
        expected_scope=SCOPE,
    )
    reversed_result = FxEvidenceIntake().ingest(
        [submission(effective_at=END, expires_at=START)],
        expected_scope=SCOPE,
    )

    assert non_utc_result.blockers[0].message == "effective_at must use UTC"
    assert reversed_result.blockers[0].message == "expires_at must be later than effective_at"
    with pytest.raises(ValueError, match="must use UTC"):
        request(occurred_at=datetime(2026, 8, 15, tzinfo=non_utc))


def test_ingest_rejects_cross_tenant_entity_or_store_scope() -> None:
    result = FxEvidenceIntake().ingest(
        [submission(scope=OTHER_SCOPE)],
        expected_scope=SCOPE,
    )

    assert result.status == "blocked"
    assert result.blockers[0].code == "cross_scope_evidence"
    assert not result.records


def test_identical_replay_is_idempotent_and_semantic_formatting_hashes_equally() -> None:
    intake = FxEvidenceIntake()
    original = submission(rate="12.5000", purposes=("reconciliation", "scenario_profit"))
    equivalent = submission(rate=Decimal("12.5"), purposes=("scenario_profit", "reconciliation"))

    first = intake.ingest([original], expected_scope=SCOPE)
    replay = intake.ingest(
        [original, equivalent],
        expected_scope=SCOPE,
        prior_content_hashes={original.idempotency_key: first.records[0].content_hash},
    )

    assert replay.status == "ready"
    assert len(replay.records) == 1
    assert replay.idempotent_replays == 2
    assert replay.records[0].content_hash == first.records[0].content_hash


def test_idempotency_key_content_drift_is_blocked_and_not_selectable() -> None:
    result = FxEvidenceIntake().ingest(
        [submission(rate="12.5"), submission(rate="12.6", evidence_id="evd-cbr-revised")],
        expected_scope=SCOPE,
    )

    assert result.status == "blocked"
    assert not result.records
    assert {item.code for item in result.blockers} == {"idempotency_content_drift"}


def test_prior_manifest_content_drift_is_blocked() -> None:
    result = FxEvidenceIntake().ingest(
        [submission()],
        expected_scope=SCOPE,
        prior_content_hashes={"fx-cny-rub-202608": "0" * 64},
    )

    assert result.status == "blocked"
    assert result.blockers[0].code == "idempotency_content_drift"


def test_reused_evidence_id_with_different_content_is_blocked() -> None:
    result = FxEvidenceIntake().ingest(
        [
            submission(idempotency_key="key-a"),
            submission(rate="12.6", idempotency_key="key-b"),
        ],
        expected_scope=SCOPE,
    )

    assert result.status == "blocked"
    assert not result.records
    assert result.blockers[0].code == "evidence_content_drift"


def test_same_validity_period_conflict_is_reported_and_selection_refuses_it() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [
            submission(evidence_id="evd-a", idempotency_key="key-a", rate="12.5"),
            submission(evidence_id="evd-b", idempotency_key="key-b", rate="12.7"),
        ],
        expected_scope=SCOPE,
    )

    selected = intake.select(result.records, request())

    assert result.status == "blocked"
    assert "validity_period_conflict" in {item.code for item in result.blockers}
    assert selected.status == "blocked"
    assert selected.blockers[0].code == "validity_period_conflict"


def test_selection_is_purpose_bound_and_deterministically_uses_latest_effective_rate() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [
            submission(
                rate="12.4",
                evidence_id="evd-old",
                idempotency_key="key-old",
                effective_at=START,
            ),
            submission(
                rate="12.8",
                evidence_id="evd-new",
                idempotency_key="key-new",
                effective_at=datetime(2026, 8, 10, tzinfo=UTC),
            ),
        ],
        expected_scope=SCOPE,
    )

    selected = intake.select(result.records, request())
    wrong_purpose = intake.select(result.records, request(purpose="cash_profit"))

    assert selected.status == "selected"
    assert selected.basis is not None
    assert selected.basis.rate == Decimal("12.8")
    assert selected.evidence_path[0].evidence_id == "evd-new"
    assert selected.to_dict()["path_kind"] == "direct"
    assert wrong_purpose.status == "blocked"
    assert wrong_purpose.blockers[0].code == "purpose_not_covered"


def test_selection_blocks_expired_future_and_future_occurrence_misuse() -> None:
    intake = FxEvidenceIntake()
    expired = intake.ingest(
        [submission(effective_at=START, expires_at=datetime(2026, 8, 10, tzinfo=UTC))],
        expected_scope=SCOPE,
    )
    future = intake.ingest(
        [submission(effective_at=datetime(2026, 8, 20, tzinfo=UTC))],
        expected_scope=SCOPE,
    )

    expired_selection = intake.select(expired.records, request())
    future_selection = intake.select(future.records, request())
    future_occurrence = intake.select(
        expired.records,
        request(as_of=datetime(2026, 8, 14, tzinfo=UTC)),
    )

    assert expired_selection.blockers[0].code == "expired_fx_evidence"
    assert future_selection.blockers[0].code == "future_effective_rate_not_permitted"
    assert future_occurrence.blockers[0].code == "future_occurrence_not_permitted"


def test_reverse_rate_is_never_inverted() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [submission(source="RUB", target="CNY", rate="0.08")],
        expected_scope=SCOPE,
    )

    selected = intake.select(result.records, request())

    assert selected.status == "blocked"
    assert selected.basis is None
    assert selected.blockers[0].code == "inverse_rate_not_permitted"


def test_selection_rejects_a_mixed_scope_input_even_when_an_in_scope_rate_exists() -> None:
    intake = FxEvidenceIntake()
    own = intake.ingest([submission()], expected_scope=SCOPE).records[0]
    foreign = intake.ingest(
        [submission(scope=OTHER_SCOPE, evidence_id="foreign", idempotency_key="foreign")],
        expected_scope=OTHER_SCOPE,
    ).records[0]

    selected = intake.select([own, foreign], request())

    assert selected.status == "blocked"
    assert selected.blockers[0].code == "cross_scope_evidence"


def test_complete_directed_triangulation_is_explicit_and_preserves_both_evidence_legs() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [
            submission(
                source="CNY",
                target="USD",
                rate="0.14",
                evidence_id="evd-cny-usd",
                idempotency_key="cny-usd",
            ),
            submission(
                source="USD",
                target="RUB",
                rate="90",
                evidence_id="evd-usd-rub",
                idempotency_key="usd-rub",
            ),
        ],
        expected_scope=SCOPE,
    )

    selected = intake.select(result.records, request(allow_triangulation=True))

    assert selected.status == "selected"
    assert selected.basis is not None
    assert selected.basis.rate == Decimal("12.60")
    assert selected.basis.evidence_id.startswith("fx-path:")
    assert [item.evidence_id for item in selected.evidence_path] == ["evd-cny-usd", "evd-usd-rub"]
    assert selected.to_dict()["path_kind"] == "triangulated"


def test_incomplete_triangulation_is_blocked_and_never_fills_a_missing_leg() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [
            submission(
                source="CNY",
                target="USD",
                rate="0.14",
                evidence_id="evd-cny-usd",
                idempotency_key="cny-usd",
            )
        ],
        expected_scope=SCOPE,
    )

    selected = intake.select(result.records, request(allow_triangulation=True))

    assert selected.status == "blocked"
    assert selected.basis is None
    assert selected.blockers[0].code == "triangulation_evidence_incomplete"


def test_selection_hash_is_stable_across_input_order_and_exposes_no_side_effects() -> None:
    intake = FxEvidenceIntake()
    result = intake.ingest(
        [
            submission(evidence_id="evd-a", idempotency_key="key-a"),
            submission(evidence_id="evd-b", idempotency_key="key-b"),
        ],
        expected_scope=SCOPE,
    )

    forward = intake.select(result.records, request())
    reverse = intake.select(tuple(reversed(result.records)), request())

    assert forward.status == "selected"
    assert forward.selection_hash == reverse.selection_hash
    assert forward.to_dict() == reverse.to_dict()
