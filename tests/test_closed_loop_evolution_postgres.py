from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, Numeric, String, Text, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

import scripts.manage_g1_database as g1_database_manager
from apps.control_plane.agent_runtime import (
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    RuntimeAuditEnvelope,
    RuntimeAuditEvent,
)
from apps.control_plane.agent_runtime_evidence import (
    AgentRuntimeRunEnvelopeRow,
    AgentRuntimeRunEventRow,
    SqlAgentRuntimeEvidenceLedger,
)
from apps.control_plane.closed_loop_evolution import (
    ClosedLoopAuthorityReceiptRegistrarPort,
    ClosedLoopAuthorityReceiptRow,
    ClosedLoopContractError,
    ClosedLoopEventEvidenceIssuerPort,
    ClosedLoopEvidenceIssuanceRow,
    ClosedLoopEvidenceIssuerPort,
    ClosedLoopOutcomeBundleRow,
    ClosedLoopOutcomeEventRow,
    ClosedLoopOutcomeEvidenceLinkRow,
    GovernedClosedLoopEvolutionWorkspace,
    _agent_run_canonical,
    _agent_run_event_hash,
    _agent_run_event_id,
    _agent_run_event_row_payload,
    _canonical_json,
    _event_hash,
    _link_hash,
    _stable_id,
)
from apps.control_plane.evidence import (
    CLOSED_LOOP_AUTHORITY_CONTRACTS,
    CLOSED_LOOP_RESERVED_SOURCES,
    ClosedLoopEvidenceAuthorityAdapter,
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    _closed_loop_claims,
    _closed_loop_claims_sha256,
    _closed_loop_postgres_jsonb_sha256,
)
from apps.control_plane.security import Principal

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
G1_CONTRACT_DATABASE_URL = os.getenv("KJDS_G1_CONTRACT_DATABASE_URL")
CLOSED_LOOP_REVISION = "20260805_0096"
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)

EVENT_OWNER = "kjds_cloe_event_issuance_owner"
GENERIC_RUNTIME = "kjds_g1_runtime"
ISSUANCE_ROLES = (
    "kjds_cloe_issuance_owner",
    EVENT_OWNER,
    "kjds_cloe_issuance_runtime",
    "kjds_cloe_experiment_authority",
    "kjds_cloe_cost_authority",
    "kjds_cloe_outcome_authority",
    "kjds_cloe_review_authority",
)
SECRET_ENVIRONMENTS = (
    "KJDS_G1_RUN_TOKEN",
    "KJDS_G1_COVERAGE_ISSUER_PASSWORD",
    "KJDS_G1_RUNTIME_PASSWORD",
    "KJDS_G1_CLOE_ISSUER_PASSWORD",
    "KJDS_G1_CLOE_EXPERIMENT_PASSWORD",
    "KJDS_G1_CLOE_COST_PASSWORD",
    "KJDS_G1_CLOE_OUTCOME_PASSWORD",
    "KJDS_G1_CLOE_REVIEW_PASSWORD",
)
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/closed_loop_evolution/bas204_closed_loop_v1.json").read_text(encoding="utf-8")
)
SEALING_KEY = b"bas204-postgres-test-sealing-key-32-bytes-minimum"
AUTHORITY_PASSWORDS = {
    "experiment": "KJDS_G1_CLOE_EXPERIMENT_PASSWORD",
    "cost": "KJDS_G1_CLOE_COST_PASSWORD",
    "business_outcome": "KJDS_G1_CLOE_OUTCOME_PASSWORD",
    "review_event": "KJDS_G1_CLOE_REVIEW_PASSWORD",
}
AUTHORITY_ROLES = {
    "experiment": "kjds_cloe_experiment_authority",
    "cost": "kjds_cloe_cost_authority",
    "business_outcome": "kjds_cloe_outcome_authority",
    "review_event": "kjds_cloe_review_authority",
}
ACL_SCHEMA_ROLES = ISSUANCE_ROLES
ACL_TABLE_ROLES = (
    "kjds_cloe_issuance_owner",
    "kjds_cloe_event_issuance_owner",
)
ACL_TABLES = ("evidence_records", "evidence_blobs")
ACL_TABLE_PRIVILEGES = ("SELECT", "INSERT")
ACL_CELLS = (
    *(
        (f"schema:public:{role}:USAGE", role, "schema", "public", "USAGE")
        for role in ACL_SCHEMA_ROLES
    ),
    *(
        (
            f"table:public.{table_name}:{role}:{privilege}",
            role,
            "table",
            table_name,
            privilege,
        )
        for role in ACL_TABLE_ROLES
        for table_name in ACL_TABLES
        for privilege in ACL_TABLE_PRIVILEGES
    ),
)
ACL_ROLE_EXPECTATIONS = {
    "kjds_cloe_issuance_owner": (False, True),
    "kjds_cloe_event_issuance_owner": (False, True),
    "kjds_cloe_issuance_runtime": (True, False),
    **{role: (True, False) for role in AUTHORITY_ROLES.values()},
}
ACL_ROLE_ATTRIBUTE_DRIFTS = tuple(
    (role, drift, restore)
    for role, (can_login, bypass_rls) in ACL_ROLE_EXPECTATIONS.items()
    for drift, restore in (
        (("NOLOGIN", "LOGIN") if can_login else ("LOGIN", "NOLOGIN")),
        ("INHERIT", "NOINHERIT"),
        ("SUPERUSER", "NOSUPERUSER"),
        ("CREATEROLE", "NOCREATEROLE"),
        ("CREATEDB", "NOCREATEDB"),
        ("REPLICATION", "NOREPLICATION"),
        (
            ("NOBYPASSRLS", "BYPASSRLS")
            if bypass_rls
            else ("BYPASSRLS", "NOBYPASSRLS")
        ),
    )
)


def _migration_config(target_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))
    return config


def _upgrade_target(target_url: str, revision: str) -> None:
    previous = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = target_url
    try:
        command.upgrade(_migration_config(target_url), revision)
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous


def _downgrade_target(target_url: str, revision: str) -> None:
    previous = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = target_url
    try:
        command.downgrade(_migration_config(target_url), revision)
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous


def _revoke_generic_runtime_harness_acl(target_url: str) -> None:
    engine = create_engine(target_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "REVOKE EXECUTE ON FUNCTION kjds_cloe_issue_event_evidence("
                "text,bytea,text,text,timestamptz,timestamptz,jsonb) "
                f"FROM {GENERIC_RUNTIME}"
            )
            connection.exec_driver_sql(
                "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
                f"FROM {GENERIC_RUNTIME}"
            )
            connection.exec_driver_sql(
                "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
                f"FROM {GENERIC_RUNTIME}"
            )
            connection.exec_driver_sql(
                f"REVOKE USAGE ON SCHEMA public FROM {GENERIC_RUNTIME}"
            )
    finally:
        engine.dispose()


def _management_state(engine) -> tuple[str, str, int, int, int]:
    with engine.connect() as connection:
        return (
            str(connection.scalar(text("SELECT current_database()"))),
            str(connection.scalar(text("SELECT version_num FROM alembic_version"))),
            int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                        "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() "
                        "AND c.relname LIKE 'closed_loop_%'"
                    )
                )
            ),
            int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() "
                        "AND p.proname LIKE 'kjds_cloe_%'"
                    )
                )
            ),
            int(
                connection.scalar(
                    text("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'trg_cloe_%'")
                )
            ),
        )


def _preflight_control_state(connection) -> dict[str, object]:
    return {
        "alembic_version": connection.scalar(text("SELECT version_num FROM alembic_version")),
        "relations": tuple(
            connection.scalars(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() "
                    "AND (c.relname LIKE 'closed\\_loop\\_%' ESCAPE '\\' "
                    "OR c.relname='uq_closed_loop_authority_evidence_source_ref') "
                    "ORDER BY c.relname"
                )
            )
        ),
        "functions": tuple(
            connection.scalars(
                text(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname=current_schema() "
                    "AND p.proname LIKE 'kjds\\_cloe\\_%' ESCAPE '\\' "
                    "ORDER BY p.proname"
                )
            )
        ),
        "triggers": tuple(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname LIKE 'trg\\_cloe\\_%' ESCAPE '\\' ORDER BY tgname"
                )
            )
        ),
        "schema_acl": connection.scalar(
            text(
                "SELECT coalesce(nspacl::text,'') FROM pg_namespace "
                "WHERE nspname=current_schema()"
            )
        ),
        "table_acl": tuple(
            connection.execute(
                text(
                    "SELECT c.relname,coalesce(c.relacl::text,'') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() "
                    "AND c.relname IN ('evidence_blobs','evidence_records','lineage_edges') "
                    "ORDER BY c.relname"
                )
            ).all()
        ),
        "roles": tuple(
            connection.execute(
                text(
                    "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                    "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
                    "WHERE rolname=ANY(:roles) ORDER BY rolname"
                ),
                {"roles": list(ISSUANCE_ROLES)},
            ).all()
        ),
        "memberships": tuple(
            connection.execute(
                text(
                    "SELECT granted.rolname,member_role.rolname "
                    "FROM pg_auth_members membership "
                    "JOIN pg_roles granted ON granted.oid=membership.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=membership.member "
                    "WHERE granted.rolname=ANY(:roles) OR member_role.rolname=ANY(:roles) "
                    "ORDER BY granted.rolname,member_role.rolname"
                ),
                {"roles": list(ISSUANCE_ROLES)},
            ).all()
        ),
    }


def _cloe_catalog_state(connection) -> dict[str, object]:
    state = _preflight_control_state(connection)
    catalog = {
        key: state[key]
        for key in (
            "alembic_version",
            "relations",
            "functions",
            "triggers",
            "roles",
            "memberships",
        )
    }
    catalog["columns"] = tuple(
        connection.execute(
            text(
                "SELECT c.relname,a.attnum,a.attname,"
                "format_type(a.atttypid,a.atttypmod),a.attnotnull,"
                "pg_get_expr(d.adbin,d.adrelid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid=c.oid "
                "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
                "WHERE n.nspname=current_schema() AND c.relname LIKE 'closed_loop_%' "
                "AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped "
                "ORDER BY c.relname,a.attnum"
            )
        ).all()
    )
    catalog["constraints"] = tuple(
        connection.execute(
            text(
                "SELECT table_row.relname,constraint_row.conname,"
                "constraint_row.contype,constraint_row.condeferrable,"
                "constraint_row.condeferred,"
                "pg_get_constraintdef(constraint_row.oid,true) "
                "FROM pg_constraint constraint_row "
                "JOIN pg_class table_row ON table_row.oid=constraint_row.conrelid "
                "JOIN pg_namespace n ON n.oid=table_row.relnamespace "
                "WHERE n.nspname=current_schema() "
                "AND table_row.relname LIKE 'closed_loop_%' "
                "ORDER BY table_row.relname,constraint_row.conname"
            )
        ).all()
    )
    catalog["indexes"] = tuple(
        connection.execute(
            text(
                "SELECT tablename,indexname,indexdef FROM pg_indexes "
                "WHERE schemaname=current_schema() AND "
                "(tablename LIKE 'closed_loop_%' "
                "OR indexname='uq_closed_loop_authority_evidence_source_ref') "
                "ORDER BY tablename,indexname"
            )
        ).all()
    )
    catalog["function_definitions"] = tuple(
        connection.execute(
            text(
                "SELECT p.proname,pg_get_function_identity_arguments(p.oid),"
                "owner_role.rolname,coalesce(p.proacl::text,'<NULL>'),"
                "pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "JOIN pg_roles owner_role ON owner_role.oid=p.proowner "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'kjds_cloe_%' "
                "ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)"
            )
        ).all()
    )
    catalog["trigger_definitions"] = tuple(
        connection.execute(
            text(
                "SELECT table_row.relname,trigger_row.tgname,trigger_row.tgenabled,"
                "pg_get_triggerdef(trigger_row.oid,true) "
                "FROM pg_trigger trigger_row "
                "JOIN pg_class table_row ON table_row.oid=trigger_row.tgrelid "
                "JOIN pg_namespace n ON n.oid=table_row.relnamespace "
                "WHERE n.nspname=current_schema() AND NOT trigger_row.tgisinternal "
                "AND trigger_row.tgname LIKE 'trg_cloe_%' "
                "ORDER BY table_row.relname,trigger_row.tgname"
            )
        ).all()
    )
    catalog["relation_ownership_acl"] = tuple(
        connection.execute(
            text(
                "SELECT c.relname,c.relkind,owner_role.rolname,"
                "coalesce(c.relacl::text,'<NULL>') "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_roles owner_role ON owner_role.oid=c.relowner "
                "WHERE n.nspname=current_schema() AND "
                "(c.relname LIKE 'closed_loop_%' OR c.relname IN "
                "('evidence_records','evidence_blobs')) "
                "ORDER BY c.relname,c.relkind"
            )
        ).all()
    )
    catalog["schema_ownership_acl"] = tuple(
        connection.execute(
            text(
                "SELECT n.nspname,owner_role.rolname,coalesce(n.nspacl::text,'<NULL>') "
                "FROM pg_namespace n JOIN pg_roles owner_role ON owner_role.oid=n.nspowner "
                "WHERE n.nspname=current_schema()"
            )
        ).all()
    )
    return catalog


def _legacy_artifact_snapshot(connection) -> dict[str, tuple[object, ...]]:
    return {
        "blobs": tuple(
            connection.execute(
                text(
                    "SELECT sha256,byte_size,encode(content_bytes,'hex'),created_at::text "
                    "FROM evidence_blobs ORDER BY sha256"
                )
            ).all()
        ),
        "evidence": tuple(
            connection.execute(
                text(
                    "SELECT id,blob_sha256,filename,content_type,source,source_ref,grade,"
                    "effective_at::text,effective_until::text,recorded_at::text,created_by,"
                    "metadata_json::text FROM evidence_records ORDER BY id"
                )
            ).all()
        ),
        "lineage": tuple(
            connection.execute(
                text(
                    "SELECT id,from_type,from_id,to_type,to_id,relationship,created_by,"
                    "recorded_at::text FROM lineage_edges ORDER BY id"
                )
            ).all()
        ),
    }


def _seed_legacy_reserved_evidence(connection, sources: tuple[str, ...]) -> None:
    recorded_at = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
    for index, source in enumerate(sources):
        content = _canonical_json({"legacy_fixture": source, "index": index})
        digest = hashlib.sha256(content).hexdigest()
        evidence_id = f"legacy-{index}-{digest[:24]}"
        connection.execute(
            text(
                "INSERT INTO evidence_blobs "
                "(sha256,byte_size,content_bytes,created_at) "
                "VALUES (:sha256,:byte_size,:content_bytes,:created_at)"
            ),
            {
                "sha256": digest,
                "byte_size": len(content),
                "content_bytes": content,
                "created_at": recorded_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evidence_records "
                "(id,blob_sha256,filename,content_type,source,source_ref,grade,"
                "effective_at,effective_until,recorded_at,created_by,metadata_json) "
                "VALUES (:id,:sha256,:filename,'application/json',:source,:source_ref,'D',"
                ":recorded_at,NULL,:recorded_at,'legacy-fixture',CAST(:metadata AS json))"
            ),
            {
                "id": evidence_id,
                "sha256": digest,
                "filename": f"legacy-{index}.json",
                "source": source,
                "source_ref": f"legacy://closed-loop/{index}",
                "recorded_at": recorded_at,
                "metadata": json.dumps(
                    {"legacy_fixture": True, "source": source},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        )
        connection.execute(
            text(
                "INSERT INTO lineage_edges "
                "(id,from_type,from_id,to_type,to_id,relationship,created_by,recorded_at) "
                "VALUES (:id,'evidence',:evidence_id,'legacy_fixture',:target_id,"
                "'legacy_closed_loop_binding','legacy-fixture',:recorded_at)"
            ),
            {
                "id": f"legacy-lineage-{index}-{digest[:16]}",
                "evidence_id": evidence_id,
                "target_id": f"legacy-target-{index}",
                "recorded_at": recorded_at,
            },
        )


def _seed_orphan_closed_loop_lineage(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO lineage_edges "
            "(id,from_type,from_id,to_type,to_id,relationship,created_by,recorded_at) "
            "VALUES ('legacy-orphan-cloe','closed_loop_outcome_bundle',:bundle_id,"
            "'evidence','legacy-missing-evidence','legacy_closed_loop_binding',"
            "'legacy-fixture',:recorded_at)"
        ),
        {
            "bundle_id": "clob_" + "a" * 40,
            "recorded_at": datetime(2026, 8, 5, 9, 0, tzinfo=UTC),
        },
    )


def _assert_preflight_failure_preserves_state(
    *, target_url: str, engine, case_id: str
) -> dict[str, object]:
    with engine.connect() as connection:
        expected_control = _preflight_control_state(connection)
        expected_legacy = _legacy_artifact_snapshot(connection)
    with pytest.raises(DBAPIError) as error:
        _upgrade_target(target_url, CLOSED_LOOP_REVISION)
    assert error.value.orig.sqlstate == "55000"
    assert "0096 upgrade blocked: legacy closed-loop artifacts exist" in str(error.value)
    assert "legacy://closed-loop" not in str(error.value)
    with engine.connect() as connection:
        assert _preflight_control_state(connection) == expected_control
        assert _legacy_artifact_snapshot(connection) == expected_legacy
    return {
        "case_id": case_id,
        "sqlstate": error.value.orig.sqlstate,
        "legacy_counts": {
            name: len(rows) for name, rows in expected_legacy.items()
        },
    }


def _clear_legacy_preflight_fixture(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE lineage_edges,evidence_records,evidence_blobs CASCADE")
        )


def _exercise_upgrade_preflight_insert_race(
    *, target_url: str, engine
) -> dict[str, object]:
    application_name = "bas204-upgrade-preflight-race"
    race_url = (
        make_url(target_url)
        .update_query_dict({"application_name": application_name})
        .render_as_string(hide_password=False)
    )
    with engine.connect() as connection:
        expected_control = _preflight_control_state(connection)
    writer = engine.connect()
    transaction = writer.begin()
    try:
        _seed_legacy_reserved_evidence(
            writer, ("closed-loop-experiment-receipt",)
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_upgrade_target, race_url, "head")
            deadline = time.monotonic() + 10
            observed_lock_wait = False
            while time.monotonic() < deadline:
                with engine.connect() as probe:
                    observed_lock_wait = bool(
                        probe.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                                "WHERE datname=current_database() "
                                "AND application_name=:application_name "
                                "AND wait_event_type='Lock')"
                            ),
                            {"application_name": application_name},
                        )
                    )
                if observed_lock_wait:
                    break
                if future.done():
                    break
                time.sleep(0.02)
            assert observed_lock_wait, "0096 upgrade did not wait on the preflight table lock"
            transaction.commit()
            with pytest.raises(DBAPIError) as error:
                future.result(timeout=10)
        assert error.value.orig.sqlstate == "55000"
        assert "0096 upgrade blocked: legacy closed-loop artifacts exist" in str(
            error.value
        )
        with engine.connect() as connection:
            assert _preflight_control_state(connection) == expected_control
            legacy = _legacy_artifact_snapshot(connection)
            assert len(legacy["evidence"]) == 1
            assert len(legacy["lineage"]) == 1
        return {
            "case_id": "concurrent_reserved_insert",
            "sqlstate": error.value.orig.sqlstate,
            "wait_event_type": "Lock",
        }
    finally:
        if transaction.is_active:
            transaction.rollback()
        writer.close()


def _exercise_upgrade_preflight(target_url: str) -> dict[str, tuple[dict[str, object], ...]]:
    engine = create_engine(target_url)
    evidence_receipts: list[dict[str, object]] = []
    try:
        for source in sorted(CLOSED_LOOP_RESERVED_SOURCES):
            with engine.begin() as connection:
                _seed_legacy_reserved_evidence(connection, (source,))
            evidence_receipts.append(
                _assert_preflight_failure_preserves_state(
                    target_url=target_url,
                    engine=engine,
                    case_id=f"source:{source}",
                )
            )
            _clear_legacy_preflight_fixture(engine)
        with engine.begin() as connection:
            _seed_legacy_reserved_evidence(
                connection, tuple(sorted(CLOSED_LOOP_RESERVED_SOURCES))
            )
        evidence_receipts.append(
            _assert_preflight_failure_preserves_state(
                target_url=target_url,
                engine=engine,
                case_id="mixed_sources_with_lineage",
            )
        )
        _clear_legacy_preflight_fixture(engine)
        with engine.begin() as connection:
            _seed_orphan_closed_loop_lineage(connection)
        lineage_receipt = _assert_preflight_failure_preserves_state(
            target_url=target_url,
            engine=engine,
            case_id="orphan_closed_loop_lineage",
        )
        _clear_legacy_preflight_fixture(engine)
        race_receipt = _exercise_upgrade_preflight_insert_race(
            target_url=target_url,
            engine=engine,
        )
        _clear_legacy_preflight_fixture(engine)
        with engine.connect() as connection:
            assert _legacy_artifact_snapshot(connection) == {
                "blobs": (),
                "evidence": (),
                "lineage": (),
            }
        return {
            "evidence": tuple(evidence_receipts),
            "lineage": (lineage_receipt,),
            "race": (race_receipt,),
        }
    finally:
        engine.dispose()


