from __future__ import annotations

import base64
import hashlib
import hmac
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from apps.control_plane.strategic_benchmark import (
    BENCHMARK_REGISTRY_SHA256,
    CONTRACT_ID,
    ELIGIBILITY_POLICY,
    EVIDENCE_SOURCE,
    METRIC_SPECS,
    OBSERVATION_CONTRACT,
    StrategicBenchmarkConflictError,
    StrategicBenchmarkEvidenceLinkRow,
    StrategicBenchmarkGroupRow,
    StrategicBenchmarkKernel,
    StrategicBenchmarkLeaderRow,
    StrategicBenchmarkObservationRow,
    StrategicBenchmarkSnapshotRow,
)
from apps.control_plane.strategic_capital_dashboard import (
    AvailableSectionProjection,
    DashboardReadContext,
    StrategicBenchmarkReadPort,
    StrategicCapitalDashboardRegistry,
)

RECORDED_AT = datetime.now(UTC) - timedelta(minutes=1)
# The complete repository Gate collects this module before a multi-minute suite.
# Keep one frozen valid-time horizon that cannot expire during that run.
NOW = datetime.now(UTC) + timedelta(days=1)
TEST_SEALING_KEY = hashlib.sha256(b"bas199-unit-test-sealing-key").digest()
ROOT = Path(__file__).resolve().parents[1]


class FakeScopeGrants:
    def __init__(self) -> None:
        self.entity_suffix = "entity"
        self.authority_version = "v1"
        self.calls = []

    def current(self, *, principal, store_ref, as_of):
        self.calls.append(as_of)
        entity_ref = f"{self.entity_suffix}-{principal.tenant_ref}"
        authority = hashlib.sha256(
            (
                f"{principal.tenant_ref}|{entity_ref}|{store_ref}|"
                f"{principal.actor_id}|{self.authority_version}|{as_of.isoformat()}"
            ).encode()
        ).hexdigest()
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority,
        }


class FakeScopedEvidence:
    def __init__(self, evidence: EvidenceService) -> None:
        self.evidence = evidence
        self.status = "ready"
        self.grades: dict[str, str] = {}

    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": self.status,
            "records": [self._record(evidence_id) for evidence_id in evidence_ids],
        }

    def _record(self, evidence_id: str) -> dict[str, str]:
        record = self.evidence.get_metadata(evidence_id)
        return {
            "evidence_id": evidence_id,
            "sha256": record.sha256,
            "grade": self.grades.get(evidence_id, record.grade.value),
        }


def principal(
    tenant: str = "tenant-a", actor: str = "operator-a", *roles: str
) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset(roles or ("operator",)),
        tenant_ref=tenant,
        store_refs=frozenset({"store-a"}),
    )


@pytest.fixture
def benchmark_runtime():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            EvidenceBlobRow.__table__,
            EvidenceRecordRow.__table__,
            StrategicBenchmarkSnapshotRow.__table__,
            StrategicBenchmarkGroupRow.__table__,
            StrategicBenchmarkObservationRow.__table__,
            StrategicBenchmarkLeaderRow.__table__,
            StrategicBenchmarkEvidenceLinkRow.__table__,
        ],
    )
    scope = FakeScopeGrants()
    evidence = EvidenceService(engine)
    scoped_evidence = FakeScopedEvidence(evidence)
    service = StrategicBenchmarkKernel(
        engine=engine,
        evidence=evidence,
        scope_grants=scope,
        scoped_evidence=scoped_evidence,
        clock=lambda: NOW,
        sealing_key=TEST_SEALING_KEY,
    )
    service._test_evidence_aliases = {}
    service._test_scoped_evidence = scoped_evidence
    return service, engine, scope, scoped_evidence


def observation(
    subject: str,
    value: str,
    lower: str,
    upper: str,
    *,
    subject_class: str = "peer",
    evidence_id: str | None = None,
    observed_at: datetime | None = None,
):
    return {
        "subject_ref": subject,
        "subject_class": subject_class,
        "value": value,
        "uncertainty_lower": lower,
        "uncertainty_upper": upper,
        "confidence_bps": 9500,
        "sample_size": 40,
        "observed_at": observed_at or NOW - timedelta(days=1),
        "evidence_refs": [evidence_id or f"evd-{subject}"],
    }


