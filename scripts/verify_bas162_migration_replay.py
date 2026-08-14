from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from apps.control_plane.database import create_database_engine
from apps.control_plane.evidence import EvidenceService
from apps.control_plane.security import Principal
from apps.control_plane.store_category_strategy import StoreCategoryStrategyWorkspace

PREFIX = "kjds_bas162_replay_"
DATABASE_NAME_RE = re.compile(r"kjds_bas162_replay_[0-9a-f]{12}")
REVISION = "20260802_0086"
PREVIOUS_REVISION = "20260802_0085"
TABLES = {
    "store_operating_profile_events": "trg_store_operating_profile_events_immutable",
    "store_operating_plan_snapshots": "trg_store_operating_plan_snapshots_immutable",
}


def _validate_database_name(value: str) -> None:
    if not value.startswith(PREFIX) or DATABASE_NAME_RE.fullmatch(value) is None:
        raise RuntimeError("Temporary database is outside the BAS-162 replay prefix")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(text("SELECT version_num FROM alembic_version")) or "")


def _triggers(engine: Engine, table_name: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.scalars(
                text(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE trigger_schema = current_schema() "
                    "AND event_object_table = :table_name"
                ),
                {"table_name": table_name},
            )
        )


def _verify_revision(engine: Engine) -> None:
    if _revision(engine) != REVISION:
        raise RuntimeError("BAS-162 replay did not reach revision 0086")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table_name, trigger_name in TABLES.items():
        if table_name not in tables:
            raise RuntimeError(f"BAS-162 table missing: {table_name}")
        if trigger_name not in _triggers(engine, table_name):
            raise RuntimeError(f"BAS-162 immutable trigger missing: {trigger_name}")


def _seed_and_verify_immutability(engine: Engine) -> None:
    principal = Principal(
        actor_id="bas162-operator",
        roles=frozenset({"operator"}),
        tenant_ref="bas162-tenant",
        store_refs=frozenset({"bas162-store"}),
    )
    entity_scope = {
        "status": "ready",
        "entity_ref": "bas162-entity",
        "authority_sha256": "a" * 64,
    }
    cutoff = datetime.now(UTC)
    workspace = StoreCategoryStrategyWorkspace(
        engine=engine,
        evidence=EvidenceService(engine),
    )
    profile = workspace.capture_profile(
        {
            "idempotency_key": "bas162-profile-v1",
            "confirmed": True,
            "store_positioning": "category_specialist",
            "assortment_mode": "hybrid",
            "price_band": "mid",
            "target_regions": ["RU"],
            "fulfillment_models": ["FBS"],
            "planned_growth_channels": ["ozon"],
            "customer_segments": ["test"],
            "operational_capabilities": ["manual-review"],
            "supporting_evidence_ids": [],
            "category_paths": [
                {
                    "path_id": "bas162-category",
                    "role": "core",
                    "level_1": {"id": "l1", "name": "Level 1"},
                    "level_2": {"id": "l2", "name": "Level 2"},
                    "level_3": {"id": "l3", "name": "Level 3"},
                    "leaf_category_id": "leaf-1",
                    "product_type_ids": ["type-1"],
                    "derived_tags": ["content_led"],
                    "target_regions": ["RU"],
                }
            ],
        },
        principal=principal,
        entity_scope=entity_scope,
        store_ref="bas162-store",
        as_of=cutoff,
    )
    plan = workspace.compile_plan(
        {
            "summary": {},
            "candidates": [],
            "snapshot_sha256": "b" * 64,
        },
        principal=principal,
        entity_scope=entity_scope,
        store_ref="bas162-store",
        as_of=cutoff,
    )
    frozen = workspace.freeze_plan(
        plan,
        idempotency_key="bas162-plan-v1",
        principal=principal,
        entity_scope=entity_scope,
        store_ref="bas162-store",
        as_of=cutoff,
    )
    for statement in (
        "UPDATE store_operating_profile_events SET store_ref='mutated' "
        f"WHERE id='{profile['profile_id']}'",
        "DELETE FROM store_operating_plan_snapshots "
        f"WHERE id='{frozen['snapshot_id']}'",
    ):
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError:
            continue
        raise RuntimeError("BAS-162 append-only mutation unexpectedly succeeded")


def main() -> None:
    source = create_database_engine()
    if source.dialect.name != "postgresql":
        source.dispose()
        raise RuntimeError("BAS-162 migration replay requires PostgreSQL")
    database_name = f"{PREFIX}{uuid4().hex[:12]}"
    _validate_database_name(database_name)
    admin = create_engine(source.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    replay_url = source.url.set(database=database_name)
    replay: Engine | None = None
    created = False
    previous_database_url = os.environ.get("KJDS_DATABASE_URL")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            replay_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        os.environ["KJDS_DATABASE_URL"] = replay_url.render_as_string(
            hide_password=False
        )
        command.upgrade(config, REVISION)
        replay = create_engine(replay_url)
        _verify_revision(replay)
        _seed_and_verify_immutability(replay)
        command.downgrade(config, PREVIOUS_REVISION)
        if _revision(replay) != PREVIOUS_REVISION:
            raise RuntimeError("BAS-162 downgrade did not reach revision 0085")
        remaining = set(TABLES) & set(inspect(replay).get_table_names())
        if remaining:
            raise RuntimeError("BAS-162 downgrade left strategy tables behind")
        command.upgrade(config, REVISION)
        _verify_revision(replay)
        print("BAS-162 PostgreSQL replay passed: base -> 0086 -> 0085 -> 0086")
    finally:
        if previous_database_url is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous_database_url
        if replay is not None:
            replay.dispose()
        if created:
            _validate_database_name(database_name)
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()
        source.dispose()


if __name__ == "__main__":
    main()
