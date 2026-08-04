from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.evidence import EvidenceGrade, EvidenceRecordRow, EvidenceService
from apps.control_plane.security import Principal
from apps.control_plane.strategic_benchmark import (
    ELIGIBILITY_POLICY,
    EVIDENCE_SOURCE,
    OBSERVATION_CONTRACT,
    StrategicBenchmarkConflictError,
    StrategicBenchmarkEvidenceLinkRow,
    StrategicBenchmarkGroupRow,
    StrategicBenchmarkKernel,
    StrategicBenchmarkLeaderRow,
    StrategicBenchmarkObservationRow,
    StrategicBenchmarkSnapshotRow,
)

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)

SNAPSHOTS = "strategic_benchmark_snapshots"
GROUPS = "strategic_benchmark_groups"
OBSERVATIONS = "strategic_benchmark_observations"
LEADERS = "strategic_benchmark_leaders"
EVIDENCE_LINKS = "strategic_benchmark_evidence_links"
TABLES = (SNAPSHOTS, GROUPS, OBSERVATIONS, LEADERS, EVIDENCE_LINKS)
RECORDED_AT = datetime.now(UTC) - timedelta(minutes=1)
NOW = datetime.now(UTC) + timedelta(minutes=5)
STORE = "store-a"


class FakeScopeGrants:
    def __init__(self) -> None:
        self.version = "v1"

    def current(self, *, principal, store_ref, as_of):
        entity_ref = f"entity-{principal.tenant_ref}"
        authority_sha256 = hashlib.sha256(
            (f"{principal.tenant_ref}|{entity_ref}|{store_ref}|{self.version}").encode()
        ).hexdigest()
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority_sha256,
        }


class FakeScopedEvidence:
    def __init__(self, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": "ready",
            "records": [
                {
                    "evidence_id": evidence_id,
                    "sha256": self.evidence.get_metadata(evidence_id).sha256,
                    "grade": self.evidence.get_metadata(evidence_id).grade.value,
                }
                for evidence_id in evidence_ids
            ],
        }


def migration_config(engine) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


@pytest.fixture(scope="module")
def engine():
    schema = f"bas199_test_{uuid4().hex}"
    admin = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    target = create_engine(url.set(query=query), pool_pre_ping=True)
    original_database_url = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = target.url.render_as_string(
        hide_password=False
    ).replace("%", "%%")
    config = migration_config(target)
    try:
        command.upgrade(config, "20260803_0093")
        command.downgrade(config, "20260803_0092")
        command.upgrade(config, "20260803_0093")
        yield target
    finally:
        if original_database_url is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = original_database_url
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def kernel(engine):
    scope = FakeScopeGrants()
    evidence = EvidenceService(engine)
    service = StrategicBenchmarkKernel(
        engine=engine,
        evidence=evidence,
        scope_grants=scope,
        scoped_evidence=FakeScopedEvidence(evidence),
        clock=lambda: NOW,
        sealing_key=hashlib.sha256(b"bas199-postgres-test-sealing-key").digest(),
    )
    return service, scope


def principal(tenant_ref: str = "tenant-a") -> Principal:
    return Principal(
        actor_id="postgres-benchmark-operator",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({STORE}),
    )


def group_payload(*, value_a: str = "0.82", value_b: str = "0.70") -> dict:
    return {
        "domain": "product_experience",
        "metric_id": "activation_rate",
        "cohort_ref": "cohort-global-verified",
        "market": "global",
        "window_start": NOW - timedelta(days=10),
        "window_end": NOW,
        "methodology_id": ELIGIBILITY_POLICY["methodology_id"],
        "methodology_version": ELIGIBILITY_POLICY["methodology_version"],
        "source_contract_id": "official-public-benchmark-v1",
        "source_contract_version": "1",
        "observations": [
            {
                "subject_ref": "frontier-peer",
                "subject_class": "peer",
                "value": value_a,
                "uncertainty_lower": "0.80",
                "uncertainty_upper": "0.84",
                "confidence_bps": 9500,
                "sample_size": 100,
                "observed_at": NOW - timedelta(days=1),
            },
            {
                "subject_ref": "baseline-peer",
                "subject_class": "peer",
                "value": value_b,
                "uncertainty_lower": "0.68",
                "uncertainty_upper": "0.72",
                "confidence_bps": 9500,
                "sample_size": 100,
                "observed_at": NOW - timedelta(days=1),
            },
        ],
    }