def group(
    *,
    domain: str = "product_experience",
    metric_id: str = "activation_rate",
    observations: list[dict] | None = None,
    source_kind: str = "official_first_party",
    methodology_version: str = "1",
    source_contract_version: str = "1",
    source_contract_id: str | None = None,
):
    contract_by_kind = {
        "official_first_party": "official-public-benchmark-v1",
        "audited_filing": "audited-filing-benchmark-v1",
        "licensed_primary": "licensed-primary-benchmark-v1",
        "terms_permitted_public_measurement": ("terms-permitted-public-measurement-v1"),
    }
    return {
        "domain": domain,
        "metric_id": metric_id,
        "cohort_ref": "cohort-global-v1",
        "market": "global",
        "window_start": NOW - timedelta(days=7),
        "window_end": NOW,
        "methodology_id": ELIGIBILITY_POLICY["methodology_id"],
        "methodology_version": methodology_version,
        "sample_definition": "Frozen comparable verified cohort, no deleted samples",
        "source_contract_id": source_contract_id or contract_by_kind.get(source_kind, f"{source_kind}-v1"),
        "source_contract_version": source_contract_version,
        "source_kind": source_kind,
        "observations": observations
        or [
            observation("subject-a", "0.82", "0.80", "0.84"),
            observation("subject-b", "0.70", "0.68", "0.72"),
        ],
    }


def build(service, groups, *, key="snapshot-key", actor=None, as_of=NOW):
    actor = actor or principal()
    scope_binding = service.scope_grants.current(
        principal=actor,
        store_ref="store-a",
        as_of=as_of,
    )
    aliases = service._test_evidence_aliases
    scoped = service._test_scoped_evidence
    evidence_ids = []
    for group_value in groups:
        for observation_value in group_value["observations"]:
            for logical_ref in observation_value["evidence_refs"]:
                grade = scoped.grades.get(logical_ref, "A")
                payload = {
                    "schema_id": OBSERVATION_CONTRACT["schema_id"],
                    "schema_version": OBSERVATION_CONTRACT["schema_version"],
                    "tenant_ref": scope_binding["tenant_ref"],
                    "entity_ref": scope_binding["entity_ref"],
                    "store_ref": scope_binding["store_ref"],
                    "scope_authority_sha256": scope_binding["authority_sha256"],
                    "domain": group_value["domain"],
                    "metric_id": group_value["metric_id"],
                    "cohort_ref": group_value["cohort_ref"],
                    "market": group_value["market"],
                    "window_start": group_value["window_start"].isoformat(),
                    "window_end": group_value["window_end"].isoformat(),
                    "methodology_id": group_value["methodology_id"],
                    "methodology_version": group_value["methodology_version"],
                    "source_contract_id": group_value["source_contract_id"],
                    "source_contract_version": group_value["source_contract_version"],
                    "subject_ref": observation_value["subject_ref"],
                    "subject_class": observation_value["subject_class"],
                    "value": str(observation_value["value"]),
                    "uncertainty_lower": str(observation_value["uncertainty_lower"]),
                    "uncertainty_upper": str(observation_value["uncertainty_upper"]),
                    "confidence_bps": observation_value["confidence_bps"],
                    "sample_size": observation_value["sample_size"],
                    "observed_at": observation_value["observed_at"].isoformat(),
                    "recorded_at": RECORDED_AT.isoformat(),
                }
                content = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                digest = hashlib.sha256(content).hexdigest()
                alias_key = (
                    logical_ref,
                    digest,
                    scope_binding["authority_sha256"],
                )
                if alias_key not in aliases:
                    record = service.evidence.capture(
                        content=content,
                        filename=f"{digest}.json",
                        content_type=OBSERVATION_CONTRACT["content_type"],
                        source=OBSERVATION_CONTRACT["evidence_source"],
                        source_ref=(OBSERVATION_CONTRACT["content_addressed_source_ref_prefix"] + digest),
                        grade=EvidenceGrade(grade),
                        effective_at=observation_value["observed_at"].isoformat(),
                        effective_until=(as_of + timedelta(days=1)).isoformat(),
                        created_by="test-suite",
                        metadata={
                            "benchmark_schema_id": OBSERVATION_CONTRACT["schema_id"],
                            "benchmark_schema_version": OBSERVATION_CONTRACT["schema_version"],
                            "tenant_ref": scope_binding["tenant_ref"],
                            "entity_ref": scope_binding["entity_ref"],
                            "store_ref": scope_binding["store_ref"],
                            "scope_authority_sha256": scope_binding["authority_sha256"],
                            "source_contract_id": group_value["source_contract_id"],
                            "source_contract_version": group_value["source_contract_version"],
                            "retention_class": "operational",
                        },
                    )
                    aliases[alias_key] = record.id
                    scoped.grades[record.id] = grade
                evidence_ids.append(aliases[alias_key])
    return service.build_snapshot(
        principal=actor,
        store_ref="store-a",
        as_of=as_of,
        idempotency_key=key,
        evidence_refs=evidence_ids,
    )


