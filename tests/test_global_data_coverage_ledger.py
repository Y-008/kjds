from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
    GlobalDataCoverageEvidenceAuthorityAdapter,
)
from apps.control_plane.global_data_coverage import canonical_json, content_sha256
from apps.control_plane.global_data_coverage_ledger import (
    DENOMINATOR_EVIDENCE_CONTRACT_ID,
    DENOMINATOR_EVIDENCE_SOURCE,
    DENOMINATOR_SCHEMA_VERSION,
    MANIFEST_EVIDENCE_CONTRACT_ID,
    MANIFEST_EVIDENCE_SOURCE,
    NATIVE_CAPS_EVIDENCE_CONTRACT_ID,
    NATIVE_CAPS_EVIDENCE_SOURCE,
    CoverageLedgerConflictError,
    GlobalDataCoverageConflictRow,
    GlobalDataCoverageEventRow,
    GlobalDataCoverageEvidenceLinkRow,
    GlobalDataCoverageFailedPageRow,
    GlobalDataCoverageFieldRow,
    GlobalDataCoverageLedger,
    GlobalDataCoverageNativeCapsRow,
    GlobalDataCoverageSnapshotRow,
    GlobalDataCoverageWindowRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "global_data_coverage"
    / "data_cov_001_bounded_universe_v1.json"
)
REGISTRY_PATH = (
    ROOT / "docs" / "project" / "registries" / "global_source_domain_registry.json"
)
STORE = "store-a"
ISSUANCE_SIGNING_KEY = b"data-cov-002-test-issuance-signing-key-v1"


class FakeScopeGrants:
    def __init__(self) -> None:
        self.version = "v1"
        self.revoked = False
        self.last_checked_at: datetime | None = None
        self.intake_authority = FakeIntakeAuthority()
        self.offset = timedelta(0)

    def clock(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def current(self, *, principal, store_ref, as_of):
        self.last_checked_at = as_of
        if self.revoked:
            return {"status": "no_data"}
        entity_ref = f"entity-{principal.tenant_ref}"
        authority_sha256 = hashlib.sha256(
            f"{principal.tenant_ref}|{entity_ref}|{store_ref}|{self.version}".encode()
        ).hexdigest()
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority_sha256,
        }


class FakeIntakeAuthority:
    def __init__(self) -> None:
        self.projections: dict[str, dict] = {}

    def register(
        self,
        *,
        purpose: str,
        payload: dict,
        data_as_of: datetime,
        source_contract_id: str,
        source_contract_version: str = "1.0.0",
    ) -> str:
        reference = f"attestation://{purpose}/{len(self.projections) + 1}"
        content_sha256 = hashlib.sha256(canonical_json(payload)).hexdigest()
        self.projections[reference] = {
            "status": "ready",
            "purpose": purpose,
            "attestation_ref": reference,
            "payload": copy.deepcopy(payload),
            "payload_sha256": content_sha256,
            "source_contract_id": source_contract_id,
            "source_contract_version": source_contract_version,
            "attestation_contract_id": "fixture-independent-source-attestation-v1",
            "attestation_contract_version": "1.0.0",
            "attestation_sha256": hashlib.sha256(f"attestation|{reference}".encode()).hexdigest(),
            "issuer_ref_sha256": hashlib.sha256(f"issuer|{reference}".encode()).hexdigest(),
            "effective_at": (data_as_of - timedelta(hours=2)).isoformat(),
            "recorded_at": (data_as_of - timedelta(hours=1)).isoformat(),
            "effective_until": (data_as_of + timedelta(days=10)).isoformat(),
        }
        return reference

    def project(self, *, purpose, attestation_ref, **_kwargs):
        projection = copy.deepcopy(self.projections.get(attestation_ref, {}))
        if projection.get("purpose") != purpose:
            return {"status": "blocked"}
        return projection