def _load_0096_migration_module():
    path = (
        Path(__file__).parents[1]
        / "migrations/versions/20260805_0096_governed_closed_loop_evolution.py"
    )
    spec = importlib.util.spec_from_file_location("bas204_acl_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BAS-204 migration module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _acl_entries(connection, *, object_kind: str, object_name: str):
    if object_kind == "schema":
        rows = connection.execute(
            text(
                "SELECT grantor.rolname,"
                "CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,"
                "acl.privilege_type,acl.is_grantable "
                "FROM pg_namespace namespace "
                "CROSS JOIN LATERAL aclexplode(coalesce(namespace.nspacl,"
                "acldefault('n',namespace.nspowner))) acl "
                "LEFT JOIN pg_roles grantor ON grantor.oid=acl.grantor "
                "LEFT JOIN pg_roles grantee ON grantee.oid=acl.grantee "
                "WHERE namespace.nspname=:name ORDER BY 1,2,3,4"
            ),
            {"name": object_name},
        ).all()
        raw_acl = connection.scalar(
            text("SELECT nspacl::text FROM pg_namespace WHERE nspname=:name"),
            {"name": object_name},
        )
    else:
        rows = connection.execute(
            text(
                "SELECT grantor.rolname,"
                "CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,"
                "acl.privilege_type,acl.is_grantable "
                "FROM pg_class relation JOIN pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "CROSS JOIN LATERAL aclexplode(coalesce(relation.relacl,"
                "acldefault('r',relation.relowner))) acl "
                "LEFT JOIN pg_roles grantor ON grantor.oid=acl.grantor "
                "LEFT JOIN pg_roles grantee ON grantee.oid=acl.grantee "
                "WHERE namespace.nspname=current_schema() "
                "AND relation.relname=:name ORDER BY 1,2,3,4"
            ),
            {"name": object_name},
        ).all()
        raw_acl = connection.scalar(
            text(
                "SELECT relation.relacl::text FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
                "WHERE namespace.nspname=current_schema() AND relation.relname=:name"
            ),
            {"name": object_name},
        )
    return tuple(tuple(row) for row in rows), raw_acl


def _acl_effective(connection, cell: tuple[str, str, str, str, str]) -> bool:
    _, role, object_kind, object_name, privilege = cell
    if object_kind == "schema":
        return bool(
            connection.scalar(
                text("SELECT has_schema_privilege(:role,:object,:privilege)"),
                {"role": role, "object": object_name, "privilege": privilege},
            )
        )
    return bool(
        connection.scalar(
            text("SELECT has_table_privilege(:role,:object,:privilege)"),
            {
                "role": role,
                "object": f"public.{object_name}",
                "privilege": privilege,
            },
        )
    )


def _acl_receipt_rows(connection) -> tuple[dict[str, object], ...]:
    if connection.scalar(
        text("SELECT to_regclass('closed_loop_acl_baseline_receipts')")
    ) is None:
        return ()
    return tuple(
        dict(row)
        for row in connection.execute(
            text(
                "SELECT cell_id,role_name,object_kind,object_name,privilege_type,"
                "migration_grantor,baseline_direct,baseline_grant_option,"
                "baseline_effective,introduced,baseline_acl_json,baseline_acl_text,"
                "baseline_acl_sha256,baseline_outside_acl_sha256,receipt_sha256,"
                "captured_at::text AS captured_at "
                "FROM closed_loop_acl_baseline_receipts ORDER BY cell_id"
            )
        ).mappings()
    )


def _acl_receipt_hash(row: dict[str, object]) -> str:
    payload = {
        key: row[key]
        for key in (
            "cell_id",
            "role_name",
            "object_kind",
            "object_name",
            "privilege_type",
            "migration_grantor",
            "baseline_direct",
            "baseline_grant_option",
            "baseline_effective",
            "introduced",
            "baseline_acl_json",
            "baseline_acl_text",
            "baseline_acl_sha256",
            "baseline_outside_acl_sha256",
        )
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "ascii"
        )
    ).hexdigest()


def _assert_acl_receipts(connection) -> tuple[dict[str, object], ...]:
    rows = _acl_receipt_rows(connection)
    assert len(rows) == 15
    assert {row["cell_id"] for row in rows} == {cell[0] for cell in ACL_CELLS}
    for row in rows:
        assert row["receipt_sha256"] == _acl_receipt_hash(row)
        assert row["baseline_acl_sha256"] == hashlib.sha256(
            row["baseline_acl_json"].encode("ascii")
        ).hexdigest()
        assert row["introduced"] is (not row["baseline_effective"])
        assert not row["baseline_grant_option"] or row["baseline_direct"]
        assert not row["baseline_direct"] or row["baseline_effective"]
    return rows


def _acl_surface_state(connection) -> dict[str, object]:
    objects = (("schema", "public"), *(('table', table) for table in ACL_TABLES))
    return {
        "control": _preflight_control_state(connection),
        "objects": tuple(
            (kind, name, *_acl_entries(connection, object_kind=kind, object_name=name))
            for kind, name in objects
        ),
        "effective": tuple(
            (cell[0], _acl_effective(connection, cell)) for cell in ACL_CELLS
        ),
        "receipts": _acl_receipt_rows(connection),
    }


def _acl_semantic_state(connection) -> tuple[object, ...]:
    state = _acl_surface_state(connection)
    return state["objects"], state["effective"]


def _apply_acl_cell(
    connection,
    cell: tuple[str, str, str, str, str],
    *,
    grant: bool,
    grant_option: bool = False,
) -> None:
    _, role, object_kind, object_name, privilege = cell
    action = "GRANT" if grant else "REVOKE"
    target = (
        f"SCHEMA {object_name}"
        if object_kind == "schema"
        else f"TABLE public.{object_name}"
    )
    suffix = " WITH GRANT OPTION" if grant and grant_option else ""
    connection.exec_driver_sql(
        f"{action} {privilege} ON {target} "
        f"{'TO' if grant else 'FROM'} {role}{suffix}"
    )


def _assert_acl_downgrade_blocked(
    *, target_url: str, engine, expected_message: str, case_id: str
) -> dict[str, str]:
    with engine.connect() as connection:
        expected = _acl_surface_state(connection)
    with pytest.raises(DBAPIError) as error:
        _downgrade_target(target_url, "20260804_0095")
    assert error.value.orig.sqlstate == "55000"
    assert expected_message in str(error.value)
    with engine.connect() as connection:
        assert _acl_surface_state(connection) == expected
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            CLOSED_LOOP_REVISION
        )
    return {"case_id": case_id, "sqlstate": "55000", "message": expected_message}


def _exercise_null_raw_acl_restore(engine) -> dict[str, object]:
    migration = _load_0096_migration_module()
    table_name = "bas204_acl_null_probe"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE {table_name}(id integer PRIMARY KEY)")
        try:
            baseline_entries, baseline_raw = migration._acl_entries(
                connection,
                schema="public",
                object_kind="table",
                object_name=table_name,
            )
            assert baseline_raw is None
            row = {
                "role_name": "kjds_cloe_issuance_runtime",
                "object_kind": "table",
                "object_name": table_name,
                "privilege_type": "SELECT",
                "introduced": True,
                "baseline_effective": False,
                "baseline_acl_sha256": migration._sha256_json(baseline_entries),
                "baseline_acl_text": None,
            }
            connection.exec_driver_sql(
                f"GRANT SELECT ON TABLE {table_name} TO kjds_cloe_issuance_runtime"
            )
            assert connection.scalar(
                text(
                    "SELECT relacl IS NOT NULL FROM pg_class relation "
                    "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
                    "WHERE namespace.nspname=current_schema() AND relation.relname=:name"
                ),
                {"name": table_name},
            )
            migration._restore_acl_baseline(
                connection,
                schema="public",
                rows=[row],
            )
            restored_entries, restored_raw = migration._acl_entries(
                connection,
                schema="public",
                object_kind="table",
                object_name=table_name,
            )
            assert restored_entries == baseline_entries
            assert restored_raw is not None
            return {
                "baseline_raw": None,
                "restored_raw_materialized": True,
                "normalized_equal": True,
            }
        finally:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name}")


def _exercise_acl_cell_roundtrip(
    *, target_url: str, engine, cell: tuple[str, str, str, str, str]
) -> dict[str, object]:
    with engine.connect() as connection:
        base_semantic = _acl_semantic_state(connection)
    with engine.begin() as connection:
        _apply_acl_cell(connection, cell, grant=True, grant_option=True)
    with engine.connect() as connection:
        baseline = _acl_surface_state(connection)
    _upgrade_target(target_url, CLOSED_LOOP_REVISION)
    with engine.connect() as connection:
        rows = _assert_acl_receipts(connection)
        receipt = next(row for row in rows if row["cell_id"] == cell[0])
        assert receipt["baseline_direct"] is True
        assert receipt["baseline_grant_option"] is True
        assert receipt["baseline_effective"] is True
        assert receipt["introduced"] is False
        object_rows = [
            row
            for row in rows
            if row["object_kind"] == cell[2] and row["object_name"] == cell[3]
        ]
        assert any(row["introduced"] for row in object_rows) or cell[2] == "schema"
    _downgrade_target(target_url, "20260804_0095")
    with engine.connect() as connection:
        assert _acl_surface_state(connection) == baseline
    with engine.begin() as connection:
        _apply_acl_cell(connection, cell, grant=False)
    with engine.connect() as connection:
        assert _acl_semantic_state(connection) == base_semantic
    return {
        "cell_id": cell[0],
        "baseline_direct": True,
        "baseline_grant_option": True,
        "restored": True,
    }


def _exercise_public_indirect_acl(target_url: str, engine) -> dict[str, object]:
    with engine.connect() as connection:
        base_semantic = _acl_semantic_state(connection)
        schema_entries, _ = _acl_entries(
            connection,
            object_kind="schema",
            object_name="public",
        )
    public_usage_preexisting = any(
        row[1] == "PUBLIC" and row[2] == "USAGE" for row in schema_entries
    )
    if not public_usage_preexisting:
        with engine.begin() as connection:
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO PUBLIC")
    with engine.connect() as connection:
        baseline = _acl_surface_state(connection)
    _upgrade_target(target_url, CLOSED_LOOP_REVISION)
    with engine.connect() as connection:
        rows = _assert_acl_receipts(connection)
        schema_rows = [row for row in rows if row["object_kind"] == "schema"]
        assert len(schema_rows) == 7
        assert all(not row["baseline_direct"] for row in schema_rows)
        assert all(row["baseline_effective"] for row in schema_rows)
        assert all(not row["introduced"] for row in schema_rows)
    _downgrade_target(target_url, "20260804_0095")
    with engine.connect() as connection:
        assert _acl_surface_state(connection) == baseline
    if not public_usage_preexisting:
        with engine.begin() as connection:
            connection.exec_driver_sql("REVOKE USAGE ON SCHEMA public FROM PUBLIC")
    with engine.connect() as connection:
        assert _acl_semantic_state(connection) == base_semantic
    return {
        "baseline_direct": False,
        "baseline_effective": True,
        "introduced": False,
        "restored": True,
    }


def _receipt_trigger_sqlstate(connection, operation: str) -> tuple[str, str]:
    statements = {
        "insert": (
            "INSERT INTO closed_loop_acl_baseline_receipts(cell_id) "
            "VALUES ('forbidden')"
        ),
        "update": (
            "UPDATE closed_loop_acl_baseline_receipts "
            "SET receipt_sha256=repeat('0',64) WHERE cell_id=(SELECT min(cell_id) "
            "FROM closed_loop_acl_baseline_receipts)"
        ),
        "delete": (
            "DELETE FROM closed_loop_acl_baseline_receipts "
            "WHERE cell_id=(SELECT min(cell_id) "
            "FROM closed_loop_acl_baseline_receipts)"
        ),
        "truncate": "TRUNCATE TABLE closed_loop_acl_baseline_receipts",
    }
    transaction = connection.begin_nested()
    try:
        connection.exec_driver_sql(statements[operation])
    except DBAPIError as error:
        transaction.rollback()
        message = "closed-loop ACL baseline receipts are immutable"
        assert message in str(error)
        return error.orig.sqlstate, message
    transaction.rollback()
    return "accepted", ""


def _receipt_triggers(connection, *, enabled: bool) -> None:
    action = "ENABLE" if enabled else "DISABLE"
    for trigger_name in (
        "trg_cloe_acl_receipt_immutable",
        "trg_cloe_acl_receipt_truncate_immutable",
    ):
        connection.exec_driver_sql(
            f"ALTER TABLE closed_loop_acl_baseline_receipts "
            f"{action} TRIGGER {trigger_name}"
        )


def _mutate_receipts(engine, statement: str, parameters=None) -> None:
    with engine.begin() as connection:
        _receipt_triggers(connection, enabled=False)
        connection.execute(text(statement), parameters or {})
        _receipt_triggers(connection, enabled=True)


def _insert_receipt_row(engine, row: dict[str, object]) -> None:
    columns = tuple(row)
    statement = (
        "INSERT INTO closed_loop_acl_baseline_receipts("
        + ",".join(columns)
        + ") VALUES ("
        + ",".join(f":{column}" for column in columns)
        + ")"
    )
    _mutate_receipts(engine, statement, row)


def _exercise_acl_receipt_integrity(
    *, target_url: str, engine
) -> dict[str, object]:
    with engine.connect() as connection:
        initial = _acl_surface_state(connection)
        trigger_rows = tuple(
            connection.execute(
                text(
                    "SELECT tgname FROM pg_trigger trigger "
                    "JOIN pg_class relation ON relation.oid=trigger.tgrelid "
                    "WHERE relation.relname='closed_loop_acl_baseline_receipts' "
                    "AND NOT trigger.tgisinternal ORDER BY tgname"
                )
            ).scalars()
        )
        assert trigger_rows == (
            "trg_cloe_acl_receipt_immutable",
            "trg_cloe_acl_receipt_truncate_immutable",
        )
        owner_dml = {}
        for operation in ("insert", "update", "delete", "truncate"):
            sqlstate, message = _receipt_trigger_sqlstate(connection, operation)
            owner_dml[operation] = {
                "sqlstate": sqlstate,
                "message": message,
                "trigger_name": (
                    "trg_cloe_acl_receipt_truncate_immutable"
                    if operation == "truncate"
                    else "trg_cloe_acl_receipt_immutable"
                ),
            }
        assert all(result["sqlstate"] == "23514" for result in owner_dml.values())
    with engine.connect() as connection:
        assert _acl_surface_state(connection) == initial

    rows = initial["receipts"]
    first = dict(rows[0])
    _mutate_receipts(
        engine,
        "UPDATE closed_loop_acl_baseline_receipts SET receipt_sha256=repeat('0',64) "
        "WHERE cell_id=:cell_id",
        {"cell_id": first["cell_id"]},
    )
    hash_drift = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL baseline drifted",
        case_id="receipt_hash_drift",
    )
    _mutate_receipts(
        engine,
        "UPDATE closed_loop_acl_baseline_receipts SET receipt_sha256=:receipt "
        "WHERE cell_id=:cell_id",
        {"cell_id": first["cell_id"], "receipt": first["receipt_sha256"]},
    )

    _mutate_receipts(
        engine,
        "DELETE FROM closed_loop_acl_baseline_receipts WHERE cell_id=:cell_id",
        {"cell_id": first["cell_id"]},
    )
    missing = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL baseline drifted",
        case_id="missing_receipt",
    )
    _insert_receipt_row(engine, first)

    _mutate_receipts(
        engine,
        "INSERT INTO closed_loop_acl_baseline_receipts "
        "SELECT cell_id||:suffix,'kjds_g1_runtime',object_kind,object_name,"
        "privilege_type,migration_grantor,baseline_direct,baseline_grant_option,"
        "baseline_effective,introduced,baseline_acl_json,baseline_acl_text,"
        "baseline_acl_sha256,baseline_outside_acl_sha256,receipt_sha256,captured_at "
        "FROM closed_loop_acl_baseline_receipts WHERE cell_id=:cell_id",
        {"cell_id": first["cell_id"], "suffix": ":extra"},
    )
    extra = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL baseline drifted",
        case_id="extra_receipt",
    )
    _mutate_receipts(
        engine,
        "DELETE FROM closed_loop_acl_baseline_receipts WHERE cell_id LIKE :pattern",
        {"pattern": "%:extra"},
    )

    with (
        pytest.raises(DBAPIError) as duplicate_error,
        engine.begin() as connection,
    ):
        _receipt_triggers(connection, enabled=False)
        connection.execute(
                text(
                    "INSERT INTO closed_loop_acl_baseline_receipts "
                    "SELECT cell_id||:suffix,role_name,object_kind,object_name,"
                "privilege_type,migration_grantor,baseline_direct,"
                "baseline_grant_option,baseline_effective,introduced,"
                "baseline_acl_json,baseline_acl_text,baseline_acl_sha256,"
                "baseline_outside_acl_sha256,receipt_sha256,captured_at "
                "FROM closed_loop_acl_baseline_receipts WHERE cell_id=:cell_id"
            ),
                {"cell_id": first["cell_id"], "suffix": ":duplicate"},
        )
    assert duplicate_error.value.orig.sqlstate == "23505"
    assert duplicate_error.value.orig.diag.constraint_name == (
        "uq_cloe_acl_baseline_cell"
    )

    invariant_statements = (
        "UPDATE closed_loop_acl_baseline_receipts "
        "SET introduced=baseline_effective WHERE cell_id=:cell_id",
        "UPDATE closed_loop_acl_baseline_receipts SET baseline_direct=false,"
        "baseline_grant_option=true WHERE cell_id=:cell_id",
        "UPDATE closed_loop_acl_baseline_receipts SET baseline_direct=true,"
        "baseline_effective=false,introduced=true WHERE cell_id=:cell_id",
    )
    for statement in invariant_statements:
        with (
            pytest.raises(DBAPIError) as invariant_error,
            engine.begin() as connection,
        ):
            _receipt_triggers(connection, enabled=False)
            connection.execute(text(statement), {"cell_id": first["cell_id"]})
        assert invariant_error.value.orig.sqlstate == "23514"
        assert invariant_error.value.orig.diag.constraint_name == (
            "ck_cloe_acl_baseline_receipt"
        )
    with engine.connect() as connection:
        assert _acl_surface_state(connection) == initial
    return {
        "trigger_names": trigger_rows,
        "migration_owner_dml": owner_dml,
        "downgrade_blocks": (hash_drift, missing, extra),
        "duplicate_constraint": "uq_cloe_acl_baseline_cell",
        "invariant_constraint": "ck_cloe_acl_baseline_receipt",
    }


def _exercise_acl_projection_drift(
    *, target_url: str, engine
) -> tuple[dict[str, str], ...]:
    with engine.connect() as connection:
        introduced = next(
            row for row in _assert_acl_receipts(connection) if row["introduced"]
        )
    cell = next(cell for cell in ACL_CELLS if cell[0] == introduced["cell_id"])
    with engine.begin() as connection:
        _apply_acl_cell(connection, cell, grant=False)
    missing = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL projection drifted",
        case_id="introduced_cell_missing",
    )
    with engine.begin() as connection:
        _apply_acl_cell(connection, cell, grant=True)

    with engine.begin() as connection:
        _apply_acl_cell(connection, cell, grant=True, grant_option=True)
    grant_option = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL projection drifted",
        case_id="introduced_cell_grant_option",
    )
    with engine.begin() as connection:
        _, role, object_kind, object_name, privilege = cell
        target = (
            f"SCHEMA {object_name}"
            if object_kind == "schema"
            else f"TABLE public.{object_name}"
        )
        connection.exec_driver_sql(
            f"REVOKE GRANT OPTION FOR {privilege} ON {target} FROM {role}"
        )

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "GRANT UPDATE ON TABLE public.evidence_records TO kjds_g1_runtime"
        )
    outside = _assert_acl_downgrade_blocked(
        target_url=target_url,
        engine=engine,
        expected_message="0096 downgrade blocked: ACL projection drifted",
        case_id="outside_acl_drift",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "REVOKE UPDATE ON TABLE public.evidence_records FROM kjds_g1_runtime"
        )
    return missing, grant_option, outside


def _exercise_acl_role_contract_drift(
    *, target_url: str, engine
) -> dict[str, tuple[dict[str, str], ...]]:
    attribute_receipts: list[dict[str, str]] = []
    for role, drift, restore in ACL_ROLE_ATTRIBUTE_DRIFTS:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"ALTER ROLE {role} {drift}")
        try:
            attribute_receipts.append(
                _assert_acl_downgrade_blocked(
                    target_url=target_url,
                    engine=engine,
                    expected_message=(
                        "0096 downgrade blocked: issuance role contract drifted"
                    ),
                    case_id=f"attribute:{role}:{drift}",
                )
            )
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"ALTER ROLE {role} {restore}")

    membership_receipts: list[dict[str, str]] = []
    for issuance_role in ISSUANCE_ROLES:
        for direction in ("inbound", "outbound"):
            granted, member = (
                (issuance_role, GENERIC_RUNTIME)
                if direction == "inbound"
                else (GENERIC_RUNTIME, issuance_role)
            )
            with engine.begin() as connection:
                connection.exec_driver_sql(f"GRANT {granted} TO {member}")
            try:
                membership_receipts.append(
                    _assert_acl_downgrade_blocked(
                        target_url=target_url,
                        engine=engine,
                        expected_message=(
                            "0096 downgrade blocked: issuance role contract drifted"
                        ),
                        case_id=f"membership:{direction}:{issuance_role}",
                    )
                )
            finally:
                with engine.begin() as connection:
                    connection.exec_driver_sql(f"REVOKE {granted} FROM {member}")
    with engine.connect() as connection:
        assert not _preflight_control_state(connection)["memberships"]
    return {
        "attributes": tuple(attribute_receipts),
        "memberships": tuple(membership_receipts),
    }


