from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, MetaData, Table, create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import apps.control_plane.global_data_coverage_ledger as ledger_module
import scripts.manage_g1_database as g1_database_manager
from apps.control_plane.database import (
    COVERAGE_ISSUER_DATABASE_URL_ENV,
    CoverageIssuerDatabasePort,
    create_coverage_issuer_port,
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.global_data_coverage_ledger import (
    GlobalDataCoverageConflictRow,
    GlobalDataCoverageEventRow,
    GlobalDataCoverageEvidenceLinkRow,
    GlobalDataCoverageFailedPageRow,
    GlobalDataCoverageFieldRow,
    GlobalDataCoverageLedger,
    GlobalDataCoverageNativeCapsRow,
    GlobalDataCoverageSnapshotRow,
    GlobalDataCoverageWindowRow,
)
from tests.test_global_data_coverage_ledger import (
    STORE,
    FakeScopeGrants,
    authority_sha256,
    bound_payload,
    principal,
)

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)
TABLES = (
    "global_data_coverage_snapshots",
    "global_data_coverage_native_caps",
    "global_data_coverage_fields",
    "global_data_coverage_failed_pages",
    "global_data_coverage_windows",
    "global_data_coverage_conflicts",
    "global_data_coverage_evidence_links",
    "global_data_coverage_events",
)
INFRASTRUCTURE_TABLES = (
    "global_data_coverage_issuance_authorities",
    "global_data_coverage_evidence_issuances",
)
CHILDREN = TABLES[1:]


def migration_config(engine) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _g1_target_url() -> str:
    return make_url(DATABASE_URL).set(
        database=g1_database_manager.DATABASE_NAME
    ).render_as_string(hide_password=False)


def _g1_admin_url() -> str:
    return make_url(DATABASE_URL).set(database="postgres").render_as_string(
        hide_password=False
    )


def _g1_receipt_snapshot():
    admin = create_engine(_g1_admin_url())
    try:
        with admin.connect() as connection:
            return g1_database_manager._g1_receipt(connection)
    finally:
        admin.dispose()


def _g1_role_snapshot(connection) -> tuple[list[tuple], list[tuple]]:
    roles = connection.execute(
        text(
            "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
            "rolreplication,rolbypassrls,shobj_description(oid,'pg_authid') "
            "FROM pg_roles WHERE rolname=ANY(:roles) ORDER BY rolname"
        ),
        {"roles": list(g1_database_manager.ROLE_NAMES)},
    ).all()
    memberships = connection.execute(
        text(
            "SELECT granted.rolname,member_role.rolname,m.admin_option "
            "FROM pg_auth_members m JOIN pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_roles member_role ON member_role.oid=m.member "
            "WHERE granted.rolname=ANY(:roles) OR member_role.rolname=ANY(:roles) "
            "ORDER BY 1,2"
        ),
        {"roles": list(g1_database_manager.ROLE_NAMES)},
    ).all()
    return roles, memberships


def _set_g1_secrets(monkeypatch, *, token: str | None = None) -> str:
    run_token = token or uuid4().hex + uuid4().hex
    monkeypatch.setenv("KJDS_G1_RUN_TOKEN", run_token)
    monkeypatch.setenv(g1_database_manager.GDC_ADMIN_DATABASE_URL_ENV, DATABASE_URL)
    for name in (
        "KJDS_G1_COVERAGE_ISSUER_PASSWORD",
        "KJDS_G1_RUNTIME_PASSWORD",
        "KJDS_G1_CLOE_ISSUER_PASSWORD",
        "KJDS_G1_CLOE_EXPERIMENT_PASSWORD",
        "KJDS_G1_CLOE_COST_PASSWORD",
        "KJDS_G1_CLOE_OUTCOME_PASSWORD",
        "KJDS_G1_CLOE_REVIEW_PASSWORD",
    ):
        monkeypatch.setenv(name, uuid4().hex + uuid4().hex)
    return run_token


def test_g1_run_lease_blocks_second_owner_and_preserves_first(monkeypatch):
    target_url = _g1_target_url()
    token_a = uuid4().hex + uuid4().hex
    token_b = uuid4().hex + uuid4().hex
    _set_g1_secrets(monkeypatch, token=token_a)
    g1_database_manager.manage("acquire", target_url)
    g1_database_manager.manage("recreate", target_url)
    owner_engine = create_engine(target_url)
    owner_connection = owner_engine.connect()
    try:
        owner_connection.execute(text("CREATE TABLE alembic_version(version_num text)"))
        owner_connection.execute(
            text("INSERT INTO alembic_version VALUES ('owner-head')")
        )
        owner_connection.commit()
        with create_engine(DATABASE_URL).connect() as admin:
            before = _g1_role_snapshot(admin)
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", token_b)
        with pytest.raises(RuntimeError, match="lease is already held"):
            g1_database_manager.manage("acquire", target_url)
        with pytest.raises(RuntimeError, match="not owned by this run"):
            g1_database_manager.manage("drop", target_url)
        assert owner_connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "owner-head"
        )
        with create_engine(DATABASE_URL).connect() as admin:
            assert _g1_role_snapshot(admin) == before
    finally:
        owner_connection.close()
        owner_engine.dispose()
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", token_a)
        g1_database_manager.manage("drop", target_url)
    with create_engine(DATABASE_URL).connect() as admin:
        assert not g1_database_manager._database_exists(admin)
        assert g1_database_manager._existing_roles(admin) == []


def test_g1_role_password_server_literal_and_invalid_secret_cleanup(monkeypatch):
    target_url = _g1_target_url()
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    raw = "quoted'value\nwith-control"
    with admin_engine.connect() as admin:
        literal = g1_database_manager._server_literal(admin, raw)
        assert admin.scalar(text(f"SELECT {literal}")) == raw
    token = _set_g1_secrets(monkeypatch)
    monkeypatch.setenv("KJDS_G1_CLOE_COST_PASSWORD", raw)
    try:
        g1_database_manager.manage("acquire", target_url)
        with pytest.raises(RuntimeError, match="credential.*invalid"):
            g1_database_manager.manage("recreate", target_url)
        with admin_engine.connect() as admin:
            assert not g1_database_manager._database_exists(admin)
            assert g1_database_manager._existing_roles(admin) == []
        g1_database_manager.manage("drop", target_url)
    finally:
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", token)
        with admin_engine.connect() as admin:
            if admin.scalar(text("SELECT to_regclass(:table_name)"), {"table_name": g1_database_manager.LEASE_TABLE}):
                admin.execute(
                    text(
                        f"DELETE FROM {g1_database_manager.LEASE_TABLE} "
                        "WHERE lease_id=:lease_id"
                    ),
                    {"lease_id": g1_database_manager.LEASE_ID},
                )
        admin_engine.dispose()


def test_g1_role_exists_failure_cleanup_preserves_preexisting_grants(monkeypatch):
    target_url = _g1_target_url()
    member = "kjds_g1_preexisting_member"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as admin:
        admin.exec_driver_sql(
            "CREATE ROLE kjds_gdc_issuance_owner NOLOGIN NOINHERIT NOSUPERUSER "
            "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
        )
        admin.exec_driver_sql(
            "CREATE ROLE kjds_gdc_issuance_runtime LOGIN NOINHERIT NOSUPERUSER "
            "NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS"
        )
        admin.exec_driver_sql(
            "CREATE ROLE kjds_g1_runtime LOGIN NOINHERIT NOSUPERUSER "
            "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
        )
        admin.exec_driver_sql(f'CREATE ROLE "{member}" NOLOGIN')
        admin.exec_driver_sql(
            "COMMENT ON ROLE kjds_gdc_issuance_owner IS 'preexisting-owner'"
        )
        admin.exec_driver_sql(
            "COMMENT ON ROLE kjds_gdc_issuance_runtime IS 'preexisting-runtime'"
        )
        admin.exec_driver_sql("COMMENT ON ROLE kjds_g1_runtime IS 'preexisting-generic'")
        admin.exec_driver_sql(
            f'GRANT kjds_gdc_issuance_owner TO "{member}" WITH ADMIN OPTION'
        )
        before = _g1_role_snapshot(admin)
    token = uuid4().hex + uuid4().hex
    monkeypatch.setenv("KJDS_G1_RUN_TOKEN", token)
    monkeypatch.setenv("KJDS_G1_COVERAGE_ISSUER_PASSWORD", uuid4().hex + uuid4().hex)
    monkeypatch.setenv("KJDS_G1_RUNTIME_PASSWORD", uuid4().hex + uuid4().hex)
    try:
        g1_database_manager.manage("acquire", target_url)
        with pytest.raises(RuntimeError, match="not owned by this run"):
            g1_database_manager.manage("recreate", target_url)
        g1_database_manager.manage("drop", target_url)
        with admin_engine.connect() as admin:
            assert _g1_role_snapshot(admin) == before
    finally:
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(
                f'REVOKE ADMIN OPTION FOR kjds_gdc_issuance_owner FROM "{member}"'
            )
            admin.exec_driver_sql(f'REVOKE kjds_gdc_issuance_owner FROM "{member}"')
            admin.exec_driver_sql(f'DROP ROLE IF EXISTS "{member}"')
            for role in g1_database_manager.ROLE_NAMES:
                admin.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        admin_engine.dispose()


def test_g1_recovery_cleans_receipt_owned_public_acl_and_is_idempotent(monkeypatch):
    target_url = _g1_target_url()
    original_token = _set_g1_secrets(monkeypatch)
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        g1_database_manager.manage("acquire", target_url)
        g1_database_manager.manage("recreate", target_url)
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(
                "GRANT USAGE ON SCHEMA public TO kjds_g1_runtime"
            )
            admin.exec_driver_sql(
                "GRANT kjds_gdc_issuance_owner TO kjds_g1_runtime WITH ADMIN OPTION"
            )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", uuid4().hex + uuid4().hex)
        g1_database_manager.manage("recover", target_url)
        g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            assert not g1_database_manager._database_exists(admin)
            assert g1_database_manager._existing_roles(admin) == []
        assert _g1_receipt_snapshot() is None
    finally:
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", original_token)
        receipt = _g1_receipt_snapshot()
        if receipt is not None:
            g1_database_manager.manage("drop", target_url)
        admin_engine.dispose()


