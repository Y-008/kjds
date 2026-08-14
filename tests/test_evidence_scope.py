from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.evidence_scope import (
    BINDING_CONTRACT,
    DIRECT_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

AS_OF = datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-cn-1",
    "authority": "kjds-scope-grant-events-v1",
}


def _authority() -> tuple[EvidenceService, ScopedEvidenceAuthority]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return evidence, ScopedEvidenceAuthority(evidence=evidence)


def _principal() -> Principal:
    return Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )


def _capture(
    evidence: EvidenceService,
    *,
    source_ref: str,
    created_by: str,
    metadata: dict | None = None,
    grade: EvidenceGrade = EvidenceGrade.B,
):
    return evidence.capture(
        content=f"immutable:{source_ref}".encode(),
        filename=f"{source_ref}.json",
        content_type="application/json",
        source="official-export",
        source_ref=f"official://{source_ref}",
        grade=grade,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by=created_by,
        metadata=metadata,
    )


def _direct_scope(*, reviewed_by: str = "reviewer-1") -> dict[str, str]:
    return {
        "evidence_scope_contract_id": DIRECT_CONTRACT,
        "tenant_ref": "tenant-cn-1",
        "entity_ref": "entity-cn-1",
        "store_ref": "store-cn-1",
        "reviewed_by": reviewed_by,
    }


def test_direct_scope_binding_is_ready_and_deterministic():
    evidence, authority = _authority()
    record = _capture(
        evidence,
        source_ref="direct",
        created_by="source-owner-1",
        metadata=_direct_scope(),
    )
    values = {
        "evidence_ids": [record.id],
        "principal": _principal(),
        "entity_scope": SCOPE,
        "store_ref": "store-cn-1",
        "as_of": AS_OF,
    }

    first = authority.project(**values)
    second = authority.project(**values)

    assert first == second
    assert first["status"] == "ready"
    assert first["records"][0]["scope_binding"] == {
        "status": "ready",
        "authority": DIRECT_CONTRACT,
        "binding_evidence_id": None,
        "reasons": [],
    }
    assert first["binding_authority_sha256"]


def test_legacy_evidence_requires_independent_grade_a_binding():
    evidence, authority = _authority()
    target = _capture(
        evidence,
        source_ref="legacy-target",
        created_by="source-owner-1",
    )
    unbound = authority.project(
        evidence_ids=[target.id],
        principal=_principal(),
        entity_scope=SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )
    binding = _capture(
        evidence,
        source_ref="legacy-binding",
        created_by="binding-recorder-1",
        grade=EvidenceGrade.A,
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": target.sha256,
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "reviewed_by": "independent-reviewer-1",
        },
    )
    bound = authority.project(
        evidence_ids=[target.id, binding.id],
        principal=_principal(),
        entity_scope=SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert unbound["status"] == "partial"
    assert unbound["source_gaps"] == ["evidence_scope_binding_missing"]
    assert bound["status"] == "ready"
    target_projection = next(
        item for item in bound["records"] if item["evidence_id"] == target.id
    )
    assert target_projection["scope_binding"] == {
        "status": "ready",
        "authority": BINDING_CONTRACT,
        "binding_evidence_id": binding.id,
        "reasons": [],
    }


def test_cross_scope_wrong_hash_and_self_review_fail_closed():
    evidence, authority = _authority()
    target = _capture(
        evidence,
        source_ref="target",
        created_by="same-actor",
    )
    binding = _capture(
        evidence,
        source_ref="conflicting-binding",
        created_by="same-actor",
        grade=EvidenceGrade.A,
        metadata={
            "evidence_scope_contract_id": BINDING_CONTRACT,
            "target_evidence_id": target.id,
            "target_evidence_sha256": "0" * 64,
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "other-store",
            "reviewed_by": "same-actor",
        },
    )

    result = authority.project(
        evidence_ids=[target.id, binding.id],
        principal=_principal(),
        entity_scope=SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == (
        f"evidence_scope_conflict:{binding.id}"
    )
    binding_projection = next(
        item for item in result["records"] if item["evidence_id"] == binding.id
    )
    assert set(binding_projection["scope_binding"]["reasons"]) >= {
        "binding_independence_missing",
        "binding_target_hash_mismatch",
        "store_ref_mismatch",
    }


def test_missing_entity_scope_is_no_data_and_never_guessed_from_tenant():
    evidence, authority = _authority()
    target = _capture(
        evidence,
        source_ref="direct-no-entity",
        created_by="source-owner-1",
        metadata=_direct_scope(),
    )

    result = authority.project(
        evidence_ids=[target.id],
        principal=_principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["records"][0]["scope_binding"]["status"] == "no_data"
    assert result["records"][0]["scope_binding"]["authority"] is None
    assert result["source_gaps"] == [
        "evidence_entity_scope_authority_missing"
    ]


def test_corrupted_evidence_blob_blocks_scope_projection():
    evidence, authority = _authority()
    record = _capture(
        evidence,
        source_ref="corrupted",
        created_by="source-owner-1",
        metadata=_direct_scope(),
    )
    with Session(evidence.engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, record.sha256)
        assert blob is not None
        blob.content_bytes = b"tampered"

    result = authority.project(
        evidence_ids=[record.id],
        principal=_principal(),
        entity_scope=SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["snapshot_sha256"] is None
    assert result["invalid_evidence_ids"] == [record.id]
    assert result["blockers"][0]["code"] == f"invalid_evidence:{record.id}"