@pytest.fixture
def engine(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'coverage-ledger.db'}")

    @event.listens_for(target, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(target)
    yield target
    target.dispose()


@pytest.fixture
def service(engine):
    scope = FakeScopeGrants()
    evidence = EvidenceService(engine)
    ledger = GlobalDataCoverageLedger(
        engine=engine,
        evidence=evidence,
        scope_grants=scope,
        clock=scope.clock,
    )
    return ledger, evidence, scope


def principal(tenant: str = "tenant-a") -> Principal:
    return Principal(
        actor_id=f"coverage-operator-{tenant}",
        roles=frozenset({"operator"}),
        tenant_ref=tenant,
        store_refs=frozenset({STORE}),
    )


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text("utf-8"))


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text("utf-8"))


def authority_sha256(scope: FakeScopeGrants, tenant: str) -> str:
    entity_ref = f"entity-{tenant}"
    return hashlib.sha256(
        f"{tenant}|{entity_ref}|{STORE}|{scope.version}".encode()
    ).hexdigest()


def _capture_json(
    evidence: EvidenceService,
    *,
    payload: dict,
    source: str,
    contract_id: str,
    schema_version: str,
    scope: FakeScopeGrants,
    tenant: str,
    as_of: datetime,
    grade: EvidenceGrade = EvidenceGrade.A,
    source_contract_id: str = "fixture.marketplace.bounded-report-v1",
):
    purpose = {
        MANIFEST_EVIDENCE_SOURCE: "manifest",
        NATIVE_CAPS_EVIDENCE_SOURCE: "native_caps",
        DENOMINATOR_EVIDENCE_SOURCE: "denominator",
    }.get(source)
    if purpose is not None:
        reference = scope.intake_authority.register(
            purpose=purpose,
            payload=payload,
            data_as_of=as_of,
            source_contract_id=source_contract_id,
        )
        authority_options = {
            "scope_grants": scope,
            "intake_authority": scope.intake_authority,
            "clock": scope.clock,
        }
        if evidence.engine.dialect.name == "postgresql":
            authority_options["issuer_port"] = scope.coverage_issuer_port
        else:
            authority_options["issuance_signing_key"] = ISSUANCE_SIGNING_KEY
        authority = GlobalDataCoverageEvidenceAuthorityAdapter(
            evidence,
            **authority_options,
        )
        method = getattr(authority, f"capture_{purpose}")
        return method(
            principal=principal(tenant),
            store_ref=STORE,
            data_as_of=as_of,
            attestation_ref=reference,
        )
    content = canonical_json(payload)
    digest = hashlib.sha256(content).hexdigest()
    return evidence.capture(
        content=content,
        filename=f"{source}-{digest[:12]}.json",
        content_type="application/json",
        source=source,
        source_ref=f"{source}://sha256/{digest}",
        grade=grade,
        effective_at=(as_of - timedelta(hours=2)).isoformat(),
        effective_until=(as_of + timedelta(days=2)).isoformat(),
        created_by="coverage-intake-authority-test",
        metadata={
            "contract_id": contract_id,
            "schema_version": schema_version,
            "payload_content_sha256": payload.get("content_sha256"),
            "tenant_ref": tenant,
            "entity_ref": f"entity-{tenant}",
            "store_ref": STORE,
            "scope_grant_authority_sha256": authority_sha256(scope, tenant),
        },
    )


