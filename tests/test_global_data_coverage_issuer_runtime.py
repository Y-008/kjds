from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

import apps.control_plane.database as database_module
from apps.control_plane.database import (
    COVERAGE_ISSUER_DATABASE_URL_ENV,
    RUNTIME_DATABASE_URL_ENV,
    coverage_issuer_database_url,
    database_health,
    runtime_database_url,
)

GENERIC = "postgresql+psycopg://kjds_runtime:runtime@db.internal:5432/kjds"
ISSUER = (
    "postgresql+psycopg://kjds_gdc_issuance_runtime:issuer@db.internal:5432/kjds"
)


class FakeHealthConnection:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.executed: list[str] = []

    def __enter__(self):
        if self.error is not None:
            raise self.error
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.executed.append(str(statement))


class FakeHealthEngine:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.connection = FakeHealthConnection(error=error)
        self.connect_count = 0
        self.dispose_count = 0

    def connect(self):
        self.connect_count += 1
        return self.connection

    def dispose(self):
        self.dispose_count += 1


def test_coverage_issuer_database_url_requires_server_only_credential(monkeypatch):
    monkeypatch.delenv(COVERAGE_ISSUER_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match="credential is required"):
        coverage_issuer_database_url(generic_url=GENERIC)


@pytest.mark.parametrize(
    "issuer",
    (
        "sqlite:///issuer.db",
        "postgresql+psycopg://kjds_runtime:issuer@db.internal:5432/kjds",
        "postgresql+psycopg://kjds_gdc_issuance_runtime@db.internal:5432/kjds",
        "postgresql+psycopg://kjds_gdc_issuance_runtime:issuer@other:5432/kjds",
        "postgresql+psycopg://kjds_gdc_issuance_runtime:issuer@db.internal:5432/other",
    ),
)
def test_coverage_issuer_database_url_rejects_principal_or_endpoint_drift(
    monkeypatch, issuer
):
    monkeypatch.setenv(COVERAGE_ISSUER_DATABASE_URL_ENV, issuer)
    with pytest.raises(RuntimeError):
        coverage_issuer_database_url(generic_url=GENERIC)


def test_coverage_issuer_database_url_accepts_exact_isolated_login(monkeypatch):
    monkeypatch.setenv(COVERAGE_ISSUER_DATABASE_URL_ENV, ISSUER)
    assert coverage_issuer_database_url(generic_url=GENERIC) == ISSUER


def test_coverage_issuer_errors_do_not_expose_password(monkeypatch):
    secret = "issuer-password-that-must-not-appear"
    monkeypatch.setenv(
        COVERAGE_ISSUER_DATABASE_URL_ENV,
        f"postgresql+psycopg://wrong:{secret}@db.internal:5432/kjds",
    )
    with pytest.raises(RuntimeError) as captured:
        coverage_issuer_database_url(generic_url=GENERIC)
    assert secret not in str(captured.value)


def test_runtime_database_url_is_separate_from_migration_database(monkeypatch):
    monkeypatch.setenv(
        "KJDS_DATABASE_URL",
        "postgresql+psycopg://admin:a@db.internal:5432/kjds",
    )
    monkeypatch.setenv(RUNTIME_DATABASE_URL_ENV, GENERIC)
    assert runtime_database_url() == GENERIC


def test_runtime_database_url_fails_closed_when_missing_or_reuses_migration_login(
    monkeypatch,
):
    migration = "postgresql+psycopg://admin:a@db.internal:5432/kjds"
    monkeypatch.setenv("KJDS_DATABASE_URL", migration)
    monkeypatch.delenv(RUNTIME_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match="credential is required"):
        runtime_database_url()
    monkeypatch.setenv(RUNTIME_DATABASE_URL_ENV, migration)
    with pytest.raises(RuntimeError, match="principals must differ"):
        runtime_database_url()


def test_database_health_default_uses_and_disposes_runtime_engine(monkeypatch):
    monkeypatch.setenv(
        "KJDS_DATABASE_URL",
        "postgresql+psycopg://migration:migration@db.internal:5432/kjds",
    )
    monkeypatch.setenv(RUNTIME_DATABASE_URL_ENV, GENERIC)
    target = FakeHealthEngine()
    captured: list[str] = []

    def create_runtime_engine(url):
        captured.append(url)
        return target

    monkeypatch.setattr(database_module, "create_database_engine", create_runtime_engine)
    assert database_health() == {"status": "ok"}
    assert captured == [GENERIC]
    assert target.connection.executed == ["SELECT 1"]
    assert target.connect_count == 1
    assert target.dispose_count == 1