def _exercise_acl_restore(target_url: str) -> dict[str, object]:
    engine = create_engine(target_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260804_0095"
            )
        null_raw = _exercise_null_raw_acl_restore(engine)
        public_indirect = _exercise_public_indirect_acl(target_url, engine)
        cell_roundtrips = tuple(
            _exercise_acl_cell_roundtrip(
                target_url=target_url,
                engine=engine,
                cell=cell,
            )
            for cell in ACL_CELLS
        )

        _upgrade_target(target_url, CLOSED_LOOP_REVISION)
        with engine.connect() as connection:
            rows = _assert_acl_receipts(connection)
            receipt_set_sha256 = hashlib.sha256(
                "".join(str(row["receipt_sha256"]) for row in rows).encode("ascii")
            ).hexdigest()
        receipt_integrity = _exercise_acl_receipt_integrity(
            target_url=target_url,
            engine=engine,
        )
        projection_drift = _exercise_acl_projection_drift(
            target_url=target_url,
            engine=engine,
        )
        role_drift = _exercise_acl_role_contract_drift(
            target_url=target_url,
            engine=engine,
        )
        _downgrade_target(target_url, "20260804_0095")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260804_0095"
            )
            assert connection.scalar(
                text("SELECT to_regclass('closed_loop_acl_baseline_receipts')")
            ) is None
            assert not connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_proc function "
                    "JOIN pg_namespace namespace ON namespace.oid=function.pronamespace "
                    "WHERE namespace.nspname=current_schema() "
                    "AND function.proname='kjds_cloe_prevent_acl_receipt_mutation')"
                )
            )
            assert not connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname IN ('trg_cloe_acl_receipt_immutable',"
                    "'trg_cloe_acl_receipt_truncate_immutable'))"
                )
            )
        return {
            "null_raw": null_raw,
            "public_indirect": public_indirect,
            "cell_roundtrips": cell_roundtrips,
            "receipt_set_sha256": receipt_set_sha256,
            "receipt_integrity": receipt_integrity,
            "projection_drift": projection_drift,
            "role_drift": role_drift,
        }
    finally:
        engine.dispose()


def _cluster_role_snapshot(connection, role_names: tuple[str, ...]) -> dict[str, object]:
    return {
        "roles": tuple(
            connection.execute(
                text(
                    "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                    "rolcanlogin,rolreplication,rolbypassrls,"
                    "shobj_description(oid,'pg_authid') FROM pg_roles "
                    "WHERE rolname=ANY(:roles) ORDER BY rolname"
                ),
                {"roles": list(role_names)},
            ).all()
        ),
        "memberships": tuple(
            connection.execute(
                text(
                    "SELECT granted.rolname,member_role.rolname "
                    "FROM pg_auth_members membership "
                    "JOIN pg_roles granted ON granted.oid=membership.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=membership.member "
                    "WHERE granted.rolname=ANY(:roles) OR member_role.rolname=ANY(:roles) "
                    "ORDER BY granted.rolname,member_role.rolname"
                ),
                {"roles": list(role_names)},
            ).all()
        ),
        "dependencies": tuple(
            connection.execute(
                text(
                    "SELECT roles.rolname,dependency.dbid,dependency.classid,"
                    "dependency.objid,dependency.deptype "
                    "FROM pg_shdepend dependency "
                    "JOIN pg_roles roles ON roles.oid=dependency.refobjid "
                    "WHERE roles.rolname=ANY(:roles) "
                    "ORDER BY roles.rolname,dependency.dbid,dependency.classid,"
                    "dependency.objid,dependency.deptype"
                ),
                {"roles": list(role_names)},
            ).all()
        ),
    }


def _provision_disposable_postgres_gate(
    *, cluster_engine, secrets: dict[str, str]
) -> dict[str, object]:
    preexisting_allowed = {
        g1_database_manager.ISSUER_OWNER_ROLE,
        g1_database_manager.ISSUER_RUNTIME_ROLE,
    }
    token_sha256 = g1_database_manager._run_token_sha256()
    with cluster_engine.connect() as connection:
        existing_roles = tuple(g1_database_manager._existing_roles(connection))
        if not set(existing_roles).issubset(preexisting_allowed):
            raise RuntimeError("G-1 disposable role namespace is not isolated")
        if g1_database_manager._database_exists(connection):
            raise RuntimeError("G-1 disposable database already exists")
        if connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE usename=ANY(:roles) AND pid<>pg_backend_pid()"
            ),
            {"roles": list(existing_roles)},
        ):
            raise RuntimeError("G-1 pre-existing role is in concurrent use")
        baseline = _cluster_role_snapshot(connection, existing_roles)
        if baseline["memberships"]:
            raise RuntimeError("G-1 pre-existing role membership drifted")
        expected_preexisting = {
            g1_database_manager.ISSUER_OWNER_ROLE: (
                False,
                False,
                False,
                False,
                False,
                False,
                True,
                None,
            ),
            g1_database_manager.ISSUER_RUNTIME_ROLE: (
                False,
                False,
                False,
                False,
                True,
                False,
                False,
                None,
            ),
        }
        for row in baseline["roles"]:
            if tuple(row[1:]) != expected_preexisting[row[0]]:
                raise RuntimeError("G-1 pre-existing role attribute drifted")

    password_by_role = {
        g1_database_manager.ISSUER_RUNTIME_ROLE: secrets[
            "KJDS_G1_COVERAGE_ISSUER_PASSWORD"
        ],
        g1_database_manager.G1_RUNTIME_ROLE: secrets["KJDS_G1_RUNTIME_PASSWORD"],
        g1_database_manager.CLOE_RUNTIME_ROLE: secrets[
            "KJDS_G1_CLOE_ISSUER_PASSWORD"
        ],
        "kjds_cloe_experiment_authority": secrets[
            "KJDS_G1_CLOE_EXPERIMENT_PASSWORD"
        ],
        "kjds_cloe_cost_authority": secrets["KJDS_G1_CLOE_COST_PASSWORD"],
        "kjds_cloe_outcome_authority": secrets[
            "KJDS_G1_CLOE_OUTCOME_PASSWORD"
        ],
        "kjds_cloe_review_authority": secrets["KJDS_G1_CLOE_REVIEW_PASSWORD"],
    }
    role_specs = {
        g1_database_manager.ISSUER_OWNER_ROLE: (
            "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
            "NOREPLICATION BYPASSRLS"
        ),
        g1_database_manager.ISSUER_RUNTIME_ROLE: (
            "LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
            "NOREPLICATION NOBYPASSRLS"
        ),
        g1_database_manager.G1_RUNTIME_ROLE: (
            "LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
            "NOREPLICATION BYPASSRLS"
        ),
        g1_database_manager.CLOE_OWNER_ROLE: (
            "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
            "NOREPLICATION BYPASSRLS"
        ),
        g1_database_manager.CLOE_EVENT_OWNER_ROLE: (
            "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
            "NOREPLICATION BYPASSRLS"
        ),
        **{
            role: (
                "LOGIN NOINHERIT NOSUPERUSER NOCREATEROLE NOCREATEDB "
                "NOREPLICATION NOBYPASSRLS"
            )
            for role in (
                g1_database_manager.CLOE_RUNTIME_ROLE,
                *g1_database_manager.CLOE_AUTHORITY_ROLES,
            )
        },
    }
    expected_comment = g1_database_manager._ownership_comment(token_sha256)
    owned_roles = tuple(
        role for role in g1_database_manager.ROLE_NAMES if role not in existing_roles
    )
    transactional_cluster = create_engine(cluster_engine.url)
    try:
        with transactional_cluster.begin() as connection:
            expected_sql = g1_database_manager._server_literal(
                connection, expected_comment
            )
            for role in owned_roles:
                password = password_by_role.get(role)
                password_clause = ""
                if password is not None:
                    password_clause = (
                        " PASSWORD "
                        + g1_database_manager._server_literal(connection, password)
                    )
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role}" {role_specs[role]}{password_clause}'
                )
                connection.exec_driver_sql(
                    f'COMMENT ON ROLE "{role}" IS {expected_sql}'
                )
    finally:
        transactional_cluster.dispose()
    with cluster_engine.connect() as connection:
        expected_sql = g1_database_manager._server_literal(connection, expected_comment)
        connection.execute(
            text(f'CREATE DATABASE "{g1_database_manager.DATABASE_NAME}"')
        )
        connection.exec_driver_sql(
            f'COMMENT ON DATABASE "{g1_database_manager.DATABASE_NAME}" IS {expected_sql}'
        )
        updated = connection.execute(
            text(
                f"UPDATE {g1_database_manager.LEASE_TABLE} SET database_owned=true "
                "WHERE lease_id=:lease AND run_token_sha256=:token "
                "AND roles_owned=false AND database_owned=false"
            ),
            {
                "lease": g1_database_manager.LEASE_ID,
                "token": token_sha256,
            },
        )
        if updated.rowcount != 1:
            raise RuntimeError("G-1 disposable database receipt was not recorded")
    return {
        "token_sha256": token_sha256,
        "expected_comment": expected_comment,
        "owned_roles": owned_roles,
        "preexisting_roles": existing_roles,
        "preexisting_snapshot": baseline,
    }


def _cleanup_disposable_postgres_gate(*, cluster_engine, receipt) -> None:
    if receipt is None:
        return
    with cluster_engine.connect() as connection:
        expected_comment = receipt["expected_comment"]
        if g1_database_manager._database_exists(connection):
            if g1_database_manager._database_comment(connection) != expected_comment:
                raise RuntimeError("G-1 disposable database ownership drifted")
            connection.execute(
                text(f'DROP DATABASE "{g1_database_manager.DATABASE_NAME}" WITH (FORCE)')
            )
        comments = g1_database_manager._role_comments(connection)
        for role in receipt["owned_roles"]:
            if comments.get(role) != expected_comment:
                raise RuntimeError("G-1 disposable role ownership drifted")
        for role in receipt["owned_roles"]:
            connection.exec_driver_sql(f'DROP ROLE "{role}"')
        deleted = connection.execute(
            text(
                f"DELETE FROM {g1_database_manager.LEASE_TABLE} "
                "WHERE lease_id=:lease AND run_token_sha256=:token"
            ),
            {
                "lease": g1_database_manager.LEASE_ID,
                "token": receipt["token_sha256"],
            },
        )
        if deleted.rowcount != 1:
            raise RuntimeError("G-1 disposable lease cleanup drifted")
        if _cluster_role_snapshot(
            connection, receipt["preexisting_roles"]
        ) != receipt["preexisting_snapshot"]:
            raise RuntimeError("G-1 pre-existing role state changed")


class _ScopeGrants:
    def current(self, *, principal, store_ref, as_of):
        del as_of
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": FIXTURE["scope"]["entity_ref"],
            "store_ref": store_ref,
            "authority_sha256": FIXTURE["scope"]["scope_grant_authority_sha256"],
        }


class _AttestationAuthority:
    def __init__(self, purpose: str, claims: dict[str, object]) -> None:
        self.purpose = purpose
        self.contract = CLOSED_LOOP_AUTHORITY_CONTRACTS[purpose]
        self.authority_id = self.contract["issuer_id"]
        self.claims = deepcopy(claims)

    def project(self, *, purpose, attestation_ref, exact_scope, data_as_of, checked_at):
        if purpose == "review_event":
            spec = {
                "issuer_actor_id": "review-authority-actor",
                "effective_at": checked_at.isoformat(),
                "recorded_at": checked_at.isoformat(),
                "review_due_at": (checked_at + timedelta(days=1)).isoformat(),
                "effective_until": (checked_at + timedelta(days=2)).isoformat(),
            }
        else:
            spec = deepcopy(FIXTURE["attestations"][purpose])
            spec.update(
                {
                    "effective_at": (data_as_of - timedelta(hours=2)).isoformat(),
                    "recorded_at": (data_as_of - timedelta(minutes=1)).isoformat(),
                    "review_due_at": (data_as_of + timedelta(days=1)).isoformat(),
                    "effective_until": (data_as_of + timedelta(days=2)).isoformat(),
                }
            )
        claims = _closed_loop_claims(purpose, deepcopy(self.claims))
        envelope = {
            "contract_id": self.contract["contract_id"],
            "purpose": purpose,
            "attestation_ref": attestation_ref,
            "authority_receipt_id": f"receipt-{purpose}-{attestation_ref}",
            "issuer_id": self.contract["issuer_id"],
            "issuer_contract_id": self.contract["issuer_contract_id"],
            "issuer_contract_version": self.contract["issuer_contract_version"],
            "issuer_contract_sha256": self.contract["issuer_contract_sha256"],
            "schema_sha256": self.contract["schema_sha256"],
            "issuer_actor_id": spec["issuer_actor_id"],
            "exact_scope": exact_scope,
            "data_as_of": data_as_of.isoformat(),
            "effective_at": datetime.fromisoformat(spec["effective_at"]).isoformat(),
            "effective_until": datetime.fromisoformat(spec["effective_until"]).isoformat(),
            "recorded_at": datetime.fromisoformat(spec["recorded_at"]).isoformat(),
            "review_due_at": datetime.fromisoformat(spec["review_due_at"]).isoformat(),
            "claims": claims,
            "claims_sha256": _closed_loop_claims_sha256(claims),
        }
        attestation_sha256 = hashlib.sha256(_canonical_json(envelope)).hexdigest()
        return {
            "status": "ready",
            **envelope,
            "attestation_sha256": attestation_sha256,
            "attestation_signature_sha256": hashlib.sha256(f"signature:{attestation_sha256}".encode()).hexdigest(),
        }

    def verify_receipt(self, *, attestation_sha256, attestation_signature_sha256, expected_envelope):
        expected_signature = hashlib.sha256(f"signature:{attestation_sha256}".encode()).hexdigest()
        if (
            attestation_signature_sha256 != expected_signature
            or hashlib.sha256(_canonical_json(expected_envelope)).hexdigest() != attestation_sha256
        ):
            return {"status": "invalid"}
        return {
            "status": "verified",
            "authority_id": self.authority_id,
            "attestation_sha256": attestation_sha256,
        }


def _principal(actor_id: str = "bundle-recorder") -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset({"operator", "reviewer"}),
        tenant_ref=FIXTURE["scope"]["tenant_ref"],
        store_refs=frozenset({FIXTURE["scope"]["store_ref"]}),
    )


def _seed_governed_agent_run(evidence: EvidenceService, *, data_as_of: datetime) -> SqlAgentRuntimeEvidenceLedger:
    ledger = SqlAgentRuntimeEvidenceLedger(engine=evidence.engine, evidence=evidence)
    scope = FIXTURE["scope"]
    scoped_input = evidence.capture(
        content=b'{"fixture":"closed-loop-agent-input"}',
        filename="closed-loop-agent-input.json",
        content_type="application/json",
        source="test-governed-input",
        source_ref="fixture://closed-loop-agent-input",
        grade=EvidenceGrade.A,
        effective_at=(data_as_of - timedelta(hours=2)).isoformat(),
        effective_until=(data_as_of + timedelta(days=2)).isoformat(),
        created_by="agent-input-authority",
    )
    context = AgentRunScopeContext(
        tenant_ref=scope["tenant_ref"],
        entity_ref=scope["entity_ref"],
        store_ref=scope["store_ref"],
        authority_sha256=scope["scope_grant_authority_sha256"],
        actor_id="agent-actor",
        scope_as_of=data_as_of,
        evidence_refs=(
            AgentRunEvidenceRef(
                evidence_id=scoped_input.id,
                evidence_sha256=scoped_input.sha256,
            ),
        ),
    )
    envelope = RuntimeAuditEnvelope(
        run_id=FIXTURE["agent_run_ref"],
        trace_id="1" * 32,
        root_span_id="2" * 16,
        scope=context,
        task_type="closed-loop-fixture",
        registry_sha256="3" * 64,
        contract_version="1.0.0",
        prompt_version="p1",
        schema_version="s1",
        routing_policy_version="r1",
        prompt_sha256="4" * 64,
        output_schema_sha256="5" * 64,
        tool_contract_sha256="6" * 64,
        idempotency_key="agent-run-fixture",
        request_sha256="8" * 64,
        input_sha256="9" * 64,
        input_field_names=(),
        input_bytes=2,
        evidence_snapshot_sha256="a" * 64,
        required_capabilities=(),
        allowed_tools=(),
        max_cost_usd="1.0",
        max_latency_ms=1000,
        max_attempts=1,
        started_at=data_as_of - timedelta(minutes=10),
    )
    assert ledger.prepare(envelope).disposition == "new"
    adapter = {
        "adapter_name": "fixture-adapter",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "adapter_config_sha256": "d" * 64,
    }
    events = (
        RuntimeAuditEvent(
            event_type="route_selected",
            safe_payload={
                "adapter_count": 1,
                "adapter_config_sha256": ["d" * 64],
            },
        ),
        RuntimeAuditEvent(
            event_type="attempt_started",
            **adapter,
            safe_payload={"attempt": 1},
        ),
        RuntimeAuditEvent(
            event_type="attempt_completed",
            **adapter,
            output_sha256="e" * 64,
            input_tokens=10,
            output_tokens=10,
            cost_usd="0.01",
            latency_ms=100,
            safe_payload={"attempt": 1},
        ),
        RuntimeAuditEvent(
            event_type="eval_completed",
            **adapter,
            output_sha256="e" * 64,
            eval_sha256="f" * 64,
            safe_payload={"passed": True, "assertion_count": 6},
        ),
        RuntimeAuditEvent(
            event_type="run_succeeded",
            output_sha256="e" * 64,
            eval_sha256="f" * 64,
            input_tokens=10,
            output_tokens=10,
            cost_usd="0.01",
            latency_ms=100,
            safe_payload={"attempt_count": 1},
        ),
    )
    for second, event in enumerate(events, start=1):
        ledger.append(
            run_id=envelope.run_id,
            event=RuntimeAuditEvent(
                event_type=event.event_type,
                reason_code=event.reason_code,
                adapter_name=event.adapter_name,
                provider=event.provider,
                model=event.model,
                adapter_config_sha256=event.adapter_config_sha256,
                output_sha256=event.output_sha256,
                eval_sha256=event.eval_sha256,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cost_usd=event.cost_usd,
                latency_ms=event.latency_ms,
                safe_payload=event.safe_payload,
                occurred_at=data_as_of - timedelta(minutes=10) + timedelta(seconds=second),
            ),
        )
    return ledger


def _capture_supporting(
    adapter: ClosedLoopEvidenceAuthorityAdapter,
    *,
    data_as_of: datetime,
    suffix: str = "",
) -> dict[str, str]:
    refs: dict[str, str] = {}
    for purpose, spec in FIXTURE["attestations"].items():
        record = getattr(adapter, f"capture_{purpose}")(
            principal=_principal(),
            store_ref=FIXTURE["scope"]["store_ref"],
            data_as_of=data_as_of,
            attestation_ref=f"{spec['attestation_ref']}{suffix}",
        )
        refs[purpose] = record.id
    return refs


def _record_bundle(
    service: GovernedClosedLoopEvolutionWorkspace,
    refs: dict[str, str],
    *,
    data_as_of: datetime,
    idempotency_key: str | None = None,
    principal: Principal | None = None,
    agent_run_ref: str | None = None,
) -> dict[str, object]:
    return service.record(
        principal=principal or _principal(),
        store_ref=FIXTURE["scope"]["store_ref"],
        as_of=data_as_of,
        agent_run_ref=agent_run_ref or FIXTURE["agent_run_ref"],
        experiment_evidence_ref=refs["experiment"],
        cost_evidence_ref=refs["cost"],
        outcome_evidence_ref=refs["business_outcome"],
        idempotency_key=idempotency_key or FIXTURE["idempotency_key"],
    )


