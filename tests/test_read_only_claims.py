from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.pilot_readiness import ReadOnlyPilotRow
from apps.control_plane.pilot_runs import ReadOnlyPilotRunRow
from apps.control_plane.read_only_claims import ReadOnlyClaimService
from apps.control_plane.sql_repository import Base


def service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    record = evidence.capture(
        content=b"successful read summary",
        filename="summary.json",
        content_type="application/json",
        source="test",
        source_ref="successful-run",
        grade=EvidenceGrade.B,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="reader",
    )
    now = datetime(2026, 7, 17, 1, 0, tzinfo=UTC)
    from apps.control_plane.domain import new_id

    pilot_id = new_id("rop")
    run_id = new_id("ror")
    state_hash = "a" * 64
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        session.add(
            ReadOnlyPilotRow(
                id=pilot_id,
                idempotency_key="claims-pilot",
                platform="ozon",
                account_alias="ozon-main",
                allowed_operations_json=["ozon.product.read"],
                max_daily_requests=10,
                max_targets=10,
                starts_at=now,
                ends_at=now,
                evidence_json=[record.id],
                status="active",
                requested_by="owner",
                reviewed_by="reviewer",
                review_rationale="approved",
                activated_by="admin",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ReadOnlyPilotRunRow(
                id=run_id,
                idempotency_key="claims-run",
                request_hash="b" * 64,
                pilot_id=pilot_id,
                operation="ozon.product.read",
                target_hash="c" * 64,
                worker_id="reader",
                status="completed",
                outcome="succeeded",
                response_sha256="d" * 64,
                response_byte_size=10,
                record_count=2,
                summary_json={
                    "contract_version": "ozon-product-read-v1",
                    "state_sha256": state_hash,
                    "info_item_count": 1,
                    "attribute_item_count": 1,
                },
                error_code=None,
                evidence_id=record.id,
                started_at=now,
                lease_expires_at=now,
                completed_at=now,
            )
        )
    return ReadOnlyClaimService(engine=engine, evidence=evidence), run_id, state_hash, record.id


def test_claim_requires_matching_successful_run_and_is_idempotent():
    claims, run_id, state_hash, evidence_id = service()
    payload = {
        "idempotency_key": "claim-1",
        "claim_type": "product_attribute",
        "payload": {"currency_code": "RUB", "stock_count": 4},
        "source_state_sha256": state_hash,
        "effective_at": "2026-07-17T01:00:00+00:00",
        "proposed_by": "reader",
    }
    created = claims.propose(run_id, **payload)
    retry = claims.propose(run_id, **payload)
    assert retry["id"] == created["id"]
    assert created["status"] == "pending_review"
    assert created["evidence_id"] == evidence_id
    assert created["formal_fact_promoted"] is False
    with pytest.raises(ValueError, match="does not match"):
        claims.propose(
            run_id,
            **{**payload, "idempotency_key": "claim-2", "source_state_sha256": "e" * 64},
        )


def test_claim_rejects_legacy_product_read_without_supported_contract():
    claims, run_id, state_hash, _ = service()
    from sqlalchemy.orm import Session

    with Session(claims.engine) as session, session.begin():
        run = session.get(ReadOnlyPilotRunRow, run_id)
        run.summary_json = {"state_sha256": state_hash, "info_item_count": 1}
    with pytest.raises(ValueError, match="supported Ozon product read contract"):
        claims.propose(
            run_id,
            idempotency_key="legacy-claim",
            claim_type="product_attribute",
            payload={"stock_count": 4},
            source_state_sha256=state_hash,
            effective_at="2026-07-17T01:00:00+00:00",
            proposed_by="reader",
        )


def test_claim_review_requires_independence_and_is_append_only():
    claims, run_id, state_hash, _ = service()
    created = claims.propose(
        run_id,
        idempotency_key="claim-review",
        claim_type="inventory_observation",
        payload={"stock_count": 4},
        source_state_sha256=state_hash,
        effective_at="2026-07-17T01:00:00+00:00",
        proposed_by="reader",
    )
    with pytest.raises(ValueError, match="independent"):
        claims.review(
            created["id"],
            decision="accepted",
            rationale="self review",
            reviewed_by="reader",
        )
    reviewed = claims.review(
        created["id"],
        decision="accepted",
        rationale="Evidence hash and payload reviewed.",
        reviewed_by="reviewer",
    )
    assert reviewed["status"] == "accepted"
    with pytest.raises(ValueError, match="pending"):
        claims.review(
            created["id"],
            decision="rejected",
            rationale="immutable",
            reviewed_by="admin",
        )


def test_claim_payload_rejects_sensitive_or_unknown_fields():
    claims, run_id, state_hash, _ = service()
    with pytest.raises(ValueError, match="prohibited"):
        claims.propose(
            run_id,
            idempotency_key="claim-unsafe",
            claim_type="product_attribute",
            payload={"customer_email": "hidden@example.test"},
            source_state_sha256=state_hash,
            effective_at="2026-07-17T01:00:00+00:00",
            proposed_by="reader",
        )
