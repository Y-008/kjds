from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apps.control_plane.postgres18_pilot import (
    Postgres18PilotAuthority,
    Postgres18PilotError,
    Postgres18PilotPolicy,
)

ROOT = Path(__file__).parents[1]
POLICY_PATH = ROOT / "docs/project/contracts/postgres18-pilot-policy-v1.json"
COMPOSE_PATH = ROOT / "compose.yaml"
RUNNER_PATH = ROOT / "scripts/verify_postgres18_pilot.py"
EVIDENCE_REPORT_PATH = (
    ROOT / "docs/project/evidence/20260803_BAS_176_POSTGRES18_PILOT_REPORT.json"
)
EVIDENCE_RECEIPT_PATH = (
    ROOT / "docs/project/evidence/20260803_BAS_176_POSTGRES18_PILOT_VERIFICATION.json"
)
SOURCE_COMMIT = "1" * 40
MIGRATION_HEAD = "20260803_0090"
SCHEMA_SHA = "c" * 64
DATA_SHA = "d" * 64


def policy_document() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def authority() -> Postgres18PilotAuthority:
    return Postgres18PilotAuthority(
        Postgres18PilotPolicy.from_document(policy_document()),
        policy_sha256=hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
    )


def benchmark(name: str, source_ms: float, candidate_ms: float) -> dict:
    return {
        "name": name,
        "sourceResultSha256": "e" * 64,
        "candidateResultSha256": "e" * 64,
        "sourceMedianMs": source_ms,
        "candidateMedianMs": candidate_ms,
        "sourceMaximumMs": source_ms * 1.2,
        "candidateMaximumMs": candidate_ms * 1.2,
        "sourcePlanNodes": ["Index Scan"],
        "candidatePlanNodes": ["Index Scan"],
    }


def lock_observation() -> dict:
    return {
        "conflictObserved": True,
        "ungrantedLockObserved": True,
        "timeoutSqlstate": "55P03",
        "waitMs": 1201.0,
        "blockerRolledBack": True,
        "rowUnchanged": True,
    }


