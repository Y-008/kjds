import json
from datetime import UTC, datetime, timedelta
from math import inf

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceBlobRow, EvidenceRecordRow, EvidenceService
from apps.control_plane.media_jobs import (
    CAMPAIGN_BRIEF_CONTRACT,
    CAMPAIGN_BRIEF_VERSION,
    COMMANDER_REQUEST_CONTRACT,
    TOOL_DESCRIPTOR_CONTRACT,
    GovernedMediaJobWorkspace,
    MediaJobEventRow,
    MediaJobEvidenceLinkRow,
    MediaJobRow,
    MediaJobScope,
    canonical_json,
    event_seal,
    sha256_bytes,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

AUTHORITY = "a" * 64
BINDING = "b" * 64
IDEMPOTENCY = "c" * 64
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


class ScopeAuthority:
    def __init__(self) -> None:
        self.current_sha = AUTHORITY
        self.entity_ref = "entity-1"
        self.calls = []

    def current(self, **kwargs):
        self.calls.append(kwargs)
        principal = kwargs["principal"]
        return {
            "status": "ready" if self.current_sha else "revoked",
            "tenant_ref": principal.tenant_ref,
            "store_ref": kwargs["store_ref"],
            "entity_ref": self.entity_ref,
            "authority_sha256": self.current_sha,
        }


def workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    authority = ScopeAuthority()
    service = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=authority,
        clock=lambda: NOW,
    )
    return engine, authority, service


PRINCIPAL = Principal(
    actor_id="actor-1",
    roles=frozenset({"operator"}),
    tenant_ref="tenant-1",
    store_refs=frozenset({"store-1"}),
)


def scope(**changes):
    values = {
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "authority_sha256": AUTHORITY,
        "subject_actor_id": "actor-1",
    }
    values.update(changes)
    return MediaJobScope(**values)


def request(**changes):
    values = {
        "tool_name": "image.generate",
        "tool_version": "v1",
        "project_ref": "project-1",
        "brief_ref": "brief-1",
        "provider": "codex-app-server",
        "connector_ref": "connector-1",
        "connector_binding_sha256": BINDING,
        "idempotency_sha256": IDEMPOTENCY,
        "prompt": "private prompt body",
    }
    values.update(changes)
    return values


def secure_submission(*, scope_changes=None, brief_changes=None, request_changes=None):
    scope_payload = {
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "authority_sha256": AUTHORITY,
        "subject_actor_id": "actor-1",
    }
    scope_payload.update(scope_changes or {})
    brief_content = {
        "contract_id": CAMPAIGN_BRIEF_CONTRACT,
        "contract_version": CAMPAIGN_BRIEF_VERSION,
        "project_ref": "project-1",
        "graph_snapshot_sha256": "1" * 64,
        **scope_payload,
        "scope_binding_sha256": sha256_bytes(canonical_json(scope_payload)),
        "objective": "Create a governed media proposal.",
        "audiences": ["buyer"],
        "channel": "marketplace",
        "constraints": ["no external write"],
        "content_asset_refs": [],
    }
    brief_content.update(brief_changes or {})
    brief_sha = sha256_bytes(canonical_json(brief_content))
    brief = {
        **brief_content,
        "brief_ref": f"campaign_brief_{brief_sha[:32]}",
        "content_sha256": brief_sha,
        "external_write_allowed": False,
    }
    descriptor_content = {
        "contract_id": TOOL_DESCRIPTOR_CONTRACT,
        "registry_sha256": "2" * 64,
        "tool_name": "media.image_generate",
        "tool_version": "1.0.0",
        "capabilities": ["image_generation"],
        "cost_upper_bound": {
            "amount_minor": 100,
            "currency": "USD",
            "basis": "engineering_dispatch_ceiling_not_invoice",
        },
        "output_contract": "content_asset_ref",
        "provider": "codex-app-server",
        "connector_ref": "connector-1",
        "connector_binding_sha256": BINDING,
    }
    descriptor_sha = sha256_bytes(canonical_json(descriptor_content))
    descriptor = {**descriptor_content, "descriptor_sha256": descriptor_sha}
    secure_request = {
        "contract_id": COMMANDER_REQUEST_CONTRACT,
        "tool_name": descriptor["tool_name"],
        "tool_version": descriptor["tool_version"],
        "project_ref": brief["project_ref"],
        "brief_ref": brief["brief_ref"],
        "campaign_brief_sha256": brief["content_sha256"],
        "provider": descriptor["provider"],
        "connector_ref": descriptor["connector_ref"],
        "connector_binding_sha256": descriptor["connector_binding_sha256"],
        "idempotency_sha256": IDEMPOTENCY,
        "output_contract": descriptor["output_contract"],
        "tool_descriptor_sha256": descriptor_sha,
        "tool_inputs_sha256": "3" * 64,
        "tool_input_ref_count": 0,
        "safe_reason_codes": [],
    }
    secure_request.update(request_changes or {})
    return secure_request, brief, descriptor