def _capture_review_authority(
    stack: dict[str, object],
    *,
    bundle_id: str,
    checked_at: datetime,
    actor_id: str,
    reason_code: str,
    attestation_ref: str,
) -> str:
    adapter = stack["adapter"]
    adapter.clock = lambda: checked_at
    authority = adapter.attestation_authorities["review_event"]
    authority.claims = {
        "bundle_id": bundle_id,
        "event_type": "review_requested",
        "reason_code": reason_code,
        "replacement_bundle_id": None,
        "requested_by_actor_id": actor_id,
    }
    return adapter.capture_review_event(
        principal=_principal(f"capture-relay-{attestation_ref}"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=checked_at,
        attestation_ref=attestation_ref,
    ).id


@pytest.fixture(scope="module")
def postgres_gate():
    assert G1_CONTRACT_DATABASE_URL is None, (
        "closed-loop PostgreSQL lifecycle contracts must run in the dedicated "
        "pre-lease G-1 phase"
    )
    target_url = (
        make_url(DATABASE_URL).set(database=g1_database_manager.DATABASE_NAME).render_as_string(hide_password=False)
    )
    saved = {name: os.environ.get(name) for name in SECRET_ENVIRONMENTS}
    secrets = {name: uuid4().hex + uuid4().hex for name in SECRET_ENVIRONMENTS}
    os.environ.update(secrets)
    acquired = False
    provision_receipt = None
    admin_engine = None
    runtime_engine = None
    preflight_receipts = None
    acl_receipts = None
    management_engine = create_engine(DATABASE_URL)
    postgres_admin_url = make_url(DATABASE_URL).set(database="postgres")
    cluster_engine = create_engine(
        postgres_admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        assert _management_state(management_engine) == (
            make_url(DATABASE_URL).database,
            "20260803_0094",
            0,
            0,
            0,
        )
        g1_database_manager.manage("acquire", target_url)
        acquired = True
        provision_receipt = _provision_disposable_postgres_gate(
            cluster_engine=cluster_engine,
            secrets=secrets,
        )
        _upgrade_target(target_url, CLOSED_LOOP_REVISION)
        replay_probe = create_engine(target_url)
        try:
            with replay_probe.connect() as connection:
                initial_upgrade_state = _cloe_catalog_state(connection)
        finally:
            replay_probe.dispose()
        _downgrade_target(target_url, "20260804_0095")
        preflight_receipts = _exercise_upgrade_preflight(target_url)
        acl_receipts = _exercise_acl_restore(target_url)
        replay_probe = create_engine(target_url)
        try:
            with replay_probe.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ("20260804_0095")
                assert (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid=c.relnamespace WHERE n.nspname=current_schema() "
                            "AND c.relname LIKE 'closed_loop_%'"
                        )
                    )
                    == 0
                )
        finally:
            replay_probe.dispose()
        _upgrade_target(target_url, CLOSED_LOOP_REVISION)
        target_probe = create_engine(target_url)
        try:
            with target_probe.connect() as connection:
                assert connection.scalar(text("SELECT current_database()")) == (g1_database_manager.DATABASE_NAME)
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (CLOSED_LOOP_REVISION)
                final_upgrade_state = _cloe_catalog_state(connection)
                assert final_upgrade_state == initial_upgrade_state
        finally:
            target_probe.dispose()
        assert _management_state(management_engine) == (
            make_url(DATABASE_URL).database,
            "20260803_0094",
            0,
            0,
            0,
        )
        g1_database_manager._grant_runtime(target_url)
        runtime_url = (
            make_url(target_url)
            .set(
                username=GENERIC_RUNTIME,
                password=secrets["KJDS_G1_RUNTIME_PASSWORD"],
            )
            .render_as_string(hide_password=False)
        )
        admin_engine = create_engine(target_url, isolation_level="AUTOCOMMIT")
        runtime_engine = create_engine(runtime_url)
        yield {
            "admin": admin_engine,
            "runtime": runtime_engine,
            "target_url": target_url,
            "secrets": secrets,
            "preflight_receipts": preflight_receipts,
            "acl_receipts": acl_receipts,
            "empty_replay": {
                "initial_catalog_sha256": hashlib.sha256(
                    repr(initial_upgrade_state).encode()
                ).hexdigest(),
                "final_catalog_sha256": hashlib.sha256(
                    repr(final_upgrade_state).encode()
                ).hexdigest(),
                "exact": True,
            },
        }
    finally:
        for candidate in (runtime_engine, admin_engine):
            if candidate is not None:
                candidate.dispose()
        try:
            if acquired:
                if provision_receipt is None:
                    g1_database_manager.manage("drop", target_url)
                else:
                    _cleanup_disposable_postgres_gate(
                        cluster_engine=cluster_engine,
                        receipt=provision_receipt,
                    )
                with cluster_engine.connect() as cluster:
                    assert not g1_database_manager._database_exists(cluster)
                    assert tuple(g1_database_manager._existing_roles(cluster)) == (
                        provision_receipt["preexisting_roles"]
                        if provision_receipt is not None
                        else ()
                    )
                    assert (
                        cluster.scalar(
                            text(f"SELECT count(*) FROM {g1_database_manager.LEASE_TABLE} WHERE lease_id=:lease"),
                            {"lease": g1_database_manager.LEASE_ID},
                        )
                        == 0
                    )
            assert _management_state(management_engine) == (
                make_url(DATABASE_URL).database,
                "20260803_0094",
                0,
                0,
                0,
            )
        finally:
            cluster_engine.dispose()
            management_engine.dispose()
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def test_postgres_upgrade_preflight_rejects_each_legacy_reserved_source_without_mutation(
    postgres_gate,
):
    receipts = postgres_gate["preflight_receipts"]["evidence"]
    expected_cases = {
        *(f"source:{source}" for source in CLOSED_LOOP_RESERVED_SOURCES),
        "mixed_sources_with_lineage",
    }
    assert {receipt["case_id"] for receipt in receipts} == expected_cases
    assert all(receipt["sqlstate"] == "55000" for receipt in receipts)
    assert all(receipt["legacy_counts"]["evidence"] >= 1 for receipt in receipts)
    with postgres_gate["admin"].connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            CLOSED_LOOP_REVISION
        )


def test_postgres_upgrade_preflight_rejects_orphan_lineage_without_mutation(
    postgres_gate,
):
    assert postgres_gate["preflight_receipts"]["lineage"] == (
        {
            "case_id": "orphan_closed_loop_lineage",
            "sqlstate": "55000",
            "legacy_counts": {"blobs": 0, "evidence": 0, "lineage": 1},
        },
    )


def test_postgres_upgrade_preflight_serializes_concurrent_reserved_insert(
    postgres_gate,
):
    assert postgres_gate["preflight_receipts"]["race"] == (
        {
            "case_id": "concurrent_reserved_insert",
            "sqlstate": "55000",
            "wait_event_type": "Lock",
        },
    )


def test_postgres_acl_restore_covers_exact_15_cells_and_mixed_baselines(
    postgres_gate,
):
    receipts = postgres_gate["acl_receipts"]
    assert len(receipts["cell_roundtrips"]) == 15
    assert {row["cell_id"] for row in receipts["cell_roundtrips"]} == {
        cell[0] for cell in ACL_CELLS
    }
    assert all(row["restored"] for row in receipts["cell_roundtrips"])
    assert len(receipts["receipt_set_sha256"]) == 64
    assert receipts["public_indirect"] == {
        "baseline_direct": False,
        "baseline_effective": True,
        "introduced": False,
        "restored": True,
    }


def test_postgres_acl_restore_accepts_normalized_null_raw_acl_representation(
    postgres_gate,
):
    assert postgres_gate["acl_receipts"]["null_raw"] == {
        "baseline_raw": None,
        "restored_raw_materialized": True,
        "normalized_equal": True,
    }


def test_postgres_acl_receipts_are_immutable_and_fail_closed_on_drift(
    postgres_gate,
):
    receipt = postgres_gate["acl_receipts"]["receipt_integrity"]
    assert receipt["trigger_names"] == (
        "trg_cloe_acl_receipt_immutable",
        "trg_cloe_acl_receipt_truncate_immutable",
    )
    assert {
        operation: result["trigger_name"]
        for operation, result in receipt["migration_owner_dml"].items()
    } == {
        "insert": "trg_cloe_acl_receipt_immutable",
        "update": "trg_cloe_acl_receipt_immutable",
        "delete": "trg_cloe_acl_receipt_immutable",
        "truncate": "trg_cloe_acl_receipt_truncate_immutable",
    }
    assert all(
        result["sqlstate"] == "23514"
        for result in receipt["migration_owner_dml"].values()
    )
    assert {item["case_id"] for item in receipt["downgrade_blocks"]} == {
        "receipt_hash_drift",
        "missing_receipt",
        "extra_receipt",
    }
    assert receipt["duplicate_constraint"] == "uq_cloe_acl_baseline_cell"
    assert receipt["invariant_constraint"] == "ck_cloe_acl_baseline_receipt"


def test_postgres_acl_downgrade_rejects_projection_and_outside_acl_drift(
    postgres_gate,
):
    receipts = postgres_gate["acl_receipts"]["projection_drift"]
    assert {receipt["case_id"] for receipt in receipts} == {
        "introduced_cell_missing",
        "introduced_cell_grant_option",
        "outside_acl_drift",
    }
    assert all(receipt["sqlstate"] == "55000" for receipt in receipts)


def test_postgres_acl_downgrade_rechecks_all_role_attributes_and_memberships(
    postgres_gate,
):
    receipts = postgres_gate["acl_receipts"]["role_drift"]
    assert len(receipts["attributes"]) == len(ACL_ROLE_ATTRIBUTE_DRIFTS)
    assert len(receipts["memberships"]) == len(ISSUANCE_ROLES) * 2
    assert all(
        receipt["sqlstate"] == "55000"
        for receipt in (*receipts["attributes"], *receipts["memberships"])
    )


def test_generic_runtime_cannot_mutate_or_truncate_acl_receipts(postgres_gate):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    with admin_engine.connect() as admin:
        expected = _acl_surface_state(admin)
    with runtime_engine.connect() as runtime:
        for operation in ("insert", "update", "delete"):
            sqlstate, _ = _receipt_trigger_sqlstate(runtime, operation)
            assert sqlstate == "23514"
        transaction = runtime.begin_nested()
        try:
            runtime.exec_driver_sql("TRUNCATE TABLE closed_loop_acl_baseline_receipts")
        except DBAPIError as error:
            transaction.rollback()
            assert error.orig.sqlstate == "42501"
        else:
            transaction.rollback()
            pytest.fail("generic runtime unexpectedly truncated ACL receipts")
        transaction = runtime.begin_nested()
        try:
            runtime.exec_driver_sql(
                "UPDATE closed_loop_acl_baseline_receipts SET "
                "baseline_direct=true,baseline_grant_option=false,"
                "baseline_effective=true,introduced=false,"
                "baseline_acl_sha256=repeat('a',64),"
                "baseline_outside_acl_sha256=repeat('b',64),"
                "receipt_sha256=repeat('c',64)"
            )
        except DBAPIError as error:
            transaction.rollback()
            assert error.orig.sqlstate == "23514"
            assert "closed-loop ACL baseline receipts are immutable" in str(error)
        else:
            transaction.rollback()
            pytest.fail("generic runtime unexpectedly rewrote ACL receipts")
    with admin_engine.connect() as admin:
        assert _acl_surface_state(admin) == expected


def test_postgres_empty_downgrade_reupgrade_replay_is_exact(postgres_gate):
    receipt = postgres_gate["empty_replay"]
    assert receipt["exact"] is True
    assert receipt["initial_catalog_sha256"] == receipt["final_catalog_sha256"]
    with postgres_gate["admin"].connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            CLOSED_LOOP_REVISION
        )


@pytest.fixture(scope="module")
def valid_postgres_stack(postgres_gate):
    target = make_url(postgres_gate["target_url"])
    secrets = postgres_gate["secrets"]

    def role_engine(role: str, secret_name: str):
        url = target.set(username=role, password=secrets[secret_name])
        return create_engine(url.render_as_string(hide_password=False))

    issuer_engine = role_engine("kjds_cloe_issuance_runtime", "KJDS_G1_CLOE_ISSUER_PASSWORD")
    authority_engines = {
        purpose: role_engine(AUTHORITY_ROLES[purpose], secret_name)
        for purpose, secret_name in AUTHORITY_PASSWORDS.items()
    }
    evidence = EvidenceService(postgres_gate["runtime"])
    scope_grants = _ScopeGrants()
    data_as_of = (datetime.now(UTC) + timedelta(minutes=1)).replace(microsecond=120000)
    ledger = _seed_governed_agent_run(evidence, data_as_of=data_as_of)
    checked_at = data_as_of
    service = GovernedClosedLoopEvolutionWorkspace(
        engine=postgres_gate["runtime"],
        evidence=evidence,
        scope_grants=scope_grants,
        clock=lambda: checked_at,
        handoff_sealing_key=SEALING_KEY,
        agent_run_receipts=ledger,
        event_evidence_issuer=ClosedLoopEventEvidenceIssuerPort(),
    )
    authorities = {
        purpose: _AttestationAuthority(purpose, spec["claims"]) for purpose, spec in FIXTURE["attestations"].items()
    }
    authorities["review_event"] = _AttestationAuthority(
        "review_event",
        {
            "bundle_id": "placeholder-bundle",
            "event_type": "review_requested",
            "reason_code": "scheduled_review",
            "replacement_bundle_id": None,
            "requested_by_actor_id": "review-requester",
        },
    )
    adapter = ClosedLoopEvidenceAuthorityAdapter(
        evidence,
        scope_grants=scope_grants,
        attestation_authorities=authorities,
        issuer_port=ClosedLoopEvidenceIssuerPort(issuer_engine),
        receipt_registrars={
            purpose: ClosedLoopAuthorityReceiptRegistrarPort(engine, purpose=purpose)
            for purpose, engine in authority_engines.items()
        },
        clock=lambda: checked_at,
    )
    try:
        refs = _capture_supporting(adapter, data_as_of=data_as_of)
        first = _record_bundle(service, refs, data_as_of=data_as_of)
        replay = _record_bundle(service, refs, data_as_of=data_as_of)
        yield {
            **postgres_gate,
            "evidence": evidence,
            "scope_grants": scope_grants,
            "ledger": ledger,
            "service": service,
            "adapter": adapter,
            "refs": refs,
            "data_as_of": data_as_of,
            "checked_at": checked_at,
            "first": first,
            "replay": replay,
        }
    finally:
        adapter.dispose()


def _issuer_sqlstate(connection) -> str:
    now = datetime.now(UTC)
    try:
        connection.execute(
            text(
                "SELECT kjds_cloe_issue_event_evidence("
                ":evidence_id,:content,:filename,:source_ref,:effective_at,"
                ":recorded_at,CAST(:metadata AS jsonb))"
            ),
            {
                "evidence_id": "evd_" + "0" * 40,
                "content": b"{}",
                "filename": "cloev_" + "0" * 40 + ".json",
                "source_ref": "closed-loop-evolution://clob_missing/cloev_missing",
                "effective_at": now,
                "recorded_at": now,
                "metadata": "{}",
            },
        )
    except DBAPIError as exc:
        connection.rollback()
        return str(exc.orig.sqlstate)
    connection.rollback()
    raise AssertionError("invalid event fixture unexpectedly issued Evidence")


def _event_counts(admin_engine) -> tuple[int, int]:
    with admin_engine.connect() as connection:
        evidence = connection.scalar(
            text("SELECT count(*) FROM evidence_records WHERE source='governed-closed-loop-evolution'")
        )
        blobs = connection.scalar(text("SELECT count(*) FROM evidence_blobs"))
    return int(evidence), int(blobs)


def _closed_loop_counts(admin_engine) -> dict[str, int]:
    with admin_engine.connect() as connection:
        return {
            name: int(connection.scalar(text(f"SELECT count(*) FROM {table}")))
            for name, table in {
                "bundles": "closed_loop_outcome_bundles",
                "links": "closed_loop_outcome_evidence_links",
                "events": "closed_loop_outcome_events",
                "authority_receipts": "closed_loop_authority_receipts",
                "issuances": "closed_loop_evidence_issuances",
            }.items()
        } | {
            "event_evidence": int(
                connection.scalar(
                    text("SELECT count(*) FROM evidence_records WHERE source='governed-closed-loop-evolution'")
                )
            )
        }


_LIFECYCLE_TABLES = {
    "authority_receipts": ("closed_loop_authority_receipts", "authority_receipt_id"),
    "issuances": ("closed_loop_evidence_issuances", "evidence_id"),
    "evidence_records": ("evidence_records", "id"),
    "evidence_blobs": ("evidence_blobs", "sha256"),
    "bundles": ("closed_loop_outcome_bundles", "bundle_id"),
    "links": ("closed_loop_outcome_evidence_links", "link_id"),
    "events": ("closed_loop_outcome_events", "event_id"),
}


def _lifecycle_surface_state(admin_engine) -> dict[str, object]:
    state: dict[str, object] = {}
    with admin_engine.connect() as connection:
        state["alembic_version"] = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
        for name, (table_name, key_name) in _LIFECYCLE_TABLES.items():
            row = connection.execute(
                text(
                    "SELECT count(*),coalesce(jsonb_agg(to_jsonb(snapshot) "
                    f"ORDER BY snapshot.{key_name})::text,'[]') FROM {table_name} snapshot"
                )
            ).one()
            state[name] = {
                "count": int(row[0]),
                "sha256": hashlib.sha256(str(row[1]).encode()).hexdigest(),
            }
    return state


def _workspace_from_stack(
    stack: dict[str, object],
    *,
    checked_at: datetime,
    event_evidence_issuer=None,
) -> GovernedClosedLoopEvolutionWorkspace:
    return GovernedClosedLoopEvolutionWorkspace(
        engine=stack["runtime"],
        evidence=stack["evidence"],
        scope_grants=stack["scope_grants"],
        clock=lambda: checked_at,
        handoff_sealing_key=SEALING_KEY,
        agent_run_receipts=stack["ledger"],
        event_evidence_issuer=(
            event_evidence_issuer or ClosedLoopEventEvidenceIssuerPort()
        ),
    )


def _orphan_event_evidence_projection(
    *,
    content: bytes,
    metadata: dict[str, object],
    effective_at: datetime,
    recorded_at: datetime,
    suffix: str,
) -> dict[str, object]:
    payload = json.loads(content)
    payload["reason_code"] = f"atomicity_orphan_{suffix}"
    payload["event_sha256"] = _event_hash(
        {
            key: payload[key]
            for key in (
                "bundle_id",
                "event_index",
                "event_type",
                "reason_code",
                "actor_id",
                "request_sha256",
                "previous_event_sha256",
                "occurred_at",
            )
        }
    )
    event_id = _stable_id("cloev", payload["event_sha256"])
    orphan_metadata = deepcopy(metadata)
    orphan_metadata["event_id"] = event_id
    orphan_metadata["event_sha256"] = payload["event_sha256"]
    orphan_content = _canonical_json(payload)
    content_sha256 = hashlib.sha256(orphan_content).hexdigest()
    return {
        "evidence_id": _stable_id("evd", content_sha256),
        "content": orphan_content,
        "filename": f"{event_id}.json",
        "source_ref": f"closed-loop-evolution://{payload['bundle_id']}/{event_id}",
        "effective_at": effective_at,
        "recorded_at": recorded_at,
        "metadata": orphan_metadata,
    }


class _DeferredOrphanInjectingEventIssuer:
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.calls = 0
        self.delegate = ClosedLoopEventEvidenceIssuerPort()

    def issue_event_evidence(self, **parameters) -> str:
        returned = self.delegate.issue_event_evidence(**parameters)
        orphan = _orphan_event_evidence_projection(
            content=parameters["content"],
            metadata=parameters["metadata"],
            effective_at=parameters["effective_at"],
            recorded_at=parameters["recorded_at"],
            suffix=self.suffix,
        )
        self.delegate.issue_event_evidence(session=parameters["session"], **orphan)
        self.calls += 1
        return returned