def report() -> dict:
    policy_sha = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    extensions = [{"name": "plpgsql", "version": "1.0"}]
    return {
        "contractId": "kjds-postgres18-pilot-report-v1",
        "observedAt": "2026-08-03T08:00:00Z",
        "sourceCommit": SOURCE_COMMIT,
        "migrationHead": MIGRATION_HEAD,
        "policySha256": policy_sha,
        "baseline": {
            "image": "postgres:17.10-alpine",
            "imageIdSha256": "a" * 64,
            "repoDigest": f"postgres@sha256:{'1' * 64}",
            "serverVersion": "PostgreSQL 17.10",
            "healthy": True,
        },
        "candidate": {
            "image": "postgres:18.4-alpine",
            "imageIdSha256": "b" * 64,
            "repoDigest": f"postgres@sha256:{'2' * 64}",
            "serverVersion": "PostgreSQL 18.4",
            "healthy": True,
        },
        "isolation": {
            "composeImage": "postgres:17-alpine",
            "composeFileUnchanged": True,
            "baselineContainerUnchanged": True,
            "disposableContainersOnly": True,
            "loopbackPortsOnly": True,
            "tmpfsDataOnly": True,
            "namedVolumesCreated": False,
            "productionDatabaseTouched": False,
        },
        "migration": {
            "sourceHead": MIGRATION_HEAD,
            "emptyUpgradeHead": MIGRATION_HEAD,
            "downgradeCheckpoint": "20260717_0024",
            "replayHead": MIGRATION_HEAD,
            "sourceSchemaSha256": SCHEMA_SHA,
            "emptyUpgradeSchemaSha256": SCHEMA_SHA,
            "replaySchemaSha256": SCHEMA_SHA,
            "sourceSchemaComponents": {
                "tables": SCHEMA_SHA,
                "columns": SCHEMA_SHA,
                "constraints": SCHEMA_SHA,
                "indexes": SCHEMA_SHA,
            },
            "emptyUpgradeSchemaComponents": {
                "tables": SCHEMA_SHA,
                "columns": SCHEMA_SHA,
                "constraints": SCHEMA_SHA,
                "indexes": SCHEMA_SHA,
            },
            "replaySchemaComponents": {
                "tables": SCHEMA_SHA,
                "columns": SCHEMA_SHA,
                "constraints": SCHEMA_SHA,
                "indexes": SCHEMA_SHA,
            },
            "tableCount": 150,
            "columnCount": 1400,
            "constraintCount": 500,
            "indexCount": 400,
        },
        "compatibility": {
            "driverCompatible": True,
            "psycopgVersion": "3.3.4",
            "sqlalchemyVersion": "2.0.51",
            "sourceExtensions": extensions,
            "candidateExtensions": extensions,
        },
        "transfer": {
            "method": "restore_frozen_pre_cutover_pg17_custom_dump",
            "archiveSha256": "f" * 64,
            "archiveBytes": 4096,
            "forwardRestorePassed": True,
            "rollbackRestorePassed": True,
            "candidateWritesAccepted": False,
            "inPlaceMajorDowngradeClaimed": False,
            "sourceDataSha256": DATA_SHA,
            "candidateDataSha256": DATA_SHA,
            "rollbackDataSha256": DATA_SHA,
            "candidateSchemaSha256": SCHEMA_SHA,
            "rollbackSchemaSha256": SCHEMA_SHA,
            "rowCount": 20000,
        },
        "benchmarks": {
            "rowCount": 20000,
            "queries": [
                benchmark("exact_scope_latest", 2.0, 2.2),
                benchmark("status_scope_aggregate", 4.0, 3.8),
                benchmark("tenant_time_aggregate", 7.0, 7.5),
            ],
        },
        "locks": {
            "baseline": lock_observation(),
            "candidate": lock_observation(),
        },
        "features": {
            "uuidv7Supported": True,
            "temporalWithoutOverlapsSupported": True,
            "temporalOverlapRejected": True,
            "aioViewAvailable": True,
            "ioMethod": "worker",
            "oauthServerCapabilityVisible": True,
            "oauthRuntimeConfigured": False,
        },
        "cleanup": {
            "containersRemoved": True,
            "networkRemoved": True,
            "temporaryArchivesRemoved": True,
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


def verify(document: dict) -> dict:
    return authority().verify(
        document,
        source_commit=SOURCE_COMMIT,
        migration_head=MIGRATION_HEAD,
    )


def test_rehearsal_passes_without_promoting_postgres18_or_the_exit_gate():
    receipt = verify(report())

    assert receipt["status"] == "PASS"
    assert receipt["migrationReplay"] is True
    assert receipt["forwardRestore"] is True
    assert receipt["rollbackRestore"] is True
    assert receipt["benchmarkGate"] is True
    assert receipt["lockGate"] is True
    assert receipt["exitGateState"] == "not_passed"
    assert receipt["baselinePromotionAllowed"] is False
    assert receipt["productionDependencyAllowed"] is False
    assert receipt["externalWriteAllowed"] is False
    assert receipt["formalFactPromotionAllowed"] is False


def test_committed_rehearsal_evidence_reopens_and_reverifies():
    document = json.loads(EVIDENCE_REPORT_PATH.read_text(encoding="utf-8"))
    recorded_receipt = json.loads(EVIDENCE_RECEIPT_PATH.read_text(encoding="utf-8"))

    verified = authority().verify(
        document,
        source_commit=document["sourceCommit"],
        migration_head=document["migrationHead"],
    )

    assert verified == recorded_receipt
    assert document["sourceCommit"] == "c6220c2b359387cc18ce7d9ae16f34bc45df28c2"
    assert hashlib.sha256(EVIDENCE_REPORT_PATH.read_bytes()).hexdigest() == (
        "d34725cbb5a7b3b997d13f9b5ccb00766b3cd281d312785eb18b7b28b894b040"
    )
    assert hashlib.sha256(EVIDENCE_RECEIPT_PATH.read_bytes()).hexdigest() == (
        "8cba72155bcdaa0a01e6901a84d3b9896e68e3ccc66dae70f0dc9b2a95825641"
    )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("baseline", "serverVersion"), "PostgreSQL 17.9", "patch level"),
        (("candidate", "serverVersion"), "PostgreSQL 19.0", "patch level"),
        (("candidate", "image"), "postgres:18-alpine", "image drift"),
        (("isolation", "composeImage"), "postgres:18.4-alpine", "isolation"),
        (("isolation", "tmpfsDataOnly"), False, "isolation"),
    ],
)
def test_version_image_and_isolation_drift_fail_closed(path, value, message):
    document = report()
    document[path[0]][path[1]] = value

    with pytest.raises(Postgres18PilotError, match=message):
        verify(document)