def bound_payload(
    evidence: EvidenceService,
    scope: FakeScopeGrants,
    *,
    tenant: str = "tenant-a",
    source_registry: dict | None = None,
    manifest_mutator: Any | None = None,
    denominator_mutator: Any | None = None,
    supporting_factory: Any | None = None,
) -> tuple[dict, str, str, datetime]:
    item = fixture()
    manifest = item["manifest"]
    native_caps = item["native_caps"]
    trusted_registry = copy.deepcopy(source_registry or registry())
    source_contract = next(
        contract
        for family in trusted_registry["source_families"]
        for contract in family["source_contracts"]
        if contract["id"] == manifest["source"]["source_id"]
    )
    manifest["source"]["source_status"] = source_contract["status"]
    native_caps["source_status"] = source_contract["status"]
    as_of = datetime.now(UTC) - timedelta(hours=1)
    manifest["registry_sha256"] = trusted_registry["content_sha256"]
    manifest["as_of"] = as_of.isoformat()
    manifest["captured_at"] = (as_of - timedelta(hours=4)).isoformat()
    manifest["recorded_at"] = (as_of - timedelta(hours=1)).isoformat()
    window = manifest["coverage"]["window"]
    window["requested_start"] = (as_of - timedelta(days=31)).isoformat()
    window["requested_end"] = (as_of - timedelta(hours=2)).isoformat()
    window["effective_start"] = window["requested_start"]
    window["effective_end"] = window["requested_end"]
    manifest["freshness"]["fresh_until"] = (as_of + timedelta(days=3)).isoformat()
    manifest["freshness"]["review_due"] = (as_of + timedelta(days=3)).isoformat()

    denominator_payload = {
        "contract_id": DENOMINATOR_EVIDENCE_CONTRACT_ID,
        "schema_version": DENOMINATOR_SCHEMA_VERSION,
        "source_id": manifest["source"]["source_id"],
        "source_family": manifest["source"]["source_family"],
        "universe_kind": manifest["universe"]["kind"],
        "expected_count": manifest["universe"]["expected_count"],
        "manifest_ref": manifest["manifest_ref"],
        "manifest_version": manifest["manifest_version"],
        "data_as_of": as_of.isoformat(),
        "window_start": window["requested_start"],
        "window_end": window["requested_end"],
        "partition_sha256": hashlib.sha256(
            canonical_json(
                {
                    "scope": manifest["scope"],
                    "query_bounds": manifest["universe"]["query_bounds"],
                    "source_id": manifest["source"]["source_id"],
                }
            )
        ).hexdigest(),
    }
    if denominator_mutator is not None:
        denominator_mutator(denominator_payload)
    denominator = _capture_json(
        evidence,
        payload=denominator_payload,
        source=DENOMINATOR_EVIDENCE_SOURCE,
        contract_id=DENOMINATOR_EVIDENCE_CONTRACT_ID,
        schema_version=DENOMINATOR_SCHEMA_VERSION,
        scope=scope,
        tenant=tenant,
        as_of=as_of,
    )
    manifest["evidence_refs"] = [
        {
            "id": denominator.id,
            "sha256": denominator.sha256,
            "grade": denominator.grade.value,
            "effective_at": denominator.metadata[
                "coverage_intake_upstream_effective_at"
            ],
            "effective_until": denominator.metadata[
                "coverage_intake_upstream_effective_until"
            ],
            "recorded_at": denominator.metadata[
                "coverage_intake_upstream_recorded_at"
            ],
        }
    ]
    if supporting_factory is not None:
        for supporting in supporting_factory(as_of):
            manifest["evidence_refs"].append(
                {
                    "id": supporting.id,
                    "sha256": supporting.sha256,
                    "grade": supporting.grade.value,
                    "effective_at": supporting.effective_at.isoformat(),
                    "effective_until": (
                        supporting.effective_until.isoformat()
                        if supporting.effective_until
                        else None
                    ),
                    "recorded_at": supporting.recorded_at.isoformat(),
                }
            )
    manifest["universe"]["expected_count_evidence_ref"] = denominator.id
    manifest["universe"]["expected_count_evidence_sha256"] = denominator.sha256
    manifest["coverage_claim"]["denominator_evidence_ref"] = denominator.id
    manifest["coverage_claim"]["denominator_evidence_sha256"] = denominator.sha256
    if manifest_mutator is not None:
        manifest_mutator(manifest)

    native_caps["content_sha256"] = content_sha256(native_caps)
    manifest["native_caps_sha256"] = native_caps["content_sha256"]
    native_evidence = _capture_json(
        evidence,
        payload=native_caps,
        source=NATIVE_CAPS_EVIDENCE_SOURCE,
        contract_id=NATIVE_CAPS_EVIDENCE_CONTRACT_ID,
        schema_version=native_caps["schema_version"],
        scope=scope,
        tenant=tenant,
        as_of=as_of,
    )
    manifest["content_sha256"] = content_sha256(manifest)
    manifest_evidence = _capture_json(
        evidence,
        payload=manifest,
        source=MANIFEST_EVIDENCE_SOURCE,
        contract_id=MANIFEST_EVIDENCE_CONTRACT_ID,
        schema_version=manifest["schema_version"],
        scope=scope,
        tenant=tenant,
        as_of=as_of,
    )
    return item, manifest_evidence.id, native_evidence.id, as_of