def _issue_event_projection(connection, projection: dict[str, object]) -> str:
    return str(
        connection.scalar(
            text(
                "SELECT kjds_cloe_issue_event_evidence("
                ":evidence_id,:content,:filename,:source_ref,:effective_at,"
                ":recorded_at,CAST(:metadata AS jsonb))"
            ),
            {
                **projection,
                "metadata": json.dumps(
                    projection["metadata"],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        )
    )


def _causal_residue_counts(admin_engine) -> dict[str, int]:
    with admin_engine.connect() as connection:
        return {
            name: int(connection.scalar(text(f"SELECT count(*) FROM {table}")))
            for name, table in {
                "authority_receipts": "closed_loop_authority_receipts",
                "issuances": "closed_loop_evidence_issuances",
                "evidence_records": "evidence_records",
                "evidence_blobs": "evidence_blobs",
                "bundles": "closed_loop_outcome_bundles",
                "links": "closed_loop_outcome_evidence_links",
                "events": "closed_loop_outcome_events",
            }.items()
        }


def _decimal_issuance_attack(
    admin_engine,
    *,
    evidence_id: str,
    field: str,
    value: str,
    suffix: str,
) -> dict[str, object]:
    with admin_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT ev.*,blob.content_bytes,receipt.* "
                    "FROM evidence_records ev "
                    "JOIN evidence_blobs blob ON blob.sha256=ev.blob_sha256 "
                    "JOIN closed_loop_evidence_issuances issuance "
                    "ON issuance.evidence_id=ev.id "
                    "JOIN closed_loop_authority_receipts receipt "
                    "ON receipt.authority_receipt_id=issuance.authority_receipt_id "
                    "WHERE ev.id=:evidence_id"
                ),
                {"evidence_id": evidence_id},
            )
            .mappings()
            .one()
        )
    payload = json.loads(bytes(row["content_bytes"]))
    payload["authority_receipt_id"] = f"cloer_decimal_{suffix}"
    payload["attestation_ref"] = f"decimal-{suffix}"
    claims = deepcopy(payload["claims"])
    claims[field] = value
    claims_sha256 = _closed_loop_claims_sha256(claims)
    payload["claims"] = claims
    payload["claims_sha256"] = claims_sha256
    attestation_envelope = {
        key: item
        for key, item in payload.items()
        if key
        not in {
            "attestation_sha256",
            "attestation_signature_sha256",
            "payload_status",
            "contains_customer_data",
            "external_write_allowed",
        }
    }
    attestation_sha256 = hashlib.sha256(
        _canonical_json(attestation_envelope)
    ).hexdigest()
    signature_sha256 = hashlib.sha256(
        f"signature:{attestation_sha256}".encode()
    ).hexdigest()
    payload["attestation_sha256"] = attestation_sha256
    payload["attestation_signature_sha256"] = signature_sha256
    content = _canonical_json(payload)
    content_sha256 = hashlib.sha256(content).hexdigest()
    metadata = deepcopy(row["metadata_json"])
    metadata.update(
        {
            "closed_loop_claims": claims,
            "closed_loop_claims_sha256": claims_sha256,
            "closed_loop_attestation_ref": payload["attestation_ref"],
            "closed_loop_authority_receipt_id": payload[
                "authority_receipt_id"
            ],
            "closed_loop_attestation_sha256": attestation_sha256,
            "closed_loop_attestation_signature_sha256": signature_sha256,
        }
    )
    scope_binding = metadata["closed_loop_scope_binding_sha256"]
    source_ref = (
        f"{row['source']}://{scope_binding}/{claims_sha256}/{content_sha256}"
    )
    metadata_sha256 = _closed_loop_postgres_jsonb_sha256(metadata)
    derived = {
        "authority_receipt_id": payload["authority_receipt_id"],
        "content_sha256": content_sha256,
        "metadata_sha256": metadata_sha256,
        "purpose": payload["purpose"],
        "source": row["source"],
        "source_ref": source_ref,
    }
    new_evidence_id = "evd_" + hashlib.sha256(
        json.dumps(
            derived,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:40]
    receipt = {
        "authority_receipt_id": payload["authority_receipt_id"],
        "purpose": payload["purpose"],
        "evidence_id": new_evidence_id,
        "content_sha256": content_sha256,
        "metadata_sha256": metadata_sha256,
        "source": row["source"],
        "source_ref": source_ref,
        "attestation_sha256": attestation_sha256,
        "attestation_signature_sha256": signature_sha256,
        "issuer_id": payload["issuer_id"],
        "issuer_contract_id": payload["issuer_contract_id"],
        "issuer_contract_version": payload["issuer_contract_version"],
        "issuer_contract_sha256": payload["issuer_contract_sha256"],
        "schema_sha256": payload["schema_sha256"],
        "issuer_actor_id": payload["issuer_actor_id"],
        **payload["exact_scope"],
        "data_as_of": payload["data_as_of"],
        "effective_at": payload["effective_at"],
        "effective_until": payload["effective_until"],
        "recorded_at": payload["recorded_at"],
        "review_due_at": payload["review_due_at"],
    }
    return {
        "receipt": receipt,
        "evidence_id": new_evidence_id,
        "content": content,
        "filename": f"{payload['purpose']}-{content_sha256}.json",
        "source": row["source"],
        "source_ref": source_ref,
        "effective_at": row["effective_at"],
        "effective_until": row["effective_until"],
        "metadata": metadata,
        "attestation_sha256": attestation_sha256,
        "attestation_signature_sha256": signature_sha256,
        "purpose": payload["purpose"],
    }


def _supporting_attack_projection(
    admin_engine,
    evidence_id: str,
    *,
    mutation: str,
) -> dict[str, object]:
    with admin_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT ev.id AS evidence_id,ev.source,ev.source_ref,"
                    "ev.effective_at,ev.effective_until,ev.metadata_json,"
                    "blob.content_bytes,issuance.authority_receipt_id,"
                    "issuance.attestation_sha256,"
                    "issuance.attestation_signature_sha256,link.*,"
                    "root.request_json,root.bundle_json "
                    "FROM evidence_records ev "
                    "JOIN evidence_blobs blob ON blob.sha256=ev.blob_sha256 "
                    "JOIN closed_loop_evidence_issuances issuance "
                    "ON issuance.evidence_id=ev.id "
                    "JOIN closed_loop_outcome_evidence_links link "
                    "ON link.evidence_id=ev.id "
                    "JOIN closed_loop_outcome_bundles root "
                    "ON root.bundle_id=link.bundle_id "
                    "WHERE ev.id=:evidence_id AND link.purpose='experiment'"
                ),
                {"evidence_id": evidence_id},
            )
            .mappings()
            .one()
        )
    payload = json.loads(bytes(row["content_bytes"]))
    claims = deepcopy(payload["claims"])
    if mutation == "causal_claim_allowed":
        claims["causal_claim_allowed"] = True
    elif mutation == "claims_sample_string":
        payload["authority_receipt_id"] = "cloer_jointly_resigned_sample_type"
        claims["sample_size"] = str(claims["sample_size"])
    elif mutation == "claims_time_z":
        payload["authority_receipt_id"] = "cloer_jointly_resigned_time_z"
        claims["window_start"] = claims["window_start"].replace("+00:00", "Z")
    elif mutation == "claims_decimal_leading_zero":
        payload["authority_receipt_id"] = "cloer_jointly_resigned_decimal_text"
        claims["confidence_level_decimal"] = (
            "0" + claims["confidence_level_decimal"]
        )
    elif mutation == "exact_scope_null":
        payload["authority_receipt_id"] = "cloer_jointly_resigned_scope_null"
        payload["exact_scope"]["entity_ref"] = None
    elif mutation == "authority_receipt_id":
        payload["authority_receipt_id"] = "cloer_jointly_resigned_receipt_drift"
    elif mutation == "authority_contract":
        payload.update(
            {
                "authority_receipt_id": "cloer_jointly_resigned_authority_drift",
                "issuer_id": "forged-closed-loop-authority",
                "issuer_contract_id": "forged-closed-loop-authority-v9",
                "issuer_contract_version": "9.9.9",
                "issuer_contract_sha256": "1" * 64,
                "schema_sha256": "2" * 64,
            }
        )
    else:
        raise AssertionError(f"unknown supporting attack mutation: {mutation}")
    claims_sha256 = _closed_loop_claims_sha256(claims)
    payload["claims"] = claims
    payload["claims_sha256"] = claims_sha256
    attestation_envelope = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "attestation_sha256",
            "attestation_signature_sha256",
            "payload_status",
            "contains_customer_data",
            "external_write_allowed",
        }
    }
    attestation_sha256 = hashlib.sha256(
        _canonical_json(attestation_envelope)
    ).hexdigest()
    attestation_signature_sha256 = hashlib.sha256(
        f"signature:{attestation_sha256}".encode()
    ).hexdigest()
    payload["attestation_sha256"] = attestation_sha256
    payload["attestation_signature_sha256"] = attestation_signature_sha256
    content = _canonical_json(payload)
    content_sha256 = hashlib.sha256(content).hexdigest()
    evidence_id = _stable_id("evd", content_sha256)
    metadata = deepcopy(row["metadata_json"])
    metadata["closed_loop_claims"] = claims
    metadata["closed_loop_claims_sha256"] = claims_sha256
    metadata["closed_loop_authority_receipt_id"] = payload["authority_receipt_id"]
    metadata["closed_loop_attestation_sha256"] = attestation_sha256
    metadata["closed_loop_attestation_signature_sha256"] = (
        attestation_signature_sha256
    )
    metadata["closed_loop_issuer_id"] = payload["issuer_id"]
    metadata["closed_loop_issuer_contract_id"] = payload["issuer_contract_id"]
    metadata["closed_loop_issuer_contract_version"] = payload[
        "issuer_contract_version"
    ]
    metadata["closed_loop_issuer_contract_sha256"] = payload[
        "issuer_contract_sha256"
    ]
    metadata["closed_loop_schema_sha256"] = payload["schema_sha256"]
    source_ref = f"{row['source']}://{metadata['closed_loop_scope_binding_sha256']}/{claims_sha256}/{content_sha256}"
    scope = {
        "tenant_ref": row["tenant_ref"],
        "entity_ref": row["entity_ref"],
        "store_ref": row["store_ref"],
        "scope_grant_authority_sha256": row["scope_grant_authority_sha256"],
    }
    link_sha256 = _link_hash(
        bundle_id=row["bundle_id"],
        purpose=row["purpose"],
        evidence_id=evidence_id,
        evidence_sha256=content_sha256,
        claims_sha256=claims_sha256,
        issuer_actor_id=row["issuer_actor_id"],
        scope=scope,
    )
    bundle_json = deepcopy(row["bundle_json"])
    bundle_json["supporting"]["experiment"].update(
        {
            "evidence_id": evidence_id,
            "evidence_sha256": content_sha256,
            "claims_sha256": claims_sha256,
        }
    )
    bundle_json["experiment_evidence_ref"] = evidence_id
    request_json = deepcopy(row["request_json"])
    request_json["experiment_evidence_ref"] = evidence_id
    return {
        **dict(row),
        "original_evidence_id": row["evidence_id"],
        "evidence_id": evidence_id,
        "payload": payload,
        "content": content,
        "content_sha256": content_sha256,
        "attestation_sha256": attestation_sha256,
        "attestation_signature_sha256": attestation_signature_sha256,
        "claims_sha256": claims_sha256,
        "metadata": metadata,
        "metadata_sha256": _closed_loop_postgres_jsonb_sha256(metadata),
        "source_ref": source_ref,
        "link_sha256": link_sha256,
        "new_link_id": _stable_id("clol", link_sha256),
        "request_json": request_json,
        "request_sha256": hashlib.sha256(_canonical_json(request_json)).hexdigest(),
        "bundle_json": bundle_json,
        "bundle_sha256": _closed_loop_postgres_jsonb_sha256(bundle_json),
    }


def _causal_attack_projection(admin_engine, evidence_id: str) -> dict[str, object]:
    return _supporting_attack_projection(
        admin_engine,
        evidence_id,
        mutation="causal_claim_allowed",
    )


def _install_causal_attack_projection(connection, attack) -> None:
    connection.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
    connection.exec_driver_sql("ALTER TABLE evidence_records DISABLE TRIGGER trg_cloe_evidence_immutable")
    connection.execute(
        text(
            "INSERT INTO evidence_blobs"
            "(sha256,byte_size,content_bytes,created_at) "
            "VALUES (:sha,:size,:content,statement_timestamp())"
        ),
        {
            "sha": attack["content_sha256"],
            "size": len(attack["content"]),
            "content": attack["content"],
        },
    )
    connection.execute(
        text(
            "INSERT INTO evidence_records("
            "id,blob_sha256,filename,content_type,source,source_ref,grade,"
            "effective_at,effective_until,recorded_at,created_by,metadata_json) "
            "VALUES (:evidence_id,:sha,:filename,'application/json',:source,"
            ":source_ref,'A',:effective_at,:effective_until,"
            ":recorded_at,:created_by,CAST(:metadata AS jsonb))"
        ),
        {
            "evidence_id": attack["evidence_id"],
            "sha": attack["content_sha256"],
            "filename": f"experiment-{attack['content_sha256']}.json",
            "source": attack["source"],
            "source_ref": attack["source_ref"],
            "effective_at": attack["effective_at"],
            "effective_until": attack["effective_until"],
            "recorded_at": attack["evidence_recorded_at"],
            "created_by": attack["issuer_actor_id"],
            "metadata": json.dumps(attack["metadata"], sort_keys=True),
        },
    )
    connection.exec_driver_sql("ALTER TABLE evidence_records ENABLE TRIGGER trg_cloe_evidence_immutable")


def _install_jointly_resigned_authority_projection(connection, attack) -> None:
    _install_causal_attack_projection(connection, attack)
    payload = attack["payload"]
    connection.execute(
        text(
            "INSERT INTO closed_loop_authority_receipts("
            "authority_receipt_id,purpose,evidence_id,content_sha256,"
            "metadata_sha256,source,source_ref,attestation_sha256,"
            "attestation_signature_sha256,issuer_id,issuer_contract_id,"
            "issuer_contract_version,issuer_contract_sha256,schema_sha256,"
            "issuer_actor_id,tenant_ref,entity_ref,store_ref,"
            "scope_grant_authority_sha256,data_as_of,effective_at,"
            "effective_until,recorded_at,review_due_at) VALUES ("
            ":receipt_id,:purpose,:evidence_id,:content_sha,:metadata_sha,"
            ":source,:source_ref,:attestation_sha,:signature_sha,:issuer_id,"
            ":issuer_contract_id,:issuer_contract_version,"
            ":issuer_contract_sha,:schema_sha,:issuer_actor_id,:tenant_ref,"
            ":entity_ref,:store_ref,:authority,:data_as_of,:effective_at,"
            ":effective_until,:recorded_at,:review_due_at)"
        ),
        {
            "receipt_id": payload["authority_receipt_id"],
            "purpose": payload["purpose"],
            "evidence_id": attack["evidence_id"],
            "content_sha": attack["content_sha256"],
            "metadata_sha": attack["metadata_sha256"],
            "source": attack["source"],
            "source_ref": attack["source_ref"],
            "attestation_sha": attack["attestation_sha256"],
            "signature_sha": attack["attestation_signature_sha256"],
            "issuer_id": payload["issuer_id"],
            "issuer_contract_id": payload["issuer_contract_id"],
            "issuer_contract_version": payload["issuer_contract_version"],
            "issuer_contract_sha": payload["issuer_contract_sha256"],
            "schema_sha": payload["schema_sha256"],
            "issuer_actor_id": payload["issuer_actor_id"],
            "tenant_ref": attack["tenant_ref"],
            "entity_ref": attack["entity_ref"],
            "store_ref": attack["store_ref"],
            "authority": attack["scope_grant_authority_sha256"],
            "data_as_of": payload["data_as_of"],
            "effective_at": payload["effective_at"],
            "effective_until": payload["effective_until"],
            "recorded_at": payload["recorded_at"],
            "review_due_at": payload["review_due_at"],
        },
    )
    connection.execute(
        text(
            "INSERT INTO closed_loop_evidence_issuances("
            "evidence_id,authority_receipt_id,content_sha256,source,source_ref,"
            "attestation_sha256,attestation_signature_sha256) VALUES ("
            ":evidence_id,:receipt_id,:content_sha,:source,:source_ref,"
            ":attestation_sha,:signature_sha)"
        ),
        {
            "evidence_id": attack["evidence_id"],
            "receipt_id": payload["authority_receipt_id"],
            "content_sha": attack["content_sha256"],
            "source": attack["source"],
            "source_ref": attack["source_ref"],
            "attestation_sha": attack["attestation_sha256"],
            "signature_sha": attack["attestation_signature_sha256"],
        },
    )


def _insert_causal_attack_link(connection, attack) -> None:
    connection.execute(
        text(
            "INSERT INTO closed_loop_outcome_evidence_links("
            "link_id,bundle_id,tenant_ref,entity_ref,store_ref,"
            "scope_grant_authority_sha256,purpose,evidence_id,evidence_sha256,"
            "evidence_source,evidence_source_ref,evidence_grade,"
            "evidence_effective_at,evidence_effective_until,"
            "evidence_recorded_at,evidence_review_due_at,issuer_actor_id,"
            "claims_sha256,link_sha256) VALUES ("
            ":link_id,:bundle_id,:tenant_ref,:entity_ref,:store_ref,"
            ":authority,:purpose,:evidence_id,:evidence_sha256,"
            ":evidence_source,:evidence_source_ref,:evidence_grade,"
            ":effective_at,:effective_until,:recorded_at,:review_due_at,"
            ":issuer_actor_id,:claims_sha256,:link_sha256)"
        ),
        {
            "link_id": attack["new_link_id"],
            "bundle_id": attack["bundle_id"],
            "tenant_ref": attack["tenant_ref"],
            "entity_ref": attack["entity_ref"],
            "store_ref": attack["store_ref"],
            "authority": attack["scope_grant_authority_sha256"],
            "purpose": attack["purpose"],
            "evidence_id": attack["evidence_id"],
            "evidence_sha256": attack["content_sha256"],
            "evidence_source": attack["evidence_source"],
            "evidence_source_ref": attack["source_ref"],
            "evidence_grade": attack["evidence_grade"],
            "effective_at": attack["evidence_effective_at"],
            "effective_until": attack["evidence_effective_until"],
            "recorded_at": attack["evidence_recorded_at"],
            "review_due_at": attack["evidence_review_due_at"],
            "issuer_actor_id": attack["issuer_actor_id"],
            "claims_sha256": attack["claims_sha256"],
            "link_sha256": attack["link_sha256"],
        },
    )


def _review_authority_attack_projection(
    connection,
    event_id: str,
    *,
    mutation: str = "authority_contract",
) -> dict[str, object]:
    row = (
        connection.execute(
            text(
                "SELECT event.*,review_ev.metadata_json AS review_metadata_json,"
                "review_ev.source AS review_source,"
                "review_ev.effective_at AS review_effective_at,"
                "review_ev.effective_until AS review_effective_until,"
                "review_ev.recorded_at AS review_recorded_at,"
                "review_ev.created_by AS review_created_by,"
                "review_blob.content_bytes AS review_content_bytes,"
                "issuance.authority_receipt_id AS authority_receipt_id "
                "FROM closed_loop_outcome_events event "
                "JOIN evidence_records review_ev "
                "ON review_ev.id=event.review_evidence_id "
                "JOIN evidence_blobs review_blob "
                "ON review_blob.sha256=review_ev.blob_sha256 "
                "JOIN closed_loop_evidence_issuances issuance "
                "ON issuance.evidence_id=review_ev.id "
                "WHERE event.event_id=:event_id"
            ),
            {"event_id": event_id},
        )
        .mappings()
        .one()
    )
    payload = json.loads(bytes(row["review_content_bytes"]))
    if mutation == "authority_contract":
        payload.update(
            {
                "issuer_id": "forged-review-authority",
                "issuer_contract_id": "forged-review-authority-v9",
                "issuer_contract_version": "9.9.9",
                "issuer_contract_sha256": "3" * 64,
                "schema_sha256": "4" * 64,
            }
        )
    elif mutation == "exact_scope_null":
        payload["exact_scope"]["entity_ref"] = None
    elif mutation == "claims_bundle_null":
        payload["claims"]["bundle_id"] = None
    elif mutation == "claims_requester_number":
        payload["claims"]["requested_by_actor_id"] = 7
    elif mutation == "data_as_of_z":
        payload["data_as_of"] = payload["data_as_of"].replace("+00:00", "Z")
    else:
        raise AssertionError(f"unknown review attack mutation: {mutation}")
    payload["claims_sha256"] = _closed_loop_claims_sha256(payload["claims"])
    attestation_envelope = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "attestation_sha256",
            "attestation_signature_sha256",
            "payload_status",
            "contains_customer_data",
            "external_write_allowed",
        }
    }
    attestation_sha256 = hashlib.sha256(
        _canonical_json(attestation_envelope)
    ).hexdigest()
    signature_sha256 = hashlib.sha256(
        f"signature:{attestation_sha256}".encode()
    ).hexdigest()
    payload["attestation_sha256"] = attestation_sha256
    payload["attestation_signature_sha256"] = signature_sha256
    content = _canonical_json(payload)
    content_sha256 = hashlib.sha256(content).hexdigest()
    metadata = deepcopy(row["review_metadata_json"])
    metadata.update(
        {
            "closed_loop_claims": payload["claims"],
            "closed_loop_claims_sha256": payload["claims_sha256"],
            "closed_loop_attestation_sha256": attestation_sha256,
            "closed_loop_attestation_signature_sha256": signature_sha256,
            "closed_loop_issuer_id": payload["issuer_id"],
            "closed_loop_issuer_contract_id": payload["issuer_contract_id"],
            "closed_loop_issuer_contract_version": payload[
                "issuer_contract_version"
            ],
            "closed_loop_issuer_contract_sha256": payload[
                "issuer_contract_sha256"
            ],
            "closed_loop_schema_sha256": payload["schema_sha256"],
        }
    )
    source_ref = (
        f"{row['review_source']}://"
        f"{metadata['closed_loop_scope_binding_sha256']}/"
        f"{payload['claims_sha256']}/{content_sha256}"
    )
    return {
        **dict(row),
        "payload": payload,
        "content": content,
        "content_sha256": content_sha256,
        "metadata": metadata,
        "metadata_sha256": _closed_loop_postgres_jsonb_sha256(metadata),
        "source_ref": source_ref,
        "attestation_sha256": attestation_sha256,
        "signature_sha256": signature_sha256,
    }


def test_fresh_0096_event_issuer_functions_are_rendered_and_current(postgres_gate):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    with admin_engine.connect() as admin:
        assert admin.scalar(text("SELECT version_num FROM alembic_version")) == (CLOSED_LOOP_REVISION)
        definitions = admin.scalars(
            text(
                "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'kjds_cloe_%'"
            )
        ).all()
        assert definitions
        assert all("{{" not in definition for definition in definitions)
        assert all("(0, 159)" not in definition for definition in definitions)
    with runtime_engine.connect() as runtime:
        assert _issuer_sqlstate(runtime) == "23514"


