from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.channel_account_authority import (
    ChannelAccountAuthorizationEventRow,
    ChannelAccountKillSwitchStateRow,
    ChannelAccountReviewDecisionRow,
)
from apps.control_plane.database import create_database_engine
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.security import KillSwitchEventRow

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "kjds_bas158_replay_"
DATABASE_NAME_RE = re.compile(r"kjds_bas158_replay_[0-9a-f]{12}")
REVISION_0081 = "20260731_0081"
REVISION_0080 = "20260730_0080"
TABLE_REQUIREMENTS = {
    "channel_account_review_decisions": {
        "unique": {
            "uq_channel_account_review_decision_sequence",
            "uq_channel_account_review_decision_hash",
        },
        "checks": {"ck_channel_account_review_decision"},
        "triggers": {
            "trg_channel_account_review_no_update",
            "trg_channel_account_review_no_delete",
        },
    },
    "channel_account_kill_switch_states": {
        "unique": {
            "uq_channel_account_kill_switch_source",
            "uq_channel_account_kill_switch_sequence",
        },
        "checks": {"ck_channel_account_kill_switch_authority"},
        "triggers": {
            "trg_channel_account_kill_no_update",
            "trg_channel_account_kill_no_delete",
        },
    },
    "channel_account_authorization_events": {
        "unique": {
            "uq_channel_account_authority_source_event",
            "uq_channel_account_authority_sequence",
            "uq_channel_account_authority_command",
            "uq_channel_account_authority_receipt",
        },
        "checks": {
            "ck_channel_account_authority_scope_required",
            "ck_channel_account_authority_sequence",
            "ck_channel_account_authority_source",
            "ck_channel_account_authority_governance",
            "ck_channel_account_authority_enums",
            "ck_channel_account_authority_time_locator",
            "ck_channel_account_authority_payload_shape",
        },
        "triggers": {
            "trg_channel_account_authority_no_update",
            "trg_channel_account_authority_no_delete",
        },
    },
}
EXECUTION_PLAN_SOURCE_KINDS = (
    "approved_channel_account_change",
    "approved_channel_account_compensation",
)


def _validate_database_name(database_name: str) -> None:
    if not database_name.startswith(PREFIX) or DATABASE_NAME_RE.fullmatch(database_name) is None:
        raise RuntimeError("Temporary database name is outside the strict BAS-158 replay prefix")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        value = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return str(value or "")


def _execution_plan_check(engine: Engine) -> str:
    with engine.connect() as connection:
        definition = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) "
                "FROM pg_constraint "
                "WHERE conrelid = 'governed_execution_plans'::regclass "
                "AND conname = 'ck_execution_plan_source_variant' "
                "AND contype = 'c'"
            )
        )
    if not isinstance(definition, str) or not definition:
        raise RuntimeError("governed execution-plan source constraint is missing")
    return definition.lower()


def _trigger_names(engine: Engine, table_name: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    "SELECT trigger_name "
                    "FROM information_schema.triggers "
                    "WHERE trigger_schema = current_schema() "
                    "AND event_object_table = :table_name"
                ),
                {"table_name": table_name},
            )
        )


def _verify_0081(engine: Engine) -> None:
    if _revision(engine) != REVISION_0081:
        raise RuntimeError("BAS-158 replay is not at Alembic revision 0081")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing_tables = sorted(set(TABLE_REQUIREMENTS) - tables)
    if missing_tables:
        raise RuntimeError("BAS-158 replay is missing authority tables: " + ", ".join(missing_tables))
    for table_name, requirements in TABLE_REQUIREMENTS.items():
        unique_names = {str(item["name"]) for item in inspector.get_unique_constraints(table_name) if item.get("name")}
        check_names = {str(item["name"]) for item in inspector.get_check_constraints(table_name) if item.get("name")}
        trigger_names = _trigger_names(engine, table_name)
        for category, required, actual in (
            ("unique constraints", requirements["unique"], unique_names),
            ("check constraints", requirements["checks"], check_names),
            ("append-only triggers", requirements["triggers"], trigger_names),
        ):
            missing = sorted(required - actual)
            if missing:
                raise RuntimeError(f"BAS-158 {table_name} is missing {category}: " + ", ".join(missing))
    definition = _execution_plan_check(engine)
    missing_source_kinds = [source_kind for source_kind in EXECUTION_PLAN_SOURCE_KINDS if source_kind not in definition]
    if missing_source_kinds:
        raise RuntimeError(
            "BAS-158 execution-plan constraint is missing source kinds: " + ", ".join(missing_source_kinds)
        )