def test_g1_recovery_replays_crash_after_acquire(monkeypatch):
    target_url = _g1_target_url()
    original_token = _set_g1_secrets(monkeypatch)
    try:
        g1_database_manager.manage("acquire", target_url)
        receipt = _g1_receipt_snapshot()
        assert receipt == (hashlib.sha256(original_token.encode()).hexdigest(), False, False)
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", uuid4().hex + uuid4().hex)
        g1_database_manager.manage("recover", target_url)
        g1_database_manager.manage("recover", target_url)
        assert _g1_receipt_snapshot() is None
        admin_engine = create_engine(_g1_admin_url())
        try:
            with admin_engine.connect() as admin:
                assert not g1_database_manager._database_exists(admin)
                assert g1_database_manager._existing_roles(admin) == []
        finally:
            admin_engine.dispose()
    finally:
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", original_token)
        if _g1_receipt_snapshot() is not None:
            g1_database_manager.manage("drop", target_url)


def test_g1_recovery_rejects_owned_sentinel_without_any_mutation(monkeypatch):
    target_url = _g1_target_url()
    original_token = _set_g1_secrets(monkeypatch)
    sentinel = f"bas211_sentinel_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        g1_database_manager.manage("acquire", target_url)
        g1_database_manager.manage("recreate", target_url)
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(
                f'CREATE SCHEMA "{sentinel}" AUTHORIZATION kjds_g1_runtime'
            )
            admin.exec_driver_sql(
                "GRANT USAGE ON SCHEMA public TO kjds_g1_runtime"
            )
            role_before = _g1_role_snapshot(admin)
            public_acl_before = admin.scalar(
                text("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
            )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", uuid4().hex + uuid4().hex)
        with pytest.raises(RuntimeError, match="unowned database dependency"):
            g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            assert g1_database_manager._database_exists(admin)
            assert _g1_role_snapshot(admin) == role_before
            assert admin.scalar(
                text("SELECT nspacl::text FROM pg_namespace WHERE nspname='public'")
            ) == public_acl_before
            assert admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": sentinel},
            ) == sentinel
    finally:
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", original_token)
        with admin_engine.connect() as admin:
            if admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": sentinel},
            ):
                owner = str(admin.scalar(text("SELECT current_user")))
                admin.exec_driver_sql(
                    f'ALTER SCHEMA "{sentinel}" OWNER TO "{owner}"'
                )
                admin.exec_driver_sql(f'DROP SCHEMA "{sentinel}"')
            if admin.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='kjds_g1_runtime')")
            ):
                admin.exec_driver_sql(
                    "REVOKE ALL PRIVILEGES ON SCHEMA public FROM kjds_g1_runtime"
                )
        receipt = _g1_receipt_snapshot()
        if receipt is not None:
            g1_database_manager.manage("drop", target_url)
        admin_engine.dispose()


def test_g1_role_drop_transaction_rolls_back_and_replays(monkeypatch):
    target_url = _g1_target_url()
    token = _set_g1_secrets(monkeypatch)
    original_cleanup = g1_database_manager._apply_role_cleanup
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")

    def fail_after_first_drop(connection, plan):
        connection.exec_driver_sql(
            f"DROP ROLE {g1_database_manager._identifier(plan.roles[0])}"
        )
        raise RuntimeError("injected role-drop interruption")

    try:
        g1_database_manager.manage("acquire", target_url)
        g1_database_manager.manage("recreate", target_url)
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            fail_after_first_drop,
        )
        with pytest.raises(RuntimeError, match="injected role-drop interruption"):
            g1_database_manager.manage("drop", target_url)
        with admin_engine.connect() as admin:
            assert not g1_database_manager._database_exists(admin)
            assert set(g1_database_manager._existing_roles(admin)) == set(
                g1_database_manager.ROLE_NAMES
            )
        receipt = _g1_receipt_snapshot()
        assert receipt == (hashlib.sha256(token.encode()).hexdigest(), True, False)
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            original_cleanup,
        )
        g1_database_manager.manage("drop", target_url)
        assert _g1_receipt_snapshot() is None
        with admin_engine.connect() as admin:
            assert g1_database_manager._existing_roles(admin) == []
    finally:
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            original_cleanup,
        )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", token)
        if _g1_receipt_snapshot() is not None:
            g1_database_manager.manage("drop", target_url)
        admin_engine.dispose()


def test_g1_recovery_preserves_unknown_role_and_schema(monkeypatch):
    target_url = _g1_target_url()
    _set_g1_secrets(monkeypatch)
    schema = f"data_cov_002_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(
                "CREATE ROLE kjds_gdc_generic_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
            )
            admin.exec_driver_sql(
                "COMMENT ON ROLE kjds_gdc_generic_runtime IS 'preexisting-runtime'"
            )
            admin.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            role_before = admin.execute(
                text(
                    "SELECT rolname,shobj_description(oid,'pg_authid') "
                    "FROM pg_roles WHERE rolname='kjds_gdc_generic_runtime'"
                )
            ).one()
        with pytest.raises(RuntimeError, match="no ownership receipt"):
            g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            assert admin.execute(
                text(
                    "SELECT rolname,shobj_description(oid,'pg_authid') "
                    "FROM pg_roles WHERE rolname='kjds_gdc_generic_runtime'"
                )
            ).one() == role_before
            assert admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": schema},
            ) == schema
    finally:
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            admin.exec_driver_sql("DROP ROLE IF EXISTS kjds_gdc_generic_runtime")
        admin_engine.dispose()


def test_g1_recovery_replays_interrupted_receipt_owned_gdc_resources(monkeypatch):
    target_url = _g1_target_url()
    original_token = _set_g1_secrets(monkeypatch)
    schema = f"data_cov_002_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        g1_database_manager.acquire_gdc_contract_resources(
            DATABASE_URL,
            schema_name=schema,
            issuer_password=uuid4().hex + uuid4().hex,
            generic_password=uuid4().hex + uuid4().hex,
        )
        with admin_engine.connect() as admin:
            admin.exec_driver_sql(f'CREATE TABLE "{schema}".owned_receipt(id integer)')
            admin.exec_driver_sql(
                f'ALTER TABLE "{schema}".owned_receipt OWNER TO kjds_gdc_issuance_owner'
            )
            admin.exec_driver_sql(
                f'GRANT USAGE ON SCHEMA "{schema}" TO kjds_gdc_generic_runtime'
            )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", uuid4().hex + uuid4().hex)
        g1_database_manager.manage("recover", target_url)
        g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            assert g1_database_manager._gdc_receipt(admin) is None
            assert _g1_role_snapshot(admin)[0] == []
            assert admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": schema},
            ) is None
    finally:
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", original_token)
        with admin_engine.connect() as admin:
            receipt = g1_database_manager._gdc_receipt(admin)
        if receipt is not None:
            g1_database_manager.release_gdc_contract_resources(DATABASE_URL)
        admin_engine.dispose()


def test_gdc_role_drop_transaction_rolls_back_and_replays(monkeypatch):
    target_url = _g1_target_url()
    original_token = _set_g1_secrets(monkeypatch)
    original_cleanup = g1_database_manager._apply_role_cleanup
    schema = f"data_cov_002_{uuid4().hex}"
    admin_engine = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")

    def fail_after_first_drop(connection, plan):
        connection.exec_driver_sql(
            f"DROP ROLE {g1_database_manager._identifier(plan.roles[0])}"
        )
        raise RuntimeError("injected GDC role-drop interruption")

    try:
        g1_database_manager.acquire_gdc_contract_resources(
            DATABASE_URL,
            schema_name=schema,
            issuer_password=uuid4().hex + uuid4().hex,
            generic_password=uuid4().hex + uuid4().hex,
        )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", uuid4().hex + uuid4().hex)
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            fail_after_first_drop,
        )
        with pytest.raises(RuntimeError, match="injected GDC role-drop interruption"):
            g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            receipt = g1_database_manager._gdc_receipt(admin)
            assert receipt is not None
            assert receipt[1:] == (schema, True, True)
            assert set(
                admin.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname=ANY(:roles)"),
                    {"roles": list(g1_database_manager.GDC_CONTRACT_ROLE_NAMES)},
                ).scalars()
            ) == set(g1_database_manager.GDC_CONTRACT_ROLE_NAMES)
            assert admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": schema},
            ) == schema
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            original_cleanup,
        )
        g1_database_manager.manage("recover", target_url)
        with admin_engine.connect() as admin:
            assert g1_database_manager._gdc_receipt(admin) is None
            assert list(
                admin.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname=ANY(:roles)"),
                    {"roles": list(g1_database_manager.GDC_CONTRACT_ROLE_NAMES)},
                ).scalars()
            ) == []
            assert admin.scalar(
                text("SELECT to_regnamespace(:schema_name)"),
                {"schema_name": schema},
            ) is None
    finally:
        monkeypatch.setattr(
            g1_database_manager,
            "_apply_role_cleanup",
            original_cleanup,
        )
        monkeypatch.setenv("KJDS_G1_RUN_TOKEN", original_token)
        with admin_engine.connect() as admin:
            receipt = g1_database_manager._gdc_receipt(admin)
        if receipt is not None:
            g1_database_manager.release_gdc_contract_resources(DATABASE_URL)
        admin_engine.dispose()


