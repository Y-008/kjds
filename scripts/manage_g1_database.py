from __future__ import annotations

import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from apps.control_plane.database import database_url

DATABASE_NAME = "kjds_g1_smoke"
ISSUER_OWNER_ROLE = "kjds_gdc_issuance_owner"
ISSUER_RUNTIME_ROLE = "kjds_gdc_issuance_runtime"
G1_RUNTIME_ROLE = "kjds_g1_runtime"
CLOE_OWNER_ROLE = "kjds_cloe_issuance_owner"
CLOE_EVENT_OWNER_ROLE = "kjds_cloe_event_issuance_owner"
CLOE_RUNTIME_ROLE = "kjds_cloe_issuance_runtime"
CLOE_AUTHORITY_ROLES = (
    "kjds_cloe_experiment_authority",
    "kjds_cloe_cost_authority",
    "kjds_cloe_outcome_authority",
    "kjds_cloe_review_authority",
)
ROLE_NAMES = (
    ISSUER_RUNTIME_ROLE,
    ISSUER_OWNER_ROLE,
    G1_RUNTIME_ROLE,
    CLOE_RUNTIME_ROLE,
    CLOE_OWNER_ROLE,
    CLOE_EVENT_OWNER_ROLE,
    *CLOE_AUTHORITY_ROLES,
)
GDC_CONTRACT_ROLE_NAMES = (
    ISSUER_RUNTIME_ROLE,
    ISSUER_OWNER_ROLE,
    "kjds_gdc_generic_runtime",
)
RUN_TOKEN_ENV = "KJDS_G1_RUN_TOKEN"
LEASE_ID = "kjds-g1-fixed-resources-v1"
LEASE_TABLE = "public.kjds_g1_run_leases"
GDC_RECEIPT_ID = "kjds-g1-gdc-contract-v1"
GDC_RECEIPT_TABLE = "public.kjds_g1_gdc_contract_receipts"
GDC_ADMIN_DATABASE_URL_ENV = "KJDS_G1_ADMIN_DATABASE_URL"
COMMENT_PREFIX = "kjds-g1-owner:"
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{48,160}$")
TOKEN_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GDC_SCHEMA_PATTERN = re.compile(r"^data_cov_002_[0-9a-f]{32}$")


@dataclass(frozen=True)
class _RoleCleanupPlan:
    roles: tuple[str, ...]
    memberships: tuple[tuple[str, str, bool], ...]
    revoke_public_schema_from: tuple[str, ...]


@dataclass(frozen=True)
class _G1RecoveryPlan:
    token_sha256: str
    roles_owned: bool
    database_owned: bool
    role_cleanup: _RoleCleanupPlan | None


@dataclass(frozen=True)
class _GdcRecoveryPlan:
    token_sha256: str
    schema_name: str
    roles_owned: bool
    schema_owned: bool
    role_cleanup: _RoleCleanupPlan | None


def _secret(name: str) -> str:
    value = str(os.getenv(name, ""))
    if not SECRET_PATTERN.fullmatch(value):
        raise RuntimeError(f"G-1 ephemeral credential {name} is missing or invalid")
    return value


def _run_token_sha256() -> str:
    return hashlib.sha256(_secret(RUN_TOKEN_ENV).encode()).hexdigest()


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise RuntimeError("G-1 database identifier is invalid")
    return f'"{value}"'


def _role_contract(role: str) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    if role not in set(ROLE_NAMES) | set(GDC_CONTRACT_ROLE_NAMES):
        raise RuntimeError("G-1 cleanup role is outside the fixed contract")
    login_roles = {
        ISSUER_RUNTIME_ROLE,
        G1_RUNTIME_ROLE,
        CLOE_RUNTIME_ROLE,
        *CLOE_AUTHORITY_ROLES,
        "kjds_gdc_generic_runtime",
    }
    bypass_roles = {
        ISSUER_OWNER_ROLE,
        G1_RUNTIME_ROLE,
        CLOE_OWNER_ROLE,
        CLOE_EVENT_OWNER_ROLE,
        "kjds_gdc_generic_runtime",
    }
    return (
        False,
        False,
        False,
        False,
        role in login_roles,
        False,
        role in bypass_roles,
    )


def _role_rows(connection, roles: tuple[str, ...]) -> dict[str, tuple[Any, ...]]:
    return {
        row.rolname: tuple(row[1:])
        for row in connection.execute(
            text(
                "SELECT r.rolname,r.rolsuper,r.rolinherit,r.rolcreaterole,"
                "r.rolcreatedb,r.rolcanlogin,r.rolreplication,r.rolbypassrls,"
                "shobj_description(r.oid,'pg_authid') AS ownership_comment "
                "FROM pg_roles r WHERE r.rolname=ANY(:roles)"
            ),
            {"roles": list(roles)},
        ).all()
    }


def _assert_role_receipts(
    connection,
    *,
    roles: tuple[str, ...],
    token_sha256: str,
) -> None:
    expected_comment = _ownership_comment(token_sha256)
    rows = _role_rows(connection, roles)
    if set(rows) != set(roles):
        raise RuntimeError("G-1 role ownership receipt set drifted")
    for role, values in rows.items():
        if tuple(values[:7]) != _role_contract(role):
            raise RuntimeError("G-1 role principal contract drifted")
        if values[7] != expected_comment:
            raise RuntimeError("G-1 role ownership receipt drifted")