@pytest.mark.parametrize(
    ("drift", "restore"),
    (
        ("NOLOGIN", "LOGIN"),
        ("INHERIT", "NOINHERIT"),
        ("SUPERUSER", "NOSUPERUSER"),
        ("CREATEROLE", "NOCREATEROLE"),
        ("CREATEDB", "NOCREATEDB"),
        ("REPLICATION", "NOREPLICATION"),
        ("NOBYPASSRLS", "BYPASSRLS"),
    ),
)
def test_event_issuer_rejects_generic_runtime_attribute_drift(postgres_gate, drift, restore):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    before = _event_counts(admin_engine)
    with runtime_engine.connect() as runtime, admin_engine.connect() as admin:
        assert _issuer_sqlstate(runtime) == "23514"
        admin.exec_driver_sql(f"ALTER ROLE {GENERIC_RUNTIME} {drift}")
        try:
            assert _issuer_sqlstate(runtime) == "42501"
            assert _event_counts(admin_engine) == before
        finally:
            admin.exec_driver_sql(f"ALTER ROLE {GENERIC_RUNTIME} {restore}")
        assert _issuer_sqlstate(runtime) == "23514"


@pytest.mark.parametrize(
    ("drift", "restore"),
    (
        ("LOGIN", "NOLOGIN"),
        ("INHERIT", "NOINHERIT"),
        ("SUPERUSER", "NOSUPERUSER"),
        ("CREATEROLE", "NOCREATEROLE"),
        ("CREATEDB", "NOCREATEDB"),
        ("REPLICATION", "NOREPLICATION"),
        ("NOBYPASSRLS", "BYPASSRLS"),
    ),
)
def test_event_issuer_rejects_owner_attribute_drift(postgres_gate, drift, restore):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    before = _event_counts(admin_engine)
    with runtime_engine.connect() as runtime, admin_engine.connect() as admin:
        assert _issuer_sqlstate(runtime) == "23514"
        admin.exec_driver_sql(f"ALTER ROLE {EVENT_OWNER} {drift}")
        try:
            assert _issuer_sqlstate(runtime) == "42501"
            assert _event_counts(admin_engine) == before
        finally:
            admin.exec_driver_sql(f"ALTER ROLE {EVENT_OWNER} {restore}")
        assert _issuer_sqlstate(runtime) == "23514"


@pytest.mark.parametrize("issuance_role", ISSUANCE_ROLES)
@pytest.mark.parametrize("direction", ("inbound", "outbound"))
def test_event_issuer_rejects_bidirectional_issuance_membership_drift(postgres_gate, issuance_role, direction):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    granted, member = (issuance_role, GENERIC_RUNTIME) if direction == "inbound" else (GENERIC_RUNTIME, issuance_role)
    before = _event_counts(admin_engine)
    with runtime_engine.connect() as runtime, admin_engine.connect() as admin:
        admin.exec_driver_sql(f"GRANT {granted} TO {member}")
        try:
            assert _issuer_sqlstate(runtime) == "42501"
            assert _event_counts(admin_engine) == before
        finally:
            admin.exec_driver_sql(f"REVOKE {granted} FROM {member}")
        assert _issuer_sqlstate(runtime) == "23514"


def test_set_role_event_owner_cannot_directly_insert_reserved_evidence(postgres_gate):
    admin_engine = postgres_gate["admin"]
    runtime_engine = postgres_gate["runtime"]
    before = _event_counts(admin_engine)
    content = b"{}"
    content_sha = hashlib.sha256(content).hexdigest()
    with admin_engine.connect() as admin:
        admin.exec_driver_sql(f"GRANT {EVENT_OWNER} TO {GENERIC_RUNTIME}")
    try:
        with runtime_engine.connect() as runtime:
            runtime.exec_driver_sql(f"SET ROLE {EVENT_OWNER}")
            try:
                runtime.execute(
                    text(
                        "INSERT INTO evidence_blobs"
                        "(sha256,byte_size,content_bytes,created_at) "
                        "VALUES (:sha,:size,:content,statement_timestamp())"
                    ),
                    {"sha": content_sha, "size": len(content), "content": content},
                )
                runtime.execute(
                    text(
                        "INSERT INTO evidence_records"
                        "(id,blob_sha256,filename,content_type,source,source_ref,grade,"
                        "effective_at,recorded_at,created_by,metadata_json) VALUES "
                        "(:id,:sha,'event.json','application/json',"
                        "'governed-closed-loop-evolution','closed-loop-evolution://x/y',"
                        "'D',statement_timestamp(),statement_timestamp(),'actor',"
                        "CAST(:metadata AS jsonb))"
                    ),
                    {
                        "id": "evd_" + content_sha[:40],
                        "sha": content_sha,
                        "metadata": json.dumps({}),
                    },
                )
            except DBAPIError as exc:
                assert str(exc.orig.sqlstate) == "42501"
                runtime.rollback()
            else:
                runtime.rollback()
                raise AssertionError("SET ROLE bypass inserted reserved Evidence")
            finally:
                runtime.exec_driver_sql("RESET ROLE")
    finally:
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(f"REVOKE {EVENT_OWNER} FROM {GENERIC_RUNTIME}")
    assert _event_counts(admin_engine) == before


def test_postgres_workspace_record_replay_and_review_lifecycle(valid_postgres_stack):
    service = valid_postgres_stack["service"]
    adapter = valid_postgres_stack["adapter"]
    first = valid_postgres_stack["first"]
    replay = valid_postgres_stack["replay"]

    assert first["status"] == "current"
    assert replay["idempotent"] is True
    assert _closed_loop_counts(valid_postgres_stack["admin"]) == {
        "bundles": 1,
        "links": 3,
        "events": 1,
        "authority_receipts": 3,
        "issuances": 3,
        "event_evidence": 1,
    }

    review_time = valid_postgres_stack["checked_at"] + timedelta(minutes=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": first["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review = adapter.capture_review_event(
        principal=_principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="review-postgres-positive",
    )
    result = service.append_review_event(
        principal=_principal("review-requester"),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=str(first["bundle_id"]),
        event_type="review_requested",
        reason_code="scheduled_review",
        review_evidence_ref=review.id,
        idempotency_key="review-postgres-positive",
    )

    assert result["status"] == "review_due"
    assert result["candidate_created"] is False
    assert result["transition_allowed"] is False
    assert result["promotion_allowed"] is False
    assert _closed_loop_counts(valid_postgres_stack["admin"]) == {
        "bundles": 1,
        "links": 3,
        "events": 2,
        "authority_receipts": 4,
        "issuances": 4,
        "event_evidence": 2,
    }


def test_postgres_exact_numeric_boundary_first_write_and_replay_are_equivalent(
    valid_postgres_stack,
):
    adapter = valid_postgres_stack["adapter"]
    authorities = adapter.attestation_authorities
    original_experiment = deepcopy(authorities["experiment"].claims)
    original_outcome = deepcopy(authorities["business_outcome"].claims)
    try:
        authorities["experiment"].claims["confidence_level_decimal"] = (
            "1.0000000"
        )
        authorities["business_outcome"].claims.update(
            {
                "confidence_level_decimal": "1.0000000",
                "value_decimal": "999999999999999999.9999999999990",
            }
        )
        refs = _capture_supporting(
            adapter,
            data_as_of=valid_postgres_stack["data_as_of"],
            suffix="-numeric-boundary",
        )
        first = _record_bundle(
            valid_postgres_stack["service"],
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key="postgres-numeric-boundary",
        )
        replay = _record_bundle(
            valid_postgres_stack["service"],
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key="postgres-numeric-boundary",
        )
    finally:
        authorities["experiment"].claims = original_experiment
        authorities["business_outcome"].claims = original_outcome

    assert first["experiment"]["confidence_level_decimal"] == "1"
    assert replay["business_outcome"]["confidence_level_decimal"] == "1"
    assert replay["business_outcome"]["value_decimal"] == (
        "999999999999999999.999999999999"
    )
    assert {**first, "idempotent": True} == replay


@pytest.mark.parametrize(
    ("purpose", "field", "value", "suffix"),
    (
        ("experiment", "confidence_level_decimal", "0.9500001", "experiment"),
        (
            "business_outcome",
            "confidence_level_decimal",
            "0.9500001",
            "outcome-confidence",
        ),
        (
            "business_outcome",
            "value_decimal",
            "42.5000000000001",
            "outcome-scale",
        ),
        (
            "business_outcome",
            "value_decimal",
            "1000000000000000000",
            "outcome-overflow",
        ),
    ),
)
def test_postgres_authority_issuer_rejects_unrepresentable_decimals_without_residue(
    valid_postgres_stack,
    request,
    purpose,
    field,
    value,
    suffix,
):
    attack = _decimal_issuance_attack(
        valid_postgres_stack["admin"],
        evidence_id=valid_postgres_stack["refs"][purpose],
        field=field,
        value=value,
        suffix=suffix,
    )
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)
    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(
                f"SET SESSION AUTHORIZATION {AUTHORITY_ROLES[purpose]}"
            )
            assert connection.scalar(
                text(
                    "SELECT kjds_cloe_register_authority_receipt("
                    "CAST(:receipt AS jsonb))"
                ),
                {
                    "receipt": json.dumps(
                        attack["receipt"],
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                },
            ) == attack["receipt"]["authority_receipt_id"]
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")
            connection.exec_driver_sql(
                "SET SESSION AUTHORIZATION kjds_cloe_issuance_runtime"
            )
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text(
                        "SELECT kjds_cloe_issue_evidence("
                        ":receipt_id,:evidence_id,:content,:filename,:source,"
                        ":source_ref,:effective_at,:effective_until,"
                        "CAST(:metadata AS jsonb),:attestation_sha256,"
                        ":signature_sha256)"
                    ),
                    {
                        "receipt_id": attack["receipt"]["authority_receipt_id"],
                        "evidence_id": attack["evidence_id"],
                        "content": attack["content"],
                        "filename": attack["filename"],
                        "source": attack["source"],
                        "source_ref": attack["source_ref"],
                        "effective_at": attack["effective_at"],
                        "effective_until": attack["effective_until"],
                        "metadata": json.dumps(
                            attack["metadata"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "attestation_sha256": attack["attestation_sha256"],
                        "signature_sha256": attack[
                            "attestation_signature_sha256"
                        ],
                    },
                )
            assert str(error.value.orig.sqlstate) == "23514"
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_record_rolls_back_after_deferred_event_evidence_failure(
    valid_postgres_stack,
):
    checked_at = valid_postgres_stack["checked_at"] + timedelta(minutes=2)
    valid_postgres_stack["adapter"].clock = lambda: checked_at
    refs = _capture_supporting(
        valid_postgres_stack["adapter"],
        data_as_of=valid_postgres_stack["data_as_of"],
        suffix="-record-atomicity",
    )
    issuer = _DeferredOrphanInjectingEventIssuer("record")
    service = _workspace_from_stack(
        valid_postgres_stack,
        checked_at=checked_at,
        event_evidence_issuer=issuer,
    )
    before = _lifecycle_surface_state(valid_postgres_stack["admin"])

    with pytest.raises(DBAPIError) as error:
        _record_bundle(
            service,
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key="postgres-record-deferred-rollback",
        )

    assert str(error.value.orig.sqlstate) == "23514"
    assert "closed-loop event Evidence has no exact ledger event" in str(error.value)
    assert issuer.calls == 1
    assert _lifecycle_surface_state(valid_postgres_stack["admin"]) == before


def test_postgres_review_rolls_back_after_deferred_event_evidence_failure(
    valid_postgres_stack,
):
    checked_at = valid_postgres_stack["checked_at"] + timedelta(minutes=3)
    bundle_id = str(valid_postgres_stack["first"]["bundle_id"])
    review_evidence_id = _capture_review_authority(
        valid_postgres_stack,
        bundle_id=bundle_id,
        checked_at=checked_at,
        actor_id="review-atomicity-requester",
        reason_code="atomicity_review",
        attestation_ref="review-postgres-atomicity",
    )
    issuer = _DeferredOrphanInjectingEventIssuer("review")
    service = _workspace_from_stack(
        valid_postgres_stack,
        checked_at=checked_at,
        event_evidence_issuer=issuer,
    )
    before = _lifecycle_surface_state(valid_postgres_stack["admin"])

    with pytest.raises(DBAPIError) as error:
        service.append_review_event(
            principal=_principal("review-atomicity-requester"),
            store_ref=FIXTURE["scope"]["store_ref"],
            bundle_id=bundle_id,
            event_type="review_requested",
            reason_code="atomicity_review",
            review_evidence_ref=review_evidence_id,
            idempotency_key="review-postgres-atomicity",
        )

    assert str(error.value.orig.sqlstate) == "23514"
    assert "closed-loop event Evidence has no exact ledger event" in str(error.value)
    assert issuer.calls == 1
    assert _lifecycle_surface_state(valid_postgres_stack["admin"]) == before


def test_postgres_issuer_only_commit_rolls_back_orphan_event_evidence(
    valid_postgres_stack,
):
    admin_engine = valid_postgres_stack["admin"]
    with admin_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT blob.content_bytes,evidence.metadata_json,"
                "evidence.effective_at,evidence.recorded_at "
                "FROM closed_loop_outcome_events event "
                "JOIN evidence_records evidence ON evidence.id=event.evidence_id "
                "JOIN evidence_blobs blob ON blob.sha256=evidence.blob_sha256 "
                "ORDER BY event.bundle_id,event.event_index LIMIT 1"
            )
        ).one()
    orphan = _orphan_event_evidence_projection(
        content=bytes(row.content_bytes),
        metadata=deepcopy(row.metadata_json),
        effective_at=row.effective_at,
        recorded_at=row.recorded_at,
        suffix="issuer_only",
    )
    before = _lifecycle_surface_state(admin_engine)

    with (
        pytest.raises(DBAPIError) as error,
        valid_postgres_stack["runtime"].begin() as connection,
    ):
        assert _issue_event_projection(connection, orphan) == orphan["evidence_id"]

    assert str(error.value.orig.sqlstate) == "23514"
    assert "closed-loop event Evidence has no exact ledger event" in str(error.value)
    assert _lifecycle_surface_state(admin_engine) == before


def test_postgres_concurrent_record_has_one_winner_and_drift_is_prewrite(
    valid_postgres_stack,
):
    checked_at = valid_postgres_stack["checked_at"] + timedelta(minutes=4)
    valid_postgres_stack["adapter"].clock = lambda: checked_at
    refs = _capture_supporting(
        valid_postgres_stack["adapter"],
        data_as_of=valid_postgres_stack["data_as_of"],
        suffix="-concurrent-record",
    )
    services = tuple(
        _workspace_from_stack(valid_postgres_stack, checked_at=checked_at)
        for _ in range(2)
    )
    barrier = Barrier(2)
    idempotency_key = "postgres-concurrent-record"
    before = _lifecycle_surface_state(valid_postgres_stack["admin"])

    def compete(service):
        barrier.wait()
        return _record_bundle(
            service,
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key=idempotency_key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(compete, services))

    assert sorted(result["idempotent"] for result in results) == [False, True]
    assert results[0]["bundle_id"] == results[1]["bundle_id"]
    assert {
        key: value for key, value in results[0].items() if key != "idempotent"
    } == {
        key: value for key, value in results[1].items() if key != "idempotent"
    }
    after = _lifecycle_surface_state(valid_postgres_stack["admin"])
    expected_deltas = {
        "authority_receipts": 0,
        "issuances": 0,
        "evidence_records": 1,
        "evidence_blobs": 1,
        "bundles": 1,
        "links": 3,
        "events": 1,
    }
    for name, delta in expected_deltas.items():
        assert after[name]["count"] == before[name]["count"] + delta

    with pytest.raises(ClosedLoopContractError, match="idempotency payload drifted"):
        _record_bundle(
            services[0],
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key=idempotency_key,
            principal=_principal("concurrent-actor-drift"),
        )
    with pytest.raises(ClosedLoopContractError, match="idempotency payload drifted"):
        _record_bundle(
            services[1],
            refs,
            data_as_of=valid_postgres_stack["data_as_of"],
            idempotency_key=idempotency_key,
            agent_run_ref="concurrent-agent-run-drift",
        )
    assert _lifecycle_surface_state(valid_postgres_stack["admin"]) == after


def _orm_column_signature(column) -> tuple[object, ...]:
    column_type = column.type
    if isinstance(column_type, Text):
        type_signature = ("text", None, None, None)
    elif isinstance(column_type, String):
        type_signature = (
            "character varying",
            column_type.length,
            None,
            None,
        )
    elif isinstance(column_type, BigInteger):
        type_signature = ("bigint", None, None, None)
    elif isinstance(column_type, Integer):
        type_signature = ("integer", None, None, None)
    elif isinstance(column_type, Numeric):
        type_signature = (
            "numeric",
            None,
            column_type.precision,
            column_type.scale,
        )
    elif isinstance(column_type, DateTime):
        type_signature = (
            "timestamp with time zone" if column_type.timezone else "timestamp without time zone",
            None,
            None,
            None,
        )
    elif isinstance(column_type, Boolean):
        type_signature = ("boolean", None, None, None)
    elif isinstance(column_type, JSON):
        type_signature = ("json", None, None, None)
    else:
        raise AssertionError(f"unmapped ORM type: {column_type!r}")
    default = (
        None
        if column.server_default is None
        else " ".join(str(column.server_default.arg).lower().split())
    )
    return (*type_signature, not column.nullable, default)


def test_postgres_orm_and_0096_catalog_contracts_are_identical(
    valid_postgres_stack,
):
    table_models = (
        ClosedLoopAuthorityReceiptRow,
        ClosedLoopEvidenceIssuanceRow,
        ClosedLoopOutcomeBundleRow,
        ClosedLoopOutcomeEvidenceLinkRow,
        ClosedLoopOutcomeEventRow,
    )
    admin_engine = valid_postgres_stack["admin"]
    with admin_engine.connect() as connection:
        for model in table_models:
            table = model.__table__
            rows = connection.execute(
                text(
                    "SELECT column_name,data_type,character_maximum_length,"
                    "numeric_precision,numeric_scale,is_nullable,column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=:table "
                    "ORDER BY ordinal_position"
                ),
                {"table": table.name},
            ).mappings().all()
            actual_columns = {
                row["column_name"]: (
                    row["data_type"],
                    row["character_maximum_length"],
                    row["numeric_precision"] if row["data_type"] == "numeric" else None,
                    row["numeric_scale"] if row["data_type"] == "numeric" else None,
                    row["is_nullable"] == "NO",
                    (
                        None
                        if row["column_default"] is None
                        else " ".join(row["column_default"].lower().split())
                    ),
                )
                for row in rows
            }
            expected_columns = {
                column.name: _orm_column_signature(column) for column in table.columns
            }
            assert actual_columns == expected_columns

            actual_constraints = set(
                connection.scalars(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname=current_schema() AND t.relname=:table "
                        "AND c.contype IN ('c','u','f')"
                    ),
                    {"table": table.name},
                )
            )
            expected_constraints = {
                constraint.name
                for constraint in table.constraints
                if constraint.name is not None
                and not constraint.name.endswith("_sqlite")
            }
            assert actual_constraints == expected_constraints

        actual_indexes = set(
            connection.scalars(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname=current_schema() "
                    "AND tablename=ANY(:tables) AND indexname LIKE 'ix_cloe_%'"
                ),
                {"tables": [model.__tablename__ for model in table_models]},
            )
        )
        expected_indexes = {
            index.name
            for model in table_models
            for index in model.__table__.indexes
            if index.name.startswith("ix_cloe_")
        }
        assert actual_indexes == expected_indexes

        authority_check = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conname='ck_cloe_authority_receipt'"
            )
        )
        issuance_check = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conname='ck_cloe_issuance'"
            )
        )
        for definition in (str(authority_check), str(issuance_check)):
            for source in (
                "closed-loop-experiment-receipt",
                "closed-loop-cost-receipt",
                "closed-loop-business-outcome-receipt",
                "closed-loop-review-authority-receipt",
            ):
                assert source in definition
            assert "closed-loop-experiment-authority-receipt" not in definition

        partial_index = connection.scalar(
            text(
                "SELECT pg_get_indexdef(indexrelid) FROM pg_index "
                "WHERE indexrelid='uq_closed_loop_authority_evidence_source_ref'::regclass"
            )
        )
        for source in (
            "closed-loop-experiment-receipt",
            "closed-loop-cost-receipt",
            "closed-loop-business-outcome-receipt",
            "closed-loop-review-authority-receipt",
            "governed-closed-loop-evolution",
        ):
            assert source in str(partial_index)

        unbounded_evidence_columns = connection.execute(
            text(
                "SELECT t.relname,a.attname,a.atttypmod "
                "FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid "
                "JOIN pg_namespace n ON n.oid=t.relnamespace "
                "WHERE n.nspname=current_schema() AND (t.relname,a.attname) IN ("
                "('closed_loop_authority_receipts','evidence_id'),"
                "('closed_loop_evidence_issuances','evidence_id'),"
                "('closed_loop_outcome_evidence_links','evidence_id'),"
                "('closed_loop_outcome_events','evidence_id'),"
                "('closed_loop_outcome_events','review_evidence_id'))"
            )
        ).all()
        assert len(unbounded_evidence_columns) == 5
        assert all(row.atttypmod == -1 for row in unbounded_evidence_columns)
        evidence_id_lengths = set(
            connection.scalars(
                text(
                    "SELECT length(evidence_id) FROM closed_loop_authority_receipts "
                    "UNION SELECT length(evidence_id) FROM closed_loop_evidence_issuances "
                    "UNION SELECT length(evidence_id) FROM closed_loop_outcome_evidence_links "
                    "UNION SELECT length(evidence_id) FROM closed_loop_outcome_events"
                )
            )
        )
        assert evidence_id_lengths == {44}


