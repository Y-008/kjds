from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import statistics
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql

from apps.control_plane.postgres18_pilot import (
    POSTGRES18_PILOT_REPORT_ID,
    Postgres18PilotAuthority,
    Postgres18PilotError,
    Postgres18PilotPolicy,
    canonical_json,
    sha256_json,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / ".runtime"
POLICY_PATH = ROOT / "docs/project/contracts/postgres18-pilot-policy-v1.json"
COMPOSE_PATH = ROOT / "compose.yaml"
DATABASE_NAME = "kjds_bas176_pilot"
ARCHIVE_NAME = "frozen-pre-cutover-pg17.dump"
CURRENT_STAGE = "startup"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,511}$")


def _stage(value: str) -> None:
    global CURRENT_STAGE
    CURRENT_STAGE = value


def _run(
    arguments: Sequence[str],
    *,
    check: bool = True,
    env: Mapping[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        list(arguments),
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(env) if env is not None else None,
    )
    return completed.stdout.strip()


def _docker(*arguments: str, check: bool = True) -> str:
    return _run(("docker", *arguments), check=check)


def _docker_object_exists(*arguments: str) -> bool:
    completed = subprocess.run(
        ["docker", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Postgres18PilotError(f"Expected JSON object: {path.name}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _full_commit() -> str:
    value = _run(("git", "rev-parse", "HEAD")).lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise Postgres18PilotError("Git HEAD is not a full SHA-1 object ID")
    return value


def _migration_head() -> str:
    versions = sorted((ROOT / "migrations/versions").glob("*.py"))
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for path in versions:
        content = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision\s*=\s*"([0-9]{8}_[0-9]{4})"', content, re.MULTILINE)
        down = re.search(
            r'^down_revision\s*=\s*(?:"([0-9]{8}_[0-9]{4})"|None)',
            content,
            re.MULTILINE,
        )
        if revision:
            revisions.add(revision.group(1))
        if down and down.group(1):
            down_revisions.add(down.group(1))
    heads = revisions - down_revisions
    if len(heads) != 1:
        raise Postgres18PilotError("Alembic migration graph is not single-head")
    return next(iter(heads))


def _compose_image() -> str:
    content = COMPOSE_PATH.read_text(encoding="utf-8")
    postgres = re.search(
        r"(?ms)^\s{2}postgres:\s*\n(?:(?:\s{4}.*\n)*?)\s{4}image:\s*([^\s#]+)",
        content,
    )
    if postgres is None:
        raise Postgres18PilotError("Compose PostgreSQL image is not inspectable")
    return postgres.group(1)


def _compose_postgres_container() -> str | None:
    value = _run(("docker", "compose", "ps", "-q", "postgres"), check=True).strip()
    return value or None


def _image_evidence(image: str, *, healthy: bool) -> dict[str, Any]:
    if not _SAFE_IMAGE.fullmatch(image):
        raise Postgres18PilotError("Docker image name is invalid")
    payload = json.loads(_docker("image", "inspect", image))
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise Postgres18PilotError("Docker image metadata is invalid")
    document = payload[0]
    image_id = str(document.get("Id") or "")
    repo_digests = document.get("RepoDigests")
    if not image_id.startswith("sha256:") or not isinstance(repo_digests, list) or not repo_digests:
        raise Postgres18PilotError("Docker image is not content-addressed")
    return {
        "image": image,
        "imageIdSha256": image_id.removeprefix("sha256:"),
        "repoDigest": str(repo_digests[0]),
        "healthy": healthy,
    }


class DisposablePostgres:
    def __init__(
        self,
        *,
        image: str,
        name: str,
        alias: str,
        network: str,
        password: str,
        major: int,
        run_id: str,
    ) -> None:
        if not all(_SAFE_NAME.fullmatch(value) for value in (name, alias, network, run_id)):
            raise Postgres18PilotError("Disposable Docker identity is invalid")
        if major not in {17, 18}:
            raise Postgres18PilotError("Disposable PostgreSQL major is invalid")
        self.image = image
        self.name = name
        self.alias = alias
        self.network = network
        self.password = password
        self.major = major
        self.run_id = run_id
        self.port: int | None = None
        self.started = False
        self.mounts: list[dict[str, Any]] = []
        self.host_ip = ""

    @property
    def psycopg_dsn(self) -> str:
        if self.port is None:
            raise Postgres18PilotError("Disposable PostgreSQL port is unavailable")
        return f"postgresql://postgres:{self.password}@127.0.0.1:{self.port}/{DATABASE_NAME}"

    @property
    def admin_dsn(self) -> str:
        if self.port is None:
            raise Postgres18PilotError("Disposable PostgreSQL port is unavailable")
        return f"postgresql://postgres:{self.password}@127.0.0.1:{self.port}/postgres"

    @property
    def sqlalchemy_url(self) -> str:
        return self.psycopg_dsn.replace("postgresql://", "postgresql+psycopg://", 1)

    def start(self) -> None:
        data_mount = (
            "/var/lib/postgresql/data"
            if self.major == 17
            else "/var/lib/postgresql"
        )
        pgdata = (
            "/var/lib/postgresql/data"
            if self.major == 17
            else "/var/lib/postgresql/18/docker"
        )
        _docker(
            "run",
            "-d",
            "--name",
            self.name,
            "--network",
            self.network,
            "--network-alias",
            self.alias,
            "--mount",
            f"type=tmpfs,destination={data_mount},tmpfs-size=1073741824",
            "-e",
            f"POSTGRES_PASSWORD={self.password}",
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            "POSTGRES_DB=postgres",
            "-e",
            f"PGDATA={pgdata}",
            "-p",
            "127.0.0.1::5432",
            "--label",
            f"io.kjds.bas176={self.run_id}",
            self.image,
        )
        self.started = True
        payload = json.loads(_docker("inspect", self.name))[0]
        binding = payload["NetworkSettings"]["Ports"]["5432/tcp"][0]
        self.host_ip = str(binding["HostIp"])
        self.port = int(binding["HostPort"])
        self.mounts = [dict(item) for item in payload.get("Mounts") or []]
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(self.admin_dsn, connect_timeout=2) as connection:
                    if connection.execute("SELECT 1").fetchone() == (1,):
                        return
            except psycopg.Error:
                time.sleep(0.5)
        raise Postgres18PilotError("Disposable PostgreSQL did not become ready")

    def create_database(self) -> None:
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DATABASE_NAME)))
            connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(DATABASE_NAME)))

    def drop_database(self) -> None:
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DATABASE_NAME)))

    def server_version(self) -> str:
        with psycopg.connect(self.admin_dsn) as connection:
            return str(connection.execute("SELECT version()").fetchone()[0])

    def remove(self) -> None:
        if self.started:
            _docker("rm", "-f", "-v", self.name, check=False)
            self.started = False