def _ensure_lease_table(connection) -> None:
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {LEASE_TABLE}("
            "lease_id text PRIMARY KEY,run_token_sha256 char(64) NOT NULL,"
            "roles_owned boolean NOT NULL DEFAULT false,"
            "database_owned boolean NOT NULL DEFAULT false,"
            "acquired_at timestamptz NOT NULL DEFAULT clock_timestamp())"
        )
    )
    connection.execute(text(f"REVOKE ALL ON TABLE {LEASE_TABLE} FROM PUBLIC"))


def _ensure_gdc_receipt_table(connection) -> None:
    connection.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {GDC_RECEIPT_TABLE}("
            "receipt_id text PRIMARY KEY,run_token_sha256 char(64) NOT NULL,"
            "schema_name text NOT NULL,roles_owned boolean NOT NULL DEFAULT false,"
            "schema_owned boolean NOT NULL DEFAULT false,"
            "acquired_at timestamptz NOT NULL DEFAULT clock_timestamp())"
        )
    )
    connection.execute(text(f"REVOKE ALL ON TABLE {GDC_RECEIPT_TABLE} FROM PUBLIC"))


def _table_exists(connection, name: str) -> bool:
    return connection.scalar(text("SELECT to_regclass(:name)"), {"name": name}) is not None


def _g1_receipt(connection) -> tuple[str, bool, bool] | None:
    if not _table_exists(connection, LEASE_TABLE):
        return None
    row = connection.execute(
        text(
            f"SELECT run_token_sha256,roles_owned,database_owned FROM {LEASE_TABLE} "
            "WHERE lease_id=:lease_id"
        ),
        {"lease_id": LEASE_ID},
    ).one_or_none()
    if row is None:
        return None
    token = str(row.run_token_sha256)
    if not TOKEN_SHA256_PATTERN.fullmatch(token):
        raise RuntimeError("G-1 fixed-resource lease receipt drifted")
    return token, bool(row.roles_owned), bool(row.database_owned)


def _gdc_receipt(connection) -> tuple[str, str, bool, bool] | None:
    if not _table_exists(connection, GDC_RECEIPT_TABLE):
        return None
    row = connection.execute(
        text(
            f"SELECT run_token_sha256,schema_name,roles_owned,schema_owned "
            f"FROM {GDC_RECEIPT_TABLE} WHERE receipt_id=:receipt_id"
        ),
        {"receipt_id": GDC_RECEIPT_ID},
    ).one_or_none()
    if row is None:
        return None
    token = str(row.run_token_sha256)
    schema_name = str(row.schema_name)
    if not TOKEN_SHA256_PATTERN.fullmatch(token) or not GDC_SCHEMA_PATTERN.fullmatch(
        schema_name
    ):
        raise RuntimeError("G-1 GDC recovery receipt drifted")
    return token, schema_name, bool(row.roles_owned), bool(row.schema_owned)


def _acquire_lease(connection, token_sha256: str) -> None:
    _ensure_lease_table(connection)
    acquired = connection.scalar(
        text(
            f"INSERT INTO {LEASE_TABLE}(lease_id,run_token_sha256) "
            "VALUES (:lease_id,:token) ON CONFLICT DO NOTHING RETURNING lease_id"
        ),
        {"lease_id": LEASE_ID, "token": token_sha256},
    )
    if acquired != LEASE_ID:
        raise RuntimeError("G-1 fixed-resource lease is already held")


def _lease_state(connection, token_sha256: str) -> tuple[bool, bool]:
    _ensure_lease_table(connection)
    row = connection.execute(
        text(
            f"SELECT run_token_sha256,roles_owned,database_owned FROM {LEASE_TABLE} "
            "WHERE lease_id=:lease_id"
        ),
        {"lease_id": LEASE_ID},
    ).one_or_none()
    if row is None or row.run_token_sha256 != token_sha256:
        raise RuntimeError("G-1 fixed-resource lease is not owned by this run")
    return bool(row.roles_owned), bool(row.database_owned)


def _database_exists(connection) -> bool:
    return bool(
        connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=:name)"),
            {"name": DATABASE_NAME},
        )
    )


def _existing_roles(connection) -> list[str]:
    return list(
        connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles) ORDER BY rolname"),
            {"roles": list(ROLE_NAMES)},
        ).scalars()
    )


def _assert_resources_absent(connection) -> None:
    if _database_exists(connection) or _existing_roles(connection):
        raise RuntimeError("G-1 fixed resource already exists and is not owned by this run")


def _ownership_comment(token_sha256: str) -> str:
    return f"{COMMENT_PREFIX}{token_sha256}"


def _server_literal(connection, value: str) -> str:
    quoted = connection.scalar(text("SELECT quote_literal(:value)"), {"value": value})
    if not isinstance(quoted, str) or not quoted.startswith("'"):
        raise RuntimeError("G-1 server literal quoting failed")
    return quoted