def _assert_constraint_violation(admin_engine, statement: str, expected: str) -> None:
    with admin_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_authority_receipts DISABLE TRIGGER USER"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_evidence_issuances DISABLE TRIGGER USER"
            )
            with pytest.raises(DBAPIError) as error:
                connection.exec_driver_sql(statement)
            expected_sqlstate = "23505" if expected.startswith("uq_") else "23503"
            assert str(error.value.orig.sqlstate) == expected_sqlstate
            assert error.value.orig.diag.constraint_name == expected
        finally:
            transaction.rollback()


@pytest.mark.parametrize(
    ("statement", "constraint_name"),
    (
        (
            "UPDATE closed_loop_authority_receipts SET evidence_id=("
            "SELECT evidence_id FROM closed_loop_authority_receipts ORDER BY evidence_id LIMIT 1) "
            "WHERE authority_receipt_id=(SELECT authority_receipt_id FROM "
            "closed_loop_authority_receipts ORDER BY evidence_id DESC LIMIT 1)",
            "uq_cloe_authority_receipt_evidence",
        ),
        (
            "UPDATE closed_loop_evidence_issuances SET authority_receipt_id=("
            "SELECT authority_receipt_id FROM closed_loop_evidence_issuances "
            "ORDER BY authority_receipt_id LIMIT 1) WHERE evidence_id=(SELECT evidence_id "
            "FROM closed_loop_evidence_issuances ORDER BY authority_receipt_id DESC LIMIT 1)",
            "uq_cloe_issuance_authority_receipt",
        ),
        (
            "UPDATE closed_loop_evidence_issuances SET evidence_id='evd_0000000000000000000000000000000000000000' "
            "WHERE evidence_id=(SELECT evidence_id FROM closed_loop_evidence_issuances LIMIT 1)",
            "fk_cloe_issuance_evidence",
        ),
        (
            "UPDATE closed_loop_evidence_issuances SET authority_receipt_id='cloer_missing' "
            "WHERE evidence_id=(SELECT evidence_id FROM closed_loop_evidence_issuances LIMIT 1)",
            "fk_cloe_issuance_authority_receipt",
        ),
    ),
)
def test_postgres_named_authority_constraints_report_exact_diagnostics(
    valid_postgres_stack,
    statement,
    constraint_name,
):
    _assert_constraint_violation(
        valid_postgres_stack["admin"],
        statement,
        constraint_name,
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "authority_contract",
        "exact_scope_null",
        "claims_bundle_null",
        "claims_requester_number",
        "data_as_of_z",
    ),
)
def test_postgres_named_deferred_event_rejects_jointly_resigned_review_drift(
    valid_postgres_stack,
    request,
    mutation,
):
    service = valid_postgres_stack["service"]
    adapter = valid_postgres_stack["adapter"]
    first = valid_postgres_stack["first"]
    review_time = valid_postgres_stack["checked_at"] + timedelta(minutes=1)
    service.clock = lambda: review_time
    adapter.clock = lambda: review_time
    review_authority = adapter.attestation_authorities["review_event"]
    review_authority.claims = {
        "bundle_id": first["bundle_id"],
        "event_type": "review_requested",
        "reason_code": "scheduled_review",
        "replacement_bundle_id": None,
        "requested_by_actor_id": "review-requester",
    }
    review = adapter.capture_review_event(
        principal=_principal("capture-relay"),
        store_ref=FIXTURE["scope"]["store_ref"],
        data_as_of=review_time,
        attestation_ref="review-postgres-joint-authority-attack",
    )
    service.append_review_event(
        principal=_principal("review-requester"),
        store_ref=FIXTURE["scope"]["store_ref"],
        bundle_id=str(first["bundle_id"]),
        event_type="review_requested",
        reason_code="scheduled_review",
        review_evidence_ref=review.id,
        idempotency_key="review-postgres-joint-authority-attack",
    )

    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    with admin_engine.connect() as connection:
        event_id = connection.scalar(
            text(
                "SELECT event_id FROM closed_loop_outcome_events "
                "WHERE review_evidence_id=:review_evidence_id"
            ),
            {"review_evidence_id": review.id},
        )
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            attack = _review_authority_attack_projection(
                connection,
                str(event_id),
                mutation=mutation,
            )
            connection.execute(
                text(
                    "CREATE TEMP TABLE cloe_review_attack_event ON COMMIT DROP AS "
                    "SELECT * FROM closed_loop_outcome_events WHERE event_id=:event_id"
                ),
                {"event_id": event_id},
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_events DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_events_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_events DISABLE TRIGGER "
                "trg_cloe_event_contract"
            )
            connection.execute(
                text("DELETE FROM closed_loop_outcome_events WHERE event_id=:event_id"),
                {"event_id": event_id},
            )
            connection.execute(
                text(
                    "INSERT INTO evidence_blobs"
                    "(sha256,byte_size,content_bytes,created_at) VALUES "
                    "(:sha,:size,:content,statement_timestamp())"
                ),
                {
                    "sha": attack["content_sha256"],
                    "size": len(attack["content"]),
                    "content": attack["content"],
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha,"
                    "filename=:filename,source_ref=:source_ref,"
                    "metadata_json=CAST(:metadata AS jsonb) WHERE id=:evidence_id"
                ),
                {
                    "sha": attack["content_sha256"],
                    "filename": f"review_event-{attack['content_sha256']}.json",
                    "source_ref": attack["source_ref"],
                    "metadata": json.dumps(attack["metadata"], sort_keys=True),
                    "evidence_id": review.id,
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records ENABLE TRIGGER USER"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_authority_receipts DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE closed_loop_authority_receipts SET "
                    "content_sha256=:content_sha,metadata_sha256=:metadata_sha,"
                    "source_ref=:source_ref,attestation_sha256=:attestation_sha,"
                    "attestation_signature_sha256=:signature_sha,"
                    "issuer_id=:issuer_id,issuer_contract_id=:issuer_contract_id,"
                    "issuer_contract_version=:issuer_contract_version,"
                    "issuer_contract_sha256=:issuer_contract_sha,schema_sha256=:schema_sha "
                    "WHERE authority_receipt_id=:receipt_id"
                ),
                {
                    "content_sha": attack["content_sha256"],
                    "metadata_sha": attack["metadata_sha256"],
                    "source_ref": attack["source_ref"],
                    "attestation_sha": attack["attestation_sha256"],
                    "signature_sha": attack["signature_sha256"],
                    "issuer_id": attack["payload"]["issuer_id"],
                    "issuer_contract_id": attack["payload"]["issuer_contract_id"],
                    "issuer_contract_version": attack["payload"][
                        "issuer_contract_version"
                    ],
                    "issuer_contract_sha": attack["payload"][
                        "issuer_contract_sha256"
                    ],
                    "schema_sha": attack["payload"]["schema_sha256"],
                    "receipt_id": attack["authority_receipt_id"],
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_authority_receipts ENABLE TRIGGER USER"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_evidence_issuances DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE closed_loop_evidence_issuances SET "
                    "content_sha256=:content_sha,source_ref=:source_ref,"
                    "attestation_sha256=:attestation_sha,"
                    "attestation_signature_sha256=:signature_sha "
                    "WHERE evidence_id=:evidence_id"
                ),
                {
                    "content_sha": attack["content_sha256"],
                    "source_ref": attack["source_ref"],
                    "attestation_sha": attack["attestation_sha256"],
                    "signature_sha": attack["signature_sha256"],
                    "evidence_id": review.id,
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_evidence_issuances ENABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE cloe_review_attack_event SET "
                    "review_evidence_sha256=:sha,review_evidence_source_ref=:source_ref,"
                    "review_attestation_sha256=:attestation_sha"
                ),
                {
                    "sha": attack["content_sha256"],
                    "source_ref": attack["source_ref"],
                    "attestation_sha": attack["attestation_sha256"],
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO closed_loop_outcome_events "
                "SELECT * FROM cloe_review_attack_event"
            )
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as deferred_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_event_contract_deferred IMMEDIATE"
                )
            assert str(deferred_error.value.orig.sqlstate) == "23514"
            assert "review authority is invalid" in str(deferred_error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


@pytest.mark.parametrize(
    ("surface", "field", "value", "expected_message"),
    (
        ("payload", "candidate_created", "false", "event JSON schema is invalid"),
        ("payload", "transition_allowed", "false", "event JSON schema is invalid"),
        ("payload", "promotion_allowed", "false", "event JSON schema is invalid"),
        ("payload", "external_write_allowed", "false", "event JSON schema is invalid"),
        ("payload", "reason_code", None, "event JSON schema is invalid"),
        ("payload", "actor_id", True, "event JSON schema is invalid"),
        ("payload", "occurred_at", "canonical-z", "event JSON schema is invalid"),
        ("metadata", "contract_id", None, "event JSON schema is invalid"),
        ("metadata", "tenant_ref", 7, "event JSON schema is invalid"),
        ("request", "actor_id", True, "event JSON schema is invalid"),
    ),
)
def test_postgres_named_deferred_event_rejects_noncanonical_json_values(
    valid_postgres_stack,
    request,
    surface,
    field,
    value,
    expected_message,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    with admin_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT event.*,ev.metadata_json,blob.content_bytes FROM "
                    "closed_loop_outcome_events event "
                    "JOIN evidence_records ev ON ev.id=event.evidence_id "
                    "JOIN evidence_blobs blob ON blob.sha256=ev.blob_sha256 "
                    "ORDER BY event.event_index DESC LIMIT 1"
                )
            )
            .mappings()
            .one()
        )
    payload = json.loads(bytes(row["content_bytes"]))
    metadata = deepcopy(row["metadata_json"])
    request_json = deepcopy(row["request_json"])
    if surface == "payload":
        payload[field] = (
            payload[field].replace("+00:00", "Z")
            if field == "occurred_at" and value == "canonical-z"
            else value
        )
    elif surface == "metadata":
        metadata[field] = value
    else:
        request_json[field] = value
    content = _canonical_json(payload)
    content_sha256 = hashlib.sha256(content).hexdigest()
    request_sha256 = _closed_loop_postgres_jsonb_sha256(request_json)
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "CREATE TEMP TABLE cloe_event_flag_attack ON COMMIT DROP AS "
                    "SELECT * FROM closed_loop_outcome_events WHERE event_id=:event_id"
                ),
                {"event_id": row["event_id"]},
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_events DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_events_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_events DISABLE TRIGGER "
                "trg_cloe_event_contract"
            )
            connection.execute(
                text("DELETE FROM closed_loop_outcome_events WHERE event_id=:event_id"),
                {"event_id": row["event_id"]},
            )
            connection.execute(
                text(
                    "INSERT INTO evidence_blobs"
                    "(sha256,byte_size,content_bytes,created_at) VALUES "
                    "(:sha,:size,:content,statement_timestamp()) "
                    "ON CONFLICT (sha256) DO NOTHING"
                ),
                {
                    "sha": content_sha256,
                    "size": len(content),
                    "content": content,
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha "
                    ",metadata_json=CAST(:metadata AS jsonb) "
                    "WHERE id=:evidence_id"
                ),
                {
                    "sha": content_sha256,
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "evidence_id": row["evidence_id"],
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records ENABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE cloe_event_flag_attack SET evidence_sha256=:sha,"
                    "request_json=CAST(:request_json AS json),"
                    "request_sha256=:request_sha256"
                ),
                {
                    "sha": content_sha256,
                    "request_json": json.dumps(request_json, sort_keys=True),
                    "request_sha256": request_sha256,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO closed_loop_outcome_events "
                "SELECT * FROM cloe_event_flag_attack"
            )
            connection.exec_driver_sql(
                f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}"
            )
            with pytest.raises(DBAPIError) as deferred_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_event_contract_deferred IMMEDIATE"
                )
            assert str(deferred_error.value.orig.sqlstate) == "23514"
            assert expected_message in str(deferred_error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_agent_run_validator_rejects_resigned_chain_without_run_started(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)
    clone_run_id = f"run-first-event-{uuid4().hex[:16]}"
    terminal_sha256 = ""

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            envelope = dict(
                connection.execute(
                    select(AgentRuntimeRunEnvelopeRow.__table__).where(
                        AgentRuntimeRunEnvelopeRow.run_id
                        == FIXTURE["agent_run_ref"]
                    )
                ).mappings().one()
            )
            original_events = list(
                connection.execute(
                    select(AgentRuntimeRunEventRow.__table__)
                    .where(
                        AgentRuntimeRunEventRow.run_id
                        == FIXTURE["agent_run_ref"]
                    )
                    .order_by(AgentRuntimeRunEventRow.event_index)
                ).mappings()
            )
            assert original_events[0]["event_type"] == "run_started"
            envelope.update(
                {
                    "run_id": clone_run_id,
                    "idempotency_sha256": hashlib.sha256(
                        f"first-event:{clone_run_id}".encode()
                    ).hexdigest(),
                }
            )
            connection.execute(
                AgentRuntimeRunEnvelopeRow.__table__.insert(), envelope
            )
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events DISABLE TRIGGER ALL"
            )
            previous_sha256 = "0" * 64
            for event_index, original in enumerate(original_events[1:], start=1):
                event = _agent_run_event_row_payload(
                    SimpleNamespace(**dict(original))
                )
                event.update(
                    {
                        "event_index": event_index,
                        "previous_event_sha256": previous_sha256,
                    }
                )
                event["event_sha256"] = _agent_run_event_hash(
                    {
                        key: value
                        for key, value in event.items()
                        if key != "event_sha256"
                    }
                )
                event_id = _agent_run_event_id(
                    clone_run_id, str(event["event_sha256"])
                )
                content = _agent_run_canonical(
                    {
                        "contract_id": "kjds-governed-agent-run-evidence-v1",
                        "run_id": clone_run_id,
                        "event_id": event_id,
                        **event,
                        "payload_status": "not_retained",
                        "proposal_only": True,
                        "formal_fact": False,
                        "external_write_allowed": False,
                    }
                )
                content_sha256 = hashlib.sha256(content).hexdigest()
                evidence_id = _stable_id("evd", content_sha256)
                connection.execute(
                    EvidenceBlobRow.__table__.insert(),
                    {
                        "sha256": content_sha256,
                        "byte_size": len(content),
                        "content_bytes": content,
                        "created_at": original["recorded_at"],
                    },
                )
                connection.execute(
                    EvidenceRecordRow.__table__.insert(),
                    {
                        "id": evidence_id,
                        "blob_sha256": content_sha256,
                        "filename": f"{event_id}.json",
                        "content_type": "application/json",
                        "source": "governed-agent-run-evidence",
                        "source_ref": f"agent-run://{clone_run_id}/{event_id}",
                        "grade": "B",
                        "effective_at": original["occurred_at"],
                        "effective_until": None,
                        "recorded_at": original["recorded_at"],
                        "created_by": "kjds-agent-runtime",
                        "metadata_json": {
                            "contract_id": "kjds-governed-agent-run-evidence-v1",
                            "tenant_ref": original["tenant_ref"],
                            "entity_ref": original["entity_ref"],
                            "store_ref": original["store_ref"],
                            "authority_sha256": original["authority_sha256"],
                            "run_id": clone_run_id,
                            "event_id": event_id,
                            "event_type": event["event_type"],
                            "event_sha256": event["event_sha256"],
                            "retention_class": "security",
                            "legal_hold": False,
                        },
                    },
                )
                event_row = dict(original)
                event_row.update(
                    {
                        "event_id": event_id,
                        "run_id": clone_run_id,
                        "event_index": event_index,
                        "previous_event_sha256": previous_sha256,
                        "event_sha256": event["event_sha256"],
                        "evidence_id": evidence_id,
                        "evidence_sha256": content_sha256,
                    }
                )
                connection.execute(
                    AgentRuntimeRunEventRow.__table__.insert(), event_row
                )
                previous_sha256 = str(event["event_sha256"])
            terminal_sha256 = previous_sha256
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events ENABLE TRIGGER ALL"
            )

            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text(
                        "SELECT kjds_cloe_validate_agent_run_contract("
                        ":run_id,:tenant_ref,:entity_ref,:store_ref,:authority,"
                        ":data_as_of,:checked_at,:terminal_sha256)"
                    ),
                    {
                        "run_id": clone_run_id,
                        "tenant_ref": FIXTURE["scope"]["tenant_ref"],
                        "entity_ref": FIXTURE["scope"]["entity_ref"],
                        "store_ref": FIXTURE["scope"]["store_ref"],
                        "authority": FIXTURE["scope"][
                            "scope_grant_authority_sha256"
                        ],
                        "data_as_of": valid_postgres_stack["data_as_of"],
                        "checked_at": valid_postgres_stack["checked_at"],
                        "terminal_sha256": terminal_sha256,
                    },
                )
            assert str(error.value.orig.sqlstate) == "23514"
            assert "must start with run_started" in str(error.value.orig)
        finally:
            transaction.rollback()

    assert _lifecycle_surface_state(admin_engine) == baseline
    with admin_engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM agent_runtime_run_envelopes "
                "WHERE run_id=:run_id"
            ),
            {"run_id": clone_run_id},
        ) == 0


def test_postgres_deferred_conservation_rejects_jointly_resigned_sensitive_agent_event(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM agent_runtime_run_events "
                        "WHERE run_id=:run_id AND event_type='run_succeeded'"
                    ),
                    {"run_id": FIXTURE["agent_run_ref"]},
                )
                .mappings()
                .one()
            )
            event = _agent_run_event_row_payload(SimpleNamespace(**dict(row)))
            event["safe_payload"] = {"attempt_count": 1, "raw_output": "forbidden"}
            event["event_sha256"] = _agent_run_event_hash(
                {key: value for key, value in event.items() if key != "event_sha256"}
            )
            event_id = _agent_run_event_id(str(row["run_id"]), str(event["event_sha256"]))
            content = _agent_run_canonical(
                {
                    "contract_id": "kjds-governed-agent-run-evidence-v1",
                    "run_id": row["run_id"],
                    "event_id": event_id,
                    **event,
                    "payload_status": "not_retained",
                    "proposal_only": True,
                    "formal_fact": False,
                    "external_write_allowed": False,
                }
            )
            content_sha256 = hashlib.sha256(content).hexdigest()
            metadata = dict(
                connection.scalar(
                    text("SELECT metadata_json FROM evidence_records WHERE id=:evidence_id"),
                    {"evidence_id": row["evidence_id"]},
                )
            )
            metadata.update(
                {
                    "event_id": event_id,
                    "event_sha256": event["event_sha256"],
                }
            )

            connection.execute(
                text(
                    "INSERT INTO evidence_blobs(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,:size,:content,statement_timestamp())"
                ),
                {"sha": content_sha256, "size": len(content), "content": content},
            )
            connection.exec_driver_sql("ALTER TABLE evidence_records DISABLE TRIGGER USER")
            connection.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha,filename=:filename,"
                    "source_ref=:source_ref,metadata_json=CAST(:metadata AS jsonb) "
                    "WHERE id=:evidence_id"
                ),
                {
                    "sha": content_sha256,
                    "filename": f"{event_id}.json",
                    "source_ref": f"agent-run://{row['run_id']}/{event_id}",
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "evidence_id": row["evidence_id"],
                },
            )
            connection.exec_driver_sql("ALTER TABLE evidence_records ENABLE TRIGGER USER")
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events DISABLE TRIGGER ALL"
            )
            connection.execute(
                text(
                    "UPDATE agent_runtime_run_events SET event_id=:event_id,"
                    "safe_payload_json=CAST(:safe_payload AS json),event_sha256=:event_sha256,"
                    "evidence_sha256=:evidence_sha256 WHERE event_id=:old_event_id"
                ),
                {
                    "event_id": event_id,
                    "safe_payload": json.dumps(event["safe_payload"], sort_keys=True),
                    "event_sha256": event["event_sha256"],
                    "evidence_sha256": content_sha256,
                    "old_event_id": row["event_id"],
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events ENABLE TRIGGER ALL"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER trg_cloe_link_contract"
            )
            connection.exec_driver_sql(
                "CREATE TEMP TABLE cloe_agent_attack_link ON COMMIT DROP AS "
                "SELECT * FROM closed_loop_outcome_evidence_links LIMIT 1"
            )
            connection.exec_driver_sql(
                "DELETE FROM closed_loop_outcome_evidence_links WHERE link_id="
                "(SELECT link_id FROM cloe_agent_attack_link)"
            )
            connection.exec_driver_sql(
                "INSERT INTO closed_loop_outcome_evidence_links "
                "SELECT * FROM cloe_agent_attack_link"
            )

            with pytest.raises(DBAPIError) as conservation_error:
                connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            assert str(conservation_error.value.orig.sqlstate) == "23514"
            assert "AgentRun success is invalid" in str(conservation_error.value.orig)
        finally:
            transaction.rollback()
    assert _lifecycle_surface_state(admin_engine) == baseline


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("event_index", "6"),
        ("cost_usd", 0),
        ("safe_payload", []),
        ("adapter_sha256", 7),
    ),
)
def test_postgres_deferred_conservation_rejects_jointly_resigned_agent_evidence_types(
    valid_postgres_stack,
    request,
    field,
    value,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            row = (
                connection.execute(
                    text(
                        "SELECT run_event.event_id,run_event.evidence_id,"
                        "blob.content_bytes FROM agent_runtime_run_events run_event "
                        "JOIN evidence_records ev ON ev.id=run_event.evidence_id "
                        "JOIN evidence_blobs blob ON blob.sha256=ev.blob_sha256 "
                        "WHERE run_event.run_id=:run_id "
                        "AND run_event.event_type='run_succeeded'"
                    ),
                    {"run_id": FIXTURE["agent_run_ref"]},
                )
                .mappings()
                .one()
            )
            payload = json.loads(bytes(row["content_bytes"]))
            payload[field] = value
            content = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
            content_sha256 = hashlib.sha256(content).hexdigest()
            connection.execute(
                text(
                    "INSERT INTO evidence_blobs"
                    "(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,:size,:content,statement_timestamp())"
                ),
                {"sha": content_sha256, "size": len(content), "content": content},
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha "
                    "WHERE id=:evidence_id"
                ),
                {"sha": content_sha256, "evidence_id": row["evidence_id"]},
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records ENABLE TRIGGER USER"
            )
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events DISABLE TRIGGER ALL"
            )
            connection.execute(
                text(
                    "UPDATE agent_runtime_run_events SET evidence_sha256=:sha "
                    "WHERE event_id=:event_id"
                ),
                {"sha": content_sha256, "event_id": row["event_id"]},
            )
            connection.exec_driver_sql(
                "ALTER TABLE agent_runtime_run_events ENABLE TRIGGER ALL"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_link_contract"
            )
            connection.exec_driver_sql(
                "CREATE TEMP TABLE cloe_agent_type_attack ON COMMIT DROP AS "
                "SELECT * FROM closed_loop_outcome_evidence_links LIMIT 1"
            )
            connection.exec_driver_sql(
                "DELETE FROM closed_loop_outcome_evidence_links WHERE link_id="
                "(SELECT link_id FROM cloe_agent_type_attack)"
            )
            connection.exec_driver_sql(
                "INSERT INTO closed_loop_outcome_evidence_links "
                "SELECT * FROM cloe_agent_type_attack"
            )
            with pytest.raises(DBAPIError) as conservation_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_link_conservation IMMEDIATE"
                )
            assert str(conservation_error.value.orig.sqlstate) == "23514"
            assert "AgentRun Evidence is invalid" in str(conservation_error.value.orig)
        finally:
            transaction.rollback()

    assert _lifecycle_surface_state(admin_engine) == baseline


