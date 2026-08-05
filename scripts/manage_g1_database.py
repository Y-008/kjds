from __future__ import annotations

import argparse
import hashlib
import os
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from apps.control_plane.database import database_url

DATABASE_NAME = "kjds_g1_smoke"
ISSUER_OWNER_ROLE = "kjds_gdc_issuance_owner"
ISSUER_RUNTIME_ROLE = "kjds_gdc_issuance_runtime"
G1_RUNTIME_ROLE = "kjds_g1_runtime"
ROLE_NAMES = (ISSUER_RUNTIME_ROLE, ISSUER_OWNER_ROLE, G1_RUNTIME_ROLE)
RUN_TOKEN_ENV = "KJDS_G1_RUN_TOKEN"
LEASE_ID = "kjds-g1-fixed-resources-v1"
LEASE_TABLE = "public.kjds_g1_run_leases"
COMMENT_PREFIX = "kjds-g1-owner:"
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{48,160}$")


def _secret(name: str) -> str:
    value = str(os.getenv(name, ""))
    if not SECRET_PATTERN.fullmatch(value):
        raise RuntimeError(f"G-1 ephemeral credential {name} is missing or invalid")
    return value


def _run_token_sha256() -> str:
    return hashlib.sha256(_secret(RUN_TOKEN_ENV).encode()).hexdigest()


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
    if (
        database_owned
        and _database_exists(connection)
        and _database_comment(connection) != expected
    ):
        raise RuntimeError("G-1 database ownership receipt drifted")
    if roles_owned:
        drifted = {
            role: comment
            for role, comment in _role_comments(connection).items()
            if comment != expected
        }
        if drifted:
            raise RuntimeError("G-1 role ownership receipt drifted")


def _create_owned_roles(
    admin_url: str,
    *,
    token_sha256: str,
    issuer_password: str,
    runtime_password: str,
) -> None:
    engine = create_engine(admin_url)
    expected = _ownership_comment(token_sha256)
    try:
        with engine.begin() as connection:
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
                f"PASSWORD '{issuer_password}'"
            )
            connection.exec_driver_sql(
                "CREATE ROLE kjds_g1_runtime LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEROLE NOCREATEDB NOREPLICATION BYPASSRLS "
                f"PASSWORD '{runtime_password}'"
            )
            for role in ROLE_NAMES:
                connection.exec_driver_sql(f'COMMENT ON ROLE "{role}" IS \'{expected}\'')
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
    connection.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
    connection.exec_driver_sql(f'COMMENT ON DATABASE "{DATABASE_NAME}" IS \'{expected}\'')
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


def _drop_owned_resources(connection, token_sha256: str) -> None:
    roles_owned, database_owned = _lease_state(connection, token_sha256)
    _assert_owned_resources(
        connection,
        token_sha256=token_sha256,
        roles_owned=roles_owned,
        database_owned=database_owned,
    )
    if database_owned and _database_exists(connection):
        connection.execute(text(f'DROP DATABASE "{DATABASE_NAME}" WITH (FORCE)'))
    if database_owned:
        connection.execute(
            text(
                f"UPDATE {LEASE_TABLE} SET database_owned=false "
                "WHERE lease_id=:lease_id AND run_token_sha256=:token"
            ),
            {"lease_id": LEASE_ID, "token": token_sha256},
        )
    if roles_owned:
        for role in ROLE_NAMES:
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
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


def manage(action: str, target_url: str) -> None:
    if action not in {"acquire", "recreate", "grant-runtime", "drop"}:
        raise ValueError("Unsupported G-1 database action")
    url = make_url(target_url)
    if url.database != DATABASE_NAME:
        raise RuntimeError(f"G-1 database manager only accepts {DATABASE_NAME!r}")
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    token_sha256 = _run_token_sha256()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            if action == "acquire":
                _acquire_lease(connection, token_sha256)
            elif action == "recreate":
                _lease_state(connection, token_sha256)
                _assert_resources_absent(connection)
                issuer_password = _secret("KJDS_G1_COVERAGE_ISSUER_PASSWORD")
                runtime_password = _secret("KJDS_G1_RUNTIME_PASSWORD")
                _create_owned_roles(
                    admin_url,
                    token_sha256=token_sha256,
                    issuer_password=issuer_password,
                    runtime_password=runtime_password,
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
                _drop_owned_resources(connection, token_sha256)
        print({"database": DATABASE_NAME, "action": action, "status": "passed"})
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("acquire", "recreate", "grant-runtime", "drop"))
    args = parser.parse_args()
    manage(args.action, database_url())


if __name__ == "__main__":
    main()