def expected_subject_token(scope: FakeScopeGrants, subject: str) -> str:
    current = scope.current(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
    )
    key = hmac.new(TEST_SEALING_KEY, b"subject-token-v2", hashlib.sha256).digest()
    binding = json.dumps(
        {
            "contract_id": CONTRACT_ID,
            "entity_ref": current["entity_ref"],
            "scope_authority_sha256": current["authority_sha256"],
            "store_ref": "store-a",
            "subject_ref": subject,
            "tenant_ref": "tenant-a",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(key, binding, hashlib.sha256).hexdigest()


def test_registry_hash_and_all_9_domains_41_metrics_are_frozen():
    raw = (ROOT / "docs/project/registries/strategic_benchmark_contracts.json").read_bytes()
    registry = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == BENCHMARK_REGISTRY_SHA256
    assert len(registry["domains"]) == 9
    assert len(METRIC_SPECS) == 41
    assert {item.direction for item in METRIC_SPECS.values()} == {
        "higher_is_better",
        "lower_is_better",
    }
    assert registry["top1_semantics"]["global_top1_allowed"] is False


@pytest.mark.parametrize(
    "read_role", ["operator", "reviewer", "compliance", "monitor", "admin"]
)
def test_real_kernel_projection_binds_dashboard_to_current_authority(
    benchmark_runtime, read_role: str
):
    service, _engine, scope, _scoped = benchmark_runtime
    built = build(service, [group()])
    current = scope.current(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
    )
    assert "scope_authority_sha256" not in built["snapshot"]
    contract = StrategicCapitalDashboardRegistry.load().payload[
        "source_contracts"
    ]["strategic_benchmark"]
    projection = StrategicBenchmarkReadPort(
        service=service,
        source_contract=contract,
    ).read(
        principal=principal("tenant-a", "operator-a", read_role),
        context=DashboardReadContext(
            tenant_ref=current["tenant_ref"],
            entity_ref=current["entity_ref"],
            store_ref=current["store_ref"],
            scope_grant_authority_sha256=current["authority_sha256"],
            data_as_of=NOW,
            authority_checked_at=NOW,
        ),
    )

    assert isinstance(projection, AvailableSectionProjection)
    assert projection.status == "ready"
    assert projection.scope_grant_authority_sha256 == current["authority_sha256"]

    with pytest.raises(KeyError, match="authorized scope"):
        service.get(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            snapshot_ref=built["snapshot"]["snapshot_ref"],
            expected_scope_authority_sha256="f" * 64,
        )


@pytest.mark.parametrize(
    ("domain", "metric_id", "values", "expected_subject"),
    [
        (
            "product_experience",
            "activation_rate",
            [("subject-high", "0.8", "0.78", "0.82"), ("subject-low", "0.6", "0.58", "0.62")],
            "subject-high",
        ),
        (
            "product_experience",
            "time_to_first_value",
            [("subject-fast", "8", "7", "9"), ("subject-slow", "15", "14", "16")],
            "subject-fast",
        ),
    ],
)
def test_conservative_interval_separation_respects_direction(
    benchmark_runtime, domain, metric_id, values, expected_subject
):
    service, _engine, scope, _scoped = benchmark_runtime
    observations = [observation(*item) for item in values]
    result = build(
        service,
        [group(domain=domain, metric_id=metric_id, observations=observations)],
    )
    projected = result["groups"][0]
    assert projected["comparison_state"] == "comparable"
    assert projected["leader_label"] == "metric_leader"
    leader = next(
        item for item in projected["observations"] if item["observation_ref"] in projected["leader_observation_refs"]
    )
    assert leader["subject_token"] == expected_subject_token(scope, expected_subject)
    assert result["snapshot"]["global_top1_claim"] is False


def test_overlap_is_frontier_not_metric_leader(benchmark_runtime):
    service, _engine, _scope, _scoped = benchmark_runtime
    result = build(
        service,
        [
            group(
                observations=[
                    observation("subject-a", "0.80", "0.70", "0.90"),
                    observation("subject-b", "0.79", "0.71", "0.88"),
                ]
            )
        ],
    )
    projected = result["groups"][0]
    assert projected["leader_label"] == "frontier_candidate"
    assert projected["reason_code"] == "uncertainty_intervals_overlap"
    assert len(projected["leader_observation_refs"]) == 2


@pytest.mark.parametrize(
    ("grade", "observed_at", "state"),
    [
        ("C", NOW - timedelta(days=1), "no_data"),
        ("A", NOW - timedelta(days=31), "stale"),
    ],
)
def test_source_grade_and_freshness_gate_leadership(benchmark_runtime, grade, observed_at, state):
    service, _engine, _scope, scoped = benchmark_runtime
    scoped.grades["evd-one"] = grade
    value = group(
        observations=[
            observation(
                "one",
                "0.8",
                "0.7",
                "0.9",
                evidence_id="evd-one",
                observed_at=observed_at,
            )
        ],
    )
    value["window_start"] = NOW - timedelta(days=40)
    result = build(service, [value])
    assert result["groups"][0]["comparison_state"] == state
    assert result["groups"][0]["leader_label"] is None


@pytest.mark.parametrize("source_kind", ["marketing_claim", "model_output", "synthetic_demo"])
def test_unregistered_source_contract_cannot_self_certify(benchmark_runtime, source_kind):
    service, _engine, _scope, _scoped = benchmark_runtime
    with pytest.raises(ValueError, match="source contract is not registered"):
        build(service, [group(source_kind=source_kind)])


def test_idempotency_is_order_independent_and_conflicts_on_drift(benchmark_runtime):
    service, engine, _scope, _scoped = benchmark_runtime
    first_group = group()
    reverse_group = deepcopy(first_group)
    reverse_group["observations"].reverse()
    first = build(service, [first_group], key="stable-key")
    replay = build(service, [reverse_group], key="stable-key")
    assert replay["snapshot"]["snapshot_ref"] == first["snapshot"]["snapshot_ref"]
    assert replay["snapshot"]["idempotent_replay"] is True
    drift = deepcopy(first_group)
    drift["observations"][0]["value"] = "0.81"
    drift["observations"][0]["uncertainty_lower"] = "0.79"
    with pytest.raises(StrategicBenchmarkConflictError):
        build(service, [drift], key="stable-key")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StrategicBenchmarkSnapshotRow)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(EvidenceRecordRow).where(EvidenceRecordRow.source == EVIDENCE_SOURCE)
            )
            == 1
        )