def _verify_0080(engine: Engine) -> None:
    if _revision(engine) != REVISION_0080:
        raise RuntimeError("BAS-158 downgrade did not reach Alembic revision 0080")
    remaining = sorted(set(TABLE_REQUIREMENTS) & set(inspect(engine).get_table_names()))
    if remaining:
        raise RuntimeError("BAS-158 downgrade left authority tables behind: " + ", ".join(remaining))
    definition = _execution_plan_check(engine)
    admitted = [source_kind for source_kind in EXECUTION_PLAN_SOURCE_KINDS if source_kind in definition]
    if admitted:
        raise RuntimeError("BAS-158 downgrade still admits execution-plan source kinds: " + ", ".join(admitted))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _seed_append_only_rows(engine: Engine, database_name: str) -> None:
    observed_at = datetime.now(UTC)
    evidence = EvidenceService(engine).capture(
        content=b'{"kind":"bas158-migration-replay","secret":false}',
        filename="bas158-migration-replay.json",
        content_type="application/json",
        source="migration_replay_fixture",
        source_ref=f"bas158-replay://{database_name}",
        grade=EvidenceGrade.A,
        effective_at=observed_at.isoformat(),
        effective_until=None,
        created_by="bas158-replay",
        metadata={"retention_class": "operational"},
    )
    synthetic_reference = "msl_BAS158ReplayLocator000000000001"
    with Session(engine) as session, session.begin():
        session.add(
            ChannelAccountReviewDecisionRow(
                id="bas158-review-decision",
                submission_evidence_id=evidence.id,
                decision_evidence_id=evidence.id,
                sequence=1,
                accepted=False,
                reviewer_id="bas158-independent-reviewer",
                decision_sha256=_digest("bas158-review-decision"),
                decided_at=observed_at,
                recorded_at=observed_at,
                tenant_ref="bas158-tenant",
                entity_ref="bas158-entity",
                store_ref="bas158-store",
            )
        )
        kill_switch = KillSwitchEventRow(
            engaged=False,
            reason="synthetic BAS-158 replay release",
            actor_id="bas158-replay",
            created_at=observed_at,
        )
        session.add(kill_switch)
        session.flush()
        session.add(
            ChannelAccountKillSwitchStateRow(
                id="bas158-kill-switch-state",
                source_event_ref="bas158-kill-switch-source-event",
                sequence=1,
                kill_switch_sequence=kill_switch.sequence,
                writes_enabled=True,
                action_id="channel_authorization_grant",
                platform="ozon",
                account_ref="bas158-synthetic-account",
                adapter_id="bas158-replay-adapter",
                adapter_version="1",
                evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                payload_sha256=_digest("bas158-kill-switch-payload"),
                effective_at=observed_at,
                recorded_at=observed_at,
                created_by="bas158-replay",
                tenant_ref="bas158-tenant",
                entity_ref="bas158-entity",
                store_ref="bas158-store",
                scope_grant_authority_sha256=_digest("bas158-scope-grant"),
                scope_as_of=observed_at,
            )
        )
        session.add(
            ChannelAccountAuthorizationEventRow(
                id="bas158-authorization-event",
                source_event_ref="bas158-authorization-source-event",
                sequence=1,
                event_type="unknown_outcome_observed",
                authorization_source="official",
                platform="ozon",
                account_ref="bas158-synthetic-account",
                adapter_id="bas158-replay-adapter",
                adapter_version="1",
                role_ref="read-only-replay",
                subaccount_ref="bas158-synthetic-subaccount",
                credential_kind="api_key_ref",
                capabilities_json=["catalog_read"],
                secret_reference=synthetic_reference,
                secret_reference_sha256=_digest(synthetic_reference),
                credential_fingerprint_sha256=_digest("bas158-synthetic-fingerprint"),
                health_status="unknown",
                readback_outcome="unknown",
                rate_limit_state="unknown",
                external_schema_version="bas158-replay-v1",
                consent_evidence_id=evidence.id,
                evidence_id=evidence.id,
                adapter_contract_sha256=_digest("bas158-adapter-contract"),
                consent_evidence_sha256=evidence.sha256,
                source_evidence_sha256=evidence.sha256,
                source_payload_sha256=_digest("bas158-source-payload"),
                payload_sha256=_digest("bas158-authorization-payload"),
                effective_at=observed_at,
                expires_at=observed_at + timedelta(days=1),
                verified_at=observed_at,
                recorded_at=observed_at,
                created_by="bas158-replay",
                tenant_ref="bas158-tenant",
                entity_ref="bas158-entity",
                store_ref="bas158-store",
                scope_grant_authority_sha256=_digest("bas158-scope-grant"),
                scope_as_of=observed_at,
            )
        )


