import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    CLOSED_LOOP_RESERVED_SOURCES,
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    LineageEdgeRow,
)
from apps.control_plane.research_inbox import ResearchInboxService
from apps.control_plane.sql_repository import Base

DEFAULT_SCOPE = {
    "tenant_ref": "tenant://default",
    "entity_ref": "entity://default",
    "store_ref": "store://default",
    "scope_grant_authority_sha256": "a" * 64,
}
FOREIGN_SCOPE = {
    "tenant_ref": "tenant://foreign",
    "entity_ref": "entity://foreign",
    "store_ref": "store://foreign",
    "scope_grant_authority_sha256": "f" * 64,
}
PUBLIC_RESEARCH_METADATA_FIELDS = {
    "evidence_role",
    "provider",
    "provider_record_id",
    "source_url",
    "captured_at",
    "raw_fields",
    "license_status",
    "review_status",
    "declared_grade",
    "promotion_status",
}
SERVER_ONLY_RESEARCH_FIELDS = {
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_grant_authority_sha256",
    "research_capture_contract_id",
    "research_capture_request_sha256",
    "research_scope_binding_sha256",
}


def assert_public_research_view(view: dict) -> None:
    assert set(view) == {
        "evidence",
        "candidate_refs",
        "integrity_valid",
        "decision_use",
        "automatic_listing",
        "automatic_procurement",
    }
    evidence = view["evidence"]
    assert set(evidence) == {
        "id",
        "sha256",
        "byte_size",
        "filename",
        "content_type",
        "source",
        "source_ref",
        "grade",
        "effective_at",
        "effective_until",
        "recorded_at",
        "created_by",
        "metadata",
    }
    assert set(evidence["metadata"]) == PUBLIC_RESEARCH_METADATA_FIELDS
    assert evidence["source_ref"] == evidence["metadata"]["provider_record_id"]
    assert evidence["recorded_at"] == evidence["metadata"]["captured_at"]

    def nested_keys(value) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(
                *(nested_keys(item) for item in value.values())
            )
        if isinstance(value, list):
            return set().union(*(nested_keys(item) for item in value))
        return set()

    assert nested_keys(view).isdisjoint(SERVER_ONLY_RESEARCH_FIELDS)


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return evidence, ResearchInboxService(evidence=evidence)


def capture(service, **overrides):
    values = {
        "content": b"provider export row",
        "filename": "signal.csv",
        "content_type": "text/csv",
        "provider": "Seerfar",
        "provider_record_id": "seerfar://export/row-1",
        "source_url": "https://www.seerfar.cn/features/",
        "observed_at": "2026-07-20T00:00:00Z",
        "declared_grade": EvidenceGrade.C,
        "license_status": "requires_review",
        "raw_fields": {"keyword": "storage box", "search_index": 81.5},
        "candidate_refs": ["candidate://storage-box-v1"],
        "created_by": "operator-1",
        "scope": DEFAULT_SCOPE,
        "authority_subject_actor_id": "operator-1",
    }
    values.update(overrides)
    exact_scope = values["scope"]
    values.setdefault(
        "authority_guard",
        lambda exact_scope=exact_scope: exact_scope,
    )
    return service.capture(**values)


def evidence_counts(evidence: EvidenceService) -> tuple[int, int, int]:
    with Session(evidence.engine) as session:
        return (
            session.scalar(select(func.count()).select_from(EvidenceRecordRow)) or 0,
            session.scalar(select(func.count()).select_from(EvidenceBlobRow)) or 0,
            session.scalar(select(func.count()).select_from(LineageEdgeRow)) or 0,
        )