def test_scope_and_authority_drift_are_non_enumerable(benchmark_runtime):
    service, _engine, scope, _scoped = benchmark_runtime
    result = build(service, [group()])
    snapshot_ref = result["snapshot"]["snapshot_ref"]
    with pytest.raises(KeyError):
        service.get(
            principal=principal("tenant-b"),
            store_ref="store-a",
            as_of=NOW,
            snapshot_ref=snapshot_ref,
        )
    scope.authority_version = "v2"
    with pytest.raises(KeyError):
        service.get(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            snapshot_ref=snapshot_ref,
        )


def test_recorded_after_cutoff_snapshot_is_not_historically_visible(
    benchmark_runtime,
):
    service, engine, _scope, _scoped = benchmark_runtime
    built = build(service, [group()], key="recorded-after-cutoff")
    snapshot_ref = built["snapshot"]["snapshot_ref"]
    with Session(engine) as session, session.begin():
        session.execute(
            update(StrategicBenchmarkSnapshotRow)
            .where(StrategicBenchmarkSnapshotRow.snapshot_ref == snapshot_ref)
            .values(created_at=NOW + timedelta(seconds=1))
        )

    assert service.list(
        principal=principal(), store_ref="store-a", as_of=NOW, limit=100
    )["items"] == []
    with pytest.raises(KeyError, match="authorized scope"):
        service.get(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            snapshot_ref=snapshot_ref,
        )


