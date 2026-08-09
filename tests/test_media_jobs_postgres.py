from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.media_jobs import (
    GovernedMediaJobWorkspace,
    MediaJobEventRow,
    MediaJobEvidenceLinkRow,
    MediaJobRow,
    canonical_json,
    event_seal,
    sha256_bytes,
)
from apps.control_plane.scope_grants import ScopeGrantEventRow
from apps.control_plane.security import Principal

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260808_0097_governed_media_jobs.py"
)
DATABASE_URL = os.getenv("KJDS_BAS183_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="BAS-183 PostgreSQL lifecycle requires KJDS_BAS183_DATABASE_URL",
)
NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
AUTHORITY = "a" * 64
BINDING = "b" * 64


class _ScopeAuthority:
    def current(self, **kwargs):
        principal = kwargs["principal"]
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": "entity-media-pg",
            "store_ref": kwargs["store_ref"],
            "authority_sha256": AUTHORITY,
        }


class _DatabaseScopeAuthority:
    """Read the committed revoke marker so the lock test observes real state."""

    def __init__(self, engine, *, tenant_ref: str, actor_id: str) -> None:
        self.engine = engine
        self.tenant_ref = tenant_ref
        self.actor_id = actor_id

    def current(self, **kwargs):
        store_ref = kwargs["store_ref"]
        with Session(self.engine) as session:
            revoked = session.scalar(
                select(ScopeGrantEventRow.sequence)
                .where(
                    ScopeGrantEventRow.tenant_ref == self.tenant_ref,
                    ScopeGrantEventRow.store_ref == store_ref,
                    ScopeGrantEventRow.subject_actor_id == self.actor_id,
                    ScopeGrantEventRow.event_type == "revoke",
                )
                .order_by(ScopeGrantEventRow.sequence.desc())
                .limit(1)
            )
        if revoked is not None:
            return {
                "status": "no_data",
                "tenant_ref": self.tenant_ref,
                "entity_ref": None,
                "store_ref": store_ref,
                "authority_sha256": None,
            }
        return {
            "status": "ready",
            "tenant_ref": self.tenant_ref,
            "entity_ref": "entity-media-pg",
            "store_ref": store_ref,
            "authority_sha256": AUTHORITY,
        }


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def _migrate(direction: str, revision: str) -> None:
    previous = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = DATABASE_URL
    try:
        getattr(command, direction)(_config(), revision)
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous


def _sqlstate(error: BaseException) -> str | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        state = getattr(current, "sqlstate", None)
        if state:
            return str(state)
        original = getattr(current, "orig", None)
        if isinstance(original, BaseException) and id(original) not in seen:
            current = original
        else:
            current = current.__cause__ or current.__context__
    return None


@pytest.fixture(scope="module")
def engine():
    target = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with target.connect() as connection:
            assert connection.scalar(text("SELECT current_database()"))
        yield target
    finally:
        target.dispose()


def _principal(actor: str, tenant: str) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset({"operator"}),
        tenant_ref=tenant,
        store_refs=frozenset({"store-media-pg"}),
    )


def _request(idempotency: str, **changes):
    values = {
        "tool_name": "image.generate",
        "tool_version": "v1",
        "project_ref": "project-media-pg",
        "brief_ref": "brief-media-pg",
        "provider": "codex-app-server",
        "connector_ref": "connector-media-pg",
        "connector_binding_sha256": BINDING,
        "idempotency_sha256": idempotency,
        "prompt": "private PostgreSQL prompt",
    }
    values.update(changes)
    return values


def _workspace(engine, *, tick: int = 0) -> GovernedMediaJobWorkspace:
    return GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_ScopeAuthority(),
        clock=lambda: NOW + timedelta(seconds=tick),
    )


def _authority_workspace(engine, principal: Principal) -> GovernedMediaJobWorkspace:
    return GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_DatabaseScopeAuthority(
            engine,
            tenant_ref=principal.tenant_ref,
            actor_id=principal.actor_id,
        ),
        clock=lambda: NOW,
    )