def _database_comment(connection) -> str | None:
    return connection.scalar(
        text(
            "SELECT shobj_description(oid,'pg_database') FROM pg_database "
            "WHERE datname=:name"
        ),
        {"name": DATABASE_NAME},
    )


def _role_comments(connection) -> dict[str, str | None]:
    return dict(
        connection.execute(
            text(
                "SELECT rolname,shobj_description(oid,'pg_authid') FROM pg_roles "
                "WHERE rolname=ANY(:roles)"
            ),
            {"roles": list(ROLE_NAMES)},
        ).all()
    )


def _assert_owned_resources(
    connection,
    *,
    token_sha256: str,
    roles_owned: bool,
    database_owned: bool,
) -> None:
    expected = _ownership_comment(token_sha256)
    if database_owned:
        if not _database_exists(connection):
            raise RuntimeError("G-1 database ownership receipt set drifted")
        if _database_comment(connection) != expected:
            raise RuntimeError("G-1 database ownership receipt drifted")
    if roles_owned:
        _assert_role_receipts(
            connection,
            roles=ROLE_NAMES,
            token_sha256=token_sha256,
        )


def _create_owned_roles(
    admin_url: str,
    *,
    token_sha256: str,
    issuer_password: str,
    runtime_password: str,
    closed_loop_passwords: dict[str, str],
) -> None:
    engine = create_engine(admin_url)
    expected = _ownership_comment(token_sha256)
    try:
        with engine.begin() as connection:
            issuer_password_sql = _server_literal(connection, issuer_password)
            runtime_password_sql = _server_literal(connection, runtime_password)
            closed_loop_password_sql = {
                role: _server_literal(connection, password)
                for role, password in closed_loop_passwords.items()
            }
            expected_sql = _server_literal(connection, expected)
            roles_owned, database_owned = _lease_state(connection, token_sha256)
            if roles_owned or database_owned or _existing_roles(connection):
                raise RuntimeError("G-1 role creation precondition drifted")
            connection.exec_driver_sql(
                "CREATE ROLE kjds_gdc_issuance_owner NOLOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_gdc_issuance_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS "
                f"PASSWORD {issuer_password_sql}"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_g1_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS "
                f"PASSWORD {runtime_password_sql}"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_cloe_issuance_owner NOLOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_cloe_event_issuance_owner NOLOGIN NOINHERIT "
                "NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
            )
            for role in (CLOE_RUNTIME_ROLE, *CLOE_AUTHORITY_ROLES):
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role}" LOGIN NOINHERIT NOSUPERUSER '
                    "NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS "
                    f"PASSWORD {closed_loop_password_sql[role]}"
                )
            for role in ROLE_NAMES:
                connection.exec_driver_sql(
                    f'COMMENT ON ROLE "{role}" IS {expected_sql}'
                )
            connection.execute(
                text(
                    f"UPDATE {LEASE_TABLE} SET roles_owned=true "
                    "WHERE lease_id=:lease_id AND run_token_sha256=:token"
                ),
                {"lease_id": LEASE_ID, "token": token_sha256},
            )
    finally:
        engine.dispose()


def _create_owned_database(connection, token_sha256: str) -> None:
    roles_owned, database_owned = _lease_state(connection, token_sha256)
    if not roles_owned or database_owned or _database_exists(connection):
        raise RuntimeError("G-1 database creation precondition drifted")
    expected = _ownership_comment(token_sha256)
    expected_sql = _server_literal(connection, expected)
    connection.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
    connection.exec_driver_sql(
        f'COMMENT ON DATABASE "{DATABASE_NAME}" IS {expected_sql}'
    )
    connection.execute(
        text(
            f"UPDATE {LEASE_TABLE} SET database_owned=true "
            "WHERE lease_id=:lease_id AND run_token_sha256=:token"
        ),
        {"lease_id": LEASE_ID, "token": token_sha256},
    )


def _grant_runtime(target_url: str) -> None:
    engine = create_engine(target_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("GRANT USAGE ON SCHEMA public TO kjds_g1_runtime"))
            connection.execute(
                text(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public "
                    "TO kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public "
                    "TO kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE ALL ON TABLE global_data_coverage_issuance_authorities,"
                    "global_data_coverage_evidence_issuances FROM kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION kjds_gdc_issue_evidence("
                    "text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz) "
                    "FROM kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE ALL ON TABLE closed_loop_authority_receipts,"
                    "closed_loop_evidence_issuances FROM kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION kjds_cloe_issue_evidence("
                    "text,text,bytea,text,text,text,timestamptz,timestamptz,"
                    "jsonb,text,text) FROM kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION kjds_cloe_issue_event_evidence("
                    "text,bytea,text,text,timestamptz,timestamptz,jsonb) "
                    "TO kjds_g1_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE EXECUTE ON FUNCTION "
                    "kjds_cloe_register_authority_receipt(jsonb) "
                    "FROM kjds_g1_runtime"
                )
            )
            identity = connection.execute(
                text(
                    "SELECT r.rolsuper,r.rolinherit,r.rolcreaterole,r.rolcreatedb,"
                    "r.rolreplication,r.rolbypassrls FROM pg_roles r "
                    "WHERE r.rolname='kjds_g1_runtime'"
                )
            ).one()
            if any(identity[:5]) or identity[5] is not True:
                raise RuntimeError("G-1 generic runtime principal contract drifted")
    finally:
        engine.dispose()


