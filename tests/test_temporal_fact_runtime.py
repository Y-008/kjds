from sqlalchemy import create_engine, inspect

from apps.control_plane import runtime as runtime_module
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.skill_usage_sql import SqlSkillUsageLedger
from apps.control_plane.temporal_fact_sql import SqlTemporalFactStore


def test_build_runtime_injects_sql_temporal_fact_store_without_startup_ddl(monkeypatch):
    """Composition binds the adapter to the shared engine and stays side-effect free."""

    engine = create_engine("sqlite://")
    monkeypatch.setenv("KJDS_REPOSITORY", "memory")
    monkeypatch.setattr(runtime_module, "build_repository", InMemoryRepository)
    monkeypatch.setattr(runtime_module, "create_database_engine", lambda: engine)

    services = runtime_module.build_runtime()

    assert isinstance(services.temporal_fact_store, SqlTemporalFactStore)
    assert isinstance(services.skill_usage_ledger, SqlSkillUsageLedger)
    assert services.temporal_fact_store.engine is services.engine is engine
    assert services.skill_usage_ledger.engine is engine
    # The temporal table is owned by migrations; runtime composition must not
    # create DDL implicitly.
    assert not inspect(engine).has_table("temporal_fact_revisions")
    assert not inspect(engine).has_table("skill_usage_events")

    engine.dispose()