@pytest.fixture(scope="module")
def engine():
    schema = f"data_cov_002_{uuid4().hex}"
    issuer_password = f"gdc-{uuid4().hex}-{uuid4().hex}"
    generic_password = f"app-{uuid4().hex}-{uuid4().hex}"
    previous_run_token = os.environ.get(g1_database_manager.RUN_TOKEN_ENV)
    previous_database_url = os.environ.get("KJDS_DATABASE_URL")
    acquired = False
    database_url_changed = False
    admin = None
    target = None
    issuer_engine = None
    generic_engine = None
    if previous_run_token is None:
        os.environ[g1_database_manager.RUN_TOKEN_ENV] = uuid4().hex + uuid4().hex
    try:
        g1_database_manager.acquire_gdc_contract_resources(
            DATABASE_URL,
            schema_name=schema,
            issuer_password=issuer_password,
            generic_password=generic_password,
        )
        acquired = True
        admin = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}".alembic_version '
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
        url = make_url(DATABASE_URL)
        query = dict(url.query)
        query["options"] = f"-csearch_path={schema}"
        target = create_engine(url.set(query=query), pool_pre_ping=True)
        issuer_url = url.set(
            username="kjds_gdc_issuance_runtime",
            password=issuer_password,
            query=query,
        )
        issuer_engine = create_engine(issuer_url, pool_pre_ping=True)
        generic_url = url.set(
            username="kjds_gdc_generic_runtime",
            password=generic_password,
            query=query,
        )
        generic_engine = create_engine(generic_url, pool_pre_ping=True)
        target.coverage_issuer_engine = issuer_engine
        target.generic_engine = generic_engine
        os.environ["KJDS_DATABASE_URL"] = target.url.render_as_string(
            hide_password=False
        ).replace("%", "%%")
        database_url_changed = True
        config = migration_config(target)
        command.upgrade(config, "20260803_0094")
        command.upgrade(config, "20260804_0095")
        command.downgrade(config, "20260803_0094")
        command.upgrade(config, "20260804_0095")
        with admin.begin() as connection:
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO kjds_gdc_generic_runtime'))
            connection.execute(
                text(
                    f'GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA "{schema}" '
                    "TO kjds_gdc_generic_runtime"
                )
            )
            connection.execute(
                text(
                    f'REVOKE ALL ON TABLE "{schema}".global_data_coverage_issuance_authorities,'
                    f'"{schema}".global_data_coverage_evidence_issuances '
                    "FROM kjds_gdc_generic_runtime"
                )
            )
        yield target
    finally:
        if database_url_changed:
            if previous_database_url is None:
                os.environ.pop("KJDS_DATABASE_URL", None)
            else:
                os.environ["KJDS_DATABASE_URL"] = previous_database_url
        if issuer_engine is not None:
            issuer_engine.dispose()
        if generic_engine is not None:
            generic_engine.dispose()
        if target is not None:
            target.dispose()
        if admin is not None:
            admin.dispose()
        try:
            if acquired:
                g1_database_manager.release_gdc_contract_resources(DATABASE_URL)
        finally:
            if previous_run_token is None:
                os.environ.pop(g1_database_manager.RUN_TOKEN_ENV, None)
            else:
                os.environ[g1_database_manager.RUN_TOKEN_ENV] = previous_run_token


def test_gdc_fixture_setup_failure_releases_receipt_owned_resources(monkeypatch):
    _set_g1_secrets(monkeypatch)

    def fail_upgrade(*_args, **_kwargs):
        raise RuntimeError("injected GDC fixture setup failure")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)
    fixture = engine.__wrapped__()
    with pytest.raises(RuntimeError, match="injected GDC fixture setup failure"):
        next(fixture)
    admin_engine = create_engine(DATABASE_URL)
    try:
        with admin_engine.connect() as admin:
            assert g1_database_manager._gdc_receipt(admin) is None
            assert list(
                admin.execute(
                    text("SELECT rolname FROM pg_roles WHERE rolname=ANY(:roles)"),
                    {"roles": list(g1_database_manager.GDC_CONTRACT_ROLE_NAMES)},
                ).scalars()
            ) == []
            assert g1_database_manager._matching_gdc_schemas(admin) == []
    finally:
        admin_engine.dispose()


@pytest.fixture
def service(engine):
    scope = FakeScopeGrants()
    scope.coverage_issuer_port = CoverageIssuerDatabasePort(
        engine.coverage_issuer_engine
    )
    evidence = EvidenceService(engine.generic_engine)
    ledger = GlobalDataCoverageLedger(
        engine=engine.generic_engine,
        evidence=evidence,
        scope_grants=scope,
        clock=scope.clock,
    )
    return ledger, evidence, scope


def write(ledger, *, payload, key="pg-key", tenant="tenant-a"):
    _, manifest_id, native_id, data_as_of = payload
    return ledger.record(
        principal=principal(tenant),
        store_ref=STORE,
        data_as_of=data_as_of,
        idempotency_key=key,
        manifest_evidence_id=manifest_id,
        native_caps_evidence_id=native_id,
    )


def reflected(engine, name: str) -> Table:
    return Table(name, MetaData(), autoload_with=engine)


def clone_values(engine, table_name: str, *, snapshot_id: str) -> dict:
    table = reflected(engine, table_name)
    with engine.connect() as connection:
        row = connection.execute(
            select(table).where(table.c.snapshot_id == snapshot_id).limit(1)
        ).mappings().one()
    return dict(row)


def test_empty_upgrade_downgrade_reupgrade_and_single_head(engine):
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260804_0095"
        assert all(
            connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) == name
            for name in TABLES + INFRASTRUCTURE_TABLES
        )


def test_dedicated_principal_contract_survives_migration_replay(engine):
    with engine.connect() as connection:
        roles = connection.execute(
            text(
                "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
                "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime') "
                "ORDER BY rolname"
            )
        ).all()
        assert roles == [
            ("kjds_gdc_issuance_owner", False, False, False, False, False, False, True),
            ("kjds_gdc_issuance_runtime", False, False, False, False, True, False, False),
        ]
        assert connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_auth_members m "
                "JOIN pg_roles granted ON granted.oid=m.roleid "
                "WHERE granted.rolname IN "
                "('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime'))"
            )
        ) is False


@pytest.mark.parametrize(
    ("drift_sql", "restore_sql"),
    (
        (
            "ALTER ROLE kjds_gdc_issuance_runtime SUPERUSER",
            "ALTER ROLE kjds_gdc_issuance_runtime NOSUPERUSER",
        ),
        (
            "GRANT kjds_gdc_issuance_owner TO kjds_gdc_generic_runtime",
            "REVOKE kjds_gdc_issuance_owner FROM kjds_gdc_generic_runtime",
        ),
    ),
)
def test_preexisting_issuer_role_drift_fails_before_schema_changes(
    engine, drift_sql, restore_sql
):
    schema = f"data_cov_role_drift_{uuid4().hex}"
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    drift_engine = create_engine(url.set(query=query), pool_pre_ping=True)
    previous_database_url = os.environ.get("KJDS_DATABASE_URL")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE SCHEMA "{schema}"'))
        admin.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        admin.execute(
            text(
                f"INSERT INTO \"{schema}\".alembic_version VALUES ('20260803_0094')"
            )
        )
        admin.execute(text(drift_sql))
    try:
        os.environ["KJDS_DATABASE_URL"] = drift_engine.url.render_as_string(
            hide_password=False
        ).replace("%", "%%")
        with pytest.raises(
            RuntimeError,
            match="principal contract drifted|must not have role members",
        ):
            command.upgrade(migration_config(drift_engine), "20260804_0095")
        with drift_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('global_data_coverage_snapshots')")
            ) is None
    finally:
        if previous_database_url is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous_database_url
        drift_engine.dispose()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(restore_sql))
            admin.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.parametrize(
    "protected_role",
    ("kjds_gdc_issuance_owner", "kjds_gdc_issuance_runtime"),
)
def test_preexisting_issuer_outgoing_membership_fails_before_schema_changes(
    engine, protected_role
):
    schema = f"data_cov_role_edge_{uuid4().hex}"
    high_role = f"kjds_gdc_preflight_high_{uuid4().hex[:10]}"
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    drift_engine = create_engine(url.set(query=query), pool_pre_ping=True)
    previous_database_url = os.environ.get("KJDS_DATABASE_URL")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE SCHEMA "{schema}"'))
        admin.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        admin.execute(
            text(f"INSERT INTO \"{schema}\".alembic_version VALUES ('20260803_0094')")
        )
        admin.exec_driver_sql(
            f'CREATE ROLE "{high_role}" NOLOGIN NOINHERIT NOSUPERUSER '
            "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
        )
        admin.exec_driver_sql(f'GRANT "{high_role}" TO "{protected_role}"')
    try:
        os.environ["KJDS_DATABASE_URL"] = drift_engine.url.render_as_string(
            hide_password=False
        ).replace("%", "%%")
        with pytest.raises(RuntimeError, match="must not have role members"):
            command.upgrade(migration_config(drift_engine), "20260804_0095")
        with drift_engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('global_data_coverage_snapshots')")
            ) is None
    finally:
        if previous_database_url is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous_database_url
        drift_engine.dispose()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.exec_driver_sql(f'REVOKE "{high_role}" FROM "{protected_role}"')
            admin.exec_driver_sql(f'DROP ROLE "{high_role}"')
            admin.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def test_runtime_factory_rejects_generic_owner_membership(engine, monkeypatch):
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        engine.coverage_issuer_engine.url.render_as_string(hide_password=False),
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(
            text("GRANT kjds_gdc_issuance_owner TO kjds_gdc_generic_runtime")
        )
    try:
        with pytest.raises(
            RuntimeError,
            match="principal contract drifted|issuer isolation|role members",
        ):
            create_coverage_issuer_port(
                generic_url=engine.generic_engine.url.render_as_string(
                    hide_password=False
                ),
            )
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(
                text("REVOKE kjds_gdc_issuance_owner FROM kjds_gdc_generic_runtime")
            )


def test_misgranted_owner_member_still_cannot_insert_reserved_evidence(engine):
    fake_sha = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(
            text("GRANT kjds_gdc_issuance_owner TO kjds_gdc_generic_runtime")
        )
    try:
        with (
            engine.generic_engine.begin() as generic,
            pytest.raises(DBAPIError, match="dedicated issuer"),
            generic.begin_nested(),
        ):
            generic.execute(text("SET LOCAL ROLE kjds_gdc_issuance_owner"))
            generic.execute(
                text(
                    "INSERT INTO evidence_blobs(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,2,decode('7b7d','hex'),now()) ON CONFLICT DO NOTHING"
                ),
                {"sha": fake_sha},
            )
            generic.execute(
                text(
                    "INSERT INTO evidence_records(id,blob_sha256,filename,content_type,"
                    "source,source_ref,grade,effective_at,recorded_at,created_by,metadata_json) "
                    "VALUES ('evd_bbbbbbbbbbbbbbbbbbbbbbbb',:sha,'fake.json',"
                    "'application/json','global-data-coverage-manifest','owner-member-fake',"
                    "'A',now(),now(),'attacker','{}'::json)"
                ),
                {"sha": fake_sha},
            )
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(
                text("REVOKE kjds_gdc_issuance_owner FROM kjds_gdc_generic_runtime")
            )