def test_migration_transfer_and_rollback_fingerprints_must_be_exact():
    document = report()
    document["migration"]["replaySchemaSha256"] = "9" * 64
    with pytest.raises(Postgres18PilotError, match="migration schema drift"):
        verify(document)

    document = report()
    document["transfer"]["candidateDataSha256"] = "8" * 64
    with pytest.raises(Postgres18PilotError, match="transfer data drift"):
        verify(document)

    document = report()
    document["transfer"]["candidateWritesAccepted"] = True
    with pytest.raises(Postgres18PilotError, match="rollback contract drift"):
        verify(document)


def test_query_result_and_latency_regressions_fail_closed():
    document = report()
    document["benchmarks"]["queries"][0]["candidateResultSha256"] = "7" * 64
    with pytest.raises(Postgres18PilotError, match="benchmark result drift"):
        verify(document)

    document = report()
    document["benchmarks"]["queries"][0]["candidateMedianMs"] = 76.0
    with pytest.raises(Postgres18PilotError, match="latency regression"):
        verify(document)


def test_lock_timeout_cleanup_and_feature_controls_fail_closed():
    document = report()
    document["locks"]["candidate"]["timeoutSqlstate"] = "57014"
    with pytest.raises(Postgres18PilotError, match="candidate lock behavior"):
        verify(document)

    document = report()
    document["cleanup"]["networkRemoved"] = False
    with pytest.raises(Postgres18PilotError, match="cleanup failed"):
        verify(document)

    document = report()
    document["features"]["oauthRuntimeConfigured"] = True
    with pytest.raises(Postgres18PilotError, match="feature probe"):
        verify(document)


def test_secret_like_report_content_and_promotion_claims_are_rejected():
    document = report()
    document["diagnostic"] = {"password": "super-secret-value"}
    with pytest.raises(Postgres18PilotError, match="Secret-like"):
        verify(document)

    document = report()
    document["controls"]["baselinePromotionAllowed"] = True
    with pytest.raises(Postgres18PilotError, match="promotion controls drift"):
        verify(document)


def test_policy_pins_patch_lines_disposable_data_and_pre_cutover_rollback():
    policy = policy_document()

    assert policy["baseline"]["compose_image"] == "postgres:17-alpine"
    assert policy["baseline"]["pilot_image"] == "postgres:17.10-alpine"
    assert policy["candidate"]["pilot_image"] == "postgres:18.4-alpine"
    assert policy["migration"]["required_head"] == MIGRATION_HEAD
    assert policy["dataset"]["synthetic_rows"] == 20000
    assert policy["dataset"]["production_data_allowed"] is False
    assert policy["isolation"]["tmpfs_data_only"] is True
    assert policy["isolation"]["compose_mutation_allowed"] is False
    assert policy["rollback"]["method"] == (
        "restore_frozen_pre_cutover_pg17_custom_dump"
    )
    assert policy["rollback"]["candidate_writes_during_cutover_allowed"] is False
    assert policy["promotion"]["exit_gate_state"] == "not_passed"


def test_runner_never_upgrades_compose_or_claims_an_in_place_downgrade():
    runner = RUNNER_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "postgres:17-alpine" in compose
    assert "postgres:18" not in compose
    assert '"compose", "up"' not in runner
    assert '"compose", "down"' not in runner
    assert "restore_frozen_pre_cutover_pg17_custom_dump" in runner
    assert '"inPlaceMajorDowngradeClaimed": False' in runner
    assert '"candidateWritesAccepted": False' in runner
    assert '"productionDatabaseTouched": False' in runner
    assert "constraint_row.contype <> 'n'" in runner
    assert "attribute.attnotnull" in runner
    assert "pg_catalog.format_type" in runner
    assert "mod(i, 8)" in runner
    assert "i % 8" not in runner
    assert "completed.returncode == 0" in runner