def _database_oid(connection, name: str) -> int | None:
    value = connection.scalar(
        text("SELECT oid::bigint FROM pg_database WHERE datname=:name"),
        {"name": name},
    )
    return int(value) if value is not None else None


def _schema_comment(connection, schema_name: str) -> str | None:
    return connection.scalar(
        text(
            "SELECT obj_description(oid,'pg_namespace') FROM pg_namespace "
            "WHERE nspname=:schema_name"
        ),
        {"schema_name": schema_name},
    )


def _matching_gdc_schemas(connection) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname ~ '^data_cov_002_[0-9a-f]{32}$' ORDER BY nspname"
            )
        ).scalars()
    )


def _role_memberships(
    connection,
    roles: tuple[str, ...],
) -> tuple[tuple[str, str, bool], ...]:
    return tuple(
        (str(row.member_name), str(row.parent_name), bool(row.admin_option))
        for row in connection.execute(
            text(
                "SELECT member.rolname AS member_name,parent.rolname AS parent_name,"
                "m.admin_option FROM pg_auth_members m "
                "JOIN pg_roles member ON member.oid=m.member "
                "JOIN pg_roles parent ON parent.oid=m.roleid "
                "WHERE member.rolname=ANY(:roles) OR parent.rolname=ANY(:roles) "
                "ORDER BY member.rolname,parent.rolname"
            ),
            {"roles": list(roles)},
        ).all()
    )


def _role_dependency_rows(
    connection,
    *,
    role: str,
    allowed_schema: str | None,
) -> list[Any]:
    return list(
        connection.execute(
            text(
                "WITH current_db AS ("
                " SELECT oid FROM pg_database WHERE datname=current_database()"
                "), allowed_schema AS ("
                " SELECT oid FROM pg_namespace WHERE nspname=:allowed_schema"
                "), public_schema AS ("
                " SELECT oid FROM pg_namespace WHERE nspname='public'"
                ") "
                "SELECT d.dbid::bigint AS dbid,d.classid::regclass::text AS class_name,"
                "d.objid::bigint AS objid,d.objsubid,d.deptype,"
                "(d.dbid=(SELECT oid FROM current_db) AND ("
                " (d.classid='pg_namespace'::regclass AND d.objid IN (SELECT oid FROM allowed_schema)) OR"
                " (d.classid='pg_class'::regclass AND EXISTS (SELECT 1 FROM pg_class c "
                "   WHERE c.oid=d.objid AND c.relnamespace IN (SELECT oid FROM allowed_schema))) OR"
                " (d.classid='pg_proc'::regclass AND EXISTS (SELECT 1 FROM pg_proc p "
                "   WHERE p.oid=d.objid AND p.pronamespace IN (SELECT oid FROM allowed_schema))) OR"
                " (d.classid='pg_type'::regclass AND EXISTS (SELECT 1 FROM pg_type t "
                "   WHERE t.oid=d.objid AND t.typnamespace IN (SELECT oid FROM allowed_schema)))"
                ")) AS in_allowed_schema,"
                "(d.dbid=(SELECT oid FROM current_db) AND d.classid='pg_namespace'::regclass "
                " AND d.objid IN (SELECT oid FROM public_schema)) AS is_public_schema "
                "FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid "
                "WHERE d.refclassid='pg_authid'::regclass AND r.rolname=:role "
                "ORDER BY d.dbid,d.classid,d.objid,d.objsubid,d.deptype"
            ),
            {"role": role, "allowed_schema": allowed_schema},
        ).mappings()
    )


def _public_schema_dependency_key(connection) -> tuple[int, int]:
    row = connection.execute(
        text(
            "SELECT d.oid::bigint AS database_oid,n.oid::bigint AS schema_oid "
            "FROM pg_database d CROSS JOIN pg_namespace n "
            "WHERE d.datname=current_database() AND n.nspname='public'"
        )
    ).one()
    return int(row.database_oid), int(row.schema_oid)


def _preflight_role_cleanup(
    connection,
    *,
    roles: tuple[str, ...],
    token_sha256: str,
    allowed_database_oid: int | None = None,
    allowed_schema: str | None = None,
    allowed_external_acl_dependencies: frozenset[tuple[int, int]] = frozenset(),
) -> _RoleCleanupPlan:
    _assert_role_receipts(
        connection,
        roles=roles,
        token_sha256=token_sha256,
    )
    memberships = _role_memberships(connection, roles)
    role_set = set(roles)
    if any(member not in role_set or parent not in role_set for member, parent, _ in memberships):
        raise RuntimeError("G-1 role membership dependency is outside the run receipt")
    public_acl_roles: list[str] = []
    for role in roles:
        for dependency in _role_dependency_rows(
            connection,
            role=role,
            allowed_schema=allowed_schema,
        ):
            class_name = str(dependency["class_name"])
            target_database_dependency = (
                allowed_database_oid is not None
                and (
                    int(dependency["dbid"]) == allowed_database_oid
                    or (
                        class_name.endswith("pg_database")
                        and int(dependency["objid"]) == allowed_database_oid
                    )
                )
            )
            if target_database_dependency or bool(dependency["in_allowed_schema"]):
                continue
            if bool(dependency["is_public_schema"]) and dependency["deptype"] == "a":
                public_acl_roles.append(role)
                continue
            if (
                dependency["deptype"] == "a"
                and class_name.endswith("pg_namespace")
                and (int(dependency["dbid"]), int(dependency["objid"]))
                in allowed_external_acl_dependencies
            ):
                continue
            if class_name.endswith("pg_auth_members"):
                continue
            raise RuntimeError("G-1 role has an unowned database dependency")
    return _RoleCleanupPlan(
        roles=roles,
        memberships=memberships,
        revoke_public_schema_from=tuple(sorted(set(public_acl_roles))),
    )