def test_runtime_owner_membership_drift_is_rechecked_per_issuance(
    service, engine, monkeypatch
):
    _, evidence, scope = service
    _, manifest_id, _, _ = bound_payload(evidence, scope)
    content, record = evidence.content(manifest_id)
    metadata = dict(record.metadata)
    checked_at = datetime.fromisoformat(
        metadata["coverage_intake_authority_checked_at"]
    )
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        engine.coverage_issuer_engine.url.render_as_string(hide_password=False),
    )
    issuer_port = create_coverage_issuer_port(
        generic_url=engine.generic_engine.url.render_as_string(hide_password=False)
    )
    with engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM evidence_records WHERE source LIKE "
                "'global-data-coverage-%'),"
                "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
            )
        ).one()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(
            text("GRANT kjds_gdc_issuance_owner TO kjds_gdc_issuance_runtime")
        )
    try:
        with pytest.raises(PermissionError, match="issuer login is not active"):
            issuer_port.issue_evidence(
                evidence_id=f"evd_{uuid4().hex}",
                content=content,
                source=record.source,
                source_ref=record.source_ref,
                effective_at=record.effective_at,
                effective_until=record.effective_until,
                metadata=metadata,
                issuance_sha256=metadata["coverage_intake_issuance_sha256"],
                authority_checked_at=checked_at,
            )
        with (
            engine.coverage_issuer_engine.begin() as issuer,
            pytest.raises(DBAPIError, match="principal is invalid"),
        ):
            issuer.execute(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": f"evd_{uuid4().hex}",
                    "content": content,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "effective_at": record.effective_at,
                    "effective_until": record.effective_until,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "issuance_sha256": metadata[
                        "coverage_intake_issuance_sha256"
                    ],
                    "authority_checked_at": checked_at,
                },
            )
        fake_sha = hashlib.sha256(b"{}").hexdigest()
        with (
            engine.coverage_issuer_engine.begin() as issuer,
            pytest.raises(DBAPIError, match="dedicated issuer"),
        ):
            issuer.execute(text("SET LOCAL ROLE kjds_gdc_issuance_owner"))
            issuer.execute(
                text(
                    "INSERT INTO evidence_blobs(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,2,decode('7b7d','hex'),now()) ON CONFLICT DO NOTHING"
                ),
                {"sha": fake_sha},
            )
            issuer.execute(
                text(
                    "INSERT INTO evidence_records(id,blob_sha256,filename,content_type,"
                    "source,source_ref,grade,effective_at,recorded_at,created_by,metadata_json) "
                    "VALUES (:id,:sha,'fake.json','application/json',"
                    "'global-data-coverage-manifest','runtime-owner-fake','A',"
                    "now(),now(),'attacker','{}'::json)"
                ),
                {"id": f"evd_{uuid4().hex}", "sha": fake_sha},
            )
        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM evidence_records WHERE source LIKE "
                    "'global-data-coverage-%'),"
                    "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
                )
            ).one()
        assert after == before
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(
                text("REVOKE kjds_gdc_issuance_owner FROM kjds_gdc_issuance_runtime")
            )
    try:
        assert issuer_port.issue_evidence(
            evidence_id=f"evd_{uuid4().hex}",
            content=content,
            source=record.source,
            source_ref=record.source_ref,
            effective_at=record.effective_at,
            effective_until=record.effective_until,
            metadata=metadata,
            issuance_sha256=metadata["coverage_intake_issuance_sha256"],
            authority_checked_at=checked_at,
        ) == record.id
    finally:
        issuer_port.dispose()


def test_runtime_high_privilege_membership_drift_is_rejected_bidirectionally(
    service, engine, monkeypatch
):
    _, evidence, scope = service
    _, manifest_id, _, _ = bound_payload(evidence, scope)
    content, record = evidence.content(manifest_id)
    metadata = dict(record.metadata)
    checked_at = datetime.fromisoformat(
        metadata["coverage_intake_authority_checked_at"]
    )
    high_role = f"kjds_gdc_high_{uuid4().hex[:12]}"
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        engine.coverage_issuer_engine.url.render_as_string(hide_password=False),
    )
    issuer_port = create_coverage_issuer_port(
        generic_url=engine.generic_engine.url.render_as_string(hide_password=False)
    )
    with engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM evidence_records),"
                "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
            )
        ).one()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        schema = admin.scalar(text("SELECT current_schema()"))
        admin.exec_driver_sql(
            f'CREATE ROLE "{high_role}" NOLOGIN NOINHERIT NOSUPERUSER '
            "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
        )
        admin.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{high_role}"')
        admin.exec_driver_sql(
            f'GRANT INSERT ON evidence_blobs,evidence_records TO "{high_role}"'
        )
        admin.exec_driver_sql(
            f'GRANT "{high_role}" TO kjds_gdc_issuance_runtime'
        )
    try:
        with pytest.raises(PermissionError, match="issuer login is not active"):
            issuer_port.issue_evidence(
                evidence_id=f"evd_{uuid4().hex}",
                content=content,
                source=record.source,
                source_ref=record.source_ref,
                effective_at=record.effective_at,
                effective_until=record.effective_until,
                metadata=metadata,
                issuance_sha256=metadata["coverage_intake_issuance_sha256"],
                authority_checked_at=checked_at,
            )
        with (
            engine.coverage_issuer_engine.begin() as issuer,
            pytest.raises(DBAPIError, match="principal is invalid"),
        ):
            issuer.execute(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": f"evd_{uuid4().hex}",
                    "content": content,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "effective_at": record.effective_at,
                    "effective_until": record.effective_until,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "issuance_sha256": metadata[
                        "coverage_intake_issuance_sha256"
                    ],
                    "authority_checked_at": checked_at,
                },
            )
        fake_sha = hashlib.sha256(b"{}").hexdigest()
        with (
            engine.coverage_issuer_engine.begin() as issuer,
            pytest.raises(DBAPIError, match="dedicated issuer"),
        ):
            issuer.exec_driver_sql(f'SET LOCAL ROLE "{high_role}"')
            issuer.execute(
                text(
                    "INSERT INTO evidence_blobs(sha256,byte_size,content_bytes,created_at) "
                    "VALUES (:sha,2,decode('7b7d','hex'),now()) ON CONFLICT DO NOTHING"
                ),
                {"sha": fake_sha},
            )
            issuer.execute(
                text(
                    "INSERT INTO evidence_records(id,blob_sha256,filename,content_type,"
                    "source,source_ref,grade,effective_at,recorded_at,created_by,metadata_json) "
                    "VALUES (:id,:sha,'fake.json','application/json',"
                    "'global-data-coverage-manifest','high-role-fake','A',"
                    "now(),now(),'attacker','{}'::json)"
                ),
                {"id": f"evd_{uuid4().hex}", "sha": fake_sha},
            )
        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM evidence_records),"
                    "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
                )
            ).one()
        assert after == before
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.exec_driver_sql(
                f'REVOKE "{high_role}" FROM kjds_gdc_issuance_runtime'
            )
            admin.exec_driver_sql(f'DROP OWNED BY "{high_role}"')
            admin.exec_driver_sql(f'DROP ROLE "{high_role}"')
    try:
        assert issuer_port.issue_evidence(
            evidence_id=f"evd_{uuid4().hex}",
            content=content,
            source=record.source,
            source_ref=record.source_ref,
            effective_at=record.effective_at,
            effective_until=record.effective_until,
            metadata=metadata,
            issuance_sha256=metadata["coverage_intake_issuance_sha256"],
            authority_checked_at=checked_at,
        ) == record.id
    finally:
        issuer_port.dispose()


