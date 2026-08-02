from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.channel_account_authority import (
    ChannelAccountAdapterRegistry,
    ChannelAccountAuthorizationAuthority,
    ChannelAccountGovernanceEvidenceAuthority,
    ChannelAccountReviewDecisionRow,
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime.now(UTC) - timedelta(minutes=2)
ENTITY_SCOPE = {
    "status": "ready",
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "authority_sha256": "a" * 64,
}


class CanonicalMutationScope:
    def resolve(self, *, principal, entity_scope, store_ref, **_values):
        if principal.actor_id == "same-store-attacker":
            raise PermissionError("canonical mutation scope denied")
        expected = (
            "tenant-a",
            "entity-a",
            "ozon-primary",
            "a" * 64,
        )
        supplied = (
            principal.tenant_ref,
            entity_scope.get("entity_ref"),
            store_ref,
            entity_scope.get("authority_sha256"),
        )
        if entity_scope.get("status") != "ready" or supplied != expected:
            raise PermissionError("canonical mutation scope denied")
        return {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "ozon-primary",
            "scope_grant_authority_sha256": "a" * 64,
        }


class PerSubjectAuthorityHashScope(CanonicalMutationScope):
    """Models real per-subject Scope Grants: same tenant/entity/store, distinct authority hash."""

    def resolve(self, *, principal, entity_scope, store_ref, **_values):
        if entity_scope.get("status") != "ready":
            raise PermissionError("canonical mutation scope denied")
        if (
            principal.tenant_ref != entity_scope.get("tenant_ref")
            or entity_scope.get("entity_ref") != "entity-a"
            or store_ref != "ozon-primary"
        ):
            raise PermissionError("canonical mutation scope denied")
        authority = "a" * 64 if principal.actor_id == "operator-a" else "b" * 64
        return {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "ozon-primary",
            "scope_grant_authority_sha256": authority,
        }


def principal(actor, *roles, tenant="tenant-a", store="ozon-primary"):
    return Principal(
        actor_id=actor,
        roles=frozenset(roles),
        tenant_ref=tenant,
        store_refs=frozenset({store}),
    )


def services():
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
            ChannelAccountReviewDecisionRow.__table__,
        ],
    )
    evidence = EvidenceService(engine)
    return (
        evidence,
        ChannelAccountGovernanceEvidenceAuthority(
            evidence=evidence,
            scope_authority=CanonicalMutationScope(),
        ),
    )


def test_general_repository_cannot_forge_reserved_source_or_contract():
    evidence, _authority = services()
    common = {
        "content": b"{}",
        "filename": "forged.json",
        "content_type": "application/json",
        "source_ref": "forged://1",
        "grade": EvidenceGrade.A,
        "effective_at": NOW.isoformat(),
        "effective_until": None,
        "created_by": "attacker",
    }
    with pytest.raises(
        ValueError,
        match="separation-of-duties",
    ):
        evidence.capture(
            source="channel_account_authorization_consent",
            metadata={"reviewed_by": "attacker-review"},
            **common,
        )
    with pytest.raises(
        ValueError,
        match="separation-of-duties",
    ):
        evidence.capture(
            source="untrusted-upload",
            metadata={
                "contract_id": ("kjds-channel-account-consent-evidence-v1"),
                "reviewed_by": "attacker-review",
            },
            **common,
        )


def test_dedicated_review_derives_reviewer_and_canonical_content():
    evidence, authority = services()
    submitter = principal("operator-a", "operator", "reviewer")
    reviewer = principal("reviewer-a", "reviewer")
    canonical = {
        "contract_id": "kjds-channel-account-consent-evidence-v1",
        "status": "authorized",
        "revoked": False,
        "immutable": True,
    }
    submission = authority.submit(
        principal=submitter,
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        purpose="consent",
        effective_at=NOW.isoformat(),
        effective_until=None,
        idempotency_key="consent-a",
        semantic_metadata={
            "status": "authorized",
            "revoked": False,
            "immutable": True,
        },
        canonical_payload=canonical,
    )
    with pytest.raises(
        ValueError,
        match="independent submission",
    ):
        authority.review(
            principal=submitter,
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale="self review must fail",
            as_of=datetime.now(UTC),
        )
    reviewed = authority.review(
        principal=reviewer,
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        submission_evidence_id=submission["evidence_id"],
        accepted=True,
        rationale="independent review",
        as_of=datetime.now(UTC),
    )
    content, record = evidence.content(reviewed["evidence_id"])
    assert json.loads(content) == canonical
    assert record.metadata["submitted_by"] == "operator-a"
    assert record.metadata["reviewed_by"] == "reviewer-a"
    assert record.created_by == "operator-a"
    assert "secret-ref://" not in content.decode()