def test_postgres_capture_lock_matches_scope_grant_trigger_key():
    calls = []

    class PostgreSQLBind:
        class dialect:
            name = "postgresql"

    class PostgreSQLSession:
        @staticmethod
        def get_bind():
            return PostgreSQLBind()

        @staticmethod
        def execute(statement, parameters):
            calls.append((str(statement), parameters))

    EvidenceService.lock_scope_authority_in_session(
        tenant_ref="tenant://default",
        store_ref="store://default",
        subject_actor_id="operator-1",
        session=PostgreSQLSession(),
    )

    assert len(calls) == 1
    statement, parameters = calls[0]
    assert "pg_advisory_xact_lock" in statement
    assert "hashtextextended" in statement
    assert (
        "concat_ws(chr(31), CAST(:tenant_ref AS text), "
        "CAST(:store_ref AS text), CAST(:subject_actor_id AS text))"
        in statement
    )
    assert parameters == {
        "tenant_ref": "tenant://default",
        "store_ref": "store://default",
        "subject_actor_id": "operator-1",
    }


def seed_decoys(evidence: EvidenceService, *, count: int) -> None:
    content = b"bounded research inbox decoy"
    digest = hashlib.sha256(content).hexdigest()
    recorded_at = datetime.now(UTC) + timedelta(minutes=5)
    reserved_sources = sorted(CLOSED_LOOP_RESERVED_SOURCES)
    with Session(evidence.engine) as session, session.begin():
        session.add(
            EvidenceBlobRow(
                sha256=digest,
                byte_size=len(content),
                content_bytes=content,
                created_at=recorded_at,
            )
        )
        for index in range(count):
            decoy_kind = index % 4
            reserved = decoy_kind == 0
            source = reserved_sources[index % len(reserved_sources)] if reserved else "operational-decoy"
            session.add(
                EvidenceRecordRow(
                    id=f"evd_decoy_{index:04d}",
                    blob_sha256=digest,
                    filename="decoy.json",
                    content_type="application/json",
                    source=source,
                    source_ref=f"decoy://{index:04d}",
                    grade=EvidenceGrade.D.value,
                    effective_at=recorded_at,
                    effective_until=None,
                    recorded_at=recorded_at,
                    created_by="test-seeder",
                    metadata_json={
                        "evidence_role": (
                            ResearchInboxService.EVIDENCE_ROLE
                            if decoy_kind in {0, 1, 3}
                            else "operational_snapshot"
                        ),
                        **(FOREIGN_SCOPE if decoy_kind in {0, 1} else DEFAULT_SCOPE),
                    },
                )
            )


def seed_equal_timestamp_research_rows(
    evidence: EvidenceService,
    *,
    evidence_ids: list[str],
    scope: dict[str, str] | None = None,
    candidate_ref: str | None = None,
    raw_fields: dict | None = None,
) -> None:
    content = b"equal timestamp research signal"
    digest = hashlib.sha256(content).hexdigest()
    recorded_at = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    exact_scope = scope or DEFAULT_SCOPE
    exact_raw_fields = {} if raw_fields is None else raw_fields
    with Session(evidence.engine) as session, session.begin():
        if session.get(EvidenceBlobRow, digest) is None:
            session.add(
                EvidenceBlobRow(
                    sha256=digest,
                    byte_size=len(content),
                    content_bytes=content,
                    created_at=recorded_at,
                )
            )
        for evidence_id in evidence_ids:
            provider = "research-fixture"
            provider_record_id = f"fixture://{evidence_id}"
            source_url = f"https://example.com/research/{evidence_id}"
            observed_at = recorded_at.isoformat()
            request_sha256 = ResearchInboxService._capture_request_sha256(
                content_sha256=digest,
                filename="research.json",
                content_type="application/json",
                provider=provider,
                provider_record_id=provider_record_id,
                source_url=source_url,
                observed_at=observed_at,
                declared_grade=EvidenceGrade.C.value,
                license_status="requires_review",
                raw_fields=exact_raw_fields,
                exact_scope=exact_scope,
            )
            session.add(
                EvidenceRecordRow(
                    id=evidence_id,
                    blob_sha256=digest,
                    filename="research.json",
                    content_type="application/json",
                    source=provider,
                    source_ref=ResearchInboxService._governed_source_ref(
                        provider_record_id=provider_record_id,
                        exact_scope=exact_scope,
                    ),
                    grade=EvidenceGrade.C.value,
                    effective_at=recorded_at,
                    effective_until=None,
                    recorded_at=recorded_at,
                    created_by="test-seeder",
                    metadata_json={
                        "evidence_role": ResearchInboxService.EVIDENCE_ROLE,
                        "provider": provider,
                        "provider_record_id": provider_record_id,
                        "source_url": source_url,
                        "captured_at": observed_at,
                        "raw_fields": exact_raw_fields,
                        "license_status": "requires_review",
                        "review_status": "pending_authority_review",
                        "declared_grade": EvidenceGrade.C.value,
                        "promotion_status": "auxiliary_only",
                        "research_capture_contract_id": (
                            ResearchInboxService.CAPTURE_CONTRACT_ID
                        ),
                        "research_capture_request_sha256": request_sha256,
                        "research_scope_binding_sha256": (
                            ResearchInboxService._scope_binding_sha256(exact_scope)
                        ),
                        **exact_scope,
                    },
                )
            )
    if candidate_ref is not None:
        for evidence_id in evidence_ids:
            evidence.link(
                evidence_id=evidence_id,
                target_type=ResearchInboxService.TARGET_TYPE,
                target_id=candidate_ref,
                relationship=ResearchInboxService.RELATIONSHIP,
                created_by="test-seeder",
            )