def _run_alembic(instance: DisposablePostgres, action: str, revision: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    previous = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = instance.sqlalchemy_url
    try:
        if action == "upgrade":
            command.upgrade(config, revision)
        elif action == "downgrade":
            command.downgrade(config, revision)
        else:
            raise Postgres18PilotError("Alembic action is invalid")
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous


def _alembic_head(instance: DisposablePostgres) -> str:
    with psycopg.connect(instance.psycopg_dsn) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None:
        raise Postgres18PilotError("Alembic version row is missing")
    return str(row[0])


def _schema_inventory(instance: DisposablePostgres) -> dict[str, Any]:
    with psycopg.connect(instance.psycopg_dsn) as connection:
        tables = connection.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        columns = connection.execute(
            """
            SELECT namespace.nspname, relation.relname, attribute.attname,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                   attribute.attnotnull, attribute.attidentity,
                   attribute.attgenerated
            FROM pg_catalog.pg_attribute AS attribute
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = attribute.attrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY namespace.nspname, relation.relname, attribute.attname
            """
        ).fetchall()
        constraints = connection.execute(
            """
            SELECT namespace.nspname, relation.relname,
                   constraint_row.conname, constraint_row.contype
            FROM pg_catalog.pg_constraint AS constraint_row
            JOIN pg_catalog.pg_class AS relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND constraint_row.contype <> 'n'
            ORDER BY namespace.nspname, relation.relname,
                     constraint_row.conname, constraint_row.contype
            """
        ).fetchall()
        indexes = connection.execute(
            """
            SELECT schemaname, tablename, indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY schemaname, tablename, indexname
            """
        ).fetchall()
    payload = {
        "tables": [list(row) for row in tables],
        "columns": [list(row) for row in columns],
        "constraints": [list(row) for row in constraints],
        "indexes": [list(row) for row in indexes],
    }
    return {
        "sha256": sha256_json(payload),
        "componentSha256": {
            key: sha256_json(value) for key, value in payload.items()
        },
        "tableCount": len(tables),
        "columnCount": len(columns),
        "constraintCount": len(constraints),
        "indexCount": len(indexes),
    }


def _extensions(instance: DisposablePostgres) -> list[dict[str, str]]:
    with psycopg.connect(instance.psycopg_dsn) as connection:
        rows = connection.execute(
            "SELECT extname, extversion FROM pg_extension ORDER BY extname"
        ).fetchall()
    return [{"name": str(name), "version": str(version)} for name, version in rows]


def _seed_dataset(instance: DisposablePostgres, rows: int) -> None:
    with psycopg.connect(instance.psycopg_dsn) as connection, connection.transaction():
        connection.execute("CREATE SCHEMA bas176_pilot")
        connection.execute(
            """
            CREATE TABLE bas176_pilot.scoped_events (
                event_id bigint PRIMARY KEY,
                tenant_ref text NOT NULL,
                entity_ref text NOT NULL,
                store_ref text NOT NULL,
                occurred_at timestamptz NOT NULL,
                amount numeric(18, 6) NOT NULL,
                status text NOT NULL,
                payload_sha256 char(64) NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX ix_bas176_scope_time
            ON bas176_pilot.scoped_events
                (tenant_ref, entity_ref, store_ref, occurred_at DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX ix_bas176_status_scope
            ON bas176_pilot.scoped_events (status, tenant_ref, entity_ref)
            """
        )
        connection.execute(
            """
            INSERT INTO bas176_pilot.scoped_events (
                event_id, tenant_ref, entity_ref, store_ref,
                occurred_at, amount, status, payload_sha256
            )
            SELECT i,
                   'tenant-' || mod(i, 8)::text,
                   'entity-' || mod(i, 32)::text,
                   'store-' || mod(i, 128)::text,
                   timestamptz '2026-08-03 00:00:00+00' - make_interval(secs => i),
                   (mod(i, 100000)::numeric / 100.0),
                   CASE WHEN mod(i, 4) = 0 THEN 'ready' ELSE 'observed' END,
                   md5(i::text) || md5('kjds-' || i::text)
            FROM generate_series(1, %s) AS source(i)
            """,
            (rows,),
        )
        connection.execute("ANALYZE bas176_pilot.scoped_events")


def _dataset_fingerprint(instance: DisposablePostgres) -> dict[str, Any]:
    with psycopg.connect(instance.psycopg_dsn) as connection:
        row = connection.execute(
            """
            SELECT count(*)::bigint,
                   md5(string_agg(
                       event_id::text || ':' || tenant_ref || ':' || entity_ref || ':' ||
                       store_ref || ':' || occurred_at::text || ':' || amount::text || ':' ||
                       status || ':' || payload_sha256,
                       '|' ORDER BY event_id
                   ))
            FROM bas176_pilot.scoped_events
            """
        ).fetchone()
    if row is None:
        raise Postgres18PilotError("Synthetic dataset fingerprint is missing")
    return {"rowCount": int(row[0]), "sha256": hashlib.sha256(str(row[1]).encode()).hexdigest()}


def _dump_source(source: DisposablePostgres, output: Path) -> None:
    container_archive = f"/tmp/{ARCHIVE_NAME}"
    _docker(
        "exec",
        source.name,
        "pg_dump",
        "-U",
        "postgres",
        "-d",
        DATABASE_NAME,
        "--format=custom",
        "--no-owner",
        "--no-acl",
        f"--file={container_archive}",
    )
    _docker("cp", f"{source.name}:{container_archive}", str(output))
    _docker("exec", source.name, "rm", "-f", container_archive, check=False)


def _restore_archive(instance: DisposablePostgres, archive: Path) -> None:
    container_archive = f"/tmp/{ARCHIVE_NAME}"
    instance.create_database()
    _docker("cp", str(archive), f"{instance.name}:{container_archive}")
    try:
        _docker(
            "exec",
            instance.name,
            "pg_restore",
            "-U",
            "postgres",
            "-d",
            DATABASE_NAME,
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            container_archive,
        )
    finally:
        _docker("exec", instance.name, "rm", "-f", container_archive, check=False)


_BENCHMARK_QUERIES = {
    "exact_scope_latest": """
        SELECT event_id, status, amount::text
        FROM bas176_pilot.scoped_events
        WHERE tenant_ref = 'tenant-3'
          AND entity_ref = 'entity-11'
          AND store_ref = 'store-43'
        ORDER BY occurred_at DESC
        LIMIT 100
    """,
    "tenant_time_aggregate": """
        SELECT store_ref, count(*)::bigint, sum(amount)::text
        FROM bas176_pilot.scoped_events
        WHERE tenant_ref = 'tenant-3'
          AND occurred_at >= timestamptz '2026-08-02 19:00:00+00'
        GROUP BY store_ref
        ORDER BY store_ref
    """,
    "status_scope_aggregate": """
        SELECT entity_ref, count(*)::bigint,
               min(occurred_at)::text, max(occurred_at)::text
        FROM bas176_pilot.scoped_events
        WHERE status = 'ready' AND tenant_ref = 'tenant-5'
        GROUP BY entity_ref
        ORDER BY entity_ref
    """,
}


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return str(value)


def _plan_nodes(plan: Mapping[str, Any]) -> list[str]:
    names = [str(plan.get("Node Type") or "UNKNOWN")]
    for child in plan.get("Plans") or []:
        if isinstance(child, Mapping):
            names.extend(_plan_nodes(child))
    return names


def _benchmark(instance: DisposablePostgres, warmups: int, measured: int) -> dict[str, Any]:
    output: dict[str, Any] = {}
    with psycopg.connect(instance.psycopg_dsn) as connection:
        for name, query in _BENCHMARK_QUERIES.items():
            rows = connection.execute(query).fetchall()
            result_sha = hashlib.sha256(canonical_json(_json_value(rows))).hexdigest()
            samples: list[float] = []
            nodes: list[str] = []
            for run in range(warmups + measured):
                explain = connection.execute(
                    f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
                ).fetchone()
                if explain is None or not isinstance(explain[0], list):
                    raise Postgres18PilotError("PostgreSQL benchmark plan is invalid")
                document = explain[0][0]
                if run >= warmups:
                    samples.append(float(document["Execution Time"]))
                    nodes = _plan_nodes(document["Plan"])
            output[name] = {
                "resultSha256": result_sha,
                "medianMs": round(statistics.median(samples), 6),
                "maximumMs": round(max(samples), 6),
                "planNodes": sorted(set(nodes)),
            }
    return output


def _lock_observation(instance: DisposablePostgres, timeout_ms: int) -> dict[str, Any]:
    blocker = psycopg.connect(instance.psycopg_dsn)
    waiter = psycopg.connect(instance.psycopg_dsn)
    observer = psycopg.connect(instance.psycopg_dsn)
    state: dict[str, Any] = {}
    try:
        blocker.execute("BEGIN")
        blocker.execute(
            "SELECT event_id FROM bas176_pilot.scoped_events WHERE event_id = 1 FOR UPDATE"
        )
        waiter_pid = waiter.info.backend_pid

        def wait_for_lock() -> None:
            started = time.perf_counter()
            try:
                waiter.execute("BEGIN")
                waiter.execute(f"SET LOCAL lock_timeout = '{timeout_ms}ms'")
                waiter.execute(
                    "UPDATE bas176_pilot.scoped_events SET status = 'blocked' WHERE event_id = 1"
                )
                state["sqlstate"] = "unexpected_success"
            except psycopg.Error as exc:
                state["sqlstate"] = exc.sqlstate
            finally:
                state["waitMs"] = (time.perf_counter() - started) * 1000
                waiter.rollback()

        thread = threading.Thread(target=wait_for_lock, daemon=True)
        thread.start()
        time.sleep(max(0.2, min(timeout_ms / 3000, 0.5)))
        ungranted = int(
            observer.execute(
                "SELECT count(*) FROM pg_locks WHERE pid = %s AND granted = false",
                (waiter_pid,),
            ).fetchone()[0]
        )
        thread.join(timeout=(timeout_ms / 1000) + 3)
        if thread.is_alive():
            raise Postgres18PilotError("PostgreSQL lock waiter did not terminate")
        blocker.rollback()
        row = observer.execute(
            "SELECT status FROM bas176_pilot.scoped_events WHERE event_id = 1"
        ).fetchone()
        return {
            "conflictObserved": state.get("sqlstate") == "55P03",
            "ungrantedLockObserved": ungranted >= 1,
            "timeoutSqlstate": state.get("sqlstate"),
            "waitMs": round(float(state.get("waitMs") or 0.0), 3),
            "blockerRolledBack": True,
            "rowUnchanged": row == ("observed",),
        }
    finally:
        blocker.rollback()
        waiter.rollback()
        observer.rollback()
        blocker.close()
        waiter.close()
        observer.close()


def _feature_probe(candidate: DisposablePostgres) -> dict[str, Any]:
    with psycopg.connect(candidate.psycopg_dsn) as connection:
        uuid_value = str(connection.execute("SELECT uuidv7()::text").fetchone()[0])
        io_method = str(connection.execute("SHOW io_method").fetchone()[0])
        aio_view = bool(
            connection.execute(
                "SELECT to_regclass('pg_catalog.pg_aios') IS NOT NULL"
            ).fetchone()[0]
        )
        oauth_setting = connection.execute(
            "SELECT current_setting('oauth_validator_libraries', true)"
        ).fetchone()[0]
        connection.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        connection.execute(
            """
            CREATE TEMP TABLE bas176_temporal_probe (
                entity_id bigint NOT NULL,
                valid_at tstzrange NOT NULL,
                PRIMARY KEY (entity_id, valid_at WITHOUT OVERLAPS)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO bas176_temporal_probe VALUES
                (1, tstzrange('2026-01-01', '2026-02-01', '[)'))
            """
        )
        connection.execute("SAVEPOINT overlap_probe")
        overlap_rejected = False
        try:
            connection.execute(
                """
                INSERT INTO bas176_temporal_probe VALUES
                    (1, tstzrange('2026-01-15', '2026-02-15', '[)'))
                """
            )
        except psycopg.Error as exc:
            overlap_rejected = exc.sqlstate == "23P01"
            connection.execute("ROLLBACK TO SAVEPOINT overlap_probe")
        connection.rollback()
    return {
        "uuidv7Supported": len(uuid_value) == 36 and uuid_value[14] == "7",
        "temporalWithoutOverlapsSupported": True,
        "temporalOverlapRejected": overlap_rejected,
        "aioViewAvailable": aio_view,
        "ioMethod": io_method,
        "oauthServerCapabilityVisible": oauth_setting is not None,
        "oauthRuntimeConfigured": bool(str(oauth_setting or "").strip()),
    }


def _container_isolation(instances: Sequence[DisposablePostgres]) -> tuple[bool, bool]:
    loopback = all(item.host_ip == "127.0.0.1" for item in instances)
    tmpfs = all(
        item.mounts
        and all(str(mount.get("Type")) == "tmpfs" for mount in item.mounts)
        for item in instances
    )
    return loopback, tmpfs


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_output_dir(path: Path) -> Path:
    runtime = RUNTIME_ROOT.resolve()
    output = path.resolve()
    if output.parent != runtime or not output.name.startswith("postgres18-pilot-"):
        raise Postgres18PilotError("Pilot output must be a direct BAS-176 runtime directory")
    if output.exists():
        raise Postgres18PilotError("Pilot output directory already exists")
    output.mkdir(parents=True)
    return output


def _run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    _stage("policy_and_repository_validation")
    policy_document = _load_json(args.policy)
    policy = Postgres18PilotPolicy.from_document(policy_document)
    policy_sha = _sha256_file(args.policy)
    source_commit = _full_commit()
    migration_head = _migration_head()
    if migration_head != policy.migration_head:
        raise Postgres18PilotError("Repository migration head drift")
    if _compose_image() != policy.baseline_compose_image:
        raise Postgres18PilotError("PostgreSQL 17 compose baseline drift")
    if args.pull:
        _stage("image_pull")
        _docker("pull", policy.baseline_pilot_image)
        _docker("pull", policy.candidate_image)
    _stage("output_and_baseline_snapshot")
    output = _validate_output_dir(args.output_dir)
    archive = output / ARCHIVE_NAME
    compose_before = _sha256_file(COMPOSE_PATH)
    baseline_container_before = _compose_postgres_container()
    run_id = f"bas176-{uuid.uuid4().hex[:12]}"
    network = f"kjds-bas176-{uuid.uuid4().hex[:12]}"
    password = secrets.token_hex(24)
    baseline = DisposablePostgres(
        image=policy.baseline_pilot_image,
        name=f"kjds-bas176-source-{uuid.uuid4().hex[:10]}",
        alias="source17",
        network=network,
        password=password,
        major=17,
        run_id=run_id,
    )
    candidate = DisposablePostgres(
        image=policy.candidate_image,
        name=f"kjds-bas176-candidate-{uuid.uuid4().hex[:10]}",
        alias="candidate18",
        network=network,
        password=password,
        major=18,
        run_id=run_id,
    )
    rollback = DisposablePostgres(
        image=policy.baseline_pilot_image,
        name=f"kjds-bas176-rollback-{uuid.uuid4().hex[:10]}",
        alias="rollback17",
        network=network,
        password=password,
        major=17,
        run_id=run_id,
    )
    instances = (baseline, candidate, rollback)
    network_created = False
    evidence: dict[str, Any] | None = None
    try:
        _stage("disposable_container_start")
        _docker("network", "create", "--label", f"io.kjds.bas176={run_id}", network)
        network_created = True
        for instance in instances:
            instance.start()
            instance.create_database()

        _stage("empty_migration_replay")
        baseline_version = baseline.server_version()
        candidate_version = candidate.server_version()
        _run_alembic(baseline, "upgrade", "head")
        source_head = _alembic_head(baseline)
        source_schema = _schema_inventory(baseline)
        source_extensions = _extensions(baseline)

        _run_alembic(candidate, "upgrade", "head")
        empty_head = _alembic_head(candidate)
        empty_schema = _schema_inventory(candidate)
        candidate_extensions = _extensions(candidate)
        _run_alembic(candidate, "downgrade", policy.downgrade_checkpoint)
        downgrade_head = _alembic_head(candidate)
        _run_alembic(candidate, "upgrade", "head")
        replay_head = _alembic_head(candidate)
        replay_schema = _schema_inventory(candidate)

        _stage("synthetic_dataset_seed")
        _seed_dataset(baseline, policy.synthetic_rows)
        _stage("synthetic_dataset_fingerprint")
        source_data = _dataset_fingerprint(baseline)
        _stage("pg17_custom_dump")
        _dump_source(baseline, archive)
        archive_sha = _sha256_file(archive)
        archive_bytes = archive.stat().st_size

        _stage("pg18_forward_restore")
        _restore_archive(candidate, archive)
        candidate_data = _dataset_fingerprint(candidate)
        candidate_schema = _schema_inventory(candidate)
        _stage("pg17_rollback_restore")
        _restore_archive(rollback, archive)
        rollback_data = _dataset_fingerprint(rollback)
        rollback_schema = _schema_inventory(rollback)

        _stage("query_benchmark")
        source_benchmark = _benchmark(
            baseline,
            policy_document["benchmark"]["warmup_runs"],
            policy_document["benchmark"]["measured_runs"],
        )
        candidate_benchmark = _benchmark(
            candidate,
            policy_document["benchmark"]["warmup_runs"],
            policy_document["benchmark"]["measured_runs"],
        )
        query_evidence = []
        for name in sorted(_BENCHMARK_QUERIES):
            source_item = source_benchmark[name]
            candidate_item = candidate_benchmark[name]
            query_evidence.append(
                {
                    "name": name,
                    "sourceResultSha256": source_item["resultSha256"],
                    "candidateResultSha256": candidate_item["resultSha256"],
                    "sourceMedianMs": source_item["medianMs"],
                    "candidateMedianMs": candidate_item["medianMs"],
                    "sourceMaximumMs": source_item["maximumMs"],
                    "candidateMaximumMs": candidate_item["maximumMs"],
                    "sourcePlanNodes": source_item["planNodes"],
                    "candidatePlanNodes": candidate_item["planNodes"],
                }
            )
        _stage("lock_observation")
        lock_baseline = _lock_observation(baseline, policy.lock_timeout_ms)
        lock_candidate = _lock_observation(candidate, policy.lock_timeout_ms)
        _stage("postgres18_feature_probe")
        features = _feature_probe(candidate)
        loopback_only, tmpfs_only = _container_isolation(instances)
        evidence = {
            "contractId": POSTGRES18_PILOT_REPORT_ID,
            "observedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "sourceCommit": source_commit,
            "migrationHead": migration_head,
            "policySha256": policy_sha,
            "baseline": {
                **_image_evidence(policy.baseline_pilot_image, healthy=True),
                "serverVersion": baseline_version,
            },
            "candidate": {
                **_image_evidence(policy.candidate_image, healthy=True),
                "serverVersion": candidate_version,
            },
            "isolation": {
                "composeImage": policy.baseline_compose_image,
                "composeFileUnchanged": False,
                "baselineContainerUnchanged": False,
                "disposableContainersOnly": True,
                "loopbackPortsOnly": loopback_only,
                "tmpfsDataOnly": tmpfs_only,
                "namedVolumesCreated": not tmpfs_only,
                "productionDatabaseTouched": False,
            },
            "migration": {
                "sourceHead": source_head,
                "emptyUpgradeHead": empty_head,
                "downgradeCheckpoint": downgrade_head,
                "replayHead": replay_head,
                "sourceSchemaSha256": source_schema["sha256"],
                "emptyUpgradeSchemaSha256": empty_schema["sha256"],
                "replaySchemaSha256": replay_schema["sha256"],
                "sourceSchemaComponents": source_schema["componentSha256"],
                "emptyUpgradeSchemaComponents": empty_schema["componentSha256"],
                "replaySchemaComponents": replay_schema["componentSha256"],
                "tableCount": replay_schema["tableCount"],
                "columnCount": replay_schema["columnCount"],
                "constraintCount": replay_schema["constraintCount"],
                "indexCount": replay_schema["indexCount"],
            },
            "compatibility": {
                "driverCompatible": True,
                "psycopgVersion": importlib.metadata.version("psycopg"),
                "sqlalchemyVersion": importlib.metadata.version("sqlalchemy"),
                "sourceExtensions": source_extensions,
                "candidateExtensions": candidate_extensions,
            },
            "transfer": {
                "method": "restore_frozen_pre_cutover_pg17_custom_dump",
                "archiveSha256": archive_sha,
                "archiveBytes": archive_bytes,
                "forwardRestorePassed": True,
                "rollbackRestorePassed": True,
                "candidateWritesAccepted": False,
                "inPlaceMajorDowngradeClaimed": False,
                "sourceDataSha256": source_data["sha256"],
                "candidateDataSha256": candidate_data["sha256"],
                "rollbackDataSha256": rollback_data["sha256"],
                "candidateSchemaSha256": candidate_schema["sha256"],
                "rollbackSchemaSha256": rollback_schema["sha256"],
                "rowCount": source_data["rowCount"],
            },
            "benchmarks": {
                "rowCount": source_data["rowCount"],
                "queries": query_evidence,
            },
            "locks": {
                "baseline": lock_baseline,
                "candidate": lock_candidate,
            },
            "features": features,
            "cleanup": {
                "containersRemoved": False,
                "networkRemoved": False,
                "temporaryArchivesRemoved": False,
            },
            "controls": {
                "engineeringRehearsalPassed": True,
                "exitGateState": "not_passed",
                "baselinePromotionAllowed": False,
                "productionDependencyAllowed": False,
                "externalWriteAllowed": False,
                "formalFactPromotionAllowed": False,
                "productionMigrationRunbookState": "UNKNOWN",
                "independentRecoveryApprovalState": "UNKNOWN",
            },
        }
    finally:
        stage_before_cleanup = CURRENT_STAGE
        _stage("disposable_cleanup")
        try:
            for instance in reversed(instances):
                instance.remove()
            if network_created:
                _docker("network", "rm", network, check=False)
            if archive.exists():
                archive.unlink()
        except Exception:
            raise
        else:
            _stage(stage_before_cleanup)

    if evidence is None:
        raise Postgres18PilotError("PostgreSQL pilot evidence was not produced")
    compose_after = _sha256_file(COMPOSE_PATH)
    baseline_container_after = _compose_postgres_container()
    evidence["isolation"]["composeFileUnchanged"] = compose_before == compose_after
    evidence["isolation"]["baselineContainerUnchanged"] = (
        baseline_container_before == baseline_container_after
    )
    evidence["cleanup"] = {
        "containersRemoved": all(
            not _docker_object_exists("inspect", instance.name)
            for instance in instances
        ),
        "networkRemoved": not _docker_object_exists("network", "inspect", network),
        "temporaryArchivesRemoved": not any(output.glob("*.dump")),
    }
    _stage("evidence_verification")
    authority = Postgres18PilotAuthority(policy, policy_sha256=policy_sha)
    receipt = authority.verify(
        evidence,
        source_commit=source_commit,
        migration_head=migration_head,
    )
    _stage("evidence_write")
    _write_json(output / "postgres18-pilot-report.json", evidence)
    _write_json(output / "verification.json", receipt)
    return {
        "status": receipt["status"],
        "contract_id": receipt["contractId"],
        "source_commit": receipt["sourceCommit"],
        "migration_head": receipt["migrationHead"],
        "baseline_version": receipt["baselineVersion"],
        "candidate_version": receipt["candidateVersion"],
        "baseline_image_sha256": receipt["baselineImageSha256"],
        "candidate_image_sha256": receipt["candidateImageSha256"],
        "migration_replay": receipt["migrationReplay"],
        "extension_compatibility": receipt["extensionCompatibility"],
        "forward_restore": receipt["forwardRestore"],
        "rollback_restore": receipt["rollbackRestore"],
        "benchmark_gate": receipt["benchmarkGate"],
        "lock_gate": receipt["lockGate"],
        "feature_probe": receipt["featureProbe"],
        "cleanup": receipt["cleanup"],
        "exit_gate_state": receipt["exitGateState"],
        "baseline_promotion_allowed": receipt["baselinePromotionAllowed"],
        "production_dependency_allowed": receipt["productionDependencyAllowed"],
        "external_write_allowed": receipt["externalWriteAllowed"],
        "formal_fact_promotion_allowed": receipt["formalFactPromotionAllowed"],
        "report_sha256": receipt["reportSha256"],
        "output_dir": str(output),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Run the isolated PostgreSQL 18 rehearsal")
    root.add_argument("--output-dir", type=Path, required=True)
    root.add_argument("--policy", type=Path, default=POLICY_PATH)
    root.add_argument("--pull", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = _run_pilot(args)
    except Exception as exc:
        database_sqlstate = exc.sqlstate if isinstance(exc, psycopg.Error) else None
        contract_error = str(exc) if isinstance(exc, Postgres18PilotError) else None
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_code": "postgres18_pilot_failed",
                    "error_type": type(exc).__name__,
                    "failed_stage": CURRENT_STAGE,
                    "database_sqlstate": database_sqlstate or "not_applicable",
                    "contract_error": contract_error or "not_applicable",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