def capture_group(service, payload: dict, *, active: Principal | None = None) -> list[str]:
    active = active or principal()
    scope = service.scope_grants.current(
        principal=active,
        store_ref=STORE,
        as_of=NOW,
    )
    refs: list[str] = []
    for observation in payload["observations"]:
        evidence_payload = {
            "schema_id": OBSERVATION_CONTRACT["schema_id"],
            "schema_version": OBSERVATION_CONTRACT["schema_version"],
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_authority_sha256": scope["authority_sha256"],
            "domain": payload["domain"],
            "metric_id": payload["metric_id"],
            "cohort_ref": payload["cohort_ref"],
            "market": payload["market"],
            "window_start": payload["window_start"].isoformat(),
            "window_end": payload["window_end"].isoformat(),
            "methodology_id": payload["methodology_id"],
            "methodology_version": payload["methodology_version"],
            "source_contract_id": payload["source_contract_id"],
            "source_contract_version": payload["source_contract_version"],
            "subject_ref": observation["subject_ref"],
            "subject_class": observation["subject_class"],
            "value": observation["value"],
            "uncertainty_lower": observation["uncertainty_lower"],
            "uncertainty_upper": observation["uncertainty_upper"],
            "confidence_bps": observation["confidence_bps"],
            "sample_size": observation["sample_size"],
            "observed_at": observation["observed_at"].isoformat(),
            "recorded_at": RECORDED_AT.isoformat(),
        }
        content = json.dumps(evidence_payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(content).hexdigest()
        record = service.evidence.capture(
            content=content,
            filename=f"{digest}.json",
            content_type="application/json",
            source="strategic-benchmark-observation",
            source_ref=f"strategic-benchmark-observation://sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=observation["observed_at"].isoformat(),
            effective_until=(NOW + timedelta(days=1)).isoformat(),
            created_by="postgres-contract-test",
            metadata={
                "benchmark_schema_id": OBSERVATION_CONTRACT["schema_id"],
                "benchmark_schema_version": OBSERVATION_CONTRACT["schema_version"],
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "scope_authority_sha256": scope["authority_sha256"],
                "source_contract_id": payload["source_contract_id"],
                "source_contract_version": payload["source_contract_version"],
                "retention_class": "operational",
            },
        )
        refs.append(record.id)
    return refs


def build(service, *, key: str, payload: dict | None = None) -> dict:
    refs = capture_group(service, payload or group_payload())
    return service.build_snapshot(
        principal=principal(),
        store_ref=STORE,
        as_of=NOW,
        idempotency_key=key,
        evidence_refs=refs,
    )


def reflected_table(engine, table_name: str) -> Table:
    return Table(table_name, MetaData(), autoload_with=engine)


def first_row(engine, table_name: str) -> dict:
    table = reflected_table(engine, table_name)
    with engine.connect() as connection:
        return dict(connection.execute(select(table).limit(1)).mappings().one())


def test_00_migration_replay_creates_five_exact_tables_and_single_head(engine):
    inspector = inspect(engine)
    assert set(TABLES).issubset(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ("20260803_0093")
        conservation = connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc AS procedure "
                "JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace "
                "WHERE procedure.proname='kjds_check_strategic_benchmark_conservation' "
                "AND namespace.nspname=current_schema()"
            )
        )
    assert conservation == 1


