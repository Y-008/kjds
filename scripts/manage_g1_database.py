from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from apps.control_plane.database import database_url

DATABASE_NAME = "kjds_g1_smoke"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("recreate", "drop"))
    args = parser.parse_args()

    url = make_url(database_url())
    if url.database != DATABASE_NAME:
        raise RuntimeError(f"G-1 database manager only accepts {DATABASE_NAME!r}")
    admin_url = url.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)'))
        if args.action == "recreate":
            connection.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
        exists = connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=:name)"),
            {"name": DATABASE_NAME},
        )
    expected = args.action == "recreate"
    if bool(exists) is not expected:
        raise RuntimeError(f"Database {args.action} verification failed")
    print({"database": DATABASE_NAME, "action": args.action, "status": "passed"})


if __name__ == "__main__":
    main()