def _apply_public_schema_cleanup(
    connection,
    roles: tuple[str, ...],
) -> None:
    for role in roles:
        connection.exec_driver_sql(
            f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {_identifier(role)}"
        )


def _apply_role_cleanup(connection, plan: _RoleCleanupPlan) -> None:
    _apply_public_schema_cleanup(connection, plan.revoke_public_schema_from)
    for member, parent, admin_option in plan.memberships:
        if admin_option:
            connection.exec_driver_sql(
                f"REVOKE ADMIN OPTION FOR {_identifier(parent)} FROM {_identifier(member)}"
            )
        connection.exec_driver_sql(
            f"REVOKE {_identifier(parent)} FROM {_identifier(member)}"
        )
    for role in plan.roles:
        if _role_dependency_rows(connection, role=role, allowed_schema=None):
            raise RuntimeError("G-1 role dependency cleanup did not conserve the catalog")
    for role in plan.roles:
        connection.exec_driver_sql(f"DROP ROLE {_identifier(role)}")


def _prepare_g1_recovery(
    connection,
    *,
    token_sha256: str,
    roles_owned: bool,
    database_owned: bool,
    allow_interrupted_database_drop: bool,
    preserve_unowned_resources: bool = False,
    allowed_external_acl_dependencies: frozenset[tuple[int, int]] = frozenset(),
) -> _G1RecoveryPlan:
    database_exists = _database_exists(connection)
    existing_roles = set(_existing_roles(connection))
    if database_owned:
        if database_exists:
            if _database_comment(connection) != _ownership_comment(token_sha256):
                raise RuntimeError("G-1 database ownership receipt drifted")
        elif not allow_interrupted_database_drop:
            raise RuntimeError("G-1 database ownership receipt set drifted")
    elif database_exists and not preserve_unowned_resources:
        raise RuntimeError("G-1 unowned fixed database exists")
    if roles_owned:
        if existing_roles != set(ROLE_NAMES):
            raise RuntimeError("G-1 role ownership receipt set drifted")
        database_oid = _database_oid(connection, DATABASE_NAME) if database_exists else None
        cleanup = _preflight_role_cleanup(
            connection,
            roles=ROLE_NAMES,
            token_sha256=token_sha256,
            allowed_database_oid=database_oid,
            allowed_external_acl_dependencies=allowed_external_acl_dependencies,
        )
    else:
        if existing_roles and not preserve_unowned_resources:
            raise RuntimeError("G-1 unowned fixed role exists")
        cleanup = None
    return _G1RecoveryPlan(
        token_sha256=token_sha256,
        roles_owned=roles_owned,
        database_owned=database_owned,
        role_cleanup=cleanup,
    )


def _apply_g1_database_cleanup(connection, plan: _G1RecoveryPlan) -> None:
    if plan.database_owned and _database_exists(connection):
        connection.execute(text(f'DROP DATABASE "{DATABASE_NAME}" WITH (FORCE)'))
    if plan.database_owned:
        connection.execute(
            text(
                f"UPDATE {LEASE_TABLE} SET database_owned=false "
                "WHERE lease_id=:lease_id AND run_token_sha256=:token"
            ),
            {"lease_id": LEASE_ID, "token": plan.token_sha256},
        )


def _apply_g1_role_cleanup_transaction(
    admin_url: str,
    token_sha256: str,
    *,
    preserve_unowned_resources: bool,
) -> None:
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            roles_owned, database_owned = _lease_state(connection, token_sha256)
            if database_owned:
                raise RuntimeError("G-1 database cleanup did not update its receipt")
            plan = _prepare_g1_recovery(
                connection,
                token_sha256=token_sha256,
                roles_owned=roles_owned,
                database_owned=False,
                allow_interrupted_database_drop=False,
                preserve_unowned_resources=preserve_unowned_resources,
            )
            if plan.role_cleanup is not None:
                _apply_role_cleanup(connection, plan.role_cleanup)
                connection.execute(
                    text(
                        f"UPDATE {LEASE_TABLE} SET roles_owned=false "
                        "WHERE lease_id=:lease_id AND run_token_sha256=:token"
                    ),
                    {"lease_id": LEASE_ID, "token": token_sha256},
                )
            connection.execute(
                text(
                    f"DELETE FROM {LEASE_TABLE} "
                    "WHERE lease_id=:lease_id AND run_token_sha256=:token"
                ),
                {"lease_id": LEASE_ID, "token": token_sha256},
            )
    finally:
        engine.dispose()