def test_signal_is_append_only_deduplicated_and_can_link_multiple_candidates():
    evidence, service = make_service()
    first = capture(service)
    retry = capture(service, candidate_refs=["candidate://storage-box-v1", "candidate://storage-box-v2"])

    assert retry["evidence"]["id"] == first["evidence"]["id"]
    assert retry["candidate_refs"] == ["candidate://storage-box-v1", "candidate://storage-box-v2"]
    assert retry["integrity_valid"] is True
    assert retry["automatic_listing"] is False
    assert_public_research_view(first)
    assert_public_research_view(retry)
    listed = service.list(scope=DEFAULT_SCOPE)
    assert len(listed) == 1
    assert_public_research_view(listed[0])
    stored = evidence.get(first["evidence"]["id"])
    assert stored.metadata["review_status"] == "pending_authority_review"
    assert SERVER_ONLY_RESEARCH_FIELDS.issubset(stored.metadata)

    changed = capture(
        service,
        content=b"new provider export row",
        provider_record_id="seerfar://export/row-2",
    )
    assert changed["evidence"]["id"] != first["evidence"]["id"]


def test_signal_candidate_limit_is_cumulative_across_exact_replays():
    evidence, service = make_service()
    candidate_refs = [f"candidate://storage-box-v{index}" for index in range(20)]
    first = capture(service, candidate_refs=candidate_refs)
    baseline = evidence_counts(evidence)

    with pytest.raises(ValueError, match="at most 20 candidates"):
        capture(
            service,
            candidate_refs=["candidate://storage-box-overflow"],
        )

    assert evidence_counts(evidence) == baseline == (1, 1, 20)
    assert first["candidate_refs"] == sorted(candidate_refs)
    assert evidence.target_evidence_ids(
        target_type=ResearchInboxService.TARGET_TYPE,
        target_id="candidate://storage-box-overflow",
        relationship=ResearchInboxService.RELATIONSHIP,
    ) == []


def test_candidate_filter_returns_only_linked_research_signals(monkeypatch):
    evidence, service = make_service()
    one = capture(service)
    capture(
        service,
        content=b"another signal",
        provider_record_id="seerfar://export/row-2",
        candidate_refs=["candidate://other-v1"],
    )
    capture(
        service,
        scope=FOREIGN_SCOPE,
        candidate_refs=["candidate://storage-box-v1"],
    )
    monkeypatch.setattr(
        evidence,
        "target_evidence_ids",
        lambda **_: pytest.fail("Candidate lineage must remain a SQL subquery"),
    )

    rows = service.list(
        scope=DEFAULT_SCOPE,
        candidate_ref="candidate://storage-box-v1",
    )
    assert [row["evidence"]["id"] for row in rows] == [one["evidence"]["id"]]
    assert rows[0]["decision_use"] == "auxiliary_only_pending_independent_authority_review"