def test_kernel_persists_exact_scope_relations_and_verified_evidence(engine, kernel):
    service, _scope = kernel
    result = build(service, key="persist")
    assert result["groups"][0]["leader_label"] == "metric_leader"
    with Session(engine) as session:
        snapshot = session.scalar(select(StrategicBenchmarkSnapshotRow))
        groups = list(session.scalars(select(StrategicBenchmarkGroupRow)))
        observations = list(session.scalars(select(StrategicBenchmarkObservationRow)))
        leaders = list(session.scalars(select(StrategicBenchmarkLeaderRow)))
        links = list(session.scalars(select(StrategicBenchmarkEvidenceLinkRow)))
        assert snapshot is not None
        assert snapshot.group_count == len(groups) == 1
        assert snapshot.observation_count == len(observations) == 2
        assert groups[0].leader_count == len(leaders) == 1
        assert all(item.scope_authority_sha256 == snapshot.scope_authority_sha256 for item in observations)
        assert all(item.evidence_source == "strategic-benchmark-observation" for item in links)
        assert len(links) == sum(item.evidence_link_count for item in observations)


def test_exact_composite_foreign_keys_reject_scope_window_and_evidence_drift(engine, kernel):
    service, _scope = kernel
    build(service, key="fk-source")
    group = first_row(engine, GROUPS)
    group.update(
        group_ref=f"sbg_{uuid4().hex}",
        ordinal=999,
        metric_id="activation_rate_fk_drift",
        scope_authority_sha256="f" * 64,
        group_sha256="1" * 64,
        result_sha256="2" * 64,
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(reflected_table(engine, GROUPS).insert().values(**group))

    observation = first_row(engine, OBSERVATIONS)
    observation.update(
        observation_ref=f"sbo_{uuid4().hex}",
        ordinal=999,
        subject_token_sha256="3" * 64,
        window_end=observation["window_end"] + timedelta(seconds=1),
        observation_sha256="4" * 64,
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(reflected_table(engine, OBSERVATIONS).insert().values(**observation))

    link = first_row(engine, EVIDENCE_LINKS)
    other_link = None
    table = reflected_table(engine, EVIDENCE_LINKS)
    with engine.connect() as connection:
        rows = list(connection.execute(select(table)).mappings())
        other_link = next(row for row in rows if row["evidence_id"] != link["evidence_id"])
    link.update(
        link_ref=f"sbel_{uuid4().hex}",
        ordinal=999,
        evidence_id=other_link["evidence_id"],
        evidence_sha256="5" * 64,
        evidence_source_ref="strategic-benchmark-observation://sha256/" + "5" * 64,
        citation_token_sha256="6" * 64,
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(table.insert().values(**link))


@pytest.mark.parametrize("table_name", TABLES)
def test_append_only_triggers_reject_update_and_delete(engine, kernel, table_name):
    service, _scope = kernel
    build(service, key=f"immutable-{table_name}")
    table = reflected_table(engine, table_name)
    row = first_row(engine, table_name)
    primary_key = list(table.primary_key.columns)[0]
    value = row[primary_key.name]
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(table.update().where(primary_key == value).values(created_at=datetime.now(UTC)))
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(table.delete().where(primary_key == value))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", Decimal("NaN")),
        ("value", Decimal("Infinity")),
        ("value", Decimal("-1")),
        ("confidence_bps", -1),
        ("sample_size", 0),
    ],
)
def test_database_rejects_non_finite_negative_or_invalid_quality(engine, kernel, field, value):
    service, _scope = kernel
    build(service, key=f"numeric-{field}-{value}")
    row = first_row(engine, OBSERVATIONS)
    row.update(
        observation_ref=f"sbo_{uuid4().hex}",
        ordinal=999,
        subject_token_sha256=uuid4().hex * 2,
        observation_sha256="7" * 64,
    )
    row[field] = value
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(reflected_table(engine, OBSERVATIONS).insert().values(**row))


def test_duplicate_comparison_key_and_late_append_fail_closed(engine, kernel):
    service, _scope = kernel
    build(service, key="duplicate-db")
    duplicate = first_row(engine, GROUPS)
    duplicate.update(
        group_ref=f"sbg_{uuid4().hex}",
        ordinal=999,
        group_sha256="8" * 64,
        result_sha256="9" * 64,
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(reflected_table(engine, GROUPS).insert().values(**duplicate))

    late = first_row(engine, GROUPS)
    late.update(
        group_ref=f"sbg_{uuid4().hex}",
        ordinal=1000,
        metric_id="late_append_metric",
        group_sha256="a" * 64,
        result_sha256="b" * 64,
        comparison_state="no_data",
        leader_label=None,
        leader_observation_refs_json=[],
        comparable_count=0,
        ineligible_count=2,
        leader_count=0,
    )
    with pytest.raises(DBAPIError, match="group count conservation"), engine.begin() as connection:
        connection.execute(reflected_table(engine, GROUPS).insert().values(**late))

    link_table = reflected_table(engine, EVIDENCE_LINKS)
    with engine.connect() as connection:
        link_rows = list(connection.execute(select(link_table)).mappings())
    late_link = dict(link_rows[0])
    other = next(
        row
        for row in link_rows
        if row["evidence_id"] != late_link["evidence_id"]
    )
    late_link.update(
        link_ref=f"sbel_{uuid4().hex}",
        ordinal=999,
        evidence_id=other["evidence_id"],
        evidence_sha256=other["evidence_sha256"],
        evidence_source=other["evidence_source"],
        evidence_source_ref=other["evidence_source_ref"],
        evidence_grade=other["evidence_grade"],
        evidence_effective_at=other["evidence_effective_at"],
        citation_token_sha256="c" * 64,
    )
    with (
        pytest.raises(DBAPIError, match="evidence link conservation"),
        engine.begin() as connection,
    ):
        connection.execute(link_table.insert().values(**late_link))


def test_metric_leader_requires_exactly_one_relation(engine, kernel):
    service, _scope = kernel
    result = build(service, key="metric-leader-cardinality")
    snapshot_ref = result["snapshot"]["snapshot_ref"]
    group_table = reflected_table(engine, GROUPS)
    with engine.connect() as connection:
        group = dict(
            connection.execute(
                select(group_table).where(group_table.c.snapshot_ref == snapshot_ref)
            ).mappings().one()
        )
    group.update(
        group_ref=f"sbg_{uuid4().hex}",
        ordinal=999,
        metric_id="metric_leader_cardinality_probe",
        leader_count=2,
        leader_observation_refs_json=["observation-a", "observation-b"],
        group_sha256="c" * 64,
        result_sha256="d" * 64,
    )
    with (
        pytest.raises(DBAPIError, match="ck_strategic_benchmark_leader_consistency"),
        engine.begin() as connection,
    ):
        connection.execute(group_table.insert().values(**group))


def test_leader_relation_rejects_ineligible_observation(engine, kernel):
    service, _scope = kernel
    payload = group_payload()
    payload["observations"][1]["confidence_bps"] = 0
    payload["observations"][1]["sample_size"] = 1
    result = build(service, key="ineligible-leader-relation", payload=payload)
    snapshot_ref = result["snapshot"]["snapshot_ref"]
    group_table = reflected_table(engine, GROUPS)
    observation_table = reflected_table(engine, OBSERVATIONS)
    with engine.connect() as connection:
        group = connection.execute(
            select(group_table).where(group_table.c.snapshot_ref == snapshot_ref)
        ).mappings().one()
        ineligible = connection.execute(
            select(observation_table).where(
                observation_table.c.group_ref == group["group_ref"],
                observation_table.c.eligibility_state != "eligible",
            )
        ).mappings().one()
    leader_table = reflected_table(engine, LEADERS)
    leader = {
        "leader_ref": f"sbl_{uuid4().hex}",
        "observation_ref": ineligible["observation_ref"],
        "group_ref": group["group_ref"],
        "snapshot_ref": group["snapshot_ref"],
        "tenant_ref": group["tenant_ref"],
        "entity_ref": group["entity_ref"],
        "store_ref": group["store_ref"],
        "scope_authority_sha256": group["scope_authority_sha256"],
        "ordinal": 1,
        "created_at": NOW,
    }
    with (
        pytest.raises(DBAPIError, match="leader eligibility conservation"),
        engine.begin() as connection,
    ):
        connection.execute(leader_table.insert().values(**leader))


def test_concurrent_same_key_is_one_snapshot_and_request_drift_is_zero_new(engine, kernel):
    service, _scope = kernel
    refs = capture_group(service, group_payload())
    before_snapshots = 0
    before_evidence = 0
    with Session(engine) as session:
        before_snapshots = session.scalar(select(func.count()).select_from(StrategicBenchmarkSnapshotRow))
        before_evidence = session.scalar(
            select(func.count()).select_from(EvidenceRecordRow).where(EvidenceRecordRow.source == EVIDENCE_SOURCE)
        )

    def invoke():
        return service.build_snapshot(
            principal=principal(),
            store_ref=STORE,
            as_of=NOW,
            idempotency_key="concurrent-key",
            evidence_refs=refs,
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _index: invoke(), range(16)))
    assert len({item["snapshot"]["snapshot_ref"] for item in results}) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StrategicBenchmarkSnapshotRow)) == before_snapshots + 1
        assert (
            session.scalar(
                select(func.count()).select_from(EvidenceRecordRow).where(EvidenceRecordRow.source == EVIDENCE_SOURCE)
            )
            == before_evidence + 1
        )

    drift_refs = capture_group(service, group_payload(value_a="0.81"))
    with pytest.raises(StrategicBenchmarkConflictError):
        service.build_snapshot(
            principal=principal(),
            store_ref=STORE,
            as_of=NOW,
            idempotency_key="concurrent-key",
            evidence_refs=drift_refs,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StrategicBenchmarkSnapshotRow)) == before_snapshots + 1


