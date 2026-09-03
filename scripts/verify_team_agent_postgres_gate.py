"""Execute the BR-150 PostgreSQL 17 contract and process-recovery gate.

The database URL is accepted only from ``KJDS_TEAM_AGENT_DATABASE_URL`` so it
does not appear in process arguments or the receipt.  The pytest fixture owns a
random schema and removes it after the run; cluster roles may be created when
the supplied PostgreSQL authority permits it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DATABASE_ENV = "KJDS_TEAM_AGENT_DATABASE_URL"
REQUIRED_POSTGRES_MAJOR = 17
REQUIRED_ROLES = frozenset(
    {
        "kjds_gdc_issuance_owner",
        "kjds_gdc_issuance_runtime",
        "kjds_cloe_issuance_owner",
        "kjds_cloe_event_issuance_owner",
        "kjds_cloe_issuance_runtime",
        "kjds_cloe_experiment_authority",
        "kjds_cloe_cost_authority",
        "kjds_cloe_outcome_authority",
        "kjds_cloe_review_authority",
    }
)
SPAWNED_PROCESS_RECOVERY_CONTRACT = (
    "test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent"
)
REQUIRED_RECOVERY_CONTRACTS = frozenset(
    {
        SPAWNED_PROCESS_RECOVERY_CONTRACT,
        "test_postgres_spawned_workers_and_restart_recover_after_process_loss",
        "test_durable_kill_switch_fences_stale_replica_claim_and_complete",
        "test_postgres_two_runtime_instances_emit_one_terminal_transition",
        "test_task_mutation_and_checkpoint_share_one_commit_boundary",
        "test_checkpoint_restore_keeps_stronger_serializable_caller_transaction",
        "test_postgres_checkpoint_empty_history_fails_restore",
        "test_postgres_runtime_atomically_recovers_expired_lease_before_stale_heartbeat",
        "test_postgres_runtime_claim_commits_queued_time_budget_terminal",
        "test_postgres_runtime_handoff_lineage_reconciles_after_restart",
        "test_postgres_runtime_pause_preserves_retry_schedule_across_restart",
        "test_postgres_completed_response_loss_replay_converges_without_new_event",
        "test_postgres_failed_response_loss_replay_converges_without_new_event",
    }
)


class GatePreflightError(RuntimeError):
    pass


def _contract_provenance(repository: Path) -> dict[str, object]:
    config = Config(str(repository / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise GatePreflightError(f"exactly one Alembic head is required; found {heads}")
    contract_source = repository / "tests" / "test_team_agent_persistence_postgres.py"
    return {
        "alembic_head": heads[0],
        "contract_source_sha256": hashlib.sha256(contract_source.read_bytes()).hexdigest(),
    }


def _database_url() -> str:
    value = os.getenv(DATABASE_ENV, "").strip()
    if not value:
        raise GatePreflightError(f"{DATABASE_ENV} is required")
    try:
        parsed = make_url(value)
    except Exception as exc:
        raise GatePreflightError(
            f"{DATABASE_ENV} must be a valid SQLAlchemy URL"
        ) from exc
    if not parsed.drivername.startswith("postgresql"):
        raise GatePreflightError(f"{DATABASE_ENV} must use PostgreSQL")
    if not parsed.database:
        raise GatePreflightError(f"{DATABASE_ENV} must name a database")
    return value


def _preflight(database_url: str) -> dict[str, object]:
    parsed = make_url(database_url)
    query = dict(parsed.query)
    query.setdefault("connect_timeout", "5")
    engine = create_engine(parsed.set(query=query), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT current_setting('server_version_num')::integer "
                    "AS version_num, current_user AS role_name, "
                    "r.rolsuper, r.rolcreaterole, "
                    "has_database_privilege(current_user, current_database(), "
                    "'CREATE') AS can_create_schema "
                    "FROM pg_roles AS r WHERE r.rolname = current_user"
                )
            ).mappings().one()
            existing_roles = frozenset(
                connection.scalars(text("SELECT rolname FROM pg_roles")).all()
            )
    finally:
        engine.dispose()

    major = int(row["version_num"]) // 10_000
    if major != REQUIRED_POSTGRES_MAJOR:
        raise GatePreflightError(
            f"PostgreSQL {REQUIRED_POSTGRES_MAJOR} is required; found {major}"
        )
    if not row["can_create_schema"]:
        raise GatePreflightError("database role cannot create an isolated schema")
    missing_roles = sorted(REQUIRED_ROLES - existing_roles)
    if missing_roles and not (row["rolsuper"] or row["rolcreaterole"]):
        raise GatePreflightError(
            "database role cannot provision required migration roles: "
            + ", ".join(missing_roles)
        )
    return {
        "postgres_major": major,
        "can_create_schema": True,
        "required_roles_missing_before_run": missing_roles,
    }


def _junit_counts(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = (root,) if root.tag == "testsuite" else tuple(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def _junit_testcase_names(path: Path) -> frozenset[str]:
    root = ElementTree.parse(path).getroot()
    return frozenset(
        name
        for item in root.iter("testcase")
        if (name := str(item.attrib.get("name") or "").strip())
    )


def _missing_required_contracts(
    executed: frozenset[str],
) -> tuple[str, ...]:
    return tuple(sorted(REQUIRED_RECOVERY_CONTRACTS - executed))


def _required_contracts_sha256() -> str:
    payload = json.dumps(
        sorted(REQUIRED_RECOVERY_CONTRACTS),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json_receipt(path: Path | None, receipt: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _retain_junit(
    *,
    source: Path,
    destination: Path,
    database_url: str,
) -> str:
    """Retain successful JUnit evidence only when it contains no DSN secret."""

    data = source.read_bytes()
    parsed = make_url(database_url)
    forbidden = tuple(
        value.encode("utf-8")
        for value in (database_url, parsed.password)
        if value
    )
    if any(value in data for value in forbidden):
        raise GatePreflightError(
            "JUnit evidence contains database connection credentials"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def main(
    *,
    junit_output: Path | None = None,
    receipt_output: Path | None = None,
) -> int:
    repository = Path(__file__).resolve().parents[1]
    try:
        database_url = _database_url()
    except GatePreflightError as exc:
        reason = str(exc)
    else:
        try:
            preflight = {
                **_preflight(database_url),
                **_contract_provenance(repository),
            }
        except GatePreflightError as exc:
            reason = str(exc)
        except Exception:
            # Driver exceptions can embed DSN fragments.  Never serialize the
            # original exception into a user-facing or persisted receipt.
            reason = "PostgreSQL preflight connection failed"
        else:
            reason = None
    if reason is not None:
        receipt = {
            "status": "BLOCKED",
            "gate": "BR-150-postgresql-17-multiprocess",
            "reason": reason,
        }
        _write_json_receipt(receipt_output, receipt)
        print(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="team-agent-pg17-gate-") as temp_dir:
        junit_path = Path(temp_dir) / "junit.xml"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--junitxml",
                str(junit_path),
                "tests/test_team_agent_persistence_postgres.py",
            ],
            cwd=repository,
            env={**os.environ, DATABASE_ENV: database_url},
            check=False,
        )
        if not junit_path.exists():
            print("PostgreSQL gate did not produce JUnit evidence", file=sys.stderr)
            return result.returncode or 3
        counts = _junit_counts(junit_path)
        executed_contracts = _junit_testcase_names(junit_path)
        missing_required_contracts = _missing_required_contracts(executed_contracts)

        junit_sha256 = None
        if (
            not result.returncode
            and not counts["failures"]
            and not counts["errors"]
            and not counts["skipped"]
            and not missing_required_contracts
            and junit_output is not None
        ):
            try:
                junit_sha256 = _retain_junit(
                    source=junit_path,
                    destination=junit_output,
                    database_url=database_url,
                )
            except GatePreflightError as exc:
                receipt = {
                    "status": "FAILED",
                    "gate": "BR-150-postgresql-17-multiprocess",
                    **preflight,
                    **counts,
                    "pytest_exit_code": result.returncode,
                    "reason": str(exc),
                }
                _write_json_receipt(receipt_output, receipt)
                print(
                    json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                    file=sys.stderr,
                )
                return 5

    if (
        result.returncode
        or counts["failures"]
        or counts["errors"]
        or counts["skipped"]
        or missing_required_contracts
    ):
        receipt = {
            "status": "FAILED",
            "gate": "BR-150-postgresql-17-multiprocess",
            **preflight,
            **counts,
            "pytest_exit_code": result.returncode,
        }
        if missing_required_contracts:
            receipt.update(
                {
                    "reason": "required recovery contracts missing from JUnit",
                    "missing_required_contracts": list(missing_required_contracts),
                }
            )
        _write_json_receipt(receipt_output, receipt)
        print(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return result.returncode or 4

    receipt = {
        "status": "PASSED",
        "gate": "BR-150-postgresql-17-multiprocess",
        "verified_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        **preflight,
        **counts,
        "required_recovery_contract_count": len(REQUIRED_RECOVERY_CONTRACTS),
        "required_recovery_contracts_sha256": _required_contracts_sha256(),
        "spawned_process_recovery_executed": (
            SPAWNED_PROCESS_RECOVERY_CONTRACT in executed_contracts
        ),
        "business_truth_proven": False,
        "external_write_allowed": False,
    }
    if junit_sha256 is not None:
        receipt["junit_sha256"] = junit_sha256
    _write_json_receipt(receipt_output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Execute the BR-150 PostgreSQL 17 acceptance Gate."
    )
    parser.add_argument(
        "--junit-output",
        type=Path,
        help="Retain credential-checked JUnit XML after a zero-skip pass.",
    )
    parser.add_argument(
        "--receipt-output",
        type=Path,
        help="Write the credential-free machine receipt as JSON.",
    )
    args = parser.parse_args()
    raise SystemExit(
        main(
            junit_output=args.junit_output,
            receipt_output=args.receipt_output,
        )
    )