def test_compare_detects_source_contract_drift_and_stable_leader_subject(
    benchmark_runtime,
):
    service, _engine, _scope, _scoped = benchmark_runtime
    baseline = build(service, [group()], key="baseline")
    current = build(service, [group()], key="current")
    stable = service.compare(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        snapshot_ref=current["snapshot"]["snapshot_ref"],
        baseline_snapshot_ref=baseline["snapshot"]["snapshot_ref"],
    )
    assert stable["comparisons"][0]["leader_changed"] is False
    drift = build(
        service,
        [group(source_kind="audited_filing")],
        key="source-drift",
    )
    invalidated = service.compare(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        snapshot_ref=drift["snapshot"]["snapshot_ref"],
        baseline_snapshot_ref=baseline["snapshot"]["snapshot_ref"],
    )
    assert invalidated["comparisons"][0] == {
        **{
            key: invalidated["comparisons"][0][key]
            for key in (
                "domain",
                "metric_id",
                "cohort_ref",
                "market",
                "direction",
                "unit",
                "current_group_ref",
                "baseline_group_ref",
            )
        },
        "state": "invalidated",
        "reason_code": "source_or_method_drift",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", "NaN"),
        ("value", "Infinity"),
        ("value", "-1"),
        ("sample_size", 1.5),
        ("confidence_bps", -1),
    ],
)
def test_rejects_invalid_numeric_inputs(benchmark_runtime, field, value):
    service, _engine, _scope, _scoped = benchmark_runtime
    payload = group()
    payload["observations"][0][field] = value
    with pytest.raises(ValueError):
        build(service, [payload])


def test_ratio_count_privacy_and_no_other_truth_outputs(benchmark_runtime):
    service, engine, _scope, scoped = benchmark_runtime
    with pytest.raises(ValueError, match="between 0 and 1"):
        build(
            service,
            [group(observations=[observation("ratio", "1.1", "1", "1.2")])],
        )
    scoped.grades["evd-account"] = "B"
    account_group = group(
        domain="global_acquisition_and_sales",
        metric_id="verified_account_coverage",
        observations=[
            observation(
                "company@example.com",
                "10",
                "9",
                "11",
                evidence_id="evd-account",
            )
        ],
    )
    with pytest.raises(ValueError, match="bounded identifier"):
        build(service, [account_group], key="raw-contact")
    account_group["observations"][0]["subject_ref"] = "subject-account-1"
    result = build(service, [account_group], key="account-count")
    projection = result["groups"][0]["observations"][0]
    assert projection["value_projection"] == {"mode": "withheld"}
    serialized = json.dumps(result, sort_keys=True)
    assert "subject-account-1" not in serialized
    assert not any(marker in serialized for marker in ("Fact", "FinanceEntry", "Approval", "Permit", "Outbox"))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StrategicBenchmarkSnapshotRow)) == 1
        assert "subject-account-1" not in json.dumps(
            [item.subject_token_sha256 for item in session.scalars(select(StrategicBenchmarkObservationRow))]
        )


def test_confidence_and_sample_policy_block_narrow_fake_leader(benchmark_runtime):
    service, _engine, _scope, _scoped = benchmark_runtime
    low_confidence = observation("tiny", "0.99", "0.98", "1")
    low_confidence["confidence_bps"] = 0
    low_confidence["sample_size"] = 1
    result = build(service, [group(observations=[low_confidence])])
    projected = result["groups"][0]
    assert projected["comparison_state"] == "no_data"
    assert projected["leader_label"] is None
    assert projected["observations"][0]["eligibility_state"] in {
        "ineligible_confidence",
        "ineligible_sample",
    }


