from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.database import create_database_engine
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import ProductRow
from apps.control_plane.warehouse_fulfillment import (
    WarehouseExecutionEventRow,
)

PREFIX = "kjds_bas157_replay_"


def main() -> None:
    source = create_database_engine()
    database_name = f"{PREFIX}{uuid4().hex[:10]}"
    if not database_name.startswith(PREFIX):
        raise RuntimeError(
            "Temporary database name is outside the BAS-157 prefix"
        )
    admin_url = source.url.set(database="postgres")
    replay_url = source.url.set(database=database_name)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    replay = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        config = Config("alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            replay_url.render_as_string(hide_password=False),
        )
        command.upgrade(config, "head")
        replay = create_engine(replay_url)
        tables = set(inspect(replay).get_table_names())
        if "warehouse_execution_events" not in tables:
            raise RuntimeError(
                "Empty replay did not create the BAS-157 authority"
            )
        unique_constraints = {
            constraint["name"]
            for constraint in inspect(replay).get_unique_constraints(
                "warehouse_execution_events"
            )
        }
        required_unique_constraints = {
            "uq_warehouse_execution_source_event",
            "uq_warehouse_execution_aggregate_sequence",
            "uq_warehouse_execution_command",
            "uq_warehouse_execution_receipt",
        }
        if not required_unique_constraints <= unique_constraints:
            raise RuntimeError(
                "BAS-157 one-time Permit/Readback uniqueness is incomplete"
            )
        with replay.connect() as connection:
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT trigger_name "
                        "FROM information_schema.triggers "
                        "WHERE event_object_table = "
                        "'warehouse_execution_events'"
                    )
                )
            )
        required_triggers = {
            "trg_warehouse_execution_no_update",
            "trg_warehouse_execution_no_delete",
        }
        if not required_triggers <= triggers:
            raise RuntimeError(
                "BAS-157 append-only triggers are incomplete"
            )
        observed_at = datetime.now(UTC)
        evidence = EvidenceService(replay).capture(
            content=b'{"event":"wave_created"}',
            filename="warehouse-event.json",
            content_type="application/json",
            source="authorized_warehouse_system",
            source_ref=f"bas157-replay://{database_name}",
            grade=EvidenceGrade.A,
            effective_at=observed_at.isoformat(),
            effective_until=None,
            created_by="bas157-replay",
            metadata={"retention_class": "operational"},
        )
        with Session(replay) as session, session.begin():
            session.add(
                ProductRow(
                    id="bas157-product",
                    sku="BAS157-SKU",
                    name="BAS157 replay product",
                    market="RU",
                    channel="OZON",
                    status="active",
                    created_at=observed_at,
                    tenant_ref="bas157-tenant",
                    entity_ref="bas157-entity",
                    store_ref="bas157-store",
                    scope_grant_authority_sha256="a" * 64,
                    scope_as_of=observed_at,
                    created_by="bas157-replay",
                )
            )
            session.add(
                WarehouseExecutionEventRow(
                    id="bas157-event",
                    source_event_ref="bas157-source-event",
                    aggregate_ref="bas157-wave",
                    sequence=1,
                    event_type="wave_created",
                    order_external_id="bas157-order",
                    product_id="bas157-product",
                    sku="BAS157-SKU",
                    evidence_id=evidence.id,
                    source_payload_sha256="b" * 64,
                    payload_sha256="c" * 64,
                    effective_at=observed_at,
                    recorded_at=observed_at,
                    created_by="bas157-replay",
                    tenant_ref="bas157-tenant",
                    entity_ref="bas157-entity",
                    store_ref="bas157-store",
                    warehouse_ref="bas157-warehouse",
                    scope_grant_authority_sha256="a" * 64,
                    source_evidence_sha256=evidence.sha256,
                    scope_as_of=observed_at,
                )
            )
        for statement in (
            "UPDATE warehouse_execution_events "
            "SET sku = 'MUTATED' WHERE id = 'bas157-event'",
            "DELETE FROM warehouse_execution_events "
            "WHERE id = 'bas157-event'",
        ):
            try:
                with replay.begin() as connection:
                    connection.execute(text(statement))
            except DBAPIError:
                continue
            raise RuntimeError(
                "PostgreSQL allowed mutation of append-only warehouse facts"
            )
        command.downgrade(config, "20260730_0079")
        replay.dispose()
        replay = None
        check = create_engine(replay_url)
        try:
            if "warehouse_execution_events" in set(
                inspect(check).get_table_names()
            ):
                raise RuntimeError(
                    "BAS-157 downgrade left the warehouse event table"
                )
        finally:
            check.dispose()
        command.upgrade(config, "head")
        replay = create_engine(replay_url)
        if "warehouse_execution_events" not in set(
            inspect(replay).get_table_names()
        ):
            raise RuntimeError(
                "BAS-157 re-upgrade did not restore the authority"
            )
        print(
            "BAS-157 empty PostgreSQL replay passed: "
            "base -> 0080 -> 0079 -> 0080"
        )
    finally:
        if replay is not None:
            replay.dispose()
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
            connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}"')
            )
        admin.dispose()


if __name__ == "__main__":
    main()