def test_server_side_filters_precede_limit_and_exclude_all_reserved_sources():
    evidence, service = make_service()
    signal = capture(service)
    seed_decoys(evidence, count=505)

    rows = service.list(scope=DEFAULT_SCOPE, limit=100)

    assert [row["evidence"]["id"] for row in rows] == [signal["evidence"]["id"]]
    assert {row["evidence"]["source"] for row in rows}.isdisjoint(
        CLOSED_LOOP_RESERVED_SOURCES
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"evidence_role": ResearchInboxService.EVIDENCE_ROLE},
        {
            "research_capture_contract_id": (
                ResearchInboxService.CAPTURE_CONTRACT_ID
            )
        },
    ],
)
def test_generic_evidence_capture_cannot_forge_research_contract(metadata):
    evidence, _ = make_service()

    with pytest.raises(ValueError, match="dedicated intake workflow"):
        evidence.capture(
            content=b"forged research row",
            filename="forged.json",
            content_type="application/json",
            source="forged-provider",
            source_ref="forged://row",
            grade=EvidenceGrade.D,
            effective_at="2026-08-07T00:00:00+00:00",
            effective_until=None,
            created_by="forger",
            metadata=metadata,
        )

    assert evidence_counts(evidence) == (0, 0, 0)


@pytest.mark.parametrize(
    ("recorded_at", "captured_at"),
    [
        ("2026-08-07T00:00:01+00:00", "2026-08-07T00:00:00+00:00"),
        ("2026-08-07T00:00:00Z", "2026-08-07T00:00:00+00:00"),
        ("2026-08-07T00:00:00+00:00", None),
    ],
)
def test_research_adapter_rejects_capture_time_drift_without_residue(
    recorded_at, captured_at
):
    evidence, _ = make_service()
    metadata = {
        "evidence_role": ResearchInboxService.EVIDENCE_ROLE,
        "research_capture_contract_id": ResearchInboxService.CAPTURE_CONTRACT_ID,
        "captured_at": captured_at,
    }

    with (
        Session(evidence.engine) as session,
        session.begin(),
        pytest.raises(ValueError, match="capture time"),
    ):
        evidence.capture_research_signal_evidence(
            content=b"drifted research row",
            filename="research.json",
            content_type="application/json",
            source="research-fixture",
            source_ref="research-fixture://drifted",
            grade=EvidenceGrade.C,
            effective_at="2026-08-07T00:00:00+00:00",
            recorded_at=recorded_at,
            created_by="test-seeder",
            metadata=metadata,
            session=session,
        )

    assert evidence_counts(evidence) == (0, 0, 0)


def test_research_adapter_cannot_bypass_reserved_source_ownership():
    evidence, service = make_service()

    with pytest.raises(ValueError, match="dedicated authority adapter"):
        capture(service, provider=sorted(CLOSED_LOOP_RESERVED_SOURCES)[0])

    assert evidence_counts(evidence) == (0, 0, 0)


def test_list_rejects_persisted_research_capture_time_drift():
    evidence, service = make_service()
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=["evd_research_time_drift"],
    )
    with Session(evidence.engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, "evd_research_time_drift")
        assert row is not None
        row.recorded_at = row.recorded_at + timedelta(seconds=1)

    before = evidence_counts(evidence)
    with pytest.raises(ValueError, match="metadata contract drifted"):
        service.list(scope=DEFAULT_SCOPE)
    assert evidence_counts(evidence) == before


def test_missing_candidate_returns_no_data_without_falling_back_to_global_page():
    evidence, service = make_service()
    capture(service)
    seed_decoys(evidence, count=505)

    assert (
        service.list(
            scope=DEFAULT_SCOPE,
            candidate_ref="candidate://missing-v1",
        )
        == []
    )


