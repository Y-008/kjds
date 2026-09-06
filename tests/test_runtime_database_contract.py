"""Fail-closed runtime and migration contract checks.

These tests deliberately avoid opening a real database.  The PostgreSQL
upgrade and replay gate remains the authoritative integration check; this file
guards the local contracts that are easy to regress before that gate runs.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import apps.control_plane.database as database

ROOT = Path(__file__).resolve().parents[1]


def test_project_graph_migration_declares_each_column_once_and_keeps_recorded_time():
    path = ROOT / "migrations" / "versions" / "20260906_0110_project_graph_proposals.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    column_names = [
        node.args[0].value
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Column"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        )
    ]
    assert column_names.count("recorded_at") == 1
    assert "observed_at" in column_names
    assert len(column_names) == len(set(column_names))


def test_migration_graph_has_one_current_head_after_ledger_hardening():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["20260906_0117"]
    assert script.get_revision("20260906_0117").down_revision == "20260906_0116"


def test_ledger_immutability_migration_covers_all_new_tables():
    sources = {
        revision: (ROOT / "migrations" / "versions" / filename).read_text(encoding="utf-8")
        for revision, filename in {
            "20260906_0111": "20260906_0111_new_ledger_immutability.py",
            "20260906_0112": "20260906_0112_autonomous_execution_profiles.py",
            "20260906_0113": "20260906_0113_commercial_finance_events.py",
            "20260906_0114": "20260906_0114_resource_budget_events.py",
            "20260906_0115": "20260906_0115_resource_admission_events.py",
            "20260906_0116": "20260906_0116_after_sales_events.py",
            "20260906_0117": "20260906_0117_usage_entitlement_receipt_links.py",
        }.items()
    }
    for table in database.REQUIRED_RUNTIME_TABLES[1:]:
        assert any(f'"{table}"' in source for source in sources.values())
    for source in sources.values():
        assert (
            'trg_{table}_immutable' in source
            or 'trg_commercial_finance_events_immutable' in source
            or 'trg_after_sales_events_immutable' in source
            or 'trg_skill_usage_entitlement_links_immutable' in source
        )
        assert (
            'trg_{table}_truncate_immutable' in source
            or 'trg_commercial_finance_events_truncate_immutable' in source
            or 'trg_after_sales_events_truncate_immutable' in source
            or 'trg_skill_usage_entitlement_links_truncate_immutable' in source
        )
        assert "BEFORE UPDATE OR DELETE" in source
        assert "BEFORE TRUNCATE" in source


def test_postgresql_engine_gets_a_bounded_connect_timeout(monkeypatch):
    captured: dict[str, object] = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return "engine"

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    monkeypatch.setenv(database.DATABASE_CONNECT_TIMEOUT_ENV, "999")
    assert database.create_database_engine(
        "postgresql+psycopg://user:password@db.internal:5432/kjds"
    ) == "engine"
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": 30},
    }


def test_explicit_postgresql_timeout_is_preserved(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        database,
        "create_engine",
        lambda url, **kwargs: captured.update(kwargs) or "engine",
    )
    database.create_database_engine(
        "postgresql+psycopg://user:password@db.internal:5432/kjds?connect_timeout=11"
    )
    assert captured == {"pool_pre_ping": True}


def test_non_postgresql_engine_does_not_receive_psycopg_connect_args(monkeypatch):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        database,
        "create_engine",
        lambda url, **kwargs: captured.update(kwargs) or "engine",
    )
    database.create_database_engine("sqlite://")
    assert captured == {"pool_pre_ping": True}


class _ProbeResult:
    def __init__(self, values=(), scalar_value=None):
        self.values = tuple(values)
        self.scalar_value = scalar_value

    def scalars(self):
        return iter(self.values)

    def scalar(self):
        return self.scalar_value


class _ProbeConnection:
    def __init__(self, *, missing: set[str] | None = None, heads=("head",)):
        self.missing = missing or set()
        self.heads = heads
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        if "version_num" in sql:
            return _ProbeResult(values=self.heads)
        if "to_regclass" in sql:
            table = str((params or {}).get("qualified_name", "")).removeprefix("public.")
            return _ProbeResult(scalar_value=None if table in self.missing else table)
        return _ProbeResult()


class _ProbeEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_postgresql_health_requires_current_head_and_required_tables(monkeypatch):
    monkeypatch.setattr(database, "expected_migration_heads", lambda: ("head",))
    connection = _ProbeConnection()
    assert database.database_health(_ProbeEngine(connection)) == {"status": "ok"}
    assert any("alembic_version" in statement for statement in connection.statements)
    assert any("public.alembic_version" in statement for statement in connection.statements)


def test_postgresql_health_fails_closed_on_stale_head_or_missing_table(monkeypatch):
    monkeypatch.setattr(database, "expected_migration_heads", lambda: ("head",))
    with pytest.raises(RuntimeError, match="health check failed"):
        database.database_health(_ProbeEngine(_ProbeConnection(heads=("old",))))
    with pytest.raises(RuntimeError, match="health check failed"):
        database.database_health(
            _ProbeEngine(_ProbeConnection(missing={"project_graph_proposals"}))
        )


def test_readiness_translates_degraded_health_to_http_503(monkeypatch):
    from apps.control_plane.routers import system

    monkeypatch.setattr(
        system,
        "health",
        lambda: {
            "status": "degraded",
            "database": {"status": "error", "code": "migration_not_current"},
        },
    )
    with pytest.raises(HTTPException) as caught:
        system.ready()
    assert caught.value.status_code == 503