def record(
    ledger: GlobalDataCoverageLedger,
    evidence: EvidenceService,
    scope: FakeScopeGrants,
    *,
    tenant: str = "tenant-a",
    key: str = "coverage-key-1",
    payload: tuple[dict, str, str, datetime] | None = None,
):
    item, manifest_id, native_id, data_as_of = payload or bound_payload(
        evidence, scope, tenant=tenant
    )
    receipt = ledger.record(
        principal=principal(tenant),
        store_ref=STORE,
        data_as_of=data_as_of,
        idempotency_key=key,
        manifest_evidence_id=manifest_id,
        native_caps_evidence_id=native_id,
    )
    return receipt, item, manifest_id, native_id, data_as_of


def test_record_replay_and_typed_projection_conservation(service, engine):
    ledger, evidence, scope = service
    first, payload, manifest_id, native_id, data_as_of = record(ledger, evidence, scope)
    replay = ledger.record(
        principal=principal(),
        store_ref=STORE,
        data_as_of=data_as_of,
        idempotency_key="coverage-key-1",
        manifest_evidence_id=manifest_id,
        native_caps_evidence_id=native_id,
    )

    assert first.idempotent is False
    assert replay.idempotent is True
    assert first.snapshot_id == replay.snapshot_id
    assert replay.event_count == 2
    assert replay.status == "blocked"
    assert replay.currentness == "current"
    assert replay.full_coverage_claim is False
    assert all(
        getattr(replay, field) is False
        for field in (
            "formal_fact",
            "decision",
            "approval",
            "permit",
            "pilot",
            "outbox",
            "external_write",
        )
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageSnapshotRow)) == 1
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageNativeCapsRow)) == 1
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageFieldRow)) == 5
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageFailedPageRow)) == 0
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageWindowRow)) == 2
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageConflictRow)) == 0
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageEvidenceLinkRow)) == 3
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageEventRow)) == 2


def test_same_key_payload_drift_conflicts_before_new_write(service, engine):
    ledger, evidence, scope = service
    _, original, _, native_id, data_as_of = record(ledger, evidence, scope)
    changed = copy.deepcopy(original)
    changed["manifest"]["checkpoint"]["sha256"] = "f" * 64
    changed["manifest"]["content_sha256"] = content_sha256(changed["manifest"])
    changed_manifest = _capture_json(
        evidence,
        payload=changed["manifest"],
        source=MANIFEST_EVIDENCE_SOURCE,
        contract_id=MANIFEST_EVIDENCE_CONTRACT_ID,
        schema_version=changed["manifest"]["schema_version"],
        scope=scope,
        tenant="tenant-a",
        as_of=data_as_of,
    )
    with pytest.raises(CoverageLedgerConflictError, match="payload, hash, or version drift"):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=data_as_of,
            idempotency_key="coverage-key-1",
            manifest_evidence_id=changed_manifest.id,
            native_caps_evidence_id=native_id,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageSnapshotRow)) == 1


def test_authority_rotation_is_exact_scope_independent_and_old_rows_are_hidden(service):
    ledger, evidence, scope = service
    old, *_ = record(ledger, evidence, scope, key="same-key")
    scope.version = "v2"
    assert ledger.list(principal=principal(), store_ref=STORE) == []
    with pytest.raises(KeyError, match="not found"):
        ledger.get(principal=principal(), store_ref=STORE, snapshot_id=old.snapshot_id)
    new, *_ = record(ledger, evidence, scope, key="same-key")
    assert new.snapshot_id != old.snapshot_id