@pytest.mark.parametrize(
    "mutation",
    (
        "extra",
        "missing_extra",
        "retention_class",
        "legal_hold",
        "tenant_ref_number",
    ),
)
def test_postgres_deferred_conservation_rejects_agent_metadata_shape_drift(
    valid_postgres_stack,
    request,
    mutation,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            row = (
                connection.execute(
                    text(
                        "SELECT run_event.evidence_id,ev.metadata_json "
                        "FROM agent_runtime_run_events run_event "
                        "JOIN evidence_records ev ON ev.id=run_event.evidence_id "
                        "WHERE run_event.run_id=:run_id "
                        "ORDER BY run_event.event_index LIMIT 1"
                    ),
                    {"run_id": FIXTURE["agent_run_ref"]},
                )
                .mappings()
                .one()
            )
            metadata = dict(row["metadata_json"])
            if mutation == "extra":
                metadata["raw_prompt"] = "forbidden"
            elif mutation == "missing_extra":
                metadata.pop("legal_hold")
                metadata["customer_email"] = "forbidden"
            elif mutation == "retention_class":
                metadata["retention_class"] = "compliance"
            elif mutation == "legal_hold":
                metadata["legal_hold"] = True
            else:
                metadata["tenant_ref"] = 7

            connection.exec_driver_sql(
                "ALTER TABLE evidence_records DISABLE TRIGGER USER"
            )
            connection.execute(
                text(
                    "UPDATE evidence_records SET metadata_json=CAST(:metadata AS jsonb) "
                    "WHERE id=:evidence_id"
                ),
                {
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "evidence_id": row["evidence_id"],
                },
            )
            connection.exec_driver_sql(
                "ALTER TABLE evidence_records ENABLE TRIGGER USER"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_link_contract"
            )
            connection.exec_driver_sql(
                "CREATE TEMP TABLE cloe_agent_metadata_attack ON COMMIT DROP AS "
                "SELECT * FROM closed_loop_outcome_evidence_links LIMIT 1"
            )
            connection.exec_driver_sql(
                "DELETE FROM closed_loop_outcome_evidence_links WHERE link_id="
                "(SELECT link_id FROM cloe_agent_metadata_attack)"
            )
            connection.exec_driver_sql(
                "INSERT INTO closed_loop_outcome_evidence_links "
                "SELECT * FROM cloe_agent_metadata_attack"
            )
            with pytest.raises(DBAPIError) as conservation_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_link_conservation IMMEDIATE"
                )
            assert str(conservation_error.value.orig.sqlstate) == "23514"
            assert "AgentRun Evidence is invalid" in str(conservation_error.value.orig)
        finally:
            transaction.rollback()

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_deferred_validator_rejects_jointly_resigned_receipt_drift(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    attack = _supporting_attack_projection(
        transactional_admin,
        valid_postgres_stack["refs"]["experiment"],
        mutation="authority_receipt_id",
    )
    baseline = _causal_residue_counts(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            _install_causal_attack_projection(connection, attack)
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_bundles DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_bundles_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_link_contract"
            )
            connection.execute(
                text(
                    "UPDATE closed_loop_outcome_bundles "
                    "SET request_json=CAST(:request AS json),"
                    "request_sha256=:request_sha,bundle_json=CAST(:bundle AS json),"
                    "bundle_sha256=:bundle_sha WHERE bundle_id=:bundle_id"
                ),
                {
                    "request": json.dumps(attack["request_json"], sort_keys=True),
                    "request_sha": attack["request_sha256"],
                    "bundle": json.dumps(attack["bundle_json"], sort_keys=True),
                    "bundle_sha": attack["bundle_sha256"],
                    "bundle_id": attack["bundle_id"],
                },
            )
            connection.execute(
                text(
                    "DELETE FROM closed_loop_outcome_evidence_links "
                    "WHERE link_id=:link_id"
                ),
                {"link_id": attack["link_id"]},
            )
            _insert_causal_attack_link(connection, attack)
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as conservation_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_link_contract_deferred IMMEDIATE"
                )
            assert str(conservation_error.value.orig.sqlstate) == "23514"
            assert "Evidence link binding is invalid" in str(
                conservation_error.value.orig
            )
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _causal_residue_counts(admin_engine) == baseline


@pytest.mark.parametrize(
    "mutation",
    (
        "authority_contract",
        "exact_scope_null",
        "claims_sample_string",
        "claims_time_z",
        "claims_decimal_leading_zero",
    ),
)
def test_postgres_named_deferred_link_rejects_jointly_resigned_authority_drift(
    valid_postgres_stack,
    request,
    mutation,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    attack = _supporting_attack_projection(
        transactional_admin,
        valid_postgres_stack["refs"]["experiment"],
        mutation=mutation,
    )
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            _install_jointly_resigned_authority_projection(connection, attack)
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_link_contract"
            )
            connection.execute(
                text(
                    "DELETE FROM closed_loop_outcome_evidence_links "
                    "WHERE link_id=:link_id"
                ),
                {"link_id": attack["link_id"]},
            )
            _insert_causal_attack_link(connection, attack)
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM closed_loop_evidence_issuances issuance "
                    "JOIN closed_loop_authority_receipts receipt USING "
                    "(authority_receipt_id) WHERE issuance.evidence_id=:evidence_id "
                    "AND receipt.evidence_id=:evidence_id"
                ),
                {"evidence_id": attack["evidence_id"]},
            ) == 1
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as deferred_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_link_contract_deferred IMMEDIATE"
                )
            assert str(deferred_error.value.orig.sqlstate) == "23514"
            assert "Evidence link binding is invalid" in str(deferred_error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_named_deferred_validator_rejects_evidence_blob_pointer_drift(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _causal_residue_counts(admin_engine)
    evidence_id = valid_postgres_stack["refs"]["experiment"]
    alternate_content = b'{"pointer":"drift"}'
    alternate_sha = hashlib.sha256(alternate_content).hexdigest()

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            link = connection.execute(
                text(
                    "SELECT * FROM closed_loop_outcome_evidence_links "
                    "WHERE evidence_id=:evidence_id"
                ),
                {"evidence_id": evidence_id},
            ).mappings().one()
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_link_contract"
            )
            connection.execute(
                text(
                    "DELETE FROM closed_loop_outcome_evidence_links "
                    "WHERE link_id=:link_id"
                ),
                {"link_id": link["link_id"]},
            )
            connection.execute(
                text(
                    "INSERT INTO closed_loop_outcome_evidence_links ("
                    "link_id,bundle_id,tenant_ref,entity_ref,store_ref,"
                    "scope_grant_authority_sha256,purpose,evidence_id,"
                    "evidence_sha256,evidence_source,evidence_source_ref,"
                    "evidence_grade,evidence_effective_at,"
                    "evidence_effective_until,evidence_recorded_at,"
                    "evidence_review_due_at,issuer_actor_id,claims_sha256,"
                    "link_sha256) VALUES ("
                    ":link_id,:bundle_id,:tenant_ref,:entity_ref,:store_ref,:authority,"
                    ":purpose,:evidence_id,:evidence_sha256,:evidence_source,"
                    ":evidence_source_ref,:evidence_grade,:evidence_effective_at,"
                    ":evidence_effective_until,:evidence_recorded_at,"
                    ":evidence_review_due_at,:issuer_actor_id,:claims_sha256,"
                    ":link_sha256)"
                ),
                {**dict(link), "authority": link["scope_grant_authority_sha256"]},
            )
            connection.execute(
                text(
                    "INSERT INTO evidence_blobs"
                    "(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,:size,:content,statement_timestamp())"
                ),
                {
                    "sha": alternate_sha,
                    "size": len(alternate_content),
                    "content": alternate_content,
                },
            )
            connection.exec_driver_sql("SET LOCAL session_replication_role=replica")
            connection.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha "
                    "WHERE id=:evidence_id"
                ),
                {"sha": alternate_sha, "evidence_id": evidence_id},
            )
            connection.exec_driver_sql("SET LOCAL session_replication_role=origin")
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as deferred_error:
                connection.exec_driver_sql(
                    "SET CONSTRAINTS trg_cloe_link_contract_deferred IMMEDIATE"
                )
            assert str(deferred_error.value.orig.sqlstate) == "23514"
            assert "Evidence link binding is invalid" in str(deferred_error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _causal_residue_counts(admin_engine) == baseline


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    (
        ("exact_scope_null", "authority Evidence schema is invalid"),
        ("claims_sample_string", "authority claims schema is invalid"),
    ),
)
def test_postgres_authority_issuer_rejects_noncanonical_nested_types_without_residue(
    valid_postgres_stack,
    request,
    mutation,
    expected_message,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    attack = _supporting_attack_projection(
        transactional_admin,
        valid_postgres_stack["refs"]["experiment"],
        mutation=mutation,
    )
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(
                "SET SESSION AUTHORIZATION kjds_cloe_issuance_runtime"
            )
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text(
                        "SELECT kjds_cloe_issue_evidence("
                        ":receipt_id,:evidence_id,:content,:filename,:source,"
                        ":source_ref,:effective_at,:effective_until,"
                        "CAST(:metadata AS jsonb),:attestation_sha256,"
                        ":signature_sha256)"
                    ),
                    {
                        "receipt_id": attack["authority_receipt_id"],
                        "evidence_id": attack["evidence_id"],
                        "content": attack["content"],
                        "filename": f"experiment-{attack['content_sha256']}.json",
                        "source": attack["source"],
                        "source_ref": attack["source_ref"],
                        "effective_at": attack["evidence_effective_at"],
                        "effective_until": attack["evidence_effective_until"],
                        "metadata": json.dumps(attack["metadata"], sort_keys=True),
                        "attestation_sha256": attack["attestation_sha256"],
                        "signature_sha256": attack[
                            "attestation_signature_sha256"
                        ],
                    },
                )
            assert str(error.value.orig.sqlstate) == "23514"
            assert expected_message in str(error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_authority_receipt_rejects_numeric_scope_text_without_residue(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    with admin_engine.connect() as connection:
        receipt = dict(
            connection.scalar(
                text(
                    "SELECT to_jsonb(receipt) FROM closed_loop_authority_receipts "
                    "receipt WHERE purpose='experiment' LIMIT 1"
                )
            )
        )
    receipt["authority_receipt_id"] = "cloer_numeric_tenant_attack"
    receipt["tenant_ref"] = 7
    baseline = _lifecycle_surface_state(admin_engine)

    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(
                f"SET SESSION AUTHORIZATION {AUTHORITY_ROLES['experiment']}"
            )
            with pytest.raises(DBAPIError) as error:
                connection.execute(
                    text(
                        "SELECT kjds_cloe_register_authority_receipt("
                        "CAST(:receipt AS jsonb))"
                    ),
                    {
                        "receipt": json.dumps(
                            receipt, sort_keys=True, separators=(",", ":")
                        )
                    },
                )
            assert str(error.value.orig.sqlstate) == "23514"
            assert "attestation receipt is invalid" in str(error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_issuer_link_and_conservation_reject_causal_true_without_residue(
    valid_postgres_stack,
    request,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    evidence_id = valid_postgres_stack["refs"]["experiment"]
    attack = _causal_attack_projection(transactional_admin, evidence_id)
    baseline = _causal_residue_counts(admin_engine)

    with pytest.raises(PermissionError, match="Evidence issuance failed"):
        valid_postgres_stack["adapter"].issuer_port.issue_evidence(
            authority_receipt_id=attack["authority_receipt_id"],
            evidence_id=attack["evidence_id"],
            content=attack["content"],
            filename=f"experiment-{attack['content_sha256']}.json",
            source=attack["source"],
            source_ref=attack["source_ref"],
            effective_at=attack["effective_at"],
            effective_until=attack["effective_until"],
            metadata=attack["metadata"],
            attestation_sha256=attack["attestation_sha256"],
            attestation_signature_sha256=attack["attestation_signature_sha256"],
        )
    assert _causal_residue_counts(admin_engine) == baseline


    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            _install_causal_attack_projection(connection, attack)
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as link_error:
                _insert_causal_attack_link(connection, attack)
            assert str(link_error.value.orig.sqlstate) == "23514"
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")
    assert _causal_residue_counts(admin_engine) == baseline


    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            _install_causal_attack_projection(connection, attack)
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_bundles DISABLE TRIGGER trg_cloe_closed_loop_outcome_bundles_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER "
                "trg_cloe_closed_loop_outcome_evidence_links_immutable"
            )
            connection.exec_driver_sql(
                "ALTER TABLE closed_loop_outcome_evidence_links DISABLE TRIGGER trg_cloe_link_contract"
            )
            connection.execute(
                text(
                    "UPDATE closed_loop_outcome_bundles "
                    "SET request_json=CAST(:request AS json),"
                    "request_sha256=:request_sha,bundle_json=CAST(:bundle AS json),"
                    "bundle_sha256=:bundle_sha "
                    "WHERE bundle_id=:bundle_id"
                ),
                {
                    "request": json.dumps(attack["request_json"], sort_keys=True),
                    "request_sha": attack["request_sha256"],
                    "bundle": json.dumps(attack["bundle_json"], sort_keys=True),
                    "bundle_sha": attack["bundle_sha256"],
                    "bundle_id": attack["bundle_id"],
                },
            )
            connection.execute(
                text(
                    "DELETE FROM closed_loop_outcome_evidence_links "
                    "WHERE link_id=:link_id"
                ),
                {"link_id": attack["link_id"]},
            )
            _insert_causal_attack_link(connection, attack)
            connection.exec_driver_sql(f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}")
            with pytest.raises(DBAPIError) as conservation_error:
                connection.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
            assert str(conservation_error.value.orig.sqlstate) == "23514"
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")
    assert _causal_residue_counts(admin_engine) == baseline


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("causal_claim_allowed", "false"),
        ("causal_claim_allowed", 0),
        ("request_actor", None),
        ("request_scope", None),
        ("request_actor_bool", True),
        ("request_scope_number", 7),
        ("supporting_issuer_number", 7),
        ("request_time_z", "canonical-z"),
    ),
)
def test_postgres_bundle_rejects_noncanonical_json_without_residue(
    valid_postgres_stack,
    request,
    mutation,
    value,
):
    admin_engine = valid_postgres_stack["admin"]
    transactional_admin = create_engine(valid_postgres_stack["target_url"])
    request.addfinalizer(transactional_admin.dispose)
    baseline = _lifecycle_surface_state(admin_engine)
    with transactional_admin.connect() as connection:
        transaction = connection.begin()
        try:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM closed_loop_outcome_bundles "
                        "ORDER BY recorded_at LIMIT 1"
                    )
                )
                .mappings()
                .one()
            )
            request_json = deepcopy(row["request_json"])
            request_json["idempotency_key"] = (
                f"bundle-json-{mutation}-{str(value).lower()}"
            )
            if mutation == "request_actor":
                request_json["actor_id"] = None
            elif mutation == "request_scope":
                request_json["scope"]["entity_ref"] = None
            elif mutation == "request_actor_bool":
                request_json["actor_id"] = value
            elif mutation == "request_scope_number":
                request_json["scope"]["entity_ref"] = value
            elif mutation == "request_time_z":
                request_json["data_as_of"] = request_json["data_as_of"].replace(
                    "+00:00", "Z"
                )
            bundle_json = deepcopy(row["bundle_json"])
            bundle_json.update(request_json)
            if mutation == "causal_claim_allowed":
                bundle_json["causal_claim_allowed"] = value
            elif mutation == "supporting_issuer_number":
                bundle_json["supporting"]["experiment"]["issuer_actor_id"] = value
            request_sha256 = _closed_loop_postgres_jsonb_sha256(request_json)
            bundle_sha256 = _closed_loop_postgres_jsonb_sha256(bundle_json)
            connection.exec_driver_sql(
                "CREATE TEMP TABLE cloe_bundle_causal_attack ON COMMIT DROP AS "
                "SELECT * FROM closed_loop_outcome_bundles WHERE false"
            )
            connection.execute(
                text(
                    "INSERT INTO cloe_bundle_causal_attack SELECT * FROM "
                    "closed_loop_outcome_bundles WHERE bundle_id=:bundle_id"
                ),
                {"bundle_id": row["bundle_id"]},
            )
            connection.execute(
                text(
                    "UPDATE cloe_bundle_causal_attack SET bundle_id=:new_bundle_id,"
                    "actor_id=:actor_id,entity_ref=:entity_ref,"
                    "request_json=CAST(:request_json AS json),"
                    "bundle_json=CAST(:bundle_json AS json),"
                    "idempotency_sha256=:idempotency_sha256,"
                    "request_sha256=:request_sha256,bundle_sha256=:bundle_sha256"
                ),
                {
                    "new_bundle_id": _stable_id("clob", bundle_sha256),
                    "actor_id": (
                        str(value).lower()
                        if mutation == "request_actor_bool"
                        else row["actor_id"]
                    ),
                    "entity_ref": (
                        str(value)
                        if mutation == "request_scope_number"
                        else row["entity_ref"]
                    ),
                    "request_json": json.dumps(request_json, sort_keys=True),
                    "bundle_json": json.dumps(bundle_json, sort_keys=True),
                    "idempotency_sha256": hashlib.sha256(
                        request_json["idempotency_key"].encode()
                    ).hexdigest(),
                    "request_sha256": request_sha256,
                    "bundle_sha256": bundle_sha256,
                },
            )
            connection.exec_driver_sql(
                f"GRANT SELECT ON cloe_bundle_causal_attack TO {GENERIC_RUNTIME}"
            )
            connection.exec_driver_sql(
                f"SET SESSION AUTHORIZATION {GENERIC_RUNTIME}"
            )
            with pytest.raises(DBAPIError) as error:
                connection.exec_driver_sql(
                    "INSERT INTO closed_loop_outcome_bundles "
                    "SELECT * FROM cloe_bundle_causal_attack"
                )
            assert str(error.value.orig.sqlstate) == "23514"
            assert "bundle JSON schema is invalid" in str(error.value.orig)
        finally:
            transaction.rollback()
            connection.exec_driver_sql("RESET SESSION AUTHORIZATION")

    assert _lifecycle_surface_state(admin_engine) == baseline


def test_postgres_populated_downgrade_is_fail_closed_without_mutation(
    valid_postgres_stack,
):
    target_url = valid_postgres_stack["target_url"]
    _revoke_generic_runtime_harness_acl(target_url)
    try:
        before = _lifecycle_surface_state(valid_postgres_stack["admin"])
        with valid_postgres_stack["admin"].connect() as connection:
            before_catalog = _cloe_catalog_state(connection)

        with pytest.raises(DBAPIError) as error:
            _downgrade_target(
                target_url,
                "20260804_0095",
            )

        assert str(error.value.orig.sqlstate) == "55000"
        assert "0096 downgrade blocked: closed-loop Evidence exists" in str(
            error.value
        )
        assert _lifecycle_surface_state(valid_postgres_stack["admin"]) == before
        with valid_postgres_stack["admin"].connect() as connection:
            assert _cloe_catalog_state(connection) == before_catalog
    finally:
        g1_database_manager._grant_runtime(target_url)
