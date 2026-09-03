import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_team_agent_postgres_gate as gate


def _fake_pytest_run(monkeypatch, testcase_names: list[str]) -> None:
    def run(arguments, **_kwargs):
        junit_path = Path(arguments[arguments.index("--junitxml") + 1])
        junit_path.write_text(
            "<testsuite tests=\"{}\">{}</testsuite>".format(
                len(testcase_names),
                "".join(
                    f'<testcase classname="tests.test_team_agent_persistence_postgres" '
                    f'name="{name}"/>'
                    for name in testcase_names
                ),
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", run)


def test_gate_requires_an_environment_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(gate.DATABASE_ENV, raising=False)

    with pytest.raises(gate.GatePreflightError, match="is required"):
        gate._database_url()


def test_gate_rejects_a_non_postgres_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(gate.DATABASE_ENV, "sqlite+pysqlite:///:memory:")

    with pytest.raises(gate.GatePreflightError, match="must use PostgreSQL"):
        gate._database_url()


def test_junit_counts_conserve_all_suite_outcomes(tmp_path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite tests="20" failures="1" errors="2" skipped="3"/>'
        '<testsuite tests="13" failures="0" errors="0" skipped="4"/></testsuites>',
        encoding="utf-8",
    )

    assert gate._junit_counts(report) == {
        "tests": 33,
        "failures": 1,
        "errors": 2,
        "skipped": 7,
    }


def test_required_recovery_contracts_fail_closed_when_junit_omits_one(
    tmp_path,
) -> None:
    report = tmp_path / "junit.xml"
    present = sorted(gate.REQUIRED_RECOVERY_CONTRACTS)[:-1]
    report.write_text(
        "<testsuite tests=\"{}\">{}</testsuite>".format(
            len(present),
            "".join(
                f'<testcase classname="tests.test_team_agent_persistence_postgres" '
                f'name="{name}"/>'
                for name in present
            ),
        ),
        encoding="utf-8",
    )

    executed = gate._junit_testcase_names(report)
    missing = gate._missing_required_contracts(executed)

    assert missing == (sorted(gate.REQUIRED_RECOVERY_CONTRACTS)[-1],)
    assert gate.SPAWNED_PROCESS_RECOVERY_CONTRACT in executed or missing


def test_required_recovery_contract_manifest_is_complete_and_stably_hashed(
    tmp_path,
) -> None:
    report = tmp_path / "junit.xml"
    required = sorted(gate.REQUIRED_RECOVERY_CONTRACTS)
    report.write_text(
        "<testsuites><testsuite tests=\"{}\">{}</testsuite></testsuites>".format(
            len(required),
            "".join(
                f'<testcase classname="tests.test_team_agent_persistence_postgres" '
                f'name="{name}"/>'
                for name in reversed(required)
            ),
        ),
        encoding="utf-8",
    )

    executed = gate._junit_testcase_names(report)

    assert gate._missing_required_contracts(executed) == ()
    assert gate.SPAWNED_PROCESS_RECOVERY_CONTRACT == (
        "test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent"
    )
    assert gate.SPAWNED_PROCESS_RECOVERY_CONTRACT in executed
    assert gate._required_contracts_sha256() == gate._required_contracts_sha256()
    assert len(gate._required_contracts_sha256()) == 64


def test_gate_main_rejects_zero_failure_junit_missing_spawned_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setenv(
        gate.DATABASE_ENV,
        "postgresql+psycopg://operator:secret@db.test/kjds",
    )
    monkeypatch.setattr(
        gate,
        "_preflight",
        lambda _url: {
            "postgres_major": 17,
            "can_create_schema": True,
            "required_roles_missing_before_run": [],
        },
    )
    _fake_pytest_run(
        monkeypatch,
        sorted(
            gate.REQUIRED_RECOVERY_CONTRACTS
            - {gate.SPAWNED_PROCESS_RECOVERY_CONTRACT}
        ),
    )
    receipt_path = tmp_path / "receipt.json"

    assert gate.main(receipt_output=receipt_path) == 4

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED"
    assert receipt["reason"] == "required recovery contracts missing from JUnit"
    assert receipt["missing_required_contracts"] == [
        gate.SPAWNED_PROCESS_RECOVERY_CONTRACT
    ]
    assert json.loads(capsys.readouterr().err) == receipt


def test_gate_main_derives_spawned_recovery_receipt_from_junit_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.setenv(
        gate.DATABASE_ENV,
        "postgresql+psycopg://operator:secret@db.test/kjds",
    )
    monkeypatch.setattr(
        gate,
        "_preflight",
        lambda _url: {
            "postgres_major": 17,
            "can_create_schema": True,
            "required_roles_missing_before_run": [],
        },
    )
    _fake_pytest_run(monkeypatch, sorted(gate.REQUIRED_RECOVERY_CONTRACTS))
    receipt_path = tmp_path / "receipt.json"

    assert gate.main(receipt_output=receipt_path) == 0

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "PASSED"
    assert receipt["spawned_process_recovery_executed"] is True
    assert receipt["required_recovery_contract_count"] == len(
        gate.REQUIRED_RECOVERY_CONTRACTS
    )
    assert receipt["required_recovery_contracts_sha256"] == (
        gate._required_contracts_sha256()
    )
    assert json.loads(capsys.readouterr().out) == receipt


def test_blocked_gate_receipt_does_not_leak_a_database_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(gate.DATABASE_ENV, raising=False)

    assert gate.main() == 2

    receipt = json.loads(capsys.readouterr().err)
    assert receipt == {
        "gate": "BR-150-postgresql-17-multiprocess",
        "reason": "KJDS_TEAM_AGENT_DATABASE_URL is required",
        "status": "BLOCKED",
    }


def test_driver_exception_cannot_leak_credentials_into_blocked_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = "postgresql+psycopg://operator:top-secret@db.test/kjds"
    monkeypatch.setenv(gate.DATABASE_ENV, database_url)
    monkeypatch.setattr(
        gate,
        "_preflight",
        lambda _url: (_ for _ in ()).throw(RuntimeError(database_url)),
    )

    assert gate.main() == 2

    output = capsys.readouterr().err
    assert database_url not in output
    assert "top-secret" not in output
    assert json.loads(output)["reason"] == "PostgreSQL preflight connection failed"


def test_retained_junit_is_hashed_and_rejects_database_credentials(tmp_path) -> None:
    source = tmp_path / "source.xml"
    destination = tmp_path / "evidence" / "junit.xml"
    database_url = "postgresql+psycopg://operator:top-secret@db.test/kjds"
    source.write_text('<testsuite tests="33" failures="0"/>', encoding="utf-8")

    digest = gate._retain_junit(
        source=source,
        destination=destination,
        database_url=database_url,
    )

    assert len(digest) == 64
    assert destination.read_bytes() == source.read_bytes()

    source.write_text(
        '<testsuite><system-err>top-secret</system-err></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(gate.GatePreflightError, match="contains database"):
        gate._retain_junit(
            source=source,
            destination=destination,
            database_url=database_url,
        )


def test_blocked_gate_can_write_a_machine_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    monkeypatch.delenv(gate.DATABASE_ENV, raising=False)
    receipt_path = tmp_path / "receipt.json"

    assert gate.main(receipt_output=receipt_path) == 2

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "BLOCKED"
    assert receipt["reason"] == "KJDS_TEAM_AGENT_DATABASE_URL is required"
    assert json.loads(capsys.readouterr().err) == receipt