def test_revocation_cannot_be_rewound_with_old_data_as_of(service):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    old_as_of = payload[-1]
    scope.revoked = True
    with pytest.raises(PermissionError, match="not ready"):
        record(ledger, evidence, scope, payload=payload)
    assert scope.last_checked_at is not None
    assert scope.last_checked_at > old_as_of


def test_exact_scope_reads_are_non_enumerating(service):
    ledger, evidence, scope = service
    receipt, *_ = record(ledger, evidence, scope)
    assert (
        ledger.get(principal=principal(), store_ref=STORE, snapshot_id=receipt.snapshot_id)
        .snapshot_id
        == receipt.snapshot_id
    )
    assert len(ledger.list(principal=principal(), store_ref=STORE)) == 1
    with pytest.raises(KeyError, match="not found"):
        ledger.get(
            principal=principal("tenant-b"),
            store_ref=STORE,
            snapshot_id=receipt.snapshot_id,
        )
    assert ledger.list(principal=principal("tenant-b"), store_ref=STORE) == []


def test_unrelated_grade_a_denominator_evidence_is_rejected(service, engine):
    ledger, evidence, scope = service
    item, _, native_id, data_as_of = bound_payload(evidence, scope)
    unrelated = _capture_json(
        evidence,
        payload={"claim": "unrelated"},
        source="unrelated-a-grade-source",
        contract_id="unrelated-contract-v1",
        schema_version="unrelated-v1",
        scope=scope,
        tenant="tenant-a",
        as_of=data_as_of,
    )
    declaration = item["manifest"]["evidence_refs"][0]
    declaration.update(
        {
                "id": unrelated.id,
                "sha256": unrelated.sha256,
                "grade": unrelated.grade.value,
                "effective_at": (data_as_of - timedelta(hours=1)).isoformat(),
                "effective_until": unrelated.effective_until,
                "recorded_at": (data_as_of - timedelta(minutes=30)).isoformat(),
        }
    )
    for target in (item["manifest"]["universe"], item["manifest"]["coverage_claim"]):
        target_key = (
            "expected_count_evidence_ref"
            if "expected_count_evidence_ref" in target
            else "denominator_evidence_ref"
        )
        target[target_key] = unrelated.id
        target[target_key.replace("_ref", "_sha256")] = unrelated.sha256
    item["manifest"]["content_sha256"] = content_sha256(item["manifest"])
    manifest = _capture_json(
        evidence,
        payload=item["manifest"],
        source=MANIFEST_EVIDENCE_SOURCE,
        contract_id=MANIFEST_EVIDENCE_CONTRACT_ID,
        schema_version=item["manifest"]["schema_version"],
        scope=scope,
        tenant="tenant-a",
        as_of=data_as_of,
    )
    with pytest.raises(CoverageLedgerConflictError, match="Evidence binding drift"):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=data_as_of,
            idempotency_key="unrelated-denominator",
            manifest_evidence_id=manifest.id,
            native_caps_evidence_id=native_id,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageSnapshotRow)) == 0


def test_contract_evidence_source_schema_scope_and_future_data_fail_closed(service):
    ledger, evidence, scope = service
    item, manifest_id, _, data_as_of = bound_payload(evidence, scope)
    bad_native = _capture_json(
        evidence,
        payload=item["native_caps"],
        source="caller-self-certified-native-caps",
        contract_id="caller-self-certified-native-caps-v1",
        schema_version=item["native_caps"]["schema_version"],
        scope=scope,
        tenant="tenant-a",
        as_of=data_as_of,
    )
    with pytest.raises(CoverageLedgerConflictError, match="authority mismatch"):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=data_as_of,
            idempotency_key="wrong-source",
            manifest_evidence_id=manifest_id,
            native_caps_evidence_id=bad_native.id,
        )
    with pytest.raises(ValueError, match="later than"):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=datetime.now(UTC) + timedelta(days=1),
            idempotency_key="future",
            manifest_evidence_id=manifest_id,
            native_caps_evidence_id=bad_native.id,
        )