def test_equal_timestamp_research_signals_page_without_duplicates_or_omissions():
    evidence, service = make_service()
    evidence_ids = [f"evd_research_{index:03d}" for index in reversed(range(105))]
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=evidence_ids,
    )

    first = service.list(scope=DEFAULT_SCOPE, limit=100)
    first_cursor = first[-1]["evidence"]
    second = service.list(
        scope=DEFAULT_SCOPE,
        limit=100,
        cursor_recorded_at=datetime.fromisoformat(first_cursor["recorded_at"]),
        cursor_id=first_cursor["id"],
    )

    expected = sorted(evidence_ids)
    observed = [row["evidence"]["id"] for row in first + second]
    assert len(first) == 100
    assert len(second) == 5
    assert observed == expected
    assert len(observed) == len(set(observed))


def test_same_provider_record_is_deduplicated_per_exact_scope():
    evidence, service = make_service()
    first = capture(service)
    retry = capture(service)
    foreign = capture(
        service,
        scope=FOREIGN_SCOPE,
        candidate_refs=["candidate://foreign-v1"],
    )

    assert retry["evidence"]["id"] == first["evidence"]["id"]
    assert foreign["evidence"]["id"] != first["evidence"]["id"]
    assert foreign["evidence"]["source_ref"] == first["evidence"]["source_ref"]
    assert (
        evidence.get(foreign["evidence"]["id"]).source_ref
        != evidence.get(first["evidence"]["id"]).source_ref
    )
    assert evidence.get(foreign["evidence"]["id"]).metadata["provider_record_id"] == "seerfar://export/row-1"
    assert [
        item["evidence"]["id"]
        for item in service.list(scope=DEFAULT_SCOPE)
    ] == [first["evidence"]["id"]]
    assert [
        item["evidence"]["id"]
        for item in service.list(scope=FOREIGN_SCOPE)
    ] == [foreign["evidence"]["id"]]


def test_dedup_winner_scope_drift_fails_before_candidate_link():
    evidence, service = make_service()
    original = capture(service)
    with Session(evidence.engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, original["evidence"]["id"])
        assert row is not None
        row.metadata_json = {
            **row.metadata_json,
            "scope_grant_authority_sha256": "b" * 64,
        }

    with pytest.raises(ValueError, match="scope binding drifted"):
        capture(
            service,
            candidate_refs=["candidate://must-not-link"],
        )
    assert evidence.target_evidence_ids(
        target_type=ResearchInboxService.TARGET_TYPE,
        target_id="candidate://must-not-link",
        relationship=ResearchInboxService.RELATIONSHIP,
    ) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": b"changed provider export"},
        {"filename": "renamed.csv"},
        {"content_type": "application/json"},
        {"source_url": "https://www.seerfar.cn/alternate/"},
        {"observed_at": "2026-07-21T00:00:00Z"},
        {"declared_grade": EvidenceGrade.D},
        {"license_status": "restricted"},
        {"raw_fields": {"keyword": "storage box", "search_index": 82.0}},
    ],
)
def test_capture_request_drift_fails_before_new_evidence_or_lineage(overrides):
    evidence, service = make_service()
    immutable_baseline = {
        "declared_grade": EvidenceGrade.A,
        "license_status": "verified",
    }
    original = capture(service, **immutable_baseline)
    baseline = evidence_counts(evidence)
    drifted_request = {**immutable_baseline, **overrides}

    with pytest.raises(ValueError, match="immutable .* binding drifted"):
        capture(
            service,
            candidate_refs=["candidate://must-not-link"],
            **drifted_request,
        )

    assert evidence_counts(evidence) == baseline
    assert evidence_counts(evidence) == (1, 1, 1)
    assert evidence.target_evidence_ids(
        target_type=ResearchInboxService.TARGET_TYPE,
        target_id="candidate://must-not-link",
        relationship=ResearchInboxService.RELATIONSHIP,
    ) == []
    assert evidence.get(original["evidence"]["id"]).metadata[
        "license_status"
    ] == "verified"