def test_authority_rotation_hides_old_scope_and_allows_same_key(engine, kernel):
    service, scope = kernel
    first = build(service, key="rotation-key")
    scope.version = "v2"
    assert service.list(principal=principal(), store_ref=STORE, as_of=NOW, limit=100)["items"] == []
    with pytest.raises(KeyError):
        service.get(
            principal=principal(),
            store_ref=STORE,
            as_of=NOW,
            snapshot_ref=first["snapshot"]["snapshot_ref"],
        )
    second = build(service, key="rotation-key")
    assert second["snapshot"]["snapshot_ref"] != first["snapshot"]["snapshot_ref"]


def test_schema_has_no_raw_subject_contact_or_json_only_evidence_columns(engine):
    columns = {
        table_name: {column["name"] for column in inspect(engine).get_columns(table_name)} for table_name in TABLES
    }
    serialized = json.dumps({key: sorted(value) for key, value in columns.items()})
    assert "subject_ref" not in columns[OBSERVATIONS]
    assert "evidence_ids_json" not in serialized
    assert "email" not in serialized
    assert "phone" not in serialized
    assert {LEADERS, EVIDENCE_LINKS}.issubset(columns)


def test_99_data_bearing_downgrade_locks_and_fails_without_schema_loss(engine):
    migration = Path("migrations/versions/20260803_0093_strategic_benchmark_snapshots.py").read_text(encoding="utf-8")
    assert "IN ACCESS EXCLUSIVE MODE" in migration
    assert "evidence_records, lineage_edges" in migration
    config = migration_config(engine)
    with pytest.raises(DBAPIError, match="strategic benchmark evidence exists"):
        command.downgrade(config, "20260803_0092")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ("20260803_0093")
    assert set(TABLES).issubset(inspect(engine).get_table_names())