def _require_rejected(engine: Engine, statement: str, boundary: str) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    except DBAPIError:
        return
    raise RuntimeError(f"PostgreSQL allowed {boundary} mutation of BAS-158 append-only facts")


def _verify_append_only(engine: Engine) -> None:
    for statement, boundary in (
        (
            "UPDATE channel_account_review_decisions SET accepted = NOT accepted WHERE id = 'bas158-review-decision'",
            "review-decision UPDATE",
        ),
        (
            "DELETE FROM channel_account_review_decisions WHERE id = 'bas158-review-decision'",
            "review-decision DELETE",
        ),
        (
            "UPDATE channel_account_kill_switch_states "
            "SET writes_enabled = NOT writes_enabled "
            "WHERE id = 'bas158-kill-switch-state'",
            "kill-switch UPDATE",
        ),
        (
            "DELETE FROM channel_account_kill_switch_states WHERE id = 'bas158-kill-switch-state'",
            "kill-switch DELETE",
        ),
        (
            "UPDATE channel_account_authorization_events "
            "SET health_status = 'mutated' "
            "WHERE id = 'bas158-authorization-event'",
            "authorization UPDATE",
        ),
        (
            "DELETE FROM channel_account_authorization_events WHERE id = 'bas158-authorization-event'",
            "authorization DELETE",
        ),
    ):
        _require_rejected(engine, statement, boundary)