def _prepare_gdc_recovery(
    connection,
    *,
    token_sha256: str,
    schema_name: str,
    roles_owned: bool,
    schema_owned: bool,
) -> _GdcRecoveryPlan:
    matching_schemas = _matching_gdc_schemas(connection)
    existing_roles = set(
        connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname=ANY(:roles)"),
            {"roles": list(GDC_CONTRACT_ROLE_NAMES)},
        ).scalars()
    )
    if schema_owned:
        if matching_schemas != [schema_name]:
            raise RuntimeError("G-1 GDC schema ownership receipt set drifted")
        if _schema_comment(connection, schema_name) != _ownership_comment(token_sha256):
            raise RuntimeError("G-1 GDC schema ownership receipt drifted")
    elif matching_schemas:
        raise RuntimeError("G-1 unowned GDC schema exists")
    if roles_owned:
        if existing_roles != set(GDC_CONTRACT_ROLE_NAMES):
            raise RuntimeError("G-1 GDC role ownership receipt set drifted")
        cleanup = _preflight_role_cleanup(
            connection,
            roles=GDC_CONTRACT_ROLE_NAMES,
            token_sha256=token_sha256,
            allowed_schema=schema_name if schema_owned else None,
        )
    else:
        if existing_roles:
            raise RuntimeError("G-1 unowned GDC role exists")
        cleanup = None
    return _GdcRecoveryPlan(
        token_sha256=token_sha256,
        schema_name=schema_name,
        roles_owned=roles_owned,
        schema_owned=schema_owned,
        role_cleanup=cleanup,
    )


def _apply_gdc_recovery(connection, plan: _GdcRecoveryPlan) -> None:
    if plan.schema_owned:
        connection.exec_driver_sql(f"DROP SCHEMA {_identifier(plan.schema_name)} CASCADE")
        connection.execute(
            text(
                f"UPDATE {GDC_RECEIPT_TABLE} SET schema_owned=false "
                "WHERE receipt_id=:receipt_id AND run_token_sha256=:token"
            ),
            {"receipt_id": GDC_RECEIPT_ID, "token": plan.token_sha256},
        )
    if plan.role_cleanup is not None:
        _apply_role_cleanup(connection, plan.role_cleanup)
        connection.execute(
            text(
                f"UPDATE {GDC_RECEIPT_TABLE} SET roles_owned=false "
                "WHERE receipt_id=:receipt_id AND run_token_sha256=:token"
            ),
            {"receipt_id": GDC_RECEIPT_ID, "token": plan.token_sha256},
        )
    connection.execute(
        text(
            f"DELETE FROM {GDC_RECEIPT_TABLE} "
            "WHERE receipt_id=:receipt_id AND run_token_sha256=:token"
        ),
        {"receipt_id": GDC_RECEIPT_ID, "token": plan.token_sha256},
    )


def _apply_gdc_recovery_transaction(admin_url: str, token_sha256: str) -> None:
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            receipt = _gdc_receipt(connection)
            if receipt is None or receipt[0] != token_sha256:
                raise RuntimeError("G-1 GDC recovery receipt is not owned by this run")
            plan = _prepare_gdc_recovery(
                connection,
                token_sha256=receipt[0],
                schema_name=receipt[1],
                roles_owned=receipt[2],
                schema_owned=receipt[3],
            )
            _apply_gdc_recovery(connection, plan)
    finally:
        engine.dispose()


def _drop_owned_resources(
    connection,
    token_sha256: str,
    *,
    admin_url: str,
    secondary_connection=None,
) -> None:
    roles_owned, database_owned = _lease_state(connection, token_sha256)
    secondary_plan = None
    secondary_public_key = frozenset()
    primary_public_key = frozenset({_public_schema_dependency_key(connection)})
    if roles_owned and secondary_connection is not None:
        secondary_public_key = frozenset(
            {_public_schema_dependency_key(secondary_connection)}
        )
        secondary_plan = _preflight_role_cleanup(
            secondary_connection,
            roles=ROLE_NAMES,
            token_sha256=token_sha256,
            allowed_database_oid=_database_oid(connection, DATABASE_NAME),
            allowed_external_acl_dependencies=primary_public_key,
        )
    plan = _prepare_g1_recovery(
        connection,
        token_sha256=token_sha256,
        roles_owned=roles_owned,
        database_owned=database_owned,
        allow_interrupted_database_drop=False,
        preserve_unowned_resources=True,
        allowed_external_acl_dependencies=secondary_public_key,
    )
    if secondary_connection is not None and secondary_plan is not None:
        _apply_public_schema_cleanup(
            secondary_connection,
            secondary_plan.revoke_public_schema_from,
        )
    _apply_g1_database_cleanup(connection, plan)
    _apply_g1_role_cleanup_transaction(
        admin_url,
        token_sha256,
        preserve_unowned_resources=True,
    )


