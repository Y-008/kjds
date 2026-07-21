import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
    LineageEdgeRow,
)
from apps.control_plane.pilot_readiness import PILOT_CONTROLS, PilotReadinessService
from apps.control_plane.pilot_runs import PilotRunService
from apps.control_plane.sql_repository import Base


class Incidents:
    def list(self):
        return [
            {
                "id": "drill-1",
                "mode": "drill",
                "status": "closed",
                "updated_at": "2026-07-16T00:00:00+00:00",
            }
        ]


class Switch:
    def current(self):
        return SimpleNamespace(engaged=False)


def services(*, daily=2, targets=1, lease_seconds=900, operation="ozon.product.read"):
    database = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    evidence = EvidenceService(database)
    source = evidence.capture(
        content=b"read-only pilot evidence",
        filename="pilot.txt",
        content_type="text/plain",
        source="test",
        source_ref="pilot-runs",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="owner",
    )
    pilots = PilotReadinessService(
        engine=database,
        evidence=evidence,
        incidents=Incidents(),
        kill_switch=Switch(),
    )
    pilot = pilots.create(
        idempotency_key="pilot-runs",
        platform="ozon",
        account_alias="ozon-main",
        allowed_operations=[operation],
        max_daily_requests=daily,
        max_targets=targets,
        starts_at="2026-07-17T00:00:00+00:00",
        ends_at="2026-07-20T00:00:00+00:00",
        evidence_ids=[source.id],
        requested_by="owner",
    )
    for control in PILOT_CONTROLS:
        pilots.attest(
            pilot["id"],
            control=control,
            passed=True,
            notes="verified",
            evidence_ids=[source.id],
            attested_by="owner",
        )
    pilots.submit_review(pilot["id"], actor_id="owner", as_of="2026-07-17T01:00:00+00:00")
    pilots.review(
        pilot["id"],
        accepted=True,
        rationale="independent review",
        actor_id="reviewer",
    )
    pilots.activate(pilot["id"], actor_id="admin", as_of="2026-07-17T01:00:00+00:00")
    return (
        PilotRunService(
            engine=database,
            pilots=pilots,
            evidence=evidence,
            lease_seconds=lease_seconds,
        ),
        pilot,
        evidence,
    )


def capture_response(runs, started, *, content=b'{"responses":[]}'):
    digest = hashlib.sha256(content).hexdigest()
    record = runs.capture_response(
        started["id"],
        content=content,
        response_sha256=digest,
        worker_id="reader-1",
    )
    return digest, len(content), record


def product_summary(*, state_sha256="b" * 64):
    return {
        "contract_version": "ozon-product-read-v1",
        "info_item_count": 1,
        "attribute_item_count": 1,
        "state_sha256": state_sha256,
    }


def finance_summary(*, operation_count=2, query_window_sha256="c" * 64):
    return {
        "contract_version": "ozon-finance-transactions-v1",
        "operation_count": operation_count,
        "page": 1,
        "page_size": 1000,
        "page_count": 1,
        "query_window_sha256": query_window_sha256,
    }