def test_review_accepts_distinct_subject_authority_hash_on_same_scope():
    evidence, _ = services()
    authority = ChannelAccountGovernanceEvidenceAuthority(
        evidence=evidence,
        scope_authority=PerSubjectAuthorityHashScope(),
    )
    submitter = principal("operator-a", "operator", "reviewer")
    reviewer = principal("reviewer-a", "reviewer")
    canonical = {
        "contract_id": "kjds-channel-account-consent-evidence-v1",
        "status": "authorized",
        "revoked": False,
        "immutable": True,
    }
    submission = authority.submit(
        principal=submitter,
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        purpose="consent",
        effective_at=NOW.isoformat(),
        effective_until=None,
        idempotency_key="consent-per-subject-hash",
        semantic_metadata={
            "status": "authorized",
            "revoked": False,
            "immutable": True,
        },
        canonical_payload=canonical,
    )
    reviewed = authority.review(
        principal=reviewer,
        entity_scope={**ENTITY_SCOPE, "authority_sha256": "b" * 64},
        store_ref="ozon-primary",
        submission_evidence_id=submission["evidence_id"],
        accepted=True,
        rationale="independent review under a distinct subject authority hash",
        as_of=datetime.now(UTC),
    )
    assert reviewed["reviewed_by"] == "reviewer-a"
    assert reviewed["submitted_by"] == "operator-a"


@pytest.mark.parametrize(
    "metadata",
    [
        {"reviewed_by": "self-certified"},
        {"token": "plaintext-token"},
        {"secret_reference": "vault://tenant/secret"},
        {"nested": {"cookie": "session-cookie"}},
    ],
)
def test_submission_rejects_self_review_and_credential_material(
    metadata,
):
    _evidence, authority = services()
    with pytest.raises(
        ValueError,
        match="server-owned|Credential material",
    ):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="consent",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="unsafe-a",
            semantic_metadata=metadata,
            canonical_payload={"status": "authorized"},
        )


def test_canonical_payload_also_rejects_credential_material():
    _evidence, authority = services()
    with pytest.raises(ValueError, match="Credential material"):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="lifecycle",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="unsafe-payload-a",
            semantic_metadata={"immutable": True},
            canonical_payload={"access_token": "plaintext-token"},
        )


@pytest.mark.parametrize(
    ("purpose", "metadata"),
    [
        ("consent", {"remote_operation_id": "not-valid-for-consent"}),
        ("permit", {"health_status": "healthy"}),
        ("readback", {"writes_enabled": True}),
        ("kill_switch", {"credential_kind": "api_key_ref"}),
        ("compensation", {"authorization_source": "official"}),
    ],
)
def test_each_evidence_purpose_has_a_closed_independent_schema(
    purpose,
    metadata,
):
    _evidence, authority = services()
    with pytest.raises(ValueError, match="Unknown field"):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose=purpose,
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key=f"closed-{purpose}",
            semantic_metadata=metadata,
            canonical_payload={"contract_id": f"contract-{purpose}"},
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        {"AccessToken": "plain-provider-credential"},
        {"authorization-header": "Bearer abcdefghijklmnopqrstuvwxyz012345"},
        {"nested": [{"api-key": "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUV"}]},
        {"owner": "%26lt%3BJWT%26gt%3B"},
        {"remote_operation_id": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.signature"},
    ],
)
def test_recursive_alias_and_encoded_secret_detection(unsafe):
    _evidence, authority = services()
    with pytest.raises(ValueError, match="Credential material|Unknown field"):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="readback",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="unsafe-alias",
            semantic_metadata=unsafe,
            canonical_payload={"contract_id": "readback-v1"},
        )