def counts(engine):
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                MediaJobRow,
                MediaJobEventRow,
                MediaJobEvidenceLinkRow,
                EvidenceRecordRow,
                EvidenceBlobRow,
            )
        )


def reseal_event(event: MediaJobEventRow, job: MediaJobRow) -> None:
    event.event_sha256 = event_seal(
        job=None,
        job_ref=event.job_ref,
        tenant_ref=event.tenant_ref,
        entity_ref=event.entity_ref,
        store_ref=event.store_ref,
        authority_sha256=event.scope_grant_authority_sha256,
        subject_actor_id=job.subject_actor_id,
        ordinal=event.ordinal,
        stream_kind=event.stream_kind,
        state=event.state,
        safe_reason_code=event.safe_reason_code,
        previous_event_sha256=event.previous_event_sha256,
        public_projection_json=event.public_projection_json,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        command_idempotency_sha256=event.command_idempotency_sha256,
        command_request_sha256=event.command_request_sha256,
    )


def test_media_job_same_key_replay_and_drift_are_exact():
    engine, _, service = workspace()

    first = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())
    replay = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())

    assert replay == first
    assert first.state == "QUEUED"
    assert counts(engine) == (1, 1, 1, 1, 1)


def test_secure_submission_rechecks_current_scope_immediately_before_writes():
    engine, authority, service = workspace()
    original_current = authority.current

    def rotating_current(**kwargs):
        result = original_current(**kwargs)
        if len(authority.calls) == 2:
            result = {**result, "authority_sha256": "d" * 64}
        return result

    authority.current = rotating_current
    secure_request, brief, descriptor = secure_submission()

    with pytest.raises(PermissionError, match="scope_authority_changed"):
        service.submit(
            principal=PRINCIPAL,
            store_ref="store-1",
            request=secure_request,
            campaign_brief=brief,
            tool_descriptor=descriptor,
        )

    assert len(authority.calls) == 2
    assert counts(engine) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("tenant_ref", "tenant-other"),
        ("entity_ref", "entity-other"),
        ("store_ref", "store-other"),
        ("authority_sha256", "d" * 64),
        ("subject_actor_id", "actor-other"),
    ],
)
def test_jointly_resealed_campaign_scope_drift_leaves_zero_residue(field, replacement):
    engine, _, service = workspace()
    secure_request, brief, descriptor = secure_submission(
        scope_changes={field: replacement}
    )

    with pytest.raises(PermissionError, match="campaign_brief_scope_invalid"):
        service.submit(
            principal=PRINCIPAL,
            store_ref="store-1",
            request=secure_request,
            campaign_brief=brief,
            tool_descriptor=descriptor,
        )

    assert counts(engine) == (0, 0, 0, 0, 0)