def _capture_rotation_evidence(engine, suffix: str):
    return EvidenceService(engine).capture(
        content=f"rotation-{suffix}".encode(),
        filename=f"rotation-{suffix}.json",
        content_type="application/json",
        source="media-job-authority-test",
        source_ref=f"media-job-authority-test://{suffix}",
        grade=EvidenceGrade.B,
        effective_at=NOW.isoformat(),
        effective_until=None,
        created_by="bas184-pg-test",
    )


def _hold_revoke(
    engine,
    principal: Principal,
    evidence,
    started: Event,
    acquired: Event,
    release: Event,
) -> None:
    started.set()
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(
            ScopeGrantEventRow(
                id=f"scope-revoke-{uuid4().hex}",
                tenant_ref=principal.tenant_ref,
                entity_ref="entity-media-pg",
                store_ref="store-media-pg",
                subject_actor_id=principal.actor_id,
                event_type="revoke",
                effective_at=NOW,
                evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                reason="BAS-184 concurrency test rotation",
                idempotency_key=f"revoke-{uuid4().hex}",
                request_sha256=sha256_bytes(uuid4().hex.encode()),
                created_by="bas184-pg-test",
                recorded_at=NOW,
            )
        )
        session.flush()
        acquired.set()
        assert release.wait(timeout=10)


def _surface_counts(engine) -> tuple[int, ...]:
    with Session(engine) as session:
        return tuple(
            int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (
                MediaJobRow,
                MediaJobEventRow,
                MediaJobEvidenceLinkRow,
                EvidenceRecordRow,
                EvidenceBlobRow,
            )
        )


def _catalog_state(engine) -> tuple[tuple[str, ...], tuple[str, ...]]:
    inspector = inspect(engine)
    relations = tuple(
        sorted(
            name
            for name in inspector.get_table_names()
            if name in {"media_jobs", "media_job_events", "media_job_evidence_links"}
        )
    )
    with engine.connect() as connection:
        triggers = tuple(
            sorted(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid=t.tgrelid "
                        "WHERE NOT t.tgisinternal AND c.relname IN "
                        "('media_jobs','media_job_events','media_job_evidence_links')"
                    )
                )
            )
        )
    return relations, triggers


def _build_state_event(
    session: Session,
    *,
    job_ref: str,
    state: str,
    command_marker: str,
    occurred_at: datetime,
    recorded_at: datetime | None = None,
    safe_reason_code: str | None = None,
    projection_ordinal: Any | None = None,
) -> MediaJobEventRow:
    job = session.get(MediaJobRow, job_ref)
    assert job is not None
    previous = session.scalar(
        select(MediaJobEventRow)
        .where(MediaJobEventRow.job_ref == job_ref)
        .order_by(MediaJobEventRow.ordinal.desc())
    )
    assert previous is not None
    recorded_at = recorded_at or occurred_at
    ordinal = previous.ordinal + 1
    projection = {
        "job_ref": job_ref,
        "ordinal": ordinal if projection_ordinal is None else projection_ordinal,
        "state": state,
        "safe_reason_code": safe_reason_code,
    }
    event_hash = event_seal(
        job=None,
        job_ref=job_ref,
        tenant_ref=job.tenant_ref,
        entity_ref=job.entity_ref,
        store_ref=job.store_ref,
        authority_sha256=job.scope_grant_authority_sha256,
        subject_actor_id=job.subject_actor_id,
        ordinal=ordinal,
        stream_kind="job_state",
        state=state,
        safe_reason_code=safe_reason_code,
        previous_event_sha256=previous.event_sha256,
        public_projection_json=projection,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        command_idempotency_sha256=command_marker,
        command_request_sha256=command_marker,
    )
    return MediaJobEventRow(
        event_ref=f"media_event_{uuid4().hex}",
        job_ref=job_ref,
        tenant_ref=job.tenant_ref,
        entity_ref=job.entity_ref,
        store_ref=job.store_ref,
        scope_grant_authority_sha256=job.scope_grant_authority_sha256,
        ordinal=ordinal,
        stream_kind="job_state",
        state=state,
        safe_reason_code=safe_reason_code,
        previous_event_sha256=previous.event_sha256,
        event_sha256=event_hash,
        command_idempotency_sha256=command_marker,
        command_request_sha256=command_marker,
        public_projection_json=projection,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
    )


