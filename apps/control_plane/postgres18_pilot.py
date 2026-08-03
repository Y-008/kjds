from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

POSTGRES18_PILOT_REPORT_ID = "kjds-postgres18-pilot-report-v1"
POSTGRES18_PILOT_RECEIPT_ID = "kjds-postgres18-pilot-verification-v1"

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_MIGRATION_HEAD = re.compile(r"^[0-9]{8}_[0-9]{4}$")
_VERSION = re.compile(r"(?:PostgreSQL\s+)?([0-9]+)\.([0-9]+)(?:\.([0-9]+))?")
_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "database_url",
        "password",
        "private_key",
        "secret",
    }
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|api[_-]?key|access[_-]?token)\s*[:=]\s*[^\s,;]{6,}"),
)


class Postgres18PilotError(ValueError):
    """Fail-closed PostgreSQL 18 rehearsal verification error."""


@dataclass(frozen=True)
class Postgres18PilotPolicy:
    contract_id: str
    baseline_compose_image: str
    baseline_pilot_image: str
    baseline_minimum: tuple[int, int]
    candidate_image: str
    candidate_minimum: tuple[int, int]
    migration_head: str
    downgrade_checkpoint: str
    synthetic_rows: int
    maximum_regression_ratio: float
    absolute_latency_budget_ms: float
    lock_timeout_ms: int
    lock_observation_minimum_ms: float
    lock_observation_maximum_ms: float
    container_prefix: str

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> Postgres18PilotPolicy:
        root = _mapping(document, "Pilot policy")
        baseline = _mapping(root.get("baseline"), "Baseline policy")
        candidate = _mapping(root.get("candidate"), "Candidate policy")
        migration = _mapping(root.get("migration"), "Migration policy")
        dataset = _mapping(root.get("dataset"), "Dataset policy")
        benchmark = _mapping(root.get("benchmark"), "Benchmark policy")
        isolation = _mapping(root.get("isolation"), "Isolation policy")
        rollback = _mapping(root.get("rollback"), "Rollback policy")
        promotion = _mapping(root.get("promotion"), "Promotion policy")
        if root.get("contract_id") != "kjds-postgres18-pilot-policy-v1":
            raise Postgres18PilotError("PostgreSQL 18 pilot policy contract drift")
        if baseline.get("required_major") != 17 or candidate.get("required_major") != 18:
            raise Postgres18PilotError("PostgreSQL pilot major-version policy drift")
        if dataset.get("classification") != "synthetic_non_business":
            raise Postgres18PilotError("PostgreSQL pilot dataset classification drift")
        if dataset.get("production_data_allowed") is not False:
            raise Postgres18PilotError("PostgreSQL pilot production data is not allowed")
        expected_isolation = {
            "loopback_ports_only": True,
            "tmpfs_data_only": True,
            "named_volumes_allowed": False,
            "compose_mutation_allowed": False,
            "production_database_allowed": False,
        }
        if any(isolation.get(key) is not value for key, value in expected_isolation.items()):
            raise Postgres18PilotError("PostgreSQL pilot isolation policy drift")
        if (
            rollback.get("method")
            != "restore_frozen_pre_cutover_pg17_custom_dump"
            or rollback.get("candidate_writes_during_cutover_allowed") is not False
            or rollback.get("in_place_major_downgrade_claimed") is not False
        ):
            raise Postgres18PilotError("PostgreSQL pilot rollback policy drift")
        if (
            promotion.get("engineering_rehearsal_can_promote_baseline") is not False
            or promotion.get("production_migration_runbook_state") != "UNKNOWN"
            or promotion.get("independent_recovery_approval_state") != "UNKNOWN"
            or promotion.get("exit_gate_state") != "not_passed"
            or promotion.get("external_write_allowed") is not False
            or promotion.get("formal_fact_promotion_allowed") is not False
        ):
            raise Postgres18PilotError("PostgreSQL pilot promotion policy drift")
        head = str(migration.get("required_head") or "")
        checkpoint = str(migration.get("downgrade_checkpoint") or "")
        if not _MIGRATION_HEAD.fullmatch(head) or not _MIGRATION_HEAD.fullmatch(checkpoint):
            raise Postgres18PilotError("PostgreSQL pilot migration policy is invalid")
        policy = cls(
            contract_id=str(root["contract_id"]),
            baseline_compose_image=_safe_name(baseline.get("compose_image"), "Baseline compose image"),
            baseline_pilot_image=_safe_name(baseline.get("pilot_image"), "Baseline pilot image"),
            baseline_minimum=(17, _positive_int(baseline.get("minimum_minor"), "Baseline minor")),
            candidate_image=_safe_name(candidate.get("pilot_image"), "Candidate pilot image"),
            candidate_minimum=(18, _positive_int(candidate.get("minimum_minor"), "Candidate minor")),
            migration_head=head,
            downgrade_checkpoint=checkpoint,
            synthetic_rows=_positive_int(dataset.get("synthetic_rows"), "Synthetic rows"),
            maximum_regression_ratio=_positive_float(
                benchmark.get("maximum_regression_ratio"),
                "Maximum regression ratio",
            ),
            absolute_latency_budget_ms=_positive_float(
                benchmark.get("absolute_latency_budget_ms"),
                "Absolute latency budget",
            ),
            lock_timeout_ms=_positive_int(benchmark.get("lock_timeout_ms"), "Lock timeout"),
            lock_observation_minimum_ms=_positive_float(
                benchmark.get("lock_observation_minimum_ms"),
                "Minimum lock observation",
            ),
            lock_observation_maximum_ms=_positive_float(
                benchmark.get("lock_observation_maximum_ms"),
                "Maximum lock observation",
            ),
            container_prefix=_safe_name(isolation.get("container_prefix"), "Container prefix"),
        )
        if policy.lock_observation_minimum_ms >= policy.lock_observation_maximum_ms:
            raise Postgres18PilotError("PostgreSQL lock observation window is invalid")
        return policy


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Postgres18PilotError("Pilot evidence is not canonical JSON") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class Postgres18PilotAuthority:
    """Verify a disposable PostgreSQL 17-to-18 rehearsal without promoting it."""

    def __init__(self, policy: Postgres18PilotPolicy, *, policy_sha256: str) -> None:
        self.policy = policy
        self.policy_sha256 = _sha256(policy_sha256, "Pilot policy")

    def verify(
        self,
        report: Mapping[str, Any],
        *,
        source_commit: str,
        migration_head: str,
    ) -> dict[str, Any]:
        document = _mapping(report, "PostgreSQL 18 pilot report")
        _assert_secret_free(document)
        source_commit = str(source_commit).strip().lower()
        if not _HEX_40.fullmatch(source_commit):
            raise Postgres18PilotError("Expected Git commit is invalid")
        if migration_head != self.policy.migration_head:
            raise Postgres18PilotError("Expected migration head drift")
        if document.get("contractId") != POSTGRES18_PILOT_REPORT_ID:
            raise Postgres18PilotError("PostgreSQL 18 report contract drift")
        if document.get("sourceCommit") != source_commit:
            raise Postgres18PilotError("PostgreSQL 18 source commit drift")
        if document.get("migrationHead") != migration_head:
            raise Postgres18PilotError("PostgreSQL 18 migration head drift")
        if document.get("policySha256") != self.policy_sha256:
            raise Postgres18PilotError("PostgreSQL 18 policy digest drift")

        baseline = self._verify_engine(
            document.get("baseline"),
            label="PostgreSQL 17 baseline",
            expected_image=self.policy.baseline_pilot_image,
            minimum=self.policy.baseline_minimum,
        )
        candidate = self._verify_engine(
            document.get("candidate"),
            label="PostgreSQL 18 candidate",
            expected_image=self.policy.candidate_image,
            minimum=self.policy.candidate_minimum,
        )
        if baseline["imageIdSha256"] == candidate["imageIdSha256"]:
            raise Postgres18PilotError("PostgreSQL pilot images are not distinct")

        isolation = _mapping(document.get("isolation"), "Isolation evidence")
        expected_isolation = {
            "composeImage": self.policy.baseline_compose_image,
            "composeFileUnchanged": True,
            "baselineContainerUnchanged": True,
            "disposableContainersOnly": True,
            "loopbackPortsOnly": True,
            "tmpfsDataOnly": True,
            "namedVolumesCreated": False,
            "productionDatabaseTouched": False,
        }
        if any(isolation.get(key) != value for key, value in expected_isolation.items()):
            raise Postgres18PilotError("PostgreSQL pilot isolation evidence failed")

        migration = _mapping(document.get("migration"), "Migration evidence")
        if (
            migration.get("emptyUpgradeHead") != migration_head
            or migration.get("downgradeCheckpoint") != self.policy.downgrade_checkpoint
            or migration.get("replayHead") != migration_head
            or migration.get("sourceHead") != migration_head
        ):
            raise Postgres18PilotError("PostgreSQL 18 migration replay failed")
        schema_fingerprints = {
            str(migration.get(key) or "")
            for key in (
                "sourceSchemaSha256",
                "emptyUpgradeSchemaSha256",
                "replaySchemaSha256",
            )
        }
        if len(schema_fingerprints) != 1 or not all(
            _HEX_64.fullmatch(value) for value in schema_fingerprints
        ):
            component_names = ("tables", "columns", "constraints", "indexes")
            component_sets = {
                component: {
                    str(
                        _mapping(
                            migration.get(key),
                            key,
                        ).get(component)
                        or ""
                    )
                    for key in (
                        "sourceSchemaComponents",
                        "emptyUpgradeSchemaComponents",
                        "replaySchemaComponents",
                    )
                }
                for component in component_names
            }
            drift = [
                component
                for component, values in component_sets.items()
                if len(values) != 1
                or not all(_HEX_64.fullmatch(value) for value in values)
            ]
            suffix = ",".join(drift) if drift else "aggregate"
            raise Postgres18PilotError(
                f"PostgreSQL 18 migration schema drift: {suffix}"
            )
        if any(
            _positive_int(migration.get(key), key) < 1
            for key in ("tableCount", "columnCount", "constraintCount", "indexCount")
        ):
            raise Postgres18PilotError("PostgreSQL 18 migration inventory is empty")

        compatibility = _mapping(document.get("compatibility"), "Compatibility evidence")
        if compatibility.get("driverCompatible") is not True:
            raise Postgres18PilotError("PostgreSQL driver compatibility failed")
        if compatibility.get("sourceExtensions") != compatibility.get("candidateExtensions"):
            raise Postgres18PilotError("PostgreSQL extension compatibility drift")
        if not compatibility.get("sourceExtensions"):
            raise Postgres18PilotError("PostgreSQL extension inventory is empty")

        transfer = _mapping(document.get("transfer"), "Transfer evidence")
        if (
            transfer.get("method")
            != "restore_frozen_pre_cutover_pg17_custom_dump"
            or transfer.get("forwardRestorePassed") is not True
            or transfer.get("rollbackRestorePassed") is not True
            or transfer.get("candidateWritesAccepted") is not False
            or transfer.get("inPlaceMajorDowngradeClaimed") is not False
        ):
            raise Postgres18PilotError("PostgreSQL rollback contract drift")
        _sha256(transfer.get("archiveSha256"), "Frozen backup archive")
        if _positive_int(transfer.get("archiveBytes"), "Frozen backup bytes") < 1:
            raise Postgres18PilotError("Frozen backup archive is empty")
        transfer_fingerprints = {
            str(transfer.get(key) or "")
            for key in (
                "sourceDataSha256",
                "candidateDataSha256",
                "rollbackDataSha256",
            )
        }
        if len(transfer_fingerprints) != 1 or not all(
            _HEX_64.fullmatch(value) for value in transfer_fingerprints
        ):
            raise Postgres18PilotError("PostgreSQL transfer data drift")
        restored_schema = {
            str(transfer.get("candidateSchemaSha256") or ""),
            str(transfer.get("rollbackSchemaSha256") or ""),
            next(iter(schema_fingerprints)),
        }
        if len(restored_schema) != 1:
            raise Postgres18PilotError("PostgreSQL transfer schema drift")
        if transfer.get("rowCount") != self.policy.synthetic_rows:
            raise Postgres18PilotError("PostgreSQL synthetic dataset row count drift")

        self._verify_benchmarks(document.get("benchmarks"))
        self._verify_locks(document.get("locks"))
        self._verify_features(document.get("features"))

        cleanup = _mapping(document.get("cleanup"), "Cleanup evidence")
        if cleanup != {
            "containersRemoved": True,
            "networkRemoved": True,
            "temporaryArchivesRemoved": True,
        }:
            raise Postgres18PilotError("PostgreSQL pilot cleanup failed")
        controls = _mapping(document.get("controls"), "Pilot controls")
        if controls != {
            "engineeringRehearsalPassed": True,
            "exitGateState": "not_passed",
            "baselinePromotionAllowed": False,
            "productionDependencyAllowed": False,
            "externalWriteAllowed": False,
            "formalFactPromotionAllowed": False,
            "productionMigrationRunbookState": "UNKNOWN",
            "independentRecoveryApprovalState": "UNKNOWN",
        }:
            raise Postgres18PilotError("PostgreSQL pilot promotion controls drift")
        return {
            "contractId": POSTGRES18_PILOT_RECEIPT_ID,
            "status": "PASS",
            "sourceCommit": source_commit,
            "migrationHead": migration_head,
            "baselineVersion": baseline["serverVersion"],
            "candidateVersion": candidate["serverVersion"],
            "baselineImageSha256": baseline["imageIdSha256"],
            "candidateImageSha256": candidate["imageIdSha256"],
            "migrationReplay": True,
            "extensionCompatibility": True,
            "forwardRestore": True,
            "rollbackRestore": True,
            "benchmarkGate": True,
            "lockGate": True,
            "featureProbe": True,
            "cleanup": True,
            "exitGateState": "not_passed",
            "baselinePromotionAllowed": False,
            "productionDependencyAllowed": False,
            "externalWriteAllowed": False,
            "formalFactPromotionAllowed": False,
            "reportSha256": sha256_json(document),
        }

    def _verify_engine(
        self,
        value: Any,
        *,
        label: str,
        expected_image: str,
        minimum: tuple[int, int],
    ) -> dict[str, Any]:
        engine = _mapping(value, label)
        if engine.get("image") != expected_image:
            raise Postgres18PilotError(f"{label} image drift")
        version = _postgres_version(engine.get("serverVersion"), label)
        if version < minimum or version[0] != minimum[0]:
            raise Postgres18PilotError(f"{label} patch level failed")
        _sha256(engine.get("imageIdSha256"), label)
        repo_digest = str(engine.get("repoDigest") or "")
        if "@sha256:" not in repo_digest or not _HEX_64.fullmatch(repo_digest.rsplit(":", 1)[-1]):
            raise Postgres18PilotError(f"{label} repository digest is invalid")
        if engine.get("healthy") is not True:
            raise Postgres18PilotError(f"{label} was not healthy")
        return engine

    def _verify_benchmarks(self, value: Any) -> None:
        benchmark = _mapping(value, "Benchmark evidence")
        if benchmark.get("rowCount") != self.policy.synthetic_rows:
            raise Postgres18PilotError("PostgreSQL benchmark row count drift")
        queries = benchmark.get("queries")
        if not isinstance(queries, list) or len(queries) < 3:
            raise Postgres18PilotError("PostgreSQL benchmark inventory is incomplete")
        names: set[str] = set()
        for raw_query in queries:
            query = _mapping(raw_query, "Benchmark query")
            name = _safe_name(query.get("name"), "Benchmark query name")
            if name in names:
                raise Postgres18PilotError("PostgreSQL benchmark names are duplicated")
            names.add(name)
            if query.get("sourceResultSha256") != query.get("candidateResultSha256"):
                raise Postgres18PilotError(f"PostgreSQL benchmark result drift: {name}")
            _sha256(query.get("sourceResultSha256"), f"Benchmark result {name}")
            source_ms = _nonnegative_float(query.get("sourceMedianMs"), f"Source latency {name}")
            candidate_ms = _nonnegative_float(
                query.get("candidateMedianMs"),
                f"Candidate latency {name}",
            )
            allowed_ms = max(
                self.policy.absolute_latency_budget_ms,
                source_ms * self.policy.maximum_regression_ratio,
            )
            if candidate_ms > allowed_ms:
                raise Postgres18PilotError(f"PostgreSQL benchmark latency regression: {name}")
            if not query.get("sourcePlanNodes") or not query.get("candidatePlanNodes"):
                raise Postgres18PilotError(f"PostgreSQL benchmark plan is empty: {name}")

    def _verify_locks(self, value: Any) -> None:
        locks = _mapping(value, "Lock evidence")
        for key in ("baseline", "candidate"):
            observation = _mapping(locks.get(key), f"{key} lock observation")
            if (
                observation.get("conflictObserved") is not True
                or observation.get("ungrantedLockObserved") is not True
                or observation.get("timeoutSqlstate") != "55P03"
                or observation.get("blockerRolledBack") is not True
                or observation.get("rowUnchanged") is not True
            ):
                raise Postgres18PilotError(f"PostgreSQL {key} lock behavior drift")
            wait_ms = _nonnegative_float(observation.get("waitMs"), f"{key} lock wait")
            if not (
                self.policy.lock_observation_minimum_ms
                <= wait_ms
                <= self.policy.lock_observation_maximum_ms
            ):
                raise Postgres18PilotError(f"PostgreSQL {key} lock wait budget failed")

    @staticmethod
    def _verify_features(value: Any) -> None:
        features = _mapping(value, "PostgreSQL 18 feature evidence")
        if (
            features.get("uuidv7Supported") is not True
            or features.get("temporalWithoutOverlapsSupported") is not True
            or features.get("temporalOverlapRejected") is not True
            or features.get("aioViewAvailable") is not True
            or features.get("ioMethod") not in {"sync", "worker", "io_uring"}
            or features.get("oauthServerCapabilityVisible") is not True
            or features.get("oauthRuntimeConfigured") is not False
        ):
            raise Postgres18PilotError("PostgreSQL 18 feature probe failed")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Postgres18PilotError(f"{label} must be an object")
    return dict(value)