def test_secure_request_evidence_contains_only_sealed_references_and_replays():
    engine, _, service = workspace()
    secure_request, brief, descriptor = secure_submission()

    first = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    replay = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    projected, binding = service.read_bound(
        principal=PRINCIPAL,
        store_ref="store-1",
        job_ref=first.job_ref,
    )

    with Session(engine) as session:
        blob = session.scalar(select(EvidenceBlobRow))
        assert blob is not None
        persisted = blob.content_bytes.decode("utf-8")
    assert replay == first == projected
    assert binding.tool_descriptor_sha256 == descriptor["descriptor_sha256"]
    assert binding.campaign_brief_sha256 == brief["content_sha256"]
    assert json.loads(persisted) == secure_request
    assert "prompt" not in persisted
    assert '"campaign_brief":' not in persisted
    assert '"tool_inputs":' not in persisted
    assert counts(engine) == (1, 1, 1, 1, 1)


def test_rotated_authority_cannot_rebind_existing_idempotency_winner():
    engine, authority, service = workspace()
    secure_request, brief, descriptor = secure_submission()
    first = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    authority.current_sha = "d" * 64
    rotated_request, rotated_brief, rotated_descriptor = secure_submission(
        scope_changes={"authority_sha256": "d" * 64}
    )

    with pytest.raises(ValueError, match="idempotency_scope_conflict"):
        service.submit(
            principal=PRINCIPAL,
            store_ref="store-1",
            request=rotated_request,
            campaign_brief=rotated_brief,
            tool_descriptor=rotated_descriptor,
        )
    with pytest.raises(KeyError, match="media_job_not_visible"):
        service.read_bound(
            principal=PRINCIPAL,
            store_ref="store-1",
            job_ref=first.job_ref,
        )
    assert counts(engine) == (1, 1, 1, 1, 1)


def test_secure_read_fails_closed_when_historical_tool_header_drifts():
    engine, _, service = workspace()
    secure_request, brief, descriptor = secure_submission()
    created = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    with Session(engine) as session, session.begin():
        row = session.get(MediaJobRow, created.job_ref)
        assert row is not None
        row.tool_version = "2.0.0"

    with pytest.raises(RuntimeError, match="media_job_request_header_drifted"):
        service.read_bound(
            principal=PRINCIPAL,
            store_ref="store-1",
            job_ref=created.job_ref,
        )


def test_provider_attempt_claim_rechecks_after_authority_lock(monkeypatch):
    engine, authority, service = workspace()
    secure_request, brief, descriptor = secure_submission()
    created = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    baseline = counts(engine)
    lock_calls = []

    def rotation_wins_before_lock(**kwargs):
        lock_calls.append(
            (
                kwargs["tenant_ref"],
                kwargs["store_ref"],
                kwargs["subject_actor_id"],
            )
        )
        authority.current_sha = "d" * 64

    monkeypatch.setattr(
        EvidenceService,
        "lock_scope_authority_in_session",
        rotation_wins_before_lock,
    )

    with pytest.raises(PermissionError, match="scope_authority_changed"):
        service.claim_provider_attempt(
            principal=PRINCIPAL,
            store_ref="store-1",
            job_ref=created.job_ref,
        )

    assert lock_calls == [("tenant-1", "store-1", "actor-1")]
    assert counts(engine) == baseline


def test_provider_attempt_authority_exception_preserves_counts(monkeypatch):
    engine, authority, service = workspace()
    secure_request, brief, descriptor = secure_submission()
    created = service.submit(
        principal=PRINCIPAL,
        store_ref="store-1",
        request=secure_request,
        campaign_brief=brief,
        tool_descriptor=descriptor,
    )
    baseline = counts(engine)

    def authority_failure(**kwargs):
        raise RuntimeError("scope_authority_unavailable")

    monkeypatch.setattr(authority, "current", authority_failure)
    with pytest.raises(RuntimeError, match="scope_authority_unavailable"):
        service.claim_provider_attempt(
            principal=PRINCIPAL,
            store_ref="store-1",
            job_ref=created.job_ref,
        )
    assert counts(engine) == baseline