def _insert_state_event(engine, **kwargs: Any) -> None:
    with Session(engine) as session, session.begin():
        session.add(_build_state_event(session, **kwargs))


def test_00_migration_replays_empty_0096_to_0097(engine):
    with engine.connect() as connection:
        has_version_table = bool(
            connection.scalar(
                text("SELECT to_regclass('public.alembic_version')")
            )
        )
        version = (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            if has_version_table
            else None
        )
    target_tables = {
        "media_jobs",
        "media_job_events",
        "media_job_evidence_links",
    }
    initial_tables = set(inspect(engine).get_table_names())
    if version is None:
        _migrate("upgrade", "20260805_0096")
    elif version != "20260805_0096":
        _migrate("downgrade", "20260805_0096")
    if target_tables <= initial_tables:
        assert _surface_counts(engine) == (0, 0, 0, 0, 0)
    else:
        assert not target_tables & set(inspect(engine).get_table_names())

    _migrate("upgrade", "20260808_0097")
    first = _catalog_state(engine)
    _migrate("downgrade", "20260805_0096")
    _migrate("upgrade", "20260808_0097")
    assert _catalog_state(engine) == first
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )


def test_01_media_job_migration_freezes_exact_contract():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260808_0097"' in source
    assert 'down_revision = "20260805_0096"' in source
    assert "kjds_media_job_validate_event" in source
    assert "kjds_media_job_validate_evidence_binding" in source
    assert "kjds_media_job_terminal_evidence_conservation" in source
    assert "kjds_media_job_prevent_mutation" in source
    assert "WHEN 'LOGIN_REQUIRED'" in source
    assert "WHEN 'LIMITED'" in source
    assert "ERRCODE='23514'" in source
    assert "ERRCODE='55000'" in source
    assert "DROP OWNED" not in source


def test_02_schema_has_exact_0097_relations_and_triggers(engine):
    relations, triggers = _catalog_state(engine)
    assert relations == (
        "media_job_events",
        "media_job_evidence_links",
        "media_jobs",
    )
    assert {
        "trg_media_jobs_immutable",
        "trg_media_job_events_immutable",
        "trg_media_job_evidence_links_immutable",
        "trg_media_job_event_contract",
        "trg_media_job_request_evidence",
        "trg_media_job_link_evidence",
        "trg_media_job_terminal_evidence_conservation",
    } <= set(triggers)


