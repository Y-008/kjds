from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

load_dotenv()

DEFAULT_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"
RUNTIME_DATABASE_URL_ENV = "KJDS_RUNTIME_DATABASE_URL"
COVERAGE_ISSUER_DATABASE_URL_ENV = "KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL"
COVERAGE_ISSUER_ROLE = "kjds_gdc_issuance_runtime"
CLOSED_LOOP_DATABASE_URL_ENVS = {
    "issuer": "KJDS_CLOSED_LOOP_ISSUER_DATABASE_URL",
    "experiment": "KJDS_CLOSED_LOOP_EXPERIMENT_AUTHORITY_DATABASE_URL",
    "cost": "KJDS_CLOSED_LOOP_COST_AUTHORITY_DATABASE_URL",
    "business_outcome": "KJDS_CLOSED_LOOP_OUTCOME_AUTHORITY_DATABASE_URL",
    "review_event": "KJDS_CLOSED_LOOP_REVIEW_AUTHORITY_DATABASE_URL",
}
CLOSED_LOOP_DATABASE_ROLES = {
    "issuer": "kjds_cloe_issuance_runtime",
    "experiment": "kjds_cloe_experiment_authority",
    "cost": "kjds_cloe_cost_authority",
    "business_outcome": "kjds_cloe_outcome_authority",
    "review_event": "kjds_cloe_review_authority",
}
CLOSED_LOOP_OWNER_ROLE = "kjds_cloe_issuance_owner"
CLOSED_LOOP_EVENT_OWNER_ROLE = "kjds_cloe_event_issuance_owner"
CLOSED_LOOP_ROLES = (
    CLOSED_LOOP_OWNER_ROLE,
    CLOSED_LOOP_EVENT_OWNER_ROLE,
    *CLOSED_LOOP_DATABASE_ROLES.values(),
)


def database_url() -> str:
    return os.getenv("KJDS_DATABASE_URL", DEFAULT_DATABASE_URL)


def create_database_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def runtime_database_url() -> str:
    raw = str(os.getenv(RUNTIME_DATABASE_URL_ENV, "")).strip()
    if not raw:
        raise RuntimeError("Dedicated runtime database credential is required")
    migration_raw = str(os.getenv("KJDS_DATABASE_URL", "")).strip()
    try:
        runtime = make_url(raw)
        migration = make_url(migration_raw or DEFAULT_DATABASE_URL)
    except Exception as exc:
        raise RuntimeError("Dedicated runtime database credential is invalid") from exc
    if not runtime.drivername.startswith("postgresql") or not runtime.password:
        raise RuntimeError("Dedicated runtime database credential must use PostgreSQL")
    if runtime.username == migration.username:
        raise RuntimeError("Runtime and migration database principals must differ")
    if migration_raw and (runtime.host, runtime.port, runtime.database) != (
        migration.host,
        migration.port,
        migration.database,
    ):
        raise RuntimeError("Runtime and migration databases must share one endpoint")
    return raw


def coverage_issuer_database_url(*, generic_url: str | None = None) -> str:
    raw = str(os.getenv(COVERAGE_ISSUER_DATABASE_URL_ENV, "")).strip()
    if not raw:
        raise RuntimeError("Dedicated coverage issuer database credential is required")
    try:
        issuer = make_url(raw)
        generic = make_url(generic_url or database_url())
    except Exception as exc:
        raise RuntimeError("Dedicated coverage issuer database credential is invalid") from exc
    if not issuer.drivername.startswith("postgresql"):
        raise RuntimeError("Dedicated coverage issuer database must use PostgreSQL")
    if issuer.username != COVERAGE_ISSUER_ROLE:
        raise RuntimeError("Dedicated coverage issuer database principal is invalid")
    if issuer.username == generic.username:
        raise RuntimeError("Coverage issuer and generic database principals must differ")
    if (issuer.host, issuer.port, issuer.database) != (
        generic.host,
        generic.port,
        generic.database,
    ):
        raise RuntimeError("Coverage issuer must target the generic database endpoint")
    if not issuer.password:
        raise RuntimeError("Dedicated coverage issuer database credential is incomplete")
    return raw