@pytest.mark.parametrize(
    ("semantic", "canonical"),
    [
        (
            {"allowed_capabilities": [115, 107, 95, 108, 105, 118, 101]},
            {"contract_id": "consent-v1"},
        ),
        (
            {
                "allowed_capabilities": [
                    "sk_",
                    "live_",
                    "ABCDEFGHIJKLMNOPQRSTUV123456",
                ]
            },
            {"contract_id": "consent-v1"},
        ),
        (
            {"consent_owner": "approved prose sk_" + "live_ABCDEFGHIJKLMNOPQRSTUV123456"},
            {"contract_id": "consent-v1"},
        ),
        (
            {"status": "authorized"},
            {
                "contract_id": "consent-v1",
                "secret_reference_sha256": ("msl_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
            },
        ),
        (
            {"status": "authorized"},
            {"contract_id": "consent-v1", "input_sha256": "f" * 63},
        ),
    ],
)
def test_typed_schema_rejects_fragmented_or_mistyped_secret_before_capture(
    semantic,
    canonical,
):
    evidence, authority = services()
    with pytest.raises(ValueError):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="consent",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="typed-smuggling",
            semantic_metadata=semantic,
            canonical_payload=canonical,
        )
    with Session(evidence.engine) as session:
        assert session.query(EvidenceRecordRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 0
        assert session.query(ChannelAccountReviewDecisionRow).count() == 0


@pytest.mark.parametrize(
    ("semantic", "canonical"),
    [
        (
            {"status": "authorized"},
            {
                "contract_id": "consent-v1",
                "status": "authorized",
                "secret_reference_sha256": "a" * 64,
            },
        ),
        (
            {
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABCDEFGHIJKLMNOPQRSTUV123456",
            },
            {
                "contract_id": "consent-v1",
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABCDEFGHIJKLMNOPQRSTUV123456",
            },
        ),
        (
            {
                "role_ref": "sk_",
                "subaccount_ref": "live_",
            },
            {
                "contract_id": "consent-v1",
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABCDEFGHIJKLMNOPQRSTUV123456",
            },
        ),
        (
            {
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABC",
            },
            {
                "contract_id": "DEF",
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABC",
            },
        ),
        (
            {
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABC",
            },
            {
                "contract_id": "DEF",
                "platform": "GHI",
                "role_ref": "sk_",
                "subaccount_ref": "live_",
                "consent_owner": "ABC",
            },
        ),
        (
            {
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": "0123456789abcdef" * 4,
            },
            {
                "contract_id": "consent-v1",
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": "0123456789abcdef" * 4,
            },
        ),
        (
            {
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": "&amp;lt;JWT&amp;gt;",
            },
            {
                "contract_id": "consent-v1",
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": "&amp;lt;JWT&amp;gt;",
            },
        ),
        (
            {
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": (
                    r"\u0073\u006b\u005f\u006c\u0069\u0076\u0065\u005f"
                    r"\u0041\u0042\u0043\u0044\u0045\u0046\u0047\u0048"
                ),
            },
            {
                "contract_id": "consent-v1",
                "status": "authorized",
                "revoked": False,
                "immutable": True,
                "consent_owner": (
                    r"\u0073\u006b\u005f\u006c\u0069\u0076\u0065\u005f"
                    r"\u0041\u0042\u0043\u0044\u0045\u0046\u0047\u0048"
                ),
            },
        ),
    ],
)
def test_client_digest_or_cross_scalar_secret_has_zero_persistence(
    semantic,
    canonical,
):
    evidence, authority = services()
    with pytest.raises(
        ValueError,
        match="server-derived authority|Credential material",
    ):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="consent",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="digest-or-scalar-smuggling",
            semantic_metadata=semantic,
            canonical_payload=canonical,
        )
    with Session(evidence.engine) as session:
        assert session.query(EvidenceRecordRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 0
        assert session.query(ChannelAccountReviewDecisionRow).count() == 0


def test_deeply_encoded_provider_secret_has_zero_persistence():
    evidence, authority = services()
    unsafe = "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUV123456"
    for _ in range(8):
        unsafe = "".join(
            f"%{ord(character):02X}" for character in unsafe
        )
    with pytest.raises(ValueError, match="Credential material"):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="consent",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="deep-url-encoding",
            semantic_metadata={"consent_owner": unsafe},
            canonical_payload={
                "contract_id": "consent-v1",
                "consent_owner": unsafe,
            },
        )
    with Session(evidence.engine) as session:
        assert session.query(EvidenceRecordRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 0
        assert session.query(ChannelAccountReviewDecisionRow).count() == 0


def _submit_consent(authority):
    return authority.submit(
        principal=principal("operator-a", "operator"),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        purpose="consent",
        effective_at=NOW.isoformat(),
        effective_until=None,
        idempotency_key="decision-sequence",
        semantic_metadata={
            "status": "authorized",
            "revoked": False,
            "immutable": True,
        },
        canonical_payload={
            "contract_id": "consent-v1",
            "status": "authorized",
            "revoked": False,
            "immutable": True,
        },
    )


def test_semantic_ready_cannot_split_from_blocked_canonical_blob():
    evidence, authority = services()
    with pytest.raises(ValueError, match="missing required fields"):
        authority.submit(
            principal=principal("operator-a", "operator"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            purpose="readback",
            effective_at=NOW.isoformat(),
            effective_until=None,
            idempotency_key="split-readback",
            semantic_metadata={
                "outcome": "succeeded",
                "official_or_authorized": True,
            },
            canonical_payload={
                "contract_id": "readback-v1",
                "outcome": "unknown",
                "official_or_authorized": False,
            },
        )
    with Session(evidence.engine) as session:
        assert session.query(EvidenceRecordRow).count() == 0
        assert session.query(EvidenceBlobRow).count() == 0


def _admission(evidence, evidence_id):
    authority = ChannelAccountAuthorizationAuthority(
        engine=evidence.engine,
        evidence=evidence,
        scoped_evidence=object(),
        adapters=ChannelAccountAdapterRegistry(),
    )
    authority._require_reviewed_evidence(
        record=evidence.get(evidence_id),
        purpose="consent",
        context={
            "cutoff": datetime.now(UTC) + timedelta(minutes=1),
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
            },
        },
    )


def test_latest_review_decision_blocks_old_accept_and_allows_fresh_accept():
    evidence, authority = services()
    submission = _submit_consent(authority)
    accepted = authority.review(
        principal=principal("reviewer-a", "reviewer"),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        submission_evidence_id=submission["evidence_id"],
        accepted=True,
        rationale="independent accept",
        as_of=datetime.now(UTC),
    )
    _admission(evidence, accepted["evidence_id"])
    rejected = authority.review(
        principal=principal("reviewer-b", "reviewer"),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        submission_evidence_id=submission["evidence_id"],
        accepted=False,
        rationale="later canonical rejection",
        as_of=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="latest accepted"):
        _admission(evidence, accepted["evidence_id"])
    fresh = authority.review(
        principal=principal("reviewer-c", "reviewer"),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        submission_evidence_id=submission["evidence_id"],
        accepted=True,
        rationale="fresh independent acceptance after remediation",
        as_of=datetime.now(UTC),
    )
    assert rejected["review_sequence"] == 2
    assert fresh["review_sequence"] == 3
    _admission(evidence, fresh["evidence_id"])
    with pytest.raises(ValueError, match="latest accepted"):
        _admission(evidence, accepted["evidence_id"])


def test_concurrent_reviews_are_serialized_without_orphan_reserved_evidence():
    evidence, authority = services()
    submission = _submit_consent(authority)
    same_time = datetime.now(UTC)

    def review(actor):
        return authority.review(
            principal=principal(actor, "reviewer"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale=f"independent concurrent decision by {actor}",
            as_of=same_time,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, ("reviewer-a", "reviewer-b")))

    assert sorted(item["review_sequence"] for item in results) == [1, 2]
    with Session(evidence.engine) as session:
        decisions = session.scalars(
            select(ChannelAccountReviewDecisionRow).order_by(
                ChannelAccountReviewDecisionRow.sequence
            )
        ).all()
        reviewed_rows = session.scalars(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.source
                == "channel_account_authorization_consent"
            )
        ).all()
    assert [row.sequence for row in decisions] == [1, 2]
    assert len(reviewed_rows) == len(decisions) == 2
    assert {row.decision_evidence_id for row in decisions} == {
        row.id for row in reviewed_rows
    }