@pytest.mark.parametrize(
    ("role", "drift_attribute", "restore_attribute"),
    (
        ("kjds_gdc_issuance_runtime", "NOLOGIN", "LOGIN"),
        ("kjds_gdc_issuance_runtime", "SUPERUSER", "NOSUPERUSER"),
        ("kjds_gdc_issuance_runtime", "INHERIT", "NOINHERIT"),
        ("kjds_gdc_issuance_runtime", "CREATEROLE", "NOCREATEROLE"),
        ("kjds_gdc_issuance_runtime", "CREATEDB", "NOCREATEDB"),
        ("kjds_gdc_issuance_runtime", "REPLICATION", "NOREPLICATION"),
        ("kjds_gdc_issuance_runtime", "BYPASSRLS", "NOBYPASSRLS"),
        ("kjds_gdc_issuance_owner", "LOGIN", "NOLOGIN"),
        ("kjds_gdc_issuance_owner", "SUPERUSER", "NOSUPERUSER"),
        ("kjds_gdc_issuance_owner", "INHERIT", "NOINHERIT"),
        ("kjds_gdc_issuance_owner", "CREATEROLE", "NOCREATEROLE"),
        ("kjds_gdc_issuance_owner", "CREATEDB", "NOCREATEDB"),
        ("kjds_gdc_issuance_owner", "REPLICATION", "NOREPLICATION"),
        ("kjds_gdc_issuance_owner", "NOBYPASSRLS", "BYPASSRLS"),
    ),
)
def test_dynamic_issuer_role_attribute_drift_is_rejected_per_call(
    service, engine, monkeypatch, role, drift_attribute, restore_attribute
):
    _, evidence, scope = service
    _, manifest_id, _, _ = bound_payload(evidence, scope)
    content, record = evidence.content(manifest_id)
    metadata = dict(record.metadata)
    checked_at = datetime.fromisoformat(
        metadata["coverage_intake_authority_checked_at"]
    )
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        engine.coverage_issuer_engine.url.render_as_string(hide_password=False),
    )
    issuer_port = create_coverage_issuer_port(
        generic_url=engine.generic_engine.url.render_as_string(hide_password=False)
    )
    with engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM evidence_records),"
                "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
            )
        ).one()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.exec_driver_sql(f'ALTER ROLE "{role}" {drift_attribute}')
    try:
        with pytest.raises(PermissionError, match="issuer login is not active"):
            issuer_port.issue_evidence(
                evidence_id=f"evd_{uuid4().hex}",
                content=content,
                source=record.source,
                source_ref=record.source_ref,
                effective_at=record.effective_at,
                effective_until=record.effective_until,
                metadata=metadata,
                issuance_sha256=metadata["coverage_intake_issuance_sha256"],
                authority_checked_at=checked_at,
            )
        with (
            engine.coverage_issuer_engine.begin() as issuer,
            pytest.raises(DBAPIError, match="principal is invalid"),
        ):
            issuer.execute(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": f"evd_{uuid4().hex}",
                    "content": content,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "effective_at": record.effective_at,
                    "effective_until": record.effective_until,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "issuance_sha256": metadata[
                        "coverage_intake_issuance_sha256"
                    ],
                    "authority_checked_at": checked_at,
                },
            )
        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM evidence_records),"
                    "(SELECT count(*) FROM global_data_coverage_evidence_issuances)"
                )
            ).one()
        assert after == before
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.exec_driver_sql(f'ALTER ROLE "{role}" {restore_attribute}')
    try:
        assert issuer_port.issue_evidence(
            evidence_id=record.id,
            content=content,
            source=record.source,
            source_ref=record.source_ref,
            effective_at=record.effective_at,
            effective_until=record.effective_until,
            metadata=metadata,
            issuance_sha256=metadata["coverage_intake_issuance_sha256"],
            authority_checked_at=checked_at,
        ) == record.id
    finally:
        issuer_port.dispose()


@pytest.mark.parametrize(
    "drift",
    ("missing_data_as_of", "missing_upstream_recorded_at", "future_checked_at", "expired"),
)
def test_database_issuer_rejects_authority_time_drift(service, engine, drift):
    _, evidence, scope = service
    _, manifest_id, _, _ = bound_payload(evidence, scope)
    content, record = evidence.content(manifest_id)
    metadata = dict(record.metadata)
    checked_at = datetime.fromisoformat(
        metadata["coverage_intake_authority_checked_at"]
    )
    if drift == "missing_data_as_of":
        metadata.pop("coverage_intake_data_as_of")
    elif drift == "missing_upstream_recorded_at":
        metadata.pop("coverage_intake_upstream_recorded_at")
    elif drift == "future_checked_at":
        checked_at = datetime.now(UTC) + timedelta(hours=1)
        metadata["coverage_intake_authority_checked_at"] = checked_at.isoformat()
    else:
        assert record.effective_until is not None
        checked_at = datetime.fromisoformat(record.effective_until)
        metadata["coverage_intake_authority_checked_at"] = checked_at.isoformat()
    with engine.coverage_issuer_engine.connect() as issuer:
        transaction = issuer.begin()
        with pytest.raises(DBAPIError, match="contract drifted"):
            issuer.execute(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": f"evd_{uuid4().hex}",
                    "content": content,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "effective_at": record.effective_at,
                    "effective_until": record.effective_until,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "issuance_sha256": record.metadata[
                        "coverage_intake_issuance_sha256"
                    ],
                    "authority_checked_at": checked_at,
                },
            )
        transaction.rollback()


def test_inflight_issuer_and_downgrade_share_one_advisory_lock(service, engine):
    _, evidence, scope = service
    _, manifest_id, _, _ = bound_payload(evidence, scope)
    content, record = evidence.content(manifest_id)
    metadata = dict(record.metadata)
    checked_at = datetime.fromisoformat(
        metadata["coverage_intake_authority_checked_at"]
    )
    issuer_ready = Event()
    release_issuer = Event()

    def hold_issuer_transaction():
        with engine.coverage_issuer_engine.begin() as issuer:
            returned = issuer.scalar(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": f"evd_{uuid4().hex}",
                    "content": content,
                    "source": record.source,
                    "source_ref": record.source_ref,
                    "effective_at": record.effective_at,
                    "effective_until": record.effective_until,
                    "metadata": json.dumps(metadata, separators=(",", ":")),
                    "issuance_sha256": metadata[
                        "coverage_intake_issuance_sha256"
                    ],
                    "authority_checked_at": checked_at,
                },
            )
            assert returned == record.id
            issuer_ready.set()
            assert release_issuer.wait(10)

    def attempt_downgrade():
        with pytest.raises(RuntimeError, match="downgrade refused"):
            command.downgrade(migration_config(engine), "20260803_0094")

    with ThreadPoolExecutor(max_workers=2) as pool:
        issuer_future = pool.submit(hold_issuer_transaction)
        assert issuer_ready.wait(10)
        downgrade_future = pool.submit(attempt_downgrade)
        time.sleep(0.5)
        assert not downgrade_future.done()
        release_issuer.set()
        issuer_future.result(timeout=10)
        downgrade_future.result(timeout=10)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260804_0095"
        )


def test_direct_sql_cannot_self_sign_reserved_issuance_with_arbitrary_guc(
    service, engine
):
    ledger, evidence, scope = service
    receipt = write(ledger, payload=bound_payload(evidence, scope), key="trusted-seed")
    with Session(engine.generic_engine) as session:
        function_contract = session.execute(
            text(
                "SELECT r.rolname,p.prosecdef,p.proconfig "
                "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                "WHERE p.oid='kjds_gdc_issue_evidence"
                "(text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz)'"
                "::regprocedure"
            )
        ).one()
        assert function_contract.rolname == "kjds_gdc_issuance_owner"
        assert function_contract.prosecdef is True
        assert function_contract.proconfig == ["search_path=pg_catalog, public"]
        assert session.scalar(
            text(
                "SELECT has_function_privilege(current_user,"
                "'kjds_gdc_issue_evidence(text,bytea,text,text,timestamptz,"
                "timestamptz,jsonb,text,timestamptz)',"
                "'EXECUTE')"
            )
        ) is False
        assert session.scalar(
            text(
                "SELECT has_table_privilege('kjds_gdc_issuance_runtime',"
                "'global_data_coverage_evidence_issuances','INSERT')"
            )
        ) is False
        with pytest.raises(DBAPIError, match="permission denied"):
            session.execute(
                text(
                    "SELECT kjds_gdc_issue_evidence('evd_" + "a" * 24 + "',"
                    "decode('7b7d','hex'),'global-data-coverage-manifest','fake',"
                    "now(),now()+interval '1 day','{}'::jsonb,'" + "a" * 64 + "',now())"
                )
            )
    with engine.coverage_issuer_engine.connect() as issuer_connection:
        assert issuer_connection.execute(text("SELECT current_user,session_user")).one() == (
            "kjds_gdc_issuance_runtime",
            "kjds_gdc_issuance_runtime",
        )
        with pytest.raises(DBAPIError, match="permission denied"):
            issuer_connection.execute(
                text(
                    "SELECT signing_key_secret FROM "
                    "global_data_coverage_issuance_authorities"
                )
            ).all()
    with (
        engine.coverage_issuer_engine.connect() as issuer_connection,
        pytest.raises(DBAPIError, match="permission denied"),
    ):
        issuer_connection.execute(text("SET ROLE kjds_gdc_issuance_owner"))
    with engine.generic_engine.begin() as generic_connection:
        fake_sha = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        generic_connection.execute(
            text(
                "INSERT INTO evidence_blobs(sha256,byte_size,content_bytes,created_at) "
                "VALUES (:sha,2,decode('7b7d','hex'),now()) ON CONFLICT DO NOTHING"
            ),
            {"sha": fake_sha},
        )
        with (
            pytest.raises(DBAPIError, match="dedicated issuer"),
            generic_connection.begin_nested(),
        ):
            generic_connection.execute(
                text(
                    "INSERT INTO evidence_records(id,blob_sha256,filename,content_type,"
                    "source,source_ref,grade,effective_at,recorded_at,created_by,metadata_json) "
                    "VALUES ('evd_aaaaaaaaaaaaaaaaaaaaaaaa','" + fake_sha + "','fake.json',"
                    "'application/json','global-data-coverage-manifest','fake','A',now(),now(),"
                    "'attacker','{}'::json)"
                )
            )
    assert receipt.snapshot_id


def test_runtime_factory_connects_only_the_dedicated_issuer_login(
    engine, monkeypatch
):
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        engine.coverage_issuer_engine.url.render_as_string(hide_password=False),
    )
    issuer = create_coverage_issuer_port(
        generic_url=engine.generic_engine.url.render_as_string(hide_password=False),
    )
    try:
        assert not hasattr(issuer, "engine")
        assert not hasattr(issuer, "url")
    finally:
        issuer.dispose()


def test_service_to_postgres_lifecycle_and_transaction_stamp(service, engine):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    receipt = write(ledger, payload=payload, key="lifecycle")
    assert receipt.idempotent is False
    assert ledger.get(
        principal=principal(), store_ref=STORE, snapshot_id=receipt.snapshot_id
    ).snapshot_id == receipt.snapshot_id
    assert receipt.snapshot_id in {
        item.snapshot_id
        for item in ledger.list(principal=principal(), store_ref=STORE)
    }
    with engine.connect() as connection:
        root_tx = connection.scalar(
            text(
                "SELECT transaction_stamp FROM global_data_coverage_snapshots "
                "WHERE snapshot_id=:snapshot"
            ),
            {"snapshot": receipt.snapshot_id},
        )
        assert root_tx > 0
        for table in CHILDREN:
            stamps = connection.execute(
                text(f"SELECT DISTINCT transaction_stamp FROM {table} WHERE snapshot_id=:snapshot"),
                {"snapshot": receipt.snapshot_id},
            ).scalars().all()
            if stamps:
                assert stamps == [root_tx]


