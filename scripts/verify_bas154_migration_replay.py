from __future__ import annotations

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from apps.control_plane.database import create_database_engine

PREFIX = "kjds_bas154_replay_"


def main() -> None:
    source = create_database_engine()
    database_name = f"{PREFIX}{uuid4().hex[:10]}"
    if not database_name.startswith(PREFIX):
        raise RuntimeError("Temporary database name is outside the BAS-154 prefix")
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
        required = {
            "customer_service_cases",
            "customer_service_events",
        }
        if not required <= tables:
            raise RuntimeError("Empty replay did not create BAS-154 tables")
        command.downgrade(config, "20260730_0078")
        replay.dispose()
        replay = None
        check = create_engine(replay_url)
        try:
            downgraded = set(inspect(check).get_table_names())
            if required & downgraded:
                raise RuntimeError("BAS-154 downgrade left customer-service tables")
        finally:
            check.dispose()
        command.upgrade(config, "head")
        replay = create_engine(replay_url)
        restored = set(inspect(replay).get_table_names())
        if not required <= restored:
            raise RuntimeError("BAS-154 re-upgrade did not restore tables")
        print("BAS-154 empty PostgreSQL replay passed: base -> 0079 -> 0078 -> 0079")
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
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin.dispose()


if __name__ == "__main__":
    main()