def _create_coverage_issuer_engine(
    url: str | None = None,
    *,
    generic_url: str | None = None,
) -> Engine:
    resolved = url or coverage_issuer_database_url(generic_url=generic_url)
    if url is not None:
        previous = os.environ.get(COVERAGE_ISSUER_DATABASE_URL_ENV)
        try:
            os.environ[COVERAGE_ISSUER_DATABASE_URL_ENV] = url
            resolved = coverage_issuer_database_url(generic_url=generic_url)
        finally:
            if previous is None:
                os.environ.pop(COVERAGE_ISSUER_DATABASE_URL_ENV, None)
            else:
                os.environ[COVERAGE_ISSUER_DATABASE_URL_ENV] = previous
    issuer_engine = create_engine(resolved, pool_pre_ping=True)
    generic_engine = create_engine(generic_url or database_url(), pool_pre_ping=True)
    try:
        with issuer_engine.connect() as issuer_connection:
            issuer_identity = issuer_connection.execute(
                text(
                    "SELECT current_user,session_user,rolsuper,rolinherit,"
                    "rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
                    "pg_has_role(current_user,'kjds_gdc_issuance_owner','SET') "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
        with generic_engine.connect() as generic_connection:
            generic_identity = generic_connection.execute(
                text(
                    "SELECT current_user,session_user,rolsuper,rolinherit,"
                    "rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
                    "has_function_privilege(current_user,"
                    "'kjds_gdc_issue_evidence(text,bytea,text,text,timestamptz,"
                    "timestamptz,jsonb,text,timestamptz)','EXECUTE') "
                    ",pg_has_role(current_user,'kjds_gdc_issuance_owner','SET')"
                    ",pg_has_role(current_user,'kjds_gdc_issuance_runtime','SET') "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            ).one()
        with issuer_engine.connect() as membership_connection:
            unexpected_memberships = membership_connection.scalar(
                text(
                    "SELECT count(*) FROM pg_auth_members m "
                    "JOIN pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=m.member "
                    "WHERE granted.rolname IN "
                    "('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime') "
                    "OR member_role.rolname IN "
                    "('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime',:generic)"
                ),
                {"generic": generic_identity[0]},
            )
        if (
            tuple(issuer_identity[:2]) != (COVERAGE_ISSUER_ROLE,) * 2
            or any(issuer_identity[2:8])
            or issuer_identity[8] is not False
            or unexpected_memberships != 0
        ):
            raise RuntimeError("Dedicated coverage issuer principal contract drifted")
        if (
            generic_identity[0] != generic_identity[1]
            or generic_identity[0] == COVERAGE_ISSUER_ROLE
            or any(generic_identity[2:7])
            or generic_identity[7] is not True
            or generic_identity[8] is not False
            or generic_identity[9] is not False
            or generic_identity[10] is not False
        ):
            raise RuntimeError("Generic database principal violates issuer isolation")
    except Exception:
        issuer_engine.dispose()
        raise
    finally:
        generic_engine.dispose()
    return issuer_engine


def closed_loop_database_url(
    purpose: str,
    *,
    generic_url: str | None = None,
) -> str:
    env_name = CLOSED_LOOP_DATABASE_URL_ENVS.get(purpose)
    expected_role = CLOSED_LOOP_DATABASE_ROLES.get(purpose)
    if env_name is None or expected_role is None:
        raise RuntimeError("Closed-loop database purpose is invalid")
    raw = str(os.getenv(env_name, "")).strip()
    if not raw:
        raise RuntimeError("Dedicated closed-loop database credential is required")
    try:
        dedicated = make_url(raw)
        generic = make_url(generic_url or database_url())
    except Exception as exc:
        raise RuntimeError("Dedicated closed-loop database credential is invalid") from exc
    if (
        not dedicated.drivername.startswith("postgresql")
        or dedicated.username != expected_role
        or not dedicated.password
        or dedicated.username == generic.username
        or (dedicated.host, dedicated.port, dedicated.database)
        != (generic.host, generic.port, generic.database)
    ):
        raise RuntimeError("Dedicated closed-loop database credential is invalid")
    return raw


def create_closed_loop_database_engine(
    purpose: str,
    *,
    generic_url: str | None = None,
) -> Engine:
    expected_role = CLOSED_LOOP_DATABASE_ROLES.get(purpose)
    if expected_role is None:
        raise RuntimeError("Closed-loop database purpose is invalid")
    engine = create_engine(
        closed_loop_database_url(purpose, generic_url=generic_url),
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            identity = connection.execute(
                text(
                    "SELECT current_user,session_user,rolsuper,rolinherit,"
                    "rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,"
                    "pg_has_role(current_user,:owner,'SET'),"
                    "(SELECT count(*) FROM pg_auth_members m "
                    "JOIN pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=m.member "
                    "WHERE granted.rolname=ANY(:roles) "
                    "OR member_role.rolname=ANY(:roles)) "
                    "FROM pg_roles WHERE rolname=current_user"
                ),
                {"owner": CLOSED_LOOP_OWNER_ROLE, "roles": list(CLOSED_LOOP_ROLES)},
            ).one()
        if (
            tuple(identity[:2]) != (expected_role,) * 2
            or any(identity[2:8])
            or identity[8] is not False
            or identity[9] != 0
        ):
            raise RuntimeError("Dedicated closed-loop principal contract drifted")
    except Exception:
        engine.dispose()
        raise
    return engine


class CoverageIssuerDatabasePort:
    """Narrow server-only issuer port; the underlying credential is never exposed."""

    __slots__ = ("__engine",)

    def __init__(self, engine: Engine) -> None:
        self.__engine = engine

    def issue_evidence(
        self,
        *,
        evidence_id: str,
        content: bytes,
        source: str,
        source_ref: str,
        effective_at: Any,
        effective_until: Any,
        metadata: dict[str, Any],
        issuance_sha256: str,
        authority_checked_at: Any,
    ) -> str:
        with self.__engine.begin() as connection:
            identity = connection.execute(
                text(
                    "SELECT current_user,session_user,"
                    "pg_has_role(session_user,'kjds_gdc_issuance_owner','SET'),"
                    "(SELECT count(*) FROM pg_auth_members m "
                    "JOIN pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_roles member_role ON member_role.oid=m.member "
                    "WHERE granted.rolname IN "
                    "('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime') "
                    "OR member_role.rolname IN "
                    "('kjds_gdc_issuance_owner','kjds_gdc_issuance_runtime') "
                    "OR granted.rolname=session_user OR member_role.rolname=session_user),"
                    "EXISTS (SELECT 1 FROM pg_roles owner_role "
                    "CROSS JOIN pg_roles runtime_role "
                    "WHERE owner_role.rolname='kjds_gdc_issuance_owner' "
                    "AND NOT owner_role.rolcanlogin AND NOT owner_role.rolsuper "
                    "AND NOT owner_role.rolinherit AND NOT owner_role.rolcreaterole "
                    "AND NOT owner_role.rolcreatedb AND NOT owner_role.rolreplication "
                    "AND owner_role.rolbypassrls "
                    "AND runtime_role.rolname='kjds_gdc_issuance_runtime' "
                    "AND runtime_role.rolcanlogin AND NOT runtime_role.rolsuper "
                    "AND NOT runtime_role.rolinherit AND NOT runtime_role.rolcreaterole "
                    "AND NOT runtime_role.rolcreatedb AND NOT runtime_role.rolreplication "
                    "AND NOT runtime_role.rolbypassrls)"
                )
            ).one()
            if (
                tuple(identity[:2]) != (COVERAGE_ISSUER_ROLE, COVERAGE_ISSUER_ROLE)
                or identity[2] is not False
                or identity[3] != 0
                or identity[4] is not True
            ):
                raise PermissionError("Dedicated coverage issuer login is not active")
            result = connection.scalar(
                text(
                    "SELECT kjds_gdc_issue_evidence("
                    ":evidence_id,:content,:source,:source_ref,:effective_at,"
                    ":effective_until,CAST(:metadata AS jsonb),:issuance_sha256,"
                    ":authority_checked_at)"
                ),
                {
                    "evidence_id": evidence_id,
                    "content": content,
                    "source": source,
                    "source_ref": source_ref,
                    "effective_at": effective_at,
                    "effective_until": effective_until,
                    "metadata": json.dumps(
                        metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "issuance_sha256": issuance_sha256,
                    "authority_checked_at": authority_checked_at,
                },
            )
        if not isinstance(result, str):
            raise PermissionError("Coverage issuer returned an invalid receipt")
        return result

    def dispose(self) -> None:
        self.__engine.dispose()


def create_coverage_issuer_port(*, generic_url: str | None = None) -> CoverageIssuerDatabasePort:
    return CoverageIssuerDatabasePort(
        _create_coverage_issuer_engine(generic_url=generic_url)
    )


def create_global_data_coverage_evidence_authority(
    *,
    evidence: Any,
    scope_grants: Any,
    intake_authority: Any,
    clock: Any | None = None,
) -> Any:
    """Compose the raw issuer capability only inside its governed authority."""
    from .evidence import GlobalDataCoverageEvidenceAuthorityAdapter

    engine = evidence.engine
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Production coverage intake authority requires PostgreSQL")
    issuer_port = create_coverage_issuer_port(
        generic_url=engine.url.render_as_string(hide_password=False)
    )
    return GlobalDataCoverageEvidenceAuthorityAdapter(
        evidence,
        scope_grants=scope_grants,
        intake_authority=intake_authority,
        issuer_port=issuer_port,
        clock=clock,
    )


def database_health(engine: Engine | None = None) -> dict[str, str]:
    target = engine
    owns_engine = False
    if target is None:
        runtime_url = runtime_database_url()
        try:
            target = create_database_engine(runtime_url)
        except Exception:
            raise RuntimeError("Runtime database health check failed") from None
        owns_engine = True
    try:
        with target.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        raise RuntimeError("Runtime database health check failed") from None
    finally:
        if owns_engine:
            target.dispose()