def test_sixteen_concurrent_same_key_has_one_durable_winner(service, engine):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    with ThreadPoolExecutor(max_workers=16) as pool:
        receipts = list(
            pool.map(lambda _index: write(ledger, payload=payload, key="concurrent"), range(16))
        )
    assert len({item.snapshot_id for item in receipts}) == 1
    assert sum(not item.idempotent for item in receipts) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(GlobalDataCoverageSnapshotRow)
                .where(GlobalDataCoverageSnapshotRow.snapshot_id == receipts[0].snapshot_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(GlobalDataCoverageEventRow)
                .where(GlobalDataCoverageEventRow.snapshot_id == receipts[0].snapshot_id)
            )
            == 2
        )
        root_counts = session.execute(
            text(
                "SELECT required_field_count,page_failed_count,window_gap_count,"
                "window_overlap_count,conflict_count,evidence_count "
                "FROM global_data_coverage_snapshots WHERE snapshot_id=:sid"
            ),
            {"sid": receipts[0].snapshot_id},
        ).mappings().one()
        expected_counts = {
            "global_data_coverage_native_caps": 1,
            "global_data_coverage_fields": root_counts["required_field_count"],
            "global_data_coverage_failed_pages": root_counts["page_failed_count"],
            "global_data_coverage_windows": 2
            + root_counts["window_gap_count"]
            + root_counts["window_overlap_count"],
            "global_data_coverage_conflicts": root_counts["conflict_count"],
            "global_data_coverage_evidence_links": root_counts["evidence_count"],
            "global_data_coverage_events": 2,
        }
        for table_name, expected in expected_counts.items():
            table = reflected(engine, table_name)
            assert session.scalar(
                select(func.count()).select_from(table).where(
                    table.c.snapshot_id == receipts[0].snapshot_id
                )
            ) == expected
        assert session.scalar(
            text(
                "SELECT count(*) FROM evidence_records WHERE source='global-data-coverage-ledger' "
                "AND source_ref LIKE :prefix"
            ),
            {"prefix": f"coverage-ledger://{receipts[0].snapshot_id}/%"},
        ) == 2


def test_exact_scope_and_evidence_foreign_keys_are_composite(engine):
    required_scope = {
        "snapshot_id",
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "scope_grant_authority_sha256",
        "transaction_stamp",
    }
    with engine.connect() as connection:
        for table_name in CHILDREN:
            definitions = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "WHERE t.relname=:table AND c.contype='f'"
                ),
                {"table": table_name},
            ).scalars().all()
            assert any(all(column in definition for column in required_scope) for definition in definitions)
        for table_name in (
            "global_data_coverage_evidence_links",
            "global_data_coverage_events",
        ):
            definitions = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "WHERE t.relname=:table AND c.contype='f'"
                ),
                {"table": table_name},
            ).scalars().all()
            assert any(
                all(
                    column in definition
                    for column in (
                        "evidence_id",
                        "evidence_sha256",
                        "evidence_source",
                        "evidence_source_ref",
                        "evidence_grade",
                        "evidence_effective_at",
                    )
                )
                for definition in definitions
            )


def test_orm_named_constraints_are_present_in_postgres_schema(engine):
    metadata = GlobalDataCoverageSnapshotRow.metadata
    required_by_table = {
        "global_data_coverage_snapshots": {
            "uq_gdc_scope_idempotency",
            "uq_gdc_snapshot_exact_scope_tx",
            "ck_gdc_snapshot_hashes",
            "ck_gdc_snapshot_transaction_stamp",
            "ck_gdc_snapshot_contracts",
            "ck_gdc_snapshot_conservation",
            "ck_gdc_page_conservation",
            "ck_gdc_denominator_matrix",
            "ck_gdc_snapshot_chronology",
            "ck_gdc_snapshot_status_vocabulary",
            "ck_gdc_no_promotion_or_write",
        },
        "global_data_coverage_evidence_links": {
            "fk_gdc_evidence_exact_scope",
            "fk_gdc_evidence_exact_binding",
            "ck_gdc_evidence_role",
            "ck_gdc_evidence_role_binding",
        },
        "global_data_coverage_events": {
            "fk_gdc_event_exact_scope",
            "fk_gdc_event_evidence_binding",
            "ck_gdc_event_type",
            "ck_gdc_event_binding",
        },
        "global_data_coverage_conflicts": {
            "fk_gdc_conflict_exact_scope",
            "ck_gdc_conflict_hashes",
            "ck_gdc_conflict_resolution",
        },
    }
    with engine.connect() as connection:
        for table_name, required in required_by_table.items():
            orm_names = {
                constraint.name
                for constraint in metadata.tables[table_name].constraints
                if constraint.name
            }
            postgres_names = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid WHERE t.relname=:table"
                    ),
                    {"table": table_name},
                ).scalars()
            )
            assert required <= orm_names
            assert required <= postgres_names


def test_all_ledger_tables_match_postgres_orm_contract(engine):
    metadata = GlobalDataCoverageSnapshotRow.metadata

    def normalized(value: str) -> str:
        compact = re.sub(r"[\s()]+", "", value.lower())
        return compact.replace("::text", "")

    def normalized_type(value: str) -> str:
        compact = value.lower()
        compact = compact.replace("character varying", "varchar")
        compact = compact.replace("timestamp with time zone", "timestamptz")
        return re.sub(r"\s+", "", compact)

    expected_fragments = {
        ("global_data_coverage_snapshots", "ck_gdc_snapshot_hashes"): tuple(
            f"{column}~'^[0-9a-f]{{64}}$'"
            for column in (
                "scope_grant_authority_sha256",
                "manifest_sha256",
                "manifest_evidence_sha256",
                "native_caps_sha256",
                "native_caps_evidence_sha256",
                "registry_sha256",
                "observation_sha256",
                "idempotency_sha256",
                "request_sha256",
                "checkpoint_sha256",
            )
        ),
        (
            "global_data_coverage_snapshots",
            "ck_gdc_snapshot_transaction_stamp",
        ): ("transaction_stamp>0",),
        ("global_data_coverage_snapshots", "ck_gdc_snapshot_contracts"): (
            "ledger_contract_id='kjds-global-data-coverage-ledger-v1'",
            "length(source_contract_id)>0",
            "length(source_contract_version)>0",
            "manifest_schema_version='kjds-source-coverage-manifest-v1'",
            "manifest_evidence_contract_id="
            "'kjds-global-data-coverage-manifest-evidence-v1'",
            "native_caps_schema='kjds-source-native-caps-v1'",
            "native_caps_evidence_contract_id="
            "'kjds-global-data-coverage-native-caps-evidence-v1'",
        ),
        ("global_data_coverage_native_caps", "ck_gdc_caps_hash"): (
            "content_sha256~'^[0-9a-f]{64}$'",
        ),
        ("global_data_coverage_fields", "ck_gdc_field_ordinal_hash"): (
            "ordinal>0",
            "field_name_sha256~'^[0-9a-f]{64}$'",
        ),
        ("global_data_coverage_failed_pages", "ck_gdc_page_ordinal_hash"): (
            "ordinal>0",
            "failed_ref_sha256~'^[0-9a-f]{64}$'",
        ),
        ("global_data_coverage_windows", "ck_gdc_window_interval"): (
            "ordinal>0",
            "start_at<end_at",
        ),
        ("global_data_coverage_conflicts", "ck_gdc_conflict_hashes"): (
            "ordinal>0",
            "conflict_ref_sha256~'^[0-9a-f]{64}$'",
            "subject_ref_sha256~'^[0-9a-f]{64}$'",
            "field_name_sha256~'^[0-9a-f]{64}$'",
            "valid_interval_sha256~'^[0-9a-f]{64}$'",
        ),
        ("global_data_coverage_conflicts", "ck_gdc_conflict_values"): (
            "value_hash_count>=2",
            "value_hash_count<=20",
            "value_hashes_sha256~'^[0-9a-f]{64}$'",
        ),
        (
            "global_data_coverage_evidence_links",
            "ck_gdc_evidence_scope_authority",
        ): (
            "intake_issuance_sha256~'^[0-9a-f]{64}$'",
            "intake_issuance_signature_sha256~'^[0-9a-f]{64}$'",
            "scope_binding_evidence_sha256~'^[0-9a-f]{64}$'",
        ),
        ("global_data_coverage_events", "ck_gdc_event_binding"): (
            "previous_event_sha256~'^[0-9a-f]{64}$'",
            "event_sha256~'^[0-9a-f]{64}$'",
        ),
    }
    with engine.connect() as connection:
        for table_name in TABLES:
            orm_table = metadata.tables[table_name]
            orm_constraint_names = {
                constraint.name
                for constraint in orm_table.constraints
                if constraint.name and not constraint.name.endswith("_sqlite")
            }
            postgres_constraint_names = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname=current_schema() AND t.relname=:table "
                        "AND c.contype IN ('c','u','f','x')"
                    ),
                    {"table": table_name},
                ).scalars()
            )
            assert orm_constraint_names == postgres_constraint_names

            orm_index_names = {index.name for index in orm_table.indexes if index.name}
            postgres_index_names = set(
                connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() "
                        "AND tablename=:table AND indexname LIKE 'ix_gdc_%'"
                    ),
                    {"table": table_name},
                ).scalars()
            )
            assert orm_index_names == postgres_index_names

            postgres_columns = {
                row[0]: row[1:]
                for row in connection.execute(
                    text(
                        "SELECT a.attname,format_type(a.atttypid,a.atttypmod),"
                        "a.attnotnull,pg_get_expr(d.adbin,d.adrelid) "
                        "FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid "
                        "AND d.adnum=a.attnum WHERE n.nspname=current_schema() "
                        "AND t.relname=:table AND a.attnum>0 AND NOT a.attisdropped"
                    ),
                    {"table": table_name},
                ).all()
            }
            assert set(orm_table.c.keys()) == set(postgres_columns)
            for orm_column in orm_table.c:
                postgres_type, postgres_not_null, postgres_default = postgres_columns[
                    orm_column.name
                ]
                orm_type = orm_column.type.compile(dialect=postgresql.dialect())
                assert normalized_type(orm_type) == normalized_type(postgres_type)
                assert orm_column.nullable is (not postgres_not_null)
                orm_default = (
                    None
                    if orm_column.server_default is None
                    else normalized(str(orm_column.server_default.arg))
                )
                database_default = (
                    None
                    if postgres_default is None
                    else normalized(postgres_default)
                )
                assert orm_default == database_default

        postgres_definitions = {
            (row[0], row[1]): row[2]
            for row in connection.execute(
                text(
                    "SELECT t.relname,c.conname,pg_get_constraintdef(c.oid,true) "
                    "FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname=current_schema() AND t.relname=ANY(:tables) "
                    "AND c.contype='c'"
                ),
                {"tables": list(TABLES)},
            ).all()
        }
        for key, fragments in expected_fragments.items():
            orm_constraint = next(
                constraint
                for constraint in metadata.tables[key[0]].constraints
                if isinstance(constraint, CheckConstraint) and constraint.name == key[1]
            )
            orm_definition = normalized(str(orm_constraint.sqltext))
            postgres_definition = normalized(postgres_definitions[key])
            for fragment in fragments:
                expected = normalized(fragment)
                assert expected in orm_definition
                assert expected in postgres_definition