def test_media_job_actor_and_tool_drift_conflict_before_new_job():
    engine, _, service = workspace()
    service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())
    other_actor = Principal(
        actor_id="actor-2",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-1",
        store_refs=frozenset({"store-1"}),
    )

    with pytest.raises(ValueError, match="idempotency_conflict"):
        service.submit(principal=other_actor, store_ref="store-1", request=request())
    with pytest.raises(ValueError, match="idempotency_conflict"):
        service.submit(
            principal=PRINCIPAL,
            store_ref="store-1",
            request=request(tool_name="image.other"),
        )
    assert counts(engine)[0] == 1
    with pytest.raises(ValueError, match="idempotency_conflict"):
        service.submit(principal=PRINCIPAL, store_ref="store-1", request=request(prompt="drifted"))
    assert counts(engine) == (1, 1, 1, 1, 1)


@pytest.mark.parametrize("field", ["entity_ref", "store_ref", "authority_sha256"])
def test_media_job_scope_drift_is_not_visible(field):
    _, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())
    if field == "entity_ref":
        replacement_principal = PRINCIPAL
        replacement_store = "store-1"
        service.authority.entity_ref = "other"
    elif field == "store_ref":
        replacement_principal = PRINCIPAL
        replacement_store = "other-store"
    else:
        service.authority.current_sha = "d" * 64
        replacement_principal = PRINCIPAL
        replacement_store = "store-1"

    with pytest.raises((PermissionError, ValueError, KeyError)):
        service.read(principal=replacement_principal, store_ref=replacement_store, job_ref=created.job_ref)


def test_media_job_rotation_and_revoke_block_read_and_cancel():
    engine, authority, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())
    authority.current_sha = None

    with pytest.raises(PermissionError, match="not_current"):
        service.read(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)
    with pytest.raises(PermissionError, match="not_current"):
        service.cancel(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref, idempotency_key="cancel-1")
    assert counts(engine) == (1, 1, 1, 1, 1)


def test_media_job_cancel_is_append_only_and_idempotent_state_is_terminal():
    engine, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())

    cancelled = service.cancel(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref, idempotency_key="cancel-1")
    replay_cancel = service.cancel(
        principal=PRINCIPAL,
        store_ref="store-1",
        job_ref=created.job_ref,
        idempotency_key="cancel-1",
    )
    page = service.events(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)

    assert cancelled.state == "CANCELLED"
    assert replay_cancel == cancelled
    assert [event.state for event in page] == ["QUEUED", "CANCELLED"]
    assert [event.ordinal for event in page] == [1, 2]
    assert counts(engine) == (1, 2, 2, 2, 2)
    with pytest.raises(ValueError, match="cancel_idempotency_conflict"):
        service.cancel(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref, idempotency_key="cancel-2")


def test_media_job_tampered_event_fails_closed_before_projection():
    engine, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())

    with Session(engine) as session:
        event = session.scalar(select(MediaJobEventRow).where(MediaJobEventRow.job_ref == created.job_ref))
        job = session.get(MediaJobRow, created.job_ref)
        assert event is not None and job is not None
        event.safe_reason_code = "tampered"
        event.public_projection_json = {
            **event.public_projection_json,
            "safe_reason_code": "tampered",
        }
        reseal_event(event, job)
        session.commit()

    with pytest.raises(RuntimeError, match="event_contract_drifted"):
        service.read(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)
    with pytest.raises(RuntimeError, match="event_contract_drifted"):
        service.events(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)


@pytest.mark.parametrize(
    "case",
    ["occurred_after_recorded", "previous_time_regression", "future_time"],
)
def test_media_job_self_consistent_event_time_drift_fails_closed(case):
    engine, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())

    if case == "previous_time_regression":
        with Session(engine) as session, session.begin():
            job = session.get(MediaJobRow, created.job_ref)
            assert job is not None
            service._append_event(
                session=session,
                job=job,
                scope=scope(),
                state="DISPATCHED",
                reason=None,
                now=NOW + timedelta(seconds=1),
                command_idempotency_sha256="d" * 64,
                command_request_sha256="e" * 64,
            )

    with Session(engine) as session:
        event = session.scalar(
            select(MediaJobEventRow)
            .where(MediaJobEventRow.job_ref == created.job_ref)
            .order_by(MediaJobEventRow.ordinal.desc())
        )
        job = session.get(MediaJobRow, created.job_ref)
        assert event is not None and job is not None
        if case == "occurred_after_recorded":
            event.occurred_at = NOW + timedelta(seconds=1)
            event.recorded_at = NOW
        elif case == "previous_time_regression":
            event.occurred_at = NOW - timedelta(seconds=1)
            event.recorded_at = NOW - timedelta(seconds=1)
        else:
            event.occurred_at = NOW + timedelta(minutes=6)
            event.recorded_at = event.occurred_at
        reseal_event(event, job)
        session.commit()

    with pytest.raises(RuntimeError, match="event_contract_drifted"):
        service.read(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)
    with pytest.raises(RuntimeError, match="event_contract_drifted"):
        service.events(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)


