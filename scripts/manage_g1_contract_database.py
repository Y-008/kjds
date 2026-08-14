from __future__ import annotations

import os
import re
import sys

from sqlalchemy import create_engine, text


def main() -> None:
    name = os.environ["KJDS_G1_CONTRACT_DATABASE_NAME"]
    token_sha256 = os.environ["KJDS_G1_RUN_TOKEN_SHA256"]
    admin_url = os.environ["KJDS_G1_ADMIN_DATABASE_URL"]
    if not re.fullmatch(r"kjds_g1_contract_[0-9a-f]{24}", name):
        raise RuntimeError("invalid G-1 contract database name")
    if not re.fullmatch(r"[0-9a-f]{64}", token_sha256):
        raise RuntimeError("invalid G-1 contract database owner digest")
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "drop"}:
        raise RuntimeError("unsupported G-1 contract database action")

    owner_comment = f"kjds-g1-contract:{token_sha256}"
    quoted_name = f'"{name}"'
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if sys.argv[1] == "create":
                exists = connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=:name)"
                    ),
                    {"name": name},
                )
                if exists:
                    raise RuntimeError("run-scoped G-1 contract database already exists")
                created = False
                try:
                    connection.execute(text(f"CREATE DATABASE {quoted_name}"))
                    created = True
                    connection.execute(
                        text(f"COMMENT ON DATABASE {quoted_name} IS '{owner_comment}'")
                    )
                except BaseException:
                    if created:
                        connection.execute(
                            text(f"DROP DATABASE IF EXISTS {quoted_name}")
                        )
                    raise
                return

            comment = connection.scalar(
                text(
                    "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                    "WHERE datname=:name"
                ),
                {"name": name},
            )
            if comment != owner_comment:
                raise RuntimeError("G-1 contract database is not owned by this run")
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid<>pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f"DROP DATABASE {quoted_name}"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