def test_conservation_constraint_triggers_are_frozen_separately_from_orm(engine):
    with engine.connect() as connection:
        for table_name in TABLES:
            trigger = connection.execute(
                text(
                    "SELECT t.tgname,t.tgconstraint<>0,t.tgdeferrable,"
                    "t.tginitdeferred,c.contype,p.proname,pg_get_triggerdef(t.oid,true) "
                    "FROM pg_trigger t JOIN pg_class target ON target.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=target.relnamespace "
                    "LEFT JOIN pg_constraint c ON c.oid=t.tgconstraint "
                    "JOIN pg_proc p ON p.oid=t.tgfoid "
                    "WHERE n.nspname=current_schema() AND target.relname=:table "
                    "AND t.tgname=:trigger AND NOT t.tgisinternal"
                ),
                {
                    "table": table_name,
                    "trigger": f"trg_{table_name}_conservation",
                },
            ).one()
            assert trigger[:6] == (
                f"trg_{table_name}_conservation",
                True,
                True,
                True,
                "t",
                "kjds_gdc_conservation",
            )
            definition = re.sub(r"\s+", " ", trigger[6].lower())
            assert "create constraint trigger" in definition
            assert "after insert" in definition
            assert "deferrable initially deferred" in definition
            assert "for each row" in definition
            assert "execute function kjds_gdc_conservation()" in definition


@pytest.mark.parametrize(
    "column",
    ["tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
)
def test_exact_scope_foreign_key_rejects_each_scope_drift(service, engine, column):
    ledger, evidence, scope = service
    receipt = write(
        ledger,
        payload=bound_payload(evidence, scope),
        key=f"scope-fk-drift-{column}",
    )
    table = reflected(engine, "global_data_coverage_windows")
    values = clone_values(
        engine, "global_data_coverage_windows", snapshot_id=receipt.snapshot_id
    )
    values["window_id"] = f"gdcw_{uuid4().hex}"
    values["ordinal"] = int(values["ordinal"]) + 1000
    values[column] = "f" * 64 if column.endswith("sha256") else f"drift-{column}"
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(table.insert(), values)
        connection.execute(text("SET CONSTRAINTS fk_gdc_window_exact_scope IMMEDIATE"))


@pytest.mark.parametrize(
    "field",
    [
        "evidence_id",
        "evidence_sha256",
        "evidence_source",
        "evidence_source_ref",
        "evidence_grade",
        "evidence_effective_at",
        "evidence_effective_until",
    ],
)
def test_database_rejects_each_intake_evidence_binding_drift(
    service, monkeypatch, field
):
    ledger, evidence, scope = service
    original_init = GlobalDataCoverageEvidenceLinkRow.__init__

    def forged_init(self, **kwargs):
        monkeypatch.setattr(GlobalDataCoverageEvidenceLinkRow, "__init__", original_init)
        replacements = {
            "evidence_id": f"evd_{uuid4().hex}",
            "evidence_sha256": "f" * 64,
            "evidence_source": "fixture-drift",
            "evidence_source_ref": "fixture-drift://binding",
            "evidence_grade": "B",
            "evidence_effective_at": kwargs["evidence_effective_at"] - timedelta(seconds=1),
            "evidence_effective_until": kwargs["evidence_effective_until"]
            + timedelta(seconds=1),
        }
        kwargs[field] = replacements[field]
        original_init(self, **kwargs)

    monkeypatch.setattr(GlobalDataCoverageEvidenceLinkRow, "__init__", forged_init)
    monkeypatch.setattr(ledger, "_receipt", lambda *_args, **_kwargs: None)
    with pytest.raises(DBAPIError):
        write(
            ledger,
            payload=bound_payload(evidence, scope),
            key=f"intake-binding-drift-{field}",
        )


def test_database_recomputes_event_hash(service, engine, monkeypatch):
    ledger, evidence, scope = service
    before = engine.connect().scalar(text("SELECT count(*) FROM global_data_coverage_snapshots"))
    original = ledger_module._coverage_event_sha256

    def wrong_first_hash(**kwargs):
        if kwargs["event_type"] == "snapshot_started":
            return "f" * 64
        return original(**kwargs)

    monkeypatch.setattr(ledger_module, "_coverage_event_sha256", wrong_first_hash)
    with pytest.raises(DBAPIError, match="event chain conservation"):
        write(ledger, payload=bound_payload(evidence, scope), key="bad-event-hash")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM global_data_coverage_snapshots")) == before


def test_database_rejects_event_evidence_metadata_drift(service, engine, monkeypatch):
    ledger, evidence, scope = service
    original = evidence.capture_global_data_coverage_ledger_event

    def capture_with_drift(**kwargs):
        kwargs["metadata"] = {**kwargs["metadata"], "request_sha256": "f" * 64}
        return original(**kwargs)

    monkeypatch.setattr(evidence, "capture_global_data_coverage_ledger_event", capture_with_drift)
    monkeypatch.setattr(ledger, "_verify_events", lambda *_args, **_kwargs: None)
    with pytest.raises(DBAPIError, match="event chain conservation"):
        write(ledger, payload=bound_payload(evidence, scope), key="bad-event-metadata")


@pytest.mark.parametrize(
    ("column", "mutated"),
    [
        ("checkpoint_sequence", 999),
        ("page_duplicate_count", 1),
        ("window_late_arrival_count", 1),
        ("expected_count", 101),
    ],
)
def test_canonical_manifest_blob_rejects_self_consistent_root_drift(
    service, monkeypatch, column, mutated
):
    ledger, evidence, scope = service
    original_init = GlobalDataCoverageSnapshotRow.__init__

    def forged_init(self, **kwargs):
        monkeypatch.setattr(GlobalDataCoverageSnapshotRow, "__init__", original_init)
        kwargs[column] = mutated
        original_init(self, **kwargs)

    monkeypatch.setattr(GlobalDataCoverageSnapshotRow, "__init__", forged_init)
    with pytest.raises(DBAPIError, match="canonical projection drifted"):
        write(
            ledger,
            payload=bound_payload(evidence, scope),
            key=f"canonical-root-drift-{column}",
        )


@pytest.mark.parametrize(
    ("row_type", "field", "replacement", "message"),
    [
        (
            GlobalDataCoverageNativeCapsRow,
            "schema_version",
            "fixture-drift-schema",
            "native caps canonical projection drifted",
        ),
        (
            GlobalDataCoverageFieldRow,
            "field_name_sha256",
            "f" * 64,
            "field canonical identity drifted",
        ),
        (
            GlobalDataCoverageWindowRow,
            "start_at",
            None,
            "window canonical projection drifted",
        ),
    ],
)
def test_database_rejects_typed_child_canonical_drift(
    service, monkeypatch, row_type, field, replacement, message
):
    ledger, evidence, scope = service
    original_init = row_type.__init__

    def forged_init(self, **kwargs):
        monkeypatch.setattr(row_type, "__init__", original_init)
        kwargs[field] = (
            kwargs[field] - timedelta(seconds=1) if replacement is None else replacement
        )
        original_init(self, **kwargs)

    monkeypatch.setattr(row_type, "__init__", forged_init)
    monkeypatch.setattr(ledger, "_receipt", lambda *_args, **_kwargs: None)
    with pytest.raises(DBAPIError, match=message):
        write(
            ledger,
            payload=bound_payload(evidence, scope),
            key=f"typed-child-drift-{row_type.__tablename__}",
        )


def test_database_rejects_failed_page_canonical_drift(service, monkeypatch):
    ledger, evidence, scope = service

    def add_failed_page(manifest):
        pages = manifest["coverage"]["pages"]
        pages["received_count"] = 1
        pages["failed_count"] = 1
        pages["failed_refs"] = ["page://fixture/failed-1"]

    original_init = GlobalDataCoverageFailedPageRow.__init__

    def forged_init(self, **kwargs):
        monkeypatch.setattr(GlobalDataCoverageFailedPageRow, "__init__", original_init)
        kwargs["failed_ref_sha256"] = "f" * 64
        original_init(self, **kwargs)

    monkeypatch.setattr(GlobalDataCoverageFailedPageRow, "__init__", forged_init)
    monkeypatch.setattr(ledger, "_receipt", lambda *_args, **_kwargs: None)
    with pytest.raises(DBAPIError, match="failed-page canonical projection drifted"):
        write(
            ledger,
            payload=bound_payload(evidence, scope, manifest_mutator=add_failed_page),
            key="failed-page-canonical-drift",
        )


def test_database_rejects_conflict_canonical_drift(service, monkeypatch):
    ledger, evidence, scope = service

    def add_conflict(manifest):
        field = manifest["coverage"]["fields"]["present"].pop()
        manifest["coverage"]["fields"]["conflicting"] = [field]
        manifest["conflicts"] = [
            {
                "conflict_ref": "conflict://fixture/1",
                "subject_ref_sha256": "d" * 64,
                "field": field,
                "valid_interval_sha256": "e" * 64,
                "value_hashes": ["1" * 64, "2" * 64],
                "resolution_status": "unresolved",
            }
        ]

    original_init = GlobalDataCoverageConflictRow.__init__

    def forged_init(self, **kwargs):
        monkeypatch.setattr(GlobalDataCoverageConflictRow, "__init__", original_init)
        kwargs["subject_ref_sha256"] = "f" * 64
        original_init(self, **kwargs)

    monkeypatch.setattr(GlobalDataCoverageConflictRow, "__init__", forged_init)
    monkeypatch.setattr(ledger, "_receipt", lambda *_args, **_kwargs: None)
    with pytest.raises(DBAPIError, match="conflict canonical projection drifted"):
        write(
            ledger,
            payload=bound_payload(evidence, scope, manifest_mutator=add_conflict),
            key="conflict-canonical-drift",
        )


def test_database_rejects_cross_scope_supporting_evidence(service, engine, monkeypatch):
    ledger, evidence, scope = service
    wrong_scope_record = None

    def supporting_factory(as_of):
        nonlocal wrong_scope_record
        content = b'{"contract_id":"fixture-support-v1"}'
        digest = __import__("hashlib").sha256(content).hexdigest()
        recorded_at = as_of - timedelta(hours=1)
        effective_at = as_of - timedelta(hours=2)
        effective_until = as_of + timedelta(days=1)
        good_id = f"evd_{uuid4().hex}"
        bad_id = f"evd_{uuid4().hex}"
        with Session(engine) as session, session.begin():
            if session.get(EvidenceBlobRow, digest) is None:
                session.add(
                    EvidenceBlobRow(
                        sha256=digest,
                        byte_size=len(content),
                        content_bytes=content,
                        created_at=recorded_at,
                    )
                )
            for evidence_id, tenant in ((good_id, "tenant-a"), (bad_id, "tenant-b")):
                session.add(
                    EvidenceRecordRow(
                        id=evidence_id,
                        blob_sha256=digest,
                        filename="support.json",
                        content_type="application/json",
                        source="fixture-support",
                        source_ref=f"fixture-support://{evidence_id}",
                        grade=EvidenceGrade.A.value,
                        effective_at=effective_at,
                        effective_until=effective_until,
                        recorded_at=recorded_at,
                        created_by="fixture",
                        metadata_json={
                            "evidence_scope_contract_id": "kjds-evidence-scope-v1",
                            "tenant_ref": tenant,
                            "entity_ref": f"entity-{tenant}",
                            "store_ref": STORE,
                            "scope_grant_authority_sha256": authority_sha256(scope, tenant),
                            "reviewed_by": "independent-reviewer",
                        },
                    )
                )
        wrong_scope_record = replace(
            evidence.get_metadata(bad_id),
            effective_at=effective_at,
            effective_until=effective_until,
            recorded_at=recorded_at,
        )
        return [
            replace(
                evidence.get_metadata(good_id),
                effective_at=effective_at,
                effective_until=effective_until,
                recorded_at=recorded_at,
            )
        ]

    payload = bound_payload(evidence, scope, supporting_factory=supporting_factory)
    original_insert = ledger._insert_evidence_links

    def insert_with_cross_scope(session, row, evidence_records, manifest, now):
        supporting = next(
            record for role, record in evidence_records if role == "supporting"
        )
        forged_supporting = replace(
            wrong_scope_record,
            metadata={
                **wrong_scope_record.metadata,
                "_coverage_scope_authority_contract_id": supporting.metadata[
                    "_coverage_scope_authority_contract_id"
                ],
                "_coverage_scope_binding_evidence_id": None,
                "_coverage_scope_binding_evidence_sha256": None,
            },
        )
        forged_records = [
            (role, forged_supporting if role == "supporting" else record)
            for role, record in evidence_records
        ]
        return original_insert(session, row, forged_records, manifest, now)

    monkeypatch.setattr(ledger, "_insert_evidence_links", insert_with_cross_scope)
    with pytest.raises(DBAPIError, match="supporting Evidence scope or time drifted"):
        write(ledger, payload=payload, key="cross-scope-supporting")


def test_authority_rotation_same_key_is_independent_and_old_row_hidden(service):
    ledger, evidence, scope = service
    first = write(ledger, payload=bound_payload(evidence, scope), key="authority-key")
    scope.version = "v2"
    assert ledger.list(principal=principal(), store_ref=STORE) == []
    second = write(ledger, payload=bound_payload(evidence, scope), key="authority-key")
    assert second.snapshot_id != first.snapshot_id


def test_all_ledger_tables_and_reserved_evidence_are_append_only(service, engine):
    ledger, evidence, scope = service
    receipt = write(ledger, payload=bound_payload(evidence, scope), key="immutable")
    for table_name in TABLES:
        table = reflected(engine, table_name)
        primary_key = next(iter(table.primary_key.columns))
        with engine.connect() as connection:
            row_count = connection.scalar(
                select(func.count()).select_from(table).where(
                    table.c.snapshot_id == receipt.snapshot_id
                )
            )
            trigger_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE c.relname=:table AND t.tgname=:trigger AND NOT t.tgisinternal"
                ),
                {"table": table_name, "trigger": f"trg_{table_name}_immutable"},
            )
        assert trigger_count == 1
        if row_count == 0:
            continue
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(
                table.update()
                .where(table.c.snapshot_id == receipt.snapshot_id)
                .values({primary_key.name: primary_key})
            )
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(table.delete().where(table.c.snapshot_id == receipt.snapshot_id))
    evidence_id = evidence.list_by_source("global-data-coverage-ledger", limit=1)[0].id
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text("UPDATE evidence_records SET created_by='tamper' WHERE id=:id"),
            {"id": evidence_id},
        )