def test_partial_cohort_never_projects_or_compares_metric_leader(benchmark_runtime):
    service, _engine, _scope, _scoped = benchmark_runtime
    ineligible = observation("unreliable", "0.10", "0.09", "0.11")
    ineligible["confidence_bps"] = 0
    observations = [
        observation("high", "0.82", "0.80", "0.84"),
        observation("low", "0.70", "0.68", "0.72"),
        ineligible,
    ]
    baseline = build(
        service,
        [group(observations=deepcopy(observations))],
        key="partial-baseline",
    )
    current = build(
        service,
        [group(observations=deepcopy(observations))],
        key="partial-current",
    )
    projected = current["groups"][0]
    assert projected["comparison_state"] == "partial"
    assert projected["leader_label"] is None
    assert projected["leader_observation_refs"] == []
    assert projected["counts"]["leaders"] == 0
    comparison = service.compare(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        snapshot_ref=current["snapshot"]["snapshot_ref"],
        baseline_snapshot_ref=baseline["snapshot"]["snapshot_ref"],
    )
    assert comparison["comparisons"][0]["state"] == "not_comparable"


def test_cursor_binds_exact_scope_authority_filter_as_of_and_position(
    benchmark_runtime,
):
    service, _engine, scope, _scoped = benchmark_runtime
    for index in range(3):
        build(service, [group()], key=f"cursor-{index}")
    first = service.list(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        domain="product_experience",
        metric_id="activation_rate",
        limit=1,
    )
    cursor = first["next_cursor"]
    assert cursor and len(first["items"]) == 1
    assert cursor.startswith("sbcursor_v2.")
    body = cursor.split(".", 1)[1]
    sealed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    assert all(
        marker not in sealed
        for marker in (
            b"tenant_ref",
            b"entity_ref",
            b"store_ref",
            b"scope_authority_sha256",
            first["items"][0]["snapshot_ref"].encode(),
        )
    )
    second = service.list(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW,
        domain="product_experience",
        metric_id="activation_rate",
        limit=1,
        cursor=cursor,
    )
    assert second["items"][0]["snapshot_ref"] != first["items"][0]["snapshot_ref"]
    with pytest.raises(KeyError):
        service.list(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            domain="product_experience",
            metric_id="time_to_first_value",
            limit=1,
            cursor=cursor,
        )
    with pytest.raises(KeyError):
        service.list(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            domain="product_experience",
            metric_id="activation_rate",
            limit=1,
            cursor=cursor[:-1] + ("0" if cursor[-1] != "0" else "1"),
        )
    for malformed_cursor in (
        cursor[: cursor.index(".") + 5] + "!!!!" + cursor[cursor.index(".") + 5 :],
        cursor + "=",
        cursor + "==",
    ):
        with pytest.raises(KeyError):
            service.list(
                principal=principal(),
                store_ref="store-a",
                as_of=NOW,
                domain="product_experience",
                metric_id="activation_rate",
                limit=1,
                cursor=malformed_cursor,
            )
    scope.authority_version = "v2"
    assert service.list(
        principal=principal(), store_ref="store-a", as_of=NOW, limit=100
    )["items"] == []
    with pytest.raises(KeyError):
        service.list(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            domain="product_experience",
            metric_id="activation_rate",
            limit=1,
            cursor=cursor,
        )


def test_server_sealing_key_is_required_and_public_dictionary_cannot_reproduce_subject(
    benchmark_runtime,
    monkeypatch,
):
    service, engine, scope, scoped = benchmark_runtime
    monkeypatch.delenv("KJDS_STRATEGIC_BENCHMARK_SEALING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        StrategicBenchmarkKernel(
            engine=engine,
            evidence=service.evidence,
            scope_grants=scope,
            scoped_evidence=scoped,
            clock=lambda: NOW,
        )

    result = build(service, [group()], key="subject-secret-proof")
    token = result["groups"][0]["observations"][0]["subject_token"]
    authority = scope.current(principal=principal(), store_ref="store-a", as_of=NOW)
    legacy_public_key = hashlib.sha256(
        (
            f"{authority['tenant_ref']}|{authority['entity_ref']}|"
            f"{authority['store_ref']}|{authority['authority_sha256']}|{CONTRACT_ID}"
        ).encode()
    ).digest()
    dictionary = ["peer-a", "peer-b", "kjds", "frontier", "baseline"]
    assert all(
        hmac.new(legacy_public_key, candidate.encode(), hashlib.sha256).hexdigest()
        != token
        for candidate in dictionary
    )