def test_authority_rotation_rolls_back_evidence_blob_and_lineage_atomically():
    evidence, service = make_service()
    rotated_scope = {
        **DEFAULT_SCOPE,
        "scope_grant_authority_sha256": "b" * 64,
    }
    authorities = iter([DEFAULT_SCOPE, rotated_scope])

    with pytest.raises(ValueError, match="authority is no longer current"):
        capture(
            service,
            candidate_refs=["candidate://must-not-persist"],
            authority_guard=lambda: next(authorities),
        )

    assert evidence_counts(evidence) == (0, 0, 0)
    assert service.list(scope=DEFAULT_SCOPE) == []


@pytest.mark.parametrize(
    "invalid_scope",
    [
        {**DEFAULT_SCOPE, "entity_ref": None},
        {**DEFAULT_SCOPE, "store_ref": 17},
    ],
)
def test_exact_scope_rejects_non_string_values_without_residue(invalid_scope):
    evidence, service = make_service()

    with pytest.raises(ValueError, match="exact scope is invalid"):
        capture(service, scope=invalid_scope)
    with pytest.raises(ValueError, match="exact scope is invalid"):
        service.list(scope=invalid_scope)

    assert evidence_counts(evidence) == (0, 0, 0)


def test_cursor_must_match_scope_candidate_and_database_timestamp():
    evidence, service = make_service()
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=["evd_candidate_one"],
        candidate_ref="candidate://one",
    )
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=["evd_candidate_two"],
        candidate_ref="candidate://two",
    )
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=["evd_foreign_scope"],
        scope=FOREIGN_SCOPE,
        candidate_ref="candidate://one",
    )
    cursor_time = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="current query scope"):
        service.list(
            scope=DEFAULT_SCOPE,
            candidate_ref="candidate://one",
            cursor_recorded_at=cursor_time,
            cursor_id="evd_candidate_two",
        )
    with pytest.raises(ValueError, match="current query scope"):
        service.list(
            scope=DEFAULT_SCOPE,
            candidate_ref="candidate://one",
            cursor_recorded_at=cursor_time,
            cursor_id="evd_foreign_scope",
        )
    with pytest.raises(ValueError, match="does not match"):
        service.list(
            scope=DEFAULT_SCOPE,
            candidate_ref="candidate://one",
            cursor_recorded_at=cursor_time + timedelta(seconds=1),
            cursor_id="evd_candidate_one",
        )


def test_authority_rotation_invalidates_old_cursor():
    evidence, service = make_service()
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=["evd_old_authority"],
    )
    rotated_scope = {
        **DEFAULT_SCOPE,
        "scope_grant_authority_sha256": "c" * 64,
    }

    with pytest.raises(ValueError, match="current query scope"):
        service.list(
            scope=rotated_scope,
            cursor_recorded_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
            cursor_id="evd_old_authority",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"raw_fields": {"api_key": "secret"}}, "Sensitive or invalid"),
        ({"raw_fields": {"tenant_ref": "forged"}}, "Sensitive or invalid"),
        ({"source_url": "https://example.com/export?token=secret"}, "credential query"),
        ({"license_status": "unknown"}, "license_status"),
        ({"candidate_refs": ["bad candidate ref"]}, "Candidate reference"),
        ({"candidate_refs": [None]}, "Candidate reference must be a string"),
    ],
)
def test_signal_intake_rejects_sensitive_or_unbounded_metadata(overrides, message):
    _, service = make_service()
    with pytest.raises(ValueError, match=message):
        capture(service, **overrides)


@pytest.mark.parametrize("internal_field", sorted(SERVER_ONLY_RESEARCH_FIELDS))
def test_list_rejects_self_consistent_stored_internal_raw_field(internal_field):
    evidence, service = make_service()
    seed_equal_timestamp_research_rows(
        evidence,
        evidence_ids=[f"evd_internal_raw_{internal_field}"],
        raw_fields={internal_field: "must-not-leak"},
    )
    baseline = evidence_counts(evidence)

    with pytest.raises(ValueError, match="metadata contract drifted"):
        service.list(scope=DEFAULT_SCOPE)

    assert evidence_counts(evidence) == baseline == (1, 1, 0)