@pytest.mark.parametrize("table_name", CHILDREN)
def test_late_child_append_is_rejected(service, engine, table_name):
    ledger, evidence, scope = service
    receipt = write(
        ledger,
        payload=bound_payload(evidence, scope),
        key=f"late-{table_name}",
    )
    table = reflected(engine, table_name)
    with engine.connect() as connection:
        parent = connection.execute(
            text(
                "SELECT tenant_ref,entity_ref,store_ref,scope_grant_authority_sha256,"
                "transaction_stamp FROM global_data_coverage_snapshots WHERE snapshot_id=:sid"
            ),
            {"sid": receipt.snapshot_id},
        ).mappings().one()
    with engine.connect() as connection:
        exists = connection.scalar(
            text(f"SELECT EXISTS (SELECT 1 FROM {table_name} WHERE snapshot_id=:sid)"),
            {"sid": receipt.snapshot_id},
        )
    values = (
        clone_values(engine, table_name, snapshot_id=receipt.snapshot_id)
        if exists
        else {
            "snapshot_id": receipt.snapshot_id,
            **dict(parent),
        }
    )
    primary_key = next(iter(table.primary_key.columns)).name
    values[primary_key] = f"late_{uuid4().hex}"
    for candidate in ("ordinal", "event_index"):
        if candidate in values:
            values[candidate] = int(values[candidate]) + 1000
    if "evidence_id" in values:
        values["evidence_id"] = f"evd_late_{uuid4().hex}"
    with pytest.raises(DBAPIError, match="parent transaction"), engine.begin() as connection:
        connection.execute(table.insert(), values)


def test_complete_children_cannot_support_fake_full_claim(service, engine, monkeypatch):
    ledger, evidence, scope = service
    original_validate = ledger.workspace.validate

    def fake_full(*args, **kwargs):
        observation = original_validate(*args, **kwargs)
        return replace(
            observation,
            status="complete",
            completeness="complete",
            full_coverage_claim=True,
        )

    monkeypatch.setattr(ledger.workspace, "validate", fake_full)
    monkeypatch.setattr(ledger_module, "_ledger_full_claim_eligible", lambda *_args: True)
    with pytest.raises(DBAPIError, match="full claim semantic gate"):
        write(ledger, payload=bound_payload(evidence, scope), key="fake-full-complete-children")


def test_bad_root_chronology_is_rejected(service, engine):
    ledger, evidence, scope = service
    receipt = write(ledger, payload=bound_payload(evidence, scope), key="chronology-base")
    table = reflected(engine, TABLES[0])
    values = clone_values(engine, TABLES[0], snapshot_id=receipt.snapshot_id)
    values["snapshot_id"] = f"gdcs_{uuid4().hex}"
    values["idempotency_sha256"] = uuid4().hex * 2
    values["full_coverage_claim"] = False
    values["review_due"] = values["recorded_at"]
    values["fresh_until"] = values["recorded_at"]
    with pytest.raises(DBAPIError, match="ck_gdc_snapshot_chronology"), engine.begin() as connection:
        connection.execute(table.insert(), values)


def test_downgrade_uses_writer_compatible_lock_order_and_preserves_objects(engine):
    config = migration_config(engine)
    with engine.connect() as writer:
        transaction = writer.begin()
        writer.execute(text("LOCK TABLE global_data_coverage_snapshots IN ROW EXCLUSIVE MODE"))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(command.downgrade, config, "20260803_0094")
            time.sleep(0.25)
            assert not future.done()
            writer.execute(text("LOCK TABLE evidence_blobs IN ROW EXCLUSIVE MODE NOWAIT"))
            writer.execute(text("LOCK TABLE evidence_records IN ROW EXCLUSIVE MODE NOWAIT"))
            transaction.rollback()
            with pytest.raises(Exception, match="downgrade refused"):
                future.result(timeout=15)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260804_0095"
        assert all(
            connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) == name
            for name in TABLES
        )
        assert connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "WHERE c.relname='global_data_coverage_snapshots' "
                "AND t.tgname='trg_global_data_coverage_snapshots_immutable' "
                "AND NOT t.tgisinternal"
            )
        ) == 1


def test_populated_downgrade_fails_closed_and_preserves_head(engine):
    config = migration_config(engine)
    with pytest.raises(Exception, match="downgrade refused"):
        command.downgrade(config, "20260803_0094")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260804_0095"
        assert connection.scalar(text("SELECT count(*) FROM global_data_coverage_snapshots")) > 0