def test_finance_run_accepts_only_the_bounded_sanitized_contract():
    runs, pilot, _ = services(operation="ozon.finance.read")
    started = runs.start(
        pilot["id"],
        idempotency_key="finance-run-1",
        operation="ozon.finance.read",
        target_ref="c" * 64,
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    response_sha256, response_byte_size, _ = capture_response(runs, started)
    with pytest.raises(ValueError, match="record count"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=1,
            summary=finance_summary(),
            error_code=None,
            worker_id="reader-1",
        )
    with pytest.raises(ValueError, match="query SHA-256"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=2,
            summary=finance_summary(query_window_sha256="not-a-hash"),
            error_code=None,
            worker_id="reader-1",
        )
    completed = runs.complete(
        started["id"],
        outcome="succeeded",
        response_sha256=response_sha256,
        response_byte_size=response_byte_size,
        record_count=2,
        summary=finance_summary(),
        error_code=None,
        worker_id="reader-1",
    )
    assert completed["outcome"] == "succeeded"
    assert completed["raw_response_verified"] is True


def test_read_only_run_hashes_target_enforces_limits_and_captures_only_summary():
    runs, pilot, evidence = services()
    started = runs.start(
        pilot["id"],
        idempotency_key="run-1",
        operation="ozon.product.read",
        target_ref="private-offer-id",
        worker_id="reader-1",
        request_id="req-pilot-start",
        trace_id="trace-pilot-read",
        as_of="2026-07-17T01:10:00+00:00",
    )
    assert "private-offer-id" not in str(started)
    assert started["target_material_stored"] is False
    assert started["request_id"] == "req-pilot-start"
    assert started["trace_id"] == "trace-pilot-read"
    response_sha256, response_byte_size, raw_record = capture_response(runs, started)
    completed = runs.complete(
        started["id"],
        outcome="succeeded",
        response_sha256=response_sha256,
        response_byte_size=response_byte_size,
        record_count=2,
        summary=product_summary(),
        error_code=None,
        worker_id="reader-1",
    )
    assert completed["raw_response_stored"] is True
    assert completed["raw_response_verified"] is True
    assert completed["raw_response_integrity_code"] is None
    assert completed["raw_response_evidence_id"] == raw_record.id
    assert completed["immutable_after_completion"] is True
    content, record = evidence.content(completed["evidence_id"])
    assert b"private-offer-id" not in content
    assert b'"raw_response_stored":true' in content
    assert raw_record.id.encode() in content
    assert b'"request_id":"req-pilot-start"' in content
    assert b'"trace_id":"trace-pilot-read"' in content
    assert record.metadata["raw_response_stored"] is True
    usage = runs.usage(pilot["id"], as_of="2026-07-17T02:00:00+00:00")
    assert usage["daily_requests_used"] == 1
    assert usage["targets_used"] == 1
    assert usage["raw_responses_stored"] == 1
    with pytest.raises(ValueError, match="target limit"):
        runs.start(
            pilot["id"],
            idempotency_key="run-2",
            operation="ozon.product.read",
            target_ref="another-offer",
            worker_id="reader-1",
            as_of="2026-07-17T02:10:00+00:00",
        )


def test_read_only_run_is_idempotent_immutable_and_rejects_unsafe_summary():
    runs, pilot, _ = services()
    started = runs.start(
        pilot["id"],
        idempotency_key="run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    retry = runs.start(
        pilot["id"],
        idempotency_key="run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:11:00+00:00",
    )
    assert started["execution_granted"] is True
    assert started["idempotency_replay"] is False
    assert retry["id"] == started["id"]
    assert retry["execution_granted"] is False
    assert retry["idempotency_replay"] is True
    with pytest.raises(ValueError, match="raw response evidence"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256="a" * 64,
            response_byte_size=10,
            record_count=1,
            summary={"info_item_count": 1},
            error_code=None,
            worker_id="reader-1",
        )
    with pytest.raises(ValueError, match="does not match content"):
        runs.capture_response(
            started["id"],
            content=b"raw-response",
            response_sha256="a" * 64,
            worker_id="reader-1",
        )
    response_sha256, response_byte_size, _ = capture_response(runs, started)
    with pytest.raises(ValueError, match="prohibited field"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=1,
            summary={"customer_email": "hidden@example.test"},
            error_code=None,
            worker_id="reader-1",
        )
    with pytest.raises(ValueError, match="unsupported contract version"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=2,
            summary={**product_summary(), "contract_version": "ozon-product-read-v0"},
            error_code=None,
            worker_id="reader-1",
        )
    with pytest.raises(ValueError, match="one bound info and attribute item"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=1,
            summary={**product_summary(), "attribute_item_count": 0},
            error_code=None,
            worker_id="reader-1",
        )
    with pytest.raises(ValueError, match="record count"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=1,
            summary=product_summary(),
            error_code=None,
            worker_id="reader-1",
        )
    completed = runs.complete(
        started["id"],
        outcome="succeeded",
        response_sha256=response_sha256,
        response_byte_size=response_byte_size,
        record_count=2,
        summary=product_summary(),
        error_code=None,
        worker_id="reader-1",
    )
    terminal_replay = runs.start(
        pilot["id"],
        idempotency_key="run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:12:00+00:00",
    )
    assert terminal_replay["id"] == completed["id"]
    assert terminal_replay["status"] == "completed"
    assert terminal_replay["execution_granted"] is False
    assert terminal_replay["idempotency_replay"] is True
    assert runs.complete(
        started["id"],
        outcome="succeeded",
        response_sha256=response_sha256,
        response_byte_size=response_byte_size,
        record_count=2,
        summary=product_summary(),
        error_code=None,
        worker_id="reader-1",
    )["evidence_id"] == completed["evidence_id"]
    with pytest.raises(ValueError, match="immutable"):
        runs.complete(
            started["id"],
            outcome="failed",
            response_sha256=None,
            response_byte_size=0,
            record_count=0,
            summary={"retryable": False},
            error_code="FAILED",
            worker_id="reader-1",
        )


def test_expired_read_only_run_is_reaped_with_evidence_and_rejects_late_completion():
    runs, pilot, evidence = services(lease_seconds=30)
    started = runs.start(
        pilot["id"],
        idempotency_key="run-expiring",
        operation="ozon.product.read",
        target_ref="offer-expiring",
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    assert started["lease_expires_at"] == "2026-07-17T01:10:30+00:00"
    reaped = runs.reap_expired(as_of="2026-07-17T01:11:00+00:00", actor_id="reaper")
    assert reaped["reaped"] == 1
    expired = runs.get(started["id"])
    assert expired["status"] == "expired"
    assert expired["outcome"] == "failed"
    assert expired["error_code"] == "RUN_LEASE_EXPIRED"
    assert expired["evidence_id"] == reaped["evidence_ids"][started["id"]]
    content, _ = evidence.content(expired["evidence_id"])
    assert b"RUN_LEASE_EXPIRED" in content
    expired_replay = runs.start(
        pilot["id"],
        idempotency_key="run-expiring",
        operation="ozon.product.read",
        target_ref="offer-expiring",
        worker_id="reader-1",
        as_of="2026-07-17T01:12:00+00:00",
    )
    assert expired_replay["status"] == "expired"
    assert expired_replay["execution_granted"] is False
    assert expired_replay["idempotency_replay"] is True
    with pytest.raises(ValueError, match="lease has expired"):
        runs.complete(
            started["id"],
            outcome="succeeded",
            response_sha256="a" * 64,
            response_byte_size=10,
            record_count=1,
            summary={"info_item_count": 1},
            error_code=None,
            worker_id="reader-1",
        )


def test_captured_response_is_idempotent_and_recovered_without_expiring():
    runs, pilot, evidence = services(lease_seconds=30)
    started = runs.start(
        pilot["id"],
        idempotency_key="run-checkpoint-recovery",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    content = b'{"responses":[]}'
    digest = hashlib.sha256(content).hexdigest()
    values = {
        "content": content,
        "response_sha256": digest,
        "response_byte_size": len(content),
        "record_count": 2,
        "summary": product_summary(),
        "worker_id": "reader-1",
    }
    checkpoint = runs.checkpoint_success(started["id"], **values)
    replay = runs.checkpoint_success(started["id"], **values)
    assert checkpoint["status"] == "response_captured"
    assert checkpoint["recovery_pending"] is True
    assert replay["status"] == "response_captured"
    assert replay["checkpoint_evidence_id"] == checkpoint["checkpoint_evidence_id"]
    assert len([record for record in evidence.list() if record.source_ref == started["id"]]) == 1

    result = runs.reap_expired(as_of="2026-07-17T01:11:00+00:00", actor_id="reaper")
    recovered = runs.get(started["id"])
    assert result["recovered"] == 1
    assert result["reaped"] == 0
    assert result["recovered_run_ids"] == [started["id"]]
    assert recovered["status"] == "completed"
    assert recovered["outcome"] == "succeeded"
    assert recovered["error_code"] is None
    assert recovered["raw_response_evidence_id"] == checkpoint["checkpoint_evidence_id"]
    _, summary_record = evidence.content(recovered["evidence_id"])
    assert summary_record.created_by == "reaper"


def test_captured_response_rejects_mutation_and_finalize_is_idempotent():
    runs, pilot, evidence = services()
    started = runs.start(
        pilot["id"],
        idempotency_key="run-checkpoint-immutable",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    content = b'{"responses":[]}'
    digest = hashlib.sha256(content).hexdigest()
    runs.checkpoint_success(
        started["id"],
        content=content,
        response_sha256=digest,
        response_byte_size=len(content),
        record_count=2,
        summary=product_summary(),
        worker_id="reader-1",
    )
    with pytest.raises(ValueError, match="immutable"):
        runs.checkpoint_success(
            started["id"],
            content=content,
            response_sha256=digest,
            response_byte_size=len(content),
            record_count=2,
            summary=product_summary(state_sha256="c" * 64),
            worker_id="reader-1",
        )
    completed = runs.finalize_captured(started["id"], worker_id="reader-1")
    replay = runs.finalize_captured(started["id"], worker_id="reader-1")
    assert completed["id"] == replay["id"]
    assert completed["evidence_id"] == replay["evidence_id"]
    assert len([record for record in evidence.list() if record.source_ref == started["id"]]) == 2


def test_captured_response_recomputes_blob_hash_before_finalize():
    runs, pilot, evidence = services()
    started = runs.start(
        pilot["id"],
        idempotency_key="run-checkpoint-corrupt-blob",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-07-17T01:10:00+00:00",
    )
    content = b'{"responses":[]}'
    digest = hashlib.sha256(content).hexdigest()
    checkpoint = runs.checkpoint_success(
        started["id"],
        content=content,
        response_sha256=digest,
        response_byte_size=len(content),
        record_count=2,
        summary=product_summary(),
        worker_id="reader-1",
    )
    with Session(runs.engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, digest)
        assert blob is not None
        blob.content_bytes = b"x" * len(content)

    with pytest.raises(ValueError, match="RAW_RESPONSE_EVIDENCE_HASH_MISMATCH"):
        runs.finalize_captured(started["id"], worker_id="reader-1")
    blocked = runs.get(started["id"])
    assert blocked["status"] == "response_captured"
    assert blocked["raw_response_stored"] is True
    assert blocked["raw_response_verified"] is False
    assert blocked["raw_response_integrity_code"] == "RAW_RESPONSE_EVIDENCE_HASH_MISMATCH"
    assert blocked["evidence_id"] is None
    assert checkpoint["checkpoint_evidence_id"] == blocked["raw_response_evidence_id"]
    assert len([record for record in evidence.list() if record.source_ref == started["id"]]) == 1


def test_captured_response_missing_blob_and_lineage_fail_closed():
    runs, pilot, _ = services(daily=3, targets=2)
    for suffix, mutate in (("missing", "blob"), ("unlinked", "lineage")):
        started = runs.start(
            pilot["id"],
            idempotency_key=f"run-checkpoint-{suffix}",
            operation="ozon.product.read",
            target_ref=f"offer-{suffix}",
            worker_id="reader-1",
            as_of="2026-07-17T01:10:00+00:00",
        )
        content = f'{{"response":"{suffix}"}}'.encode()
        digest = hashlib.sha256(content).hexdigest()
        checkpoint = runs.checkpoint_success(
            started["id"],
            content=content,
            response_sha256=digest,
            response_byte_size=len(content),
            record_count=2,
            summary=product_summary(state_sha256=digest),
            worker_id="reader-1",
        )
        with Session(runs.engine) as session, session.begin():
            if mutate == "blob":
                blob = session.get(EvidenceBlobRow, digest)
                assert blob is not None
                session.delete(blob)
            else:
                edge = session.scalar(
                    select(LineageEdgeRow).where(
                        LineageEdgeRow.from_id == checkpoint["checkpoint_evidence_id"],
                        LineageEdgeRow.relationship == "raw_response",
                    )
                )
                assert edge is not None
                session.delete(edge)
        expected_code = (
            "RAW_RESPONSE_EVIDENCE_MISSING"
            if mutate == "blob"
            else "RAW_RESPONSE_LINEAGE_INVALID"
        )
        with pytest.raises(ValueError, match=expected_code):
            runs.finalize_captured(started["id"], worker_id="reader-1")
        assert runs.get(started["id"])["raw_response_integrity_code"] == expected_code


def test_reaper_isolates_corrupt_response_and_recovers_healthy_run():
    runs, pilot, evidence = services(daily=3, targets=2, lease_seconds=30)
    run_ids = []
    digests = []
    for suffix in ("corrupt", "healthy"):
        started = runs.start(
            pilot["id"],
            idempotency_key=f"run-reaper-{suffix}",
            operation="ozon.product.read",
            target_ref=f"offer-{suffix}",
            worker_id="reader-1",
            as_of="2026-07-17T01:10:00+00:00",
        )
        content = f'{{"response":"{suffix}"}}'.encode()
        digest = hashlib.sha256(content).hexdigest()
        runs.checkpoint_success(
            started["id"],
            content=content,
            response_sha256=digest,
            response_byte_size=len(content),
            record_count=2,
            summary=product_summary(state_sha256=digest),
            worker_id="reader-1",
        )
        run_ids.append(started["id"])
        digests.append(digest)
    with Session(runs.engine) as session, session.begin():
        corrupt_blob = session.get(EvidenceBlobRow, digests[0])
        assert corrupt_blob is not None
        corrupt_blob.content_bytes = b"!" * corrupt_blob.byte_size

    result = runs.reap_expired(as_of="2026-07-17T01:11:00+00:00", actor_id="reaper")
    assert result["recovered"] == 1
    assert result["recovered_run_ids"] == [run_ids[1]]
    assert result["recovery_blocked"] == 1
    assert result["recovery_blocked_run_ids"] == [run_ids[0]]
    assert result["recovery_blockers"] == {
        run_ids[0]: "RAW_RESPONSE_EVIDENCE_HASH_MISMATCH"
    }
    assert result["reaped"] == 0
    assert runs.get(run_ids[0])["status"] == "response_captured"
    assert runs.get(run_ids[1])["status"] == "completed"
    assert len([record for record in evidence.list() if record.source_ref == run_ids[0]]) == 1
    assert len([record for record in evidence.list() if record.source_ref == run_ids[1]]) == 2