def test_database_health_explicit_engine_is_reused_and_not_disposed(monkeypatch):
    target = FakeHealthEngine()
    monkeypatch.setattr(
        database_module,
        "create_database_engine",
        lambda *_args, **_kwargs: pytest.fail("explicit health engine was ignored"),
    )
    assert database_health(target) == {"status": "ok"}
    assert target.connection.executed == ["SELECT 1"]
    assert target.connect_count == 1
    assert target.dispose_count == 0


def test_database_health_fails_closed_without_isolated_runtime_principal(monkeypatch):
    migration = "postgresql+psycopg://migration:migration@db.internal:5432/kjds"
    monkeypatch.setenv("KJDS_DATABASE_URL", migration)
    monkeypatch.delenv(RUNTIME_DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match="credential is required"):
        database_health()
    monkeypatch.setenv(RUNTIME_DATABASE_URL_ENV, migration)
    with pytest.raises(RuntimeError, match="principals must differ"):
        database_health()


def test_database_health_errors_hide_runtime_dsn_and_dispose_temporary_engine(
    monkeypatch,
):
    secret = "runtime-health-secret"
    monkeypatch.setenv(
        "KJDS_DATABASE_URL",
        "postgresql+psycopg://migration:migration@db.internal:5432/kjds",
    )
    monkeypatch.setenv(
        RUNTIME_DATABASE_URL_ENV,
        f"postgresql+psycopg://kjds_runtime:{secret}@db.internal:5432/kjds",
    )
    target = FakeHealthEngine(error=RuntimeError(f"connection leaked {secret}"))
    monkeypatch.setattr(
        database_module,
        "create_database_engine",
        lambda _url: target,
    )
    with pytest.raises(RuntimeError, match="health check failed") as captured:
        database_health()
    assert secret not in str(captured.value)
    assert GENERIC not in str(captured.value)
    assert target.dispose_count == 1

    monkeypatch.setenv(RUNTIME_DATABASE_URL_ENV, f"sqlite:///{secret}.db")
    with pytest.raises(RuntimeError) as invalid:
        database_health()
    assert secret not in str(invalid.value)


def test_production_composition_injects_port_only_into_coverage_authority(
    monkeypatch,
):
    class IssuerPort:
        def issue_evidence(self, **_kwargs):
            return "evd_test"

    port = IssuerPort()
    monkeypatch.setattr(
        database_module,
        "create_coverage_issuer_port",
        lambda **_kwargs: port,
    )
    evidence = SimpleNamespace(
        engine=SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            url=make_url(GENERIC),
        )
    )
    authority = database_module.create_global_data_coverage_evidence_authority(
        evidence=evidence,
        scope_grants=object(),
        intake_authority=object(),
    )
    assert authority._issuer_port is port
    assert not hasattr(evidence, "_coverage_issuer_port")


def test_only_api_receives_issuer_credential_and_runtime_hides_raw_engine():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    runtime = (root / "apps/control_plane/runtime.py").read_text(encoding="utf-8")
    evidence = (root / "apps/control_plane/evidence.py").read_text(encoding="utf-8")

    assert sum(
        line.strip().startswith("KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL:")
        for line in compose.splitlines()
    ) == 1
    assert sum(
        line.strip().startswith("KJDS_RUNTIME_DATABASE_URL:")
        for line in compose.splitlines()
    ) == 4
    assert "coverage_issuer_engine:" not in runtime
    assert "evidence.coverage_issuer_engine" not in runtime
    assert "EvidenceService(engine, coverage_issuer_port=" not in runtime
    assert "def build_global_data_coverage_evidence_authority(" in runtime
    assert "create_global_data_coverage_evidence_authority(" in runtime
    assert "global_data_coverage_evidence_authority_factory" in runtime
    assert "coverage_intake_authority_factory" in runtime
    assert "def __init__(self, engine, *, coverage_issuer_port" not in evidence