def test_03_service_submit_replay_cancel_and_append_only_are_real(engine):
    service = _workspace(engine)
    principal = _principal("actor-service-pg", "tenant-service-pg")
    request = _request("1" * 64)
    before = _surface_counts(engine)

    first = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=request,
    )
    replay = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=request,
    )
    cancelled = service.cancel(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=first.job_ref,
        idempotency_key="cancel-service-pg",
    )
    cancel_replay = service.cancel(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=first.job_ref,
        idempotency_key="cancel-service-pg",
    )

    assert replay == first
    assert cancel_replay == cancelled
    assert cancelled.state == "CANCELLED"
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        2,
        2,
        2,
        2,
    )
    with pytest.raises(DBAPIError) as error, engine.begin() as connection:
        connection.execute(
            text("UPDATE media_jobs SET tool_version='drift' WHERE job_ref=:job"),
            {"job": first.job_ref},
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == after


def test_04_postgres_rejects_illegal_resigned_transition_with_zero_residue(engine):
    service = _workspace(engine, tick=10)
    principal = _principal("actor-transition-pg", "tenant-transition-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("2" * 64),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="SUCCEEDED",
            command_marker="3" * 64,
            occurred_at=NOW + timedelta(seconds=11),
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize("paused", ["LOGIN_REQUIRED", "LIMITED"])
def test_05_paused_states_resume_by_controlled_dispatch_and_reject_success_jump(
    engine,
    paused,
):
    marker = "4" if paused == "LOGIN_REQUIRED" else "5"
    service = _workspace(engine, tick=20)
    principal = _principal(f"actor-{paused.lower()}", f"tenant-{paused.lower()}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(marker * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state=paused,
        safe_reason_code=(
            "connector_login_required"
            if paused == "LOGIN_REQUIRED"
            else "settled_entitlement_unavailable"
        ),
        command_marker="6" * 64,
        occurred_at=NOW + timedelta(seconds=21),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="7" * 64,
        occurred_at=NOW + timedelta(seconds=22),
    )
    assert [event.state for event in service.events(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    )] == ["QUEUED", paused, "DISPATCHED"]

    readback_started = _workspace(engine, tick=30).submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(("8" if paused == "LOGIN_REQUIRED" else "9") * 64),
    )
    _insert_state_event(
        engine,
        job_ref=readback_started.job_ref,
        state=paused,
        safe_reason_code=(
            "connector_login_required"
            if paused == "LOGIN_REQUIRED"
            else "settled_entitlement_unavailable"
        ),
        command_marker="a" * 64,
        occurred_at=NOW + timedelta(seconds=31),
    )
    _insert_state_event(
        engine,
        job_ref=readback_started.job_ref,
        state="RUNNING",
        command_marker="b" * 64,
        occurred_at=NOW + timedelta(seconds=32),
    )

    for offset, denied_state in enumerate(("SUCCEEDED", "CANCELLED"), start=40):
        denied = _workspace(engine, tick=offset).submit(
            principal=principal,
            store_ref="store-media-pg",
            request=_request(f"{offset:064x}"),
        )
        _insert_state_event(
            engine,
            job_ref=denied.job_ref,
            state=paused,
            safe_reason_code=(
                "connector_login_required"
                if paused == "LOGIN_REQUIRED"
                else "settled_entitlement_unavailable"
            ),
            command_marker="c" * 64,
            occurred_at=NOW + timedelta(seconds=offset + 1),
        )
        before = _surface_counts(engine)
        with pytest.raises(DBAPIError) as error:
            _insert_state_event(
                engine,
                job_ref=denied.job_ref,
                state=denied_state,
                safe_reason_code=(
                    "cancelled_by_request" if denied_state == "CANCELLED" else None
                ),
                command_marker="d" * 64,
                occurred_at=NOW + timedelta(seconds=offset + 2),
            )
        assert _sqlstate(error.value) == "23514"
        assert _surface_counts(engine) == before


def test_05b_malformed_projection_ordinal_is_23514_with_zero_residue(engine):
    service = _workspace(engine, tick=35)
    principal = _principal("actor-projection-pg", "tenant-projection-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("0" * 64),
    )
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="DISPATCHED",
            command_marker="1" * 64,
            occurred_at=NOW + timedelta(seconds=36),
            projection_ordinal="not-an-integer",
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_05c_terminal_event_without_evidence_is_23514_and_atomic(engine):
    service = _workspace(engine, tick=37)
    principal = _principal("actor-terminal-pg", "tenant-terminal-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("2" * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="3" * 64,
        occurred_at=NOW + timedelta(seconds=38),
    )
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="FAILED",
            safe_reason_code="provider_failed",
            command_marker="4" * 64,
            occurred_at=NOW + timedelta(seconds=39),
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize(
    "field,drifted_value",
    [
        ("tenant_ref", "tenant-foreign"),
        ("entity_ref", "entity-foreign"),
        ("store_ref", "store-foreign"),
        ("scope_grant_authority_sha256", "f" * 64),
        ("subject_actor_id", "actor-foreign"),
    ],
)
def test_06_request_evidence_scope_metadata_drift_is_23514_and_atomic(
    engine,
    field,
    drifted_value,
):
    service = _workspace(engine, tick=40)
    suffix = uuid4().hex
    principal = _principal(f"actor-binding-{suffix}", f"tenant-binding-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"original-{suffix}".encode())),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
        source = session.get(EvidenceRecordRow, job.request_evidence_id)
        assert source is not None
        idempotency = sha256_bytes(f"forged-{field}-{suffix}".encode())
        request = _request(idempotency)
        request_bytes = canonical_json(request)
        request_sha256 = sha256_bytes(request_bytes)
        scope_payload = {
            "tenant_ref": job.tenant_ref,
            "entity_ref": job.entity_ref,
            "store_ref": job.store_ref,
            "authority_sha256": job.scope_grant_authority_sha256,
            "subject_actor_id": job.subject_actor_id,
        }
        request_fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        forged_evidence_id = f"evd_{uuid4().hex}"
        forged_metadata = {
            "contract_id": "kjds-governed-media-job-request-v1",
            "media_job_request_fingerprint_sha256": request_fingerprint,
            "tenant_ref": job.tenant_ref,
            "entity_ref": job.entity_ref,
            "store_ref": job.store_ref,
            "scope_grant_authority_sha256": job.scope_grant_authority_sha256,
            "subject_actor_id": job.subject_actor_id,
        }
        forged_metadata[field] = drifted_value
        session.add(
            EvidenceBlobRow(
                sha256=request_sha256,
                byte_size=len(request_bytes),
                content_bytes=request_bytes,
                created_at=job.created_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=forged_evidence_id,
                blob_sha256=request_sha256,
                filename=source.filename,
                content_type=source.content_type,
                source=source.source,
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade=source.grade,
                effective_at=job.created_at,
                effective_until=None,
                recorded_at=job.created_at,
                created_by=job.subject_actor_id,
                metadata_json=forged_metadata,
            )
        )
        session.flush()
        session.add(
            MediaJobRow(
                job_ref=f"media_job_{uuid4().hex}",
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                subject_actor_id=job.subject_actor_id,
                tool_name=job.tool_name,
                tool_version=job.tool_version,
                project_ref=job.project_ref,
                brief_ref=job.brief_ref,
                provider=job.provider,
                connector_ref=job.connector_ref,
                connector_binding_sha256=job.connector_binding_sha256,
                idempotency_sha256=idempotency,
                request_sha256=request_sha256,
                request_fingerprint_sha256=request_fingerprint,
                request_evidence_id=forged_evidence_id,
                request_evidence_sha256=request_sha256,
                created_at=job.created_at,
            )
        )
        session.flush()
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_06b_request_evidence_content_swap_is_23514_and_atomic(engine):
    suffix = uuid4().hex
    service = _workspace(engine, tick=45)
    principal = _principal(f"actor-content-{suffix}", f"tenant-content-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"seed-{suffix}".encode())),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        template = session.get(MediaJobRow, created.job_ref)
        assert template is not None
        idempotency = sha256_bytes(f"swap-{suffix}".encode())
        request = _request(idempotency)
        request_bytes = canonical_json(request)
        request_sha256 = sha256_bytes(request_bytes)
        swapped_bytes = canonical_json({"swapped": suffix})
        swapped_sha256 = sha256_bytes(swapped_bytes)
        scope_payload = {
            "tenant_ref": template.tenant_ref,
            "entity_ref": template.entity_ref,
            "store_ref": template.store_ref,
            "authority_sha256": template.scope_grant_authority_sha256,
            "subject_actor_id": template.subject_actor_id,
        }
        fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        evidence_id = f"evd_{uuid4().hex}"
        session.add(
            EvidenceBlobRow(
                sha256=swapped_sha256,
                byte_size=len(swapped_bytes),
                content_bytes=swapped_bytes,
                created_at=template.created_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=evidence_id,
                blob_sha256=swapped_sha256,
                filename="media-job-request.json",
                content_type="application/json",
                source="governed-media-job-request",
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade="B",
                effective_at=template.created_at,
                effective_until=None,
                recorded_at=template.created_at,
                created_by=template.subject_actor_id,
                metadata_json={
                    "contract_id": "kjds-governed-media-job-request-v1",
                    "media_job_request_fingerprint_sha256": fingerprint,
                    "tenant_ref": template.tenant_ref,
                    "entity_ref": template.entity_ref,
                    "store_ref": template.store_ref,
                    "scope_grant_authority_sha256": (
                        template.scope_grant_authority_sha256
                    ),
                    "subject_actor_id": template.subject_actor_id,
                },
            )
        )
        session.flush()
        session.add(
            MediaJobRow(
                job_ref=f"media_job_{uuid4().hex}",
                tenant_ref=template.tenant_ref,
                entity_ref=template.entity_ref,
                store_ref=template.store_ref,
                scope_grant_authority_sha256=(
                    template.scope_grant_authority_sha256
                ),
                subject_actor_id=template.subject_actor_id,
                tool_name=template.tool_name,
                tool_version=template.tool_version,
                project_ref=template.project_ref,
                brief_ref=template.brief_ref,
                provider=template.provider,
                connector_ref=template.connector_ref,
                connector_binding_sha256=template.connector_binding_sha256,
                idempotency_sha256=idempotency,
                request_sha256=request_sha256,
                request_fingerprint_sha256=fingerprint,
                request_evidence_id=evidence_id,
                request_evidence_sha256=swapped_sha256,
                created_at=template.created_at,
            )
        )
        session.flush()
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_06c_terminal_evidence_content_swap_is_23514_and_atomic(engine):
    service = _workspace(engine, tick=50)
    principal = _principal("actor-terminal-swap", "tenant-terminal-swap")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("5" * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="6" * 64,
        occurred_at=NOW + timedelta(seconds=51),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
        event = _build_state_event(
            session,
            job_ref=created.job_ref,
            state="FAILED",
            safe_reason_code="provider_failed",
            command_marker="7" * 64,
            occurred_at=NOW + timedelta(seconds=52),
        )
        session.add(event)
        session.flush()
        swapped_bytes = canonical_json({"forged_terminal": True})
        swapped_sha256 = sha256_bytes(swapped_bytes)
        evidence_id = f"evd_{uuid4().hex}"
        session.add(
            EvidenceBlobRow(
                sha256=swapped_sha256,
                byte_size=len(swapped_bytes),
                content_bytes=swapped_bytes,
                created_at=event.recorded_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=evidence_id,
                blob_sha256=swapped_sha256,
                filename="media-job-transition.json",
                content_type="application/json",
                source="governed-media-job-transition",
                source_ref=f"media-job://{job.job_ref}/transition/{event.event_ref}",
                grade="B",
                effective_at=event.occurred_at,
                effective_until=None,
                recorded_at=event.recorded_at,
                created_by=job.subject_actor_id,
                metadata_json={
                    "contract_id": "kjds-governed-media-job-transition-v1",
                    "tenant_ref": job.tenant_ref,
                    "entity_ref": job.entity_ref,
                    "store_ref": job.store_ref,
                    "scope_grant_authority_sha256": (
                        job.scope_grant_authority_sha256
                    ),
                    "subject_actor_id": job.subject_actor_id,
                    "event_sha256": event.event_sha256,
                },
            )
        )
        session.flush()
        session.add(
            MediaJobEvidenceLinkRow(
                link_ref=f"media_link_{uuid4().hex}",
                job_ref=job.job_ref,
                event_ref=event.event_ref,
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                purpose="artifact_terminal",
                evidence_id=evidence_id,
                blob_sha256=swapped_sha256,
                source="governed-media-job-transition",
                source_ref=f"media-job://{job.job_ref}/transition/{event.event_ref}",
                effective_at=event.occurred_at,
                recorded_at=event.recorded_at,
                fresh_until=None,
            )
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize(
    "case",
    [
        "reason_mismatch",
        "occurred_after_recorded",
        "previous_time_regression",
        "future_time",
    ],
)
def test_06d_event_reason_and_time_drift_is_23514_and_atomic(engine, case):
    suffix = uuid4().hex
    service = _workspace(engine, tick=70)
    principal = _principal(f"actor-time-{suffix}", f"tenant-time-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"time-{suffix}".encode())),
    )
    occurred_at = NOW + timedelta(seconds=71)
    recorded_at = occurred_at
    reason = None
    if case == "reason_mismatch":
        reason = "unfrozen_internal_text"
    elif case == "occurred_after_recorded":
        recorded_at = occurred_at - timedelta(seconds=1)
    elif case == "previous_time_regression":
        occurred_at = NOW + timedelta(seconds=69)
        recorded_at = occurred_at
    else:
        occurred_at = datetime.now(UTC) + timedelta(days=1)
        recorded_at = occurred_at
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="DISPATCHED",
            safe_reason_code=reason,
            command_marker=sha256_bytes(case.encode()),
            occurred_at=occurred_at,
            recorded_at=recorded_at,
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_07_two_session_same_key_has_one_winner_and_exact_replay(engine):
    tenant = f"tenant-concurrent-{uuid4().hex}"
    principal = _principal("actor-concurrent-pg", tenant)
    request = _request("e" * 64)
    services = (_workspace(engine, tick=50), _workspace(engine, tick=50))
    barrier = Barrier(2)
    before = _surface_counts(engine)

    def compete(service):
        barrier.wait(timeout=10)
        return service.submit(
            principal=principal,
            store_ref="store-media-pg",
            request=request,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(compete, services))

    assert results[0] == results[1]
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        1,
        1,
        1,
        1,
    )


def test_08_two_session_actor_drift_has_one_winner_and_zero_loser_residue(engine):
    tenant = f"tenant-drift-{uuid4().hex}"
    principals = (
        _principal("actor-drift-a", tenant),
        _principal("actor-drift-b", tenant),
    )
    services = (_workspace(engine, tick=60), _workspace(engine, tick=60))
    request = _request("f" * 64)
    barrier = Barrier(2)
    before = _surface_counts(engine)

    def compete(pair):
        service, principal = pair
        barrier.wait(timeout=10)
        try:
            return service.submit(
                principal=principal,
                store_ref="store-media-pg",
                request=request,
            )
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(compete, zip(services, principals, strict=True)))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert str(errors[0]) == "media_job_idempotency_conflict"
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        1,
        1,
        1,
        1,
    )


def test_09_rotation_committed_before_claim_blocks_stale_dispatch(engine):
    suffix = uuid4().hex
    tenant = f"tenant-claim-rotation-{suffix}"
    principal = _principal(f"actor-claim-rotation-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"claim-rotation-{suffix}".encode())),
    )
    evidence = _capture_rotation_evidence(engine, suffix)
    before = _surface_counts(engine)
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()
    claim_started = Event()
    provider_attempts = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_acquired.wait(timeout=10)

        def claim():
            claim_started.set()
            projection, claimed = service.claim_provider_attempt(
                principal=principal,
                store_ref="store-media-pg",
                job_ref=created.job_ref,
            )
            if claimed:
                provider_attempts.append(projection.job_ref)
            return projection, claimed

        claim_future = executor.submit(claim)
        assert claim_started.wait(timeout=10)
        with pytest.raises(FuturesTimeoutError):
            claim_future.result(timeout=0.25)
        release_rotation.set()
        rotation.result(timeout=10)
        with pytest.raises(PermissionError, match="scope_authority_not_current"):
            claim_future.result(timeout=10)

    assert provider_attempts == []
    assert _surface_counts(engine) == before


def test_10_claim_authority_lock_blocks_rotation_until_dispatch_commit(engine, monkeypatch):
    suffix = uuid4().hex
    tenant = f"tenant-claim-first-{suffix}"
    principal = _principal(f"actor-claim-first-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"claim-first-{suffix}".encode())),
    )
    evidence = _capture_rotation_evidence(engine, suffix)
    before = _surface_counts(engine)
    claim_at_event = Event()
    allow_claim = Event()
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()
    provider_attempts = []
    original_validate = service._validate_event_chain

    def pause_after_chain(session, row, scope):
        result = original_validate(session, row, scope)
        claim_at_event.set()
        assert allow_claim.wait(timeout=10)
        return result

    monkeypatch.setattr(service, "_validate_event_chain", pause_after_chain)

    def claim():
        projection, claimed = service.claim_provider_attempt(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=created.job_ref,
        )
        if claimed:
            provider_attempts.append(projection.job_ref)
        return projection, claimed

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_future = executor.submit(claim)
        assert claim_at_event.wait(timeout=10)
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_started.wait(timeout=10)
        assert not rotation_acquired.wait(timeout=0.25)
        allow_claim.set()
        projection, claimed = claim_future.result(timeout=10)
        assert projection.job_ref == created.job_ref
        assert claimed is True
        assert rotation_acquired.wait(timeout=10)
        release_rotation.set()
        rotation.result(timeout=10)

    assert provider_attempts == [created.job_ref]
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        0,
        1,
        0,
        0,
        0,
    )


def test_99_populated_downgrade_is_55000_and_preserves_0097(engine):
    before = _surface_counts(engine)
    assert before[0] > 0

    with pytest.raises(BaseException) as error:
        _migrate("downgrade", "20260805_0096")
    assert _sqlstate(error.value) == "55000"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )
    assert _surface_counts(engine) == before