def _safe_name(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,511}", normalized):
        raise Postgres18PilotError(f"{label} is invalid")
    return normalized


def _sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower().removeprefix("sha256:")
    if not _HEX_64.fullmatch(normalized):
        raise Postgres18PilotError(f"{label} SHA-256 is invalid")
    return normalized


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise Postgres18PilotError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise Postgres18PilotError(f"{label} must be a positive integer") from exc
    if normalized <= 0:
        raise Postgres18PilotError(f"{label} must be a positive integer")
    return normalized


def _positive_float(value: Any, label: str) -> float:
    normalized = _nonnegative_float(value, label)
    if normalized <= 0:
        raise Postgres18PilotError(f"{label} must be positive")
    return normalized


def _nonnegative_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise Postgres18PilotError(f"{label} must be a finite number")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise Postgres18PilotError(f"{label} must be a finite number") from exc
    if normalized < 0 or normalized in {float("inf"), float("-inf")} or normalized != normalized:
        raise Postgres18PilotError(f"{label} must be a finite nonnegative number")
    return normalized


def _postgres_version(value: Any, label: str) -> tuple[int, int, int]:
    match = _VERSION.search(str(value or ""))
    if match is None:
        raise Postgres18PilotError(f"{label} version is invalid")
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def _assert_secret_free(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower()
            if normalized in _FORBIDDEN_KEYS:
                raise Postgres18PilotError(f"Secret-like field is forbidden at {path}")
            _assert_secret_free(item, f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_secret_free(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _FORBIDDEN_VALUE_PATTERNS):
        raise Postgres18PilotError(f"Secret-like value is forbidden at {path}")