def _gdc_admin_url(target_url: str) -> str:
    configured = str(os.getenv(GDC_ADMIN_DATABASE_URL_ENV, ""))
    if not configured:
        raise RuntimeError("G-1 GDC admin database URL is missing")
    target = make_url(target_url)
    admin = make_url(configured)
    if (
        admin.get_backend_name() != "postgresql"
        or target.get_backend_name() != "postgresql"
        or admin.host != target.host
        or admin.port != target.port
        or admin.username != target.username
        or not admin.database
        or admin.database == DATABASE_NAME
    ):
        raise RuntimeError("G-1 GDC admin database URL is outside the target cluster")
    return admin.render_as_string(hide_password=False)


def acquire_gdc_contract_resources(
    admin_url: str,
    *,
    schema_name: str,
    issuer_password: str,
    generic_password: str,
) -> None:
    if not GDC_SCHEMA_PATTERN.fullmatch(schema_name):
        raise RuntimeError("G-1 GDC contract schema name is invalid")
    token_sha256 = _run_token_sha256()
    engine = create_engine(admin_url)
    try:
        with engine.begin() as connection:
            _ensure_gdc_receipt_table(connection)
            if (
                _gdc_receipt(connection) is not None
                or _matching_gdc_schemas(connection)
                or connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=ANY(:roles))"
                    ),
                    {"roles": list(GDC_CONTRACT_ROLE_NAMES)},
                )
            ):
                raise RuntimeError("G-1 GDC fixed resource already exists")
            connection.execute(
                text(
                    f"INSERT INTO {GDC_RECEIPT_TABLE}("
                    "receipt_id,run_token_sha256,schema_name) "
                    "VALUES (:receipt_id,:token,:schema_name)"
                ),
                {
                    "receipt_id": GDC_RECEIPT_ID,
                    "token": token_sha256,
                    "schema_name": schema_name,
                },
            )
            issuer_password_sql = _server_literal(connection, issuer_password)
            generic_password_sql = _server_literal(connection, generic_password)
            expected_sql = _server_literal(connection, _ownership_comment(token_sha256))
            connection.exec_driver_sql(
                "CREATE ROLE kjds_gdc_issuance_owner NOLOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_gdc_issuance_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS "
                f"PASSWORD {issuer_password_sql}"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_gdc_generic_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS "
                f"PASSWORD {generic_password_sql}"
            )
            for role in GDC_CONTRACT_ROLE_NAMES:
                connection.exec_driver_sql(
                    f"COMMENT ON ROLE {_identifier(role)} IS {expected_sql}"
                )
            connection.exec_driver_sql(f"CREATE SCHEMA {_identifier(schema_name)}")
            connection.exec_driver_sql(
                f"COMMENT ON SCHEMA {_identifier(schema_name)} IS {expected_sql}"
            )
            connection.execute(
                text(
                    f"UPDATE {GDC_RECEIPT_TABLE} SET roles_owned=true,schema_owned=true "
                    "WHERE receipt_id=:receipt_id AND run_token_sha256=:token"
                ),
                {"receipt_id": GDC_RECEIPT_ID, "token": token_sha256},
            )
    finally:
        engine.dispose()


def release_gdc_contract_resources(admin_url: str) -> None:
    token_sha256 = _run_token_sha256()
    _apply_gdc_recovery_transaction(admin_url, token_sha256)


def _recover_stale_resources(
    g1_connection,
    *,
    g1_admin_url: str,
    gdc_admin_url: str,
) -> None:
    gdc_engine = create_engine(gdc_admin_url, isolation_level="AUTOCOMMIT")
    try:
        with gdc_engine.connect() as gdc_connection:
            g1_receipt = _g1_receipt(g1_connection)
            gdc_receipt = _gdc_receipt(gdc_connection)
            if g1_receipt is not None and gdc_receipt is not None:
                raise RuntimeError("G-1 recovery receipts overlap")
            if gdc_receipt is not None:
                if _database_exists(g1_connection):
                    raise RuntimeError("G-1 unknown fixed database exists during GDC recovery")
                extra_roles = set(_existing_roles(g1_connection)) - set(
                    GDC_CONTRACT_ROLE_NAMES
                )
                if extra_roles:
                    raise RuntimeError("G-1 unknown fixed role exists during GDC recovery")
                plan = _prepare_gdc_recovery(
                    gdc_connection,
                    token_sha256=gdc_receipt[0],
                    schema_name=gdc_receipt[1],
                    roles_owned=gdc_receipt[2],
                    schema_owned=gdc_receipt[3],
                )
                if plan.token_sha256 != gdc_receipt[0]:
                    raise RuntimeError("G-1 GDC recovery receipt drifted")
                _apply_gdc_recovery_transaction(gdc_admin_url, gdc_receipt[0])
                return
            if g1_receipt is not None:
                if (
                    "kjds_gdc_generic_runtime" in set(_existing_roles(g1_connection))
                    or _matching_gdc_schemas(gdc_connection)
                ):
                    raise RuntimeError("G-1 unknown GDC resource exists during recovery")
                secondary_plan = None
                secondary_public_key = frozenset()
                if g1_receipt[1]:
                    primary_public_key = frozenset(
                        {_public_schema_dependency_key(g1_connection)}
                    )
                    secondary_public_key = frozenset(
                        {_public_schema_dependency_key(gdc_connection)}
                    )
                    target_database_oid = _database_oid(g1_connection, DATABASE_NAME)
                    secondary_plan = _preflight_role_cleanup(
                        gdc_connection,
                        roles=ROLE_NAMES,
                        token_sha256=g1_receipt[0],
                        allowed_database_oid=target_database_oid,
                        allowed_external_acl_dependencies=primary_public_key,
                    )
                plan = _prepare_g1_recovery(
                    g1_connection,
                    token_sha256=g1_receipt[0],
                    roles_owned=g1_receipt[1],
                    database_owned=g1_receipt[2],
                    allow_interrupted_database_drop=True,
                    allowed_external_acl_dependencies=secondary_public_key,
                )
                if secondary_plan is not None:
                    _apply_public_schema_cleanup(
                        gdc_connection,
                        secondary_plan.revoke_public_schema_from,
                    )
                _apply_g1_database_cleanup(g1_connection, plan)
                _apply_g1_role_cleanup_transaction(
                    g1_admin_url,
                    g1_receipt[0],
                    preserve_unowned_resources=False,
                )
                return
            if (
                _database_exists(g1_connection)
                or _existing_roles(g1_connection)
                or "kjds_gdc_generic_runtime"
                in set(
                    gdc_connection.execute(
                        text("SELECT rolname FROM pg_roles WHERE rolname=:role"),
                        {"role": "kjds_gdc_generic_runtime"},
                    ).scalars()
                )
                or _matching_gdc_schemas(gdc_connection)
            ):
                raise RuntimeError("G-1 stale resource has no ownership receipt")
    finally:
        gdc_engine.dispose()