def test_review_decision_failure_rolls_back_reserved_evidence(monkeypatch):
    evidence, authority = services()
    submission = _submit_consent(authority)
    with Session(evidence.engine) as session:
        before_records = session.query(EvidenceRecordRow).count()

    def fail_decision(**_values):
        raise RuntimeError("simulated decision persistence failure")

    monkeypatch.setattr(authority, "_record_review_decision", fail_decision)
    with pytest.raises(RuntimeError, match="decision persistence failure"):
        authority.review(
            principal=principal("reviewer-a", "reviewer"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale="must roll back atomically",
            as_of=datetime.now(UTC),
        )
    with Session(evidence.engine) as session:
        assert session.query(EvidenceRecordRow).count() == before_records
        assert session.query(ChannelAccountReviewDecisionRow).count() == 0
def test_cross_tenant_review_fails_before_any_blob_content_read(monkeypatch):
    evidence, authority = services()
    submission = _submit_consent(authority)
    content_reads = 0
    original_content = evidence.content

    def counted_content(evidence_id):
        nonlocal content_reads
        content_reads += 1
        return original_content(evidence_id)

    monkeypatch.setattr(evidence, "content", counted_content)
    blob_queries = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _many):
        if "evidence_blobs" in statement.lower():
            blob_queries.append(statement)

    sqlalchemy_event.listen(
        evidence.engine,
        "before_cursor_execute",
        capture_sql,
    )
    with pytest.raises(PermissionError, match="canonical mutation scope denied"):
        authority.review(
            principal=principal(
                "reviewer-b",
                "reviewer",
                tenant="tenant-b",
                store="store-b",
            ),
            entity_scope={
                "status": "ready",
                "tenant_ref": "tenant-b",
                "entity_ref": "entity-b",
                "store_ref": "store-b",
            },
            store_ref="store-b",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale="must not read foreign blob",
            as_of=datetime.now(UTC),
        )
    assert content_reads == 0
    assert blob_queries == []