def test_media_job_self_consistent_illegal_transition_fails_closed():
    engine, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())

    with Session(engine) as session:
        job = session.get(MediaJobRow, created.job_ref)
        previous = session.scalar(
            select(MediaJobEventRow).where(MediaJobEventRow.job_ref == created.job_ref)
        )
        assert job is not None and previous is not None
        occurred_at = NOW + timedelta(seconds=1)
        projection = {
            "job_ref": job.job_ref,
            "ordinal": 2,
            "state": "RUNNING",
            "safe_reason_code": None,
        }
        event_hash = event_seal(
            job=None,
            job_ref=job.job_ref,
            tenant_ref=job.tenant_ref,
            entity_ref=job.entity_ref,
            store_ref=job.store_ref,
            authority_sha256=job.scope_grant_authority_sha256,
            subject_actor_id=job.subject_actor_id,
            ordinal=2,
            stream_kind="job_state",
            state="RUNNING",
            safe_reason_code=None,
            previous_event_sha256=previous.event_sha256,
            public_projection_json=projection,
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            command_idempotency_sha256="d" * 64,
            command_request_sha256="e" * 64,
        )
        session.add(
            MediaJobEventRow(
                event_ref="media_event_illegal",
                job_ref=job.job_ref,
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                ordinal=2,
                stream_kind="job_state",
                state="RUNNING",
                safe_reason_code=None,
                previous_event_sha256=previous.event_sha256,
                event_sha256=event_hash,
                command_idempotency_sha256="d" * 64,
                command_request_sha256="e" * 64,
                public_projection_json=projection,
                occurred_at=occurred_at,
                recorded_at=occurred_at,
            )
        )
        session.commit()

    with pytest.raises(RuntimeError, match="event_contract_drifted"):
        service.read(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)


def test_media_job_public_projection_contains_no_scope_prompt_or_hashes():
    _, _, service = workspace()
    created = service.submit(principal=PRINCIPAL, store_ref="store-1", request=request())
    projection = created.__repr__()
    page = service.events(principal=PRINCIPAL, store_ref="store-1", job_ref=created.job_ref)
    event_projection = page[0].__repr__()

    for forbidden in (
        "tenant-1",
        "entity-1",
        "store-1",
        AUTHORITY,
        BINDING,
        IDEMPOTENCY,
        "private prompt body",
    ):
        assert forbidden not in projection
        assert forbidden not in event_projection


def test_media_job_provider_dispatch_remains_not_admitted():
    _, _, service = workspace()
    assert service.peek().exists is False
    with pytest.raises(RuntimeError, match="provider_dispatch_not_admitted"):
        service.claim()
    with pytest.raises(RuntimeError, match="provider_dispatch_not_admitted"):
        service.record()


def test_media_job_canonical_request_rejects_nonfinite_and_excessive_depth():
    _, _, service = workspace()
    with pytest.raises(ValueError, match="non_finite"):
        service.submit(
            principal=PRINCIPAL,
            store_ref="store-1",
            request=request(extra=inf),
        )
    nested = value = {}
    for _ in range(34):
        value["next"] = {}
        value = value["next"]
    with pytest.raises(ValueError, match="too_deep"):
        service.submit(principal=PRINCIPAL, store_ref="store-1", request=request(extra=nested))