def test_event_chain_tamper_is_detected_on_read(service, engine):
    ledger, evidence, scope = service
    receipt, *_ = record(ledger, evidence, scope)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE global_data_coverage_events SET event_sha256 = :value "
                "WHERE snapshot_id = :snapshot AND event_index = 2"
            ),
            {"value": "f" * 64, "snapshot": receipt.snapshot_id},
        )
    with pytest.raises(CoverageLedgerConflictError, match="hash chain"):
        ledger.get(principal=principal(), store_ref=STORE, snapshot_id=receipt.snapshot_id)


def test_database_checks_reject_negative_counts_and_unscoped_rows(service, engine):
    ledger, evidence, scope = service
    receipt, *_ = record(ledger, evidence, scope)
    with Session(engine) as session, session.begin():
        row = session.get(GlobalDataCoverageSnapshotRow, receipt.snapshot_id)
        assert row is not None
        values = {
            column.name: getattr(row, column.name)
            for column in GlobalDataCoverageSnapshotRow.__table__.columns
        }
    values["snapshot_id"] = "gdcs_" + "f" * 32
    values["idempotency_sha256"] = "e" * 64
    values["accepted_count"] = -1
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(GlobalDataCoverageSnapshotRow.__table__.insert(), values)
    values["accepted_count"] = values["source_total"]
    values["tenant_ref"] = None
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(GlobalDataCoverageSnapshotRow.__table__.insert(), values)


def test_write_seam_and_replays_are_deterministic(service):
    ledger, evidence, scope = service
    parameters = set(inspect.signature(ledger.record).parameters)
    assert parameters.isdisjoint(
        {"tenant_ref", "entity_ref", "scope_grant_authority_sha256", "manifest"}
    )
    first, _, manifest_id, native_id, data_as_of = record(ledger, evidence, scope)
    replay_one = ledger.record(
        principal=principal(),
        store_ref=STORE,
        data_as_of=data_as_of,
        idempotency_key="coverage-key-1",
        manifest_evidence_id=manifest_id,
        native_caps_evidence_id=native_id,
    )
    replay_two = ledger.record(
        principal=principal(),
        store_ref=STORE,
        data_as_of=data_as_of,
        idempotency_key="coverage-key-1",
        manifest_evidence_id=manifest_id,
        native_caps_evidence_id=native_id,
    )
    assert first.snapshot_id == replay_one.snapshot_id
    assert replay_one == replay_two
    assert replay_one.receipt_sha256 == replay_two.receipt_sha256


def test_non_idempotency_integrity_error_is_not_swallowed(service, monkeypatch):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)

    def broken_insert(**_kwargs):
        raise IntegrityError("statement", {}, Exception("CHECK constraint failed: child"))

    monkeypatch.setattr(ledger, "_insert", broken_insert)
    with pytest.raises(IntegrityError):
        record(ledger, evidence, scope, key="child-check", payload=payload)


def test_complete_trusted_registry_remains_observation_only(engine):
    evidence = EvidenceService(engine)
    scope = FakeScopeGrants()
    trusted_registry = registry()
    source = trusted_registry["source_families"][0]["source_contracts"][0]
    source["status"] = "implemented"
    source["implementation_evidence_refs"] = ["fixture://trusted/adapter-proof"]
    trusted_registry["content_sha256"] = content_sha256(trusted_registry)
    ledger = GlobalDataCoverageLedger(
        engine=engine,
        evidence=evidence,
        scope_grants=scope,
        trusted_registry=trusted_registry,
        clock=scope.clock,
    )
    payload = bound_payload(evidence, scope, source_registry=trusted_registry)
    receipt, *_ = record(ledger, evidence, scope, key="trusted-complete", payload=payload)
    assert receipt.status == "complete"
    assert receipt.full_coverage_claim is True
    assert receipt.formal_fact is False
    assert receipt.external_write is False