def manage(action: str, target_url: str) -> None:
    if action not in {"acquire", "recreate", "grant-runtime", "drop", "recover"}:
        raise ValueError("Unsupported G-1 database action")
    url = make_url(target_url)
    if url.database != DATABASE_NAME:
        raise RuntimeError(f"G-1 database manager only accepts {DATABASE_NAME!r}")
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    token_sha256 = _run_token_sha256()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            if action == "recover":
                _recover_stale_resources(
                    connection,
                    g1_admin_url=admin_url,
                    gdc_admin_url=_gdc_admin_url(target_url),
                )
            elif action == "acquire":
                _acquire_lease(connection, token_sha256)
            elif action == "recreate":
                _lease_state(connection, token_sha256)
                _assert_resources_absent(connection)
                issuer_password = _secret("KJDS_G1_COVERAGE_ISSUER_PASSWORD")
                runtime_password = _secret("KJDS_G1_RUNTIME_PASSWORD")
                closed_loop_passwords = {
                    CLOE_RUNTIME_ROLE: _secret("KJDS_G1_CLOE_ISSUER_PASSWORD"),
                    "kjds_cloe_experiment_authority": _secret(
                        "KJDS_G1_CLOE_EXPERIMENT_PASSWORD"
                    ),
                    "kjds_cloe_cost_authority": _secret(
                        "KJDS_G1_CLOE_COST_PASSWORD"
                    ),
                    "kjds_cloe_outcome_authority": _secret(
                        "KJDS_G1_CLOE_OUTCOME_PASSWORD"
                    ),
                    "kjds_cloe_review_authority": _secret(
                        "KJDS_G1_CLOE_REVIEW_PASSWORD"
                    ),
                }
                _create_owned_roles(
                    admin_url,
                    token_sha256=token_sha256,
                    issuer_password=issuer_password,
                    runtime_password=runtime_password,
                    closed_loop_passwords=closed_loop_passwords,
                )
                _create_owned_database(connection, token_sha256)
                if not _database_exists(connection):
                    raise RuntimeError("G-1 database recreate verification failed")
            elif action == "grant-runtime":
                roles_owned, database_owned = _lease_state(connection, token_sha256)
                _assert_owned_resources(
                    connection,
                    token_sha256=token_sha256,
                    roles_owned=roles_owned,
                    database_owned=database_owned,
                )
                if not roles_owned or not database_owned:
                    raise RuntimeError("G-1 runtime grant requires owned resources")
                _grant_runtime(target_url)
            else:
                secondary_engine = None
                try:
                    secondary_url = str(os.getenv(GDC_ADMIN_DATABASE_URL_ENV, ""))
                    if secondary_url and make_url(secondary_url).database != "postgres":
                        secondary_engine = create_engine(
                            _gdc_admin_url(target_url),
                            isolation_level="AUTOCOMMIT",
                        )
                        with secondary_engine.connect() as secondary_connection:
                            _drop_owned_resources(
                                connection,
                                token_sha256,
                                admin_url=admin_url,
                                secondary_connection=secondary_connection,
                            )
                    else:
                        _drop_owned_resources(
                            connection,
                            token_sha256,
                            admin_url=admin_url,
                        )
                finally:
                    if secondary_engine is not None:
                        secondary_engine.dispose()
        print({"database": DATABASE_NAME, "action": action, "status": "passed"})
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("acquire", "recreate", "grant-runtime", "drop", "recover")
    )
    args = parser.parse_args()
    manage(args.action, database_url())


if __name__ == "__main__":
    main()