def test_same_tenant_store_forged_entity_fails_before_blob_read(monkeypatch):
    evidence, authority = services()
    submission = _submit_consent(authority)
    content_reads = 0
    original_content = evidence.content

    def counted_content(evidence_id):
        nonlocal content_reads
        content_reads += 1
        return original_content(evidence_id)

    monkeypatch.setattr(evidence, "content", counted_content)
    with pytest.raises(PermissionError, match="canonical mutation scope"):
        authority.review(
            principal=principal(
                "same-store-attacker",
                "reviewer",
            ),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale="must not read same-store foreign entity blob",
            as_of=datetime.now(UTC),
        )
    assert content_reads == 0


def test_review_rationale_secret_is_rejected_and_never_persisted():
    evidence, authority = services()
    submission = _submit_consent(authority)
    raw_secret = "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUV123456"
    with pytest.raises(ValueError, match="Credential material"):
        authority.review(
            principal=principal("reviewer-a", "reviewer"),
            entity_scope=ENTITY_SCOPE,
            store_ref="ozon-primary",
            submission_evidence_id=submission["evidence_id"],
            accepted=True,
            rationale=f"looks fine {raw_secret}",
            as_of=datetime.now(UTC),
        )
    with Session(evidence.engine) as session:
        blobs = session.scalars(select(EvidenceBlobRow)).all()
        records = session.scalars(select(EvidenceRecordRow)).all()
    serialized = (
        json.dumps(
            [record.metadata_json for record in records],
            sort_keys=True,
        )
        + b"".join(blob.content_bytes for blob in blobs).decode()
    )
    assert raw_secret not in serialized