@pytest.mark.parametrize(
    "drift",
    ["record_duplicate", "record_suppressed", "page_duplicate", "late_arrival"],
)
def test_full_claim_service_postgres_parity_closes_completeness_drifts(
    engine, drift, monkeypatch
):
    evidence = EvidenceService(engine)
    scope = FakeScopeGrants()
    trusted_registry = registry()
    source = trusted_registry["source_families"][0]["source_contracts"][0]
    source["status"] = "implemented"
    source["implementation_evidence_refs"] = ["fixture://trusted/adapter-proof"]
    trusted_registry["content_sha256"] = content_sha256(trusted_registry)

    def mutate(manifest):
        if drift == "record_duplicate":
            manifest["conservation"]["accepted_count"] -= 1
            manifest["conservation"]["duplicate_count"] = 1
        elif drift == "record_suppressed":
            manifest["conservation"]["accepted_count"] -= 1
            manifest["conservation"]["suppressed_count"] = 1
        elif drift == "page_duplicate":
            manifest["coverage"]["pages"]["duplicate_count"] = 1
        else:
            manifest["coverage"]["window"]["late_arrival_count"] = 1

    ledger = GlobalDataCoverageLedger(
        engine=engine,
        evidence=evidence,
        scope_grants=scope,
        trusted_registry=trusted_registry,
        clock=scope.clock,
    )
    captured = {}
    original_insert = ledger._insert

    def capture_observation(**kwargs):
        captured["observation"] = kwargs["observation"]
        return original_insert(**kwargs)

    monkeypatch.setattr(ledger, "_insert", capture_observation)
    payload = bound_payload(
        evidence,
        scope,
        source_registry=trusted_registry,
        manifest_mutator=mutate,
    )
    receipt, *_ = record(ledger, evidence, scope, key=f"parity-{drift}", payload=payload)
    assert receipt.status == "complete"
    assert receipt.full_coverage_claim is False
    observation = captured["observation"]
    assert observation.full_coverage_claim_scope == "not_proven"
    unsigned = dataclass_replace(observation, observation_sha256="")
    assert observation.observation_sha256 == hashlib.sha256(
        canonical_json(unsigned.to_dict())
    ).hexdigest()
    assert receipt.observation_sha256 == observation.observation_sha256


def test_review_due_and_frozen_freshness_status_fail_full_claim_closed(service, engine):
    ledger, evidence, scope = service
    receipt, *_ = record(ledger, evidence, scope)
    scope.offset = timedelta(days=4)
    stale = ledger.get(
        principal=principal(), store_ref=STORE, snapshot_id=receipt.snapshot_id
    )
    assert stale.currentness == "stale"
    assert stale.full_coverage_claim is False
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE global_data_coverage_snapshots "
                "SET freshness_status='stale', fresh_until=:future, review_due=:future "
                "WHERE snapshot_id=:snapshot"
            ),
            {
                "future": datetime.now(UTC) + timedelta(days=20),
                "snapshot": receipt.snapshot_id,
            },
        )
    scope.offset = timedelta(0)
    frozen_stale = ledger.get(
        principal=principal(), store_ref=STORE, snapshot_id=receipt.snapshot_id
    )
    assert frozen_stale.currentness == "stale"
    assert frozen_stale.full_coverage_claim is False


@pytest.mark.parametrize("role", ["manifest", "native_caps", "denominator"])
def test_intake_issuance_metadata_drift_produces_zero_snapshot(service, engine, role):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    item, manifest_id, native_id, data_as_of = payload
    evidence_id = {
        "manifest": manifest_id,
        "native_caps": native_id,
        "denominator": item["manifest"]["coverage_claim"][
            "denominator_evidence_ref"
        ],
    }[role]
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, evidence_id)
        assert row is not None
        row.metadata_json = {
            **row.metadata_json,
            "coverage_intake_attestation_sha256": "f" * 64,
        }
    with pytest.raises(CoverageLedgerConflictError, match="authority mismatch"):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=data_as_of,
            idempotency_key=f"metadata-drift-{role}",
            manifest_evidence_id=manifest_id,
            native_caps_evidence_id=native_id,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageSnapshotRow)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(EvidenceRecordRow)
                .where(EvidenceRecordRow.source == "global-data-coverage-ledger")
            )
            == 0
        )