def test_authority_rotation_allows_new_exact_scope_same_key_without_old_visibility(
    benchmark_runtime,
):
    service, _engine, scope, _scoped = benchmark_runtime
    first = build(service, [group()], key="same-key")
    first_token = first["groups"][0]["observations"][0]["subject_token"]
    scope.authority_version = "v2"
    second = build(service, [group()], key="same-key")
    second_token = second["groups"][0]["observations"][0]["subject_token"]
    assert second["snapshot"]["snapshot_ref"] != first["snapshot"]["snapshot_ref"]
    assert second_token != first_token
    visible = service.list(principal=principal(), store_ref="store-a", as_of=NOW, limit=100)
    assert [item["snapshot_ref"] for item in visible["items"]] == [second["snapshot"]["snapshot_ref"]]
    with pytest.raises(KeyError):
        service.get(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            snapshot_ref=first["snapshot"]["snapshot_ref"],
        )
    historical = service.list(
        principal=principal(),
        store_ref="store-a",
        as_of=NOW - timedelta(minutes=1),
        limit=100,
    )
    assert historical["items"] == []
    assert scope.calls[-1] == NOW


@pytest.mark.parametrize(
    ("source_contract_id", "subject_class"),
    [
        ("kjds-internal-reviewed-metric-v1", "peer"),
        ("official-public-benchmark-v1", "kjds_current"),
    ],
)
def test_source_contract_cannot_spoof_subject_class(benchmark_runtime, source_contract_id, subject_class):
    service, _engine, _scope, _scoped = benchmark_runtime
    payload = group(
        source_contract_id=source_contract_id,
        source_kind=(
            "independently_reviewed_internal"
            if source_contract_id.startswith("kjds-internal")
            else "official_first_party"
        ),
        observations=[observation("subject", "0.8", "0.7", "0.9", subject_class=subject_class)],
    )
    with pytest.raises(ValueError, match="subject class"):
        build(service, [payload])


def test_unrelated_grade_a_evidence_and_historical_backfill_are_blocked(
    benchmark_runtime,
):
    service, engine, _scope, scoped = benchmark_runtime
    unrelated = service.evidence.capture(
        content=b'{"value":"999"}',
        filename="unrelated.json",
        content_type="application/json",
        source="unrelated-a-grade-source",
        source_ref="unrelated://grade-a",
        grade=EvidenceGrade.A,
        effective_at=(NOW - timedelta(days=1)).isoformat(),
        effective_until=(NOW + timedelta(days=1)).isoformat(),
        created_by="test-suite",
    )
    with pytest.raises(ValueError, match="source is not registered"):
        service.build_snapshot(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            idempotency_key="unrelated",
            evidence_refs=[unrelated.id],
        )

    created = build(service, [group()], key="historical-source")
    evidence_id = next(item.evidence_id for item in Session(engine).scalars(select(StrategicBenchmarkEvidenceLinkRow)))
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceRecordRow)
            .where(EvidenceRecordRow.id == evidence_id)
            .values(recorded_at=NOW + timedelta(seconds=1))
        )
    scoped.grades[evidence_id] = "A"
    with pytest.raises(ValueError, match="recorded_at is after as_of"):
        service.build_snapshot(
            principal=principal(),
            store_ref="store-a",
            as_of=NOW,
            idempotency_key="historical-backfill",
            evidence_refs=[evidence_id],
        )
    assert created["snapshot"]["snapshot_ref"]


def test_projection_contains_citation_tokens_but_no_raw_evidence_ids(benchmark_runtime):
    service, engine, _scope, _scoped = benchmark_runtime
    result = build(service, [group()])
    raw_ids = {item.evidence_id for item in Session(engine).scalars(select(StrategicBenchmarkEvidenceLinkRow))}
    serialized = json.dumps(result, sort_keys=True)
    assert "citations" in serialized
    assert all(evidence_id not in serialized for evidence_id in raw_ids)


def test_duplicate_comparison_identity_is_conflict_not_silent_overwrite(
    benchmark_runtime,
):
    service, _engine, _scope, _scoped = benchmark_runtime
    with pytest.raises(StrategicBenchmarkConflictError, match="comparison identity"):
        build(
            service,
            [group(), group(source_kind="audited_filing")],
            key="duplicate-comparison",
        )