def _verify_negative_insert_matrix(engine: Engine) -> None:
    columns = (
        "id,source_event_ref,sequence,kill_switch_sequence,writes_enabled,"
        "action_id,platform,account_ref,adapter_id,adapter_version,"
        "evidence_id,evidence_sha256,payload_sha256,effective_at,recorded_at,"
        "created_by,tenant_ref,entity_ref,store_ref,"
        "scope_grant_authority_sha256,scope_as_of"
    )
    cases = (
        (
            "SELECT id || '-bad-hash', source_event_ref || '-bad-hash', sequence + 10, "
            "kill_switch_sequence,writes_enabled,action_id,platform,account_ref,adapter_id,"
            "adapter_version,evidence_id,'NOT_A_SHA256',payload_sha256,effective_at,"
            "recorded_at,created_by,tenant_ref,entity_ref,store_ref,"
            "scope_grant_authority_sha256,scope_as_of "
            "FROM channel_account_kill_switch_states WHERE id='bas158-kill-switch-state'",
            "Kill Switch invalid evidence hash INSERT",
        ),
        (
            "SELECT id || '-bad-action', source_event_ref || '-bad-action', sequence + 11, "
            "kill_switch_sequence,writes_enabled,'channel-account-authorization-change',"
            "platform,account_ref,adapter_id,adapter_version,evidence_id,evidence_sha256,"
            "payload_sha256,effective_at,recorded_at,created_by,tenant_ref,entity_ref,"
            "store_ref,scope_grant_authority_sha256,scope_as_of "
            "FROM channel_account_kill_switch_states WHERE id='bas158-kill-switch-state'",
            "Kill Switch unknown action INSERT",
        ),
        (
            "SELECT id || '-bad-time', source_event_ref || '-bad-time', sequence + 12, "
            "kill_switch_sequence,writes_enabled,action_id,platform,account_ref,adapter_id,"
            "adapter_version,evidence_id,evidence_sha256,payload_sha256,"
            "scope_as_of + interval '1 second',recorded_at,created_by,tenant_ref,entity_ref,"
            "store_ref,scope_grant_authority_sha256,scope_as_of "
            "FROM channel_account_kill_switch_states WHERE id='bas158-kill-switch-state'",
            "Kill Switch invalid time order INSERT",
        ),
    )
    for select_sql, boundary in cases:
        _require_rejected(
            engine,
            f"INSERT INTO channel_account_kill_switch_states ({columns}) {select_sql}",
            boundary,
        )
    with engine.connect() as connection:
        original = connection.execute(
            ChannelAccountAuthorizationEventRow.__table__.select().where(
                ChannelAccountAuthorizationEventRow.id
                == "bas158-authorization-event"
            )
        ).mappings().one()
    authorization_cases = (
        ({"capabilities_json": ["catalog_read", 7]}, "non-string capability"),
        ({"capabilities_json": ["catalog_read", "catalog_read"]}, "duplicate capability"),
        ({"capabilities_json": [""]}, "empty capability"),
        (
            {"scope_as_of": original["recorded_at"] + timedelta(seconds=1)},
            "scope snapshot after recorded_at",
        ),
    )
    for offset, (changes, boundary) in enumerate(
        authorization_cases,
        start=20,
    ):
        values = dict(original)
        values.update(changes)
        values.update(
            {
                "id": f"bas158-authorization-event-invalid-{offset}",
                "source_event_ref": f"bas158-authorization-invalid-{offset}",
                "sequence": offset,
            }
        )
        try:
            with engine.begin() as connection:
                connection.execute(
                    ChannelAccountAuthorizationEventRow.__table__.insert(),
                    values,
                )
        except DBAPIError:
            continue
        raise RuntimeError(
            "PostgreSQL allowed BAS-158 authorization " + boundary
        )


def main() -> None:
    source = create_database_engine()
    if source.dialect.name != "postgresql":
        source.dispose()
        raise RuntimeError("BAS-158 migration replay requires PostgreSQL")
    database_name = f"{PREFIX}{uuid4().hex[:12]}"
    _validate_database_name(database_name)
    admin_url = source.url.set(database="postgres")
    replay_url = source.url.set(database=database_name)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    replay: Engine | None = None
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            replay_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        command.upgrade(config, REVISION_0081)
        replay = create_engine(replay_url)
        _verify_0081(replay)
        _seed_append_only_rows(replay, database_name)
        _verify_append_only(replay)
        _verify_negative_insert_matrix(replay)

        command.downgrade(config, REVISION_0080)
        _verify_0080(replay)

        command.upgrade(config, REVISION_0081)
        _verify_0081(replay)
        print("BAS-158 empty PostgreSQL replay passed: base -> 0081 -> 0080 -> 0081")
    finally:
        if replay is not None:
            replay.dispose()
        if created:
            _validate_database_name(database_name)
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database_name "
                        "AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()
        source.dispose()


if __name__ == "__main__":
    main()