def test_same_payload_with_different_issuance_never_replays_old_evidence(engine):
    evidence = EvidenceService(engine)
    scope = FakeScopeGrants()
    intake = FakeIntakeAuthority()
    payload = fixture()["native_caps"]
    payload["content_sha256"] = content_sha256(payload)
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    first_ref = intake.register(
        purpose="native_caps",
        payload=payload,
        data_as_of=cutoff,
        source_contract_id="fixture.marketplace.bounded-report-v1",
        source_contract_version="1.0.0",
    )
    second_ref = intake.register(
        purpose="native_caps",
        payload=payload,
        data_as_of=cutoff,
        source_contract_id="fixture.marketplace.bounded-report-v1",
        source_contract_version="2.0.0",
    )
    authority = GlobalDataCoverageEvidenceAuthorityAdapter(
        evidence,
        scope_grants=scope,
        intake_authority=intake,
        issuance_signing_key=ISSUANCE_SIGNING_KEY,
        clock=scope.clock,
    )
    first = authority.capture_native_caps(
        principal=principal(), store_ref=STORE, data_as_of=cutoff, attestation_ref=first_ref
    )
    second = authority.capture_native_caps(
        principal=principal(), store_ref=STORE, data_as_of=cutoff, attestation_ref=second_ref
    )
    assert first.sha256 == second.sha256
    assert first.id != second.id
    assert first.source_ref != second.source_ref
    assert first.metadata["coverage_intake_issuance_sha256"] != second.metadata[
        "coverage_intake_issuance_sha256"
    ]


@pytest.mark.parametrize("role", ["manifest", "native_caps", "denominator"])
def test_intake_effective_until_drift_produces_zero_snapshot(service, engine, role):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    item, manifest_id, native_id, data_as_of = payload
    evidence_id = {
        "manifest": manifest_id,
        "native_caps": native_id,
        "denominator": item["manifest"]["coverage_claim"]["denominator_evidence_ref"],
    }[role]
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, evidence_id)
        assert row is not None
        row.effective_until = data_as_of + timedelta(days=2)
    with pytest.raises(CoverageLedgerConflictError):
        ledger.record(
            principal=principal(),
            store_ref=STORE,
            data_as_of=data_as_of,
            idempotency_key=f"effective-until-drift-{role}",
            manifest_evidence_id=manifest_id,
            native_caps_evidence_id=native_id,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(GlobalDataCoverageSnapshotRow)) == 0


def test_event_evidence_misbinding_rolls_back_entire_transaction(
    service, engine, monkeypatch
):
    ledger, evidence, scope = service
    payload = bound_payload(evidence, scope)
    original = evidence.capture_global_data_coverage_ledger_event

    def corrupt(**kwargs):
        captured = original(**kwargs)
        return dataclass_replace(captured, sha256="f" * 64)

    monkeypatch.setattr(evidence, "capture_global_data_coverage_ledger_event", corrupt)
    with pytest.raises(IntegrityError):
        record(ledger, evidence, scope, key="rollback-event", payload=payload)
    with Session(engine) as session:
        for model in (
            GlobalDataCoverageSnapshotRow,
            GlobalDataCoverageNativeCapsRow,
            GlobalDataCoverageFieldRow,
            GlobalDataCoverageWindowRow,
            GlobalDataCoverageEvidenceLinkRow,
            GlobalDataCoverageEventRow,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(EvidenceRecordRow)
                .where(EvidenceRecordRow.source == "global-data-coverage-ledger")
            )
            == 0
        )
