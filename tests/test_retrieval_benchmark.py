from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    _sha,
)
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.retrieval_benchmark import (
    GovernedRetrievalBenchmarkWorkspace,
    RetrievalBenchmarkConflictError,
    RetrievalBenchmarkContractError,
    RetrievalGoldSet,
    _canonical,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

FIXTURE = Path(
    "tests/fixtures/retrieval_benchmark/bas173_gold_questions_v1.json"
)
AUTHORITY_A = "a" * 64
DATA_AS_OF = datetime.now(UTC) + timedelta(minutes=5)


class FakeScopeGrants:
    def __init__(self) -> None:
        self.status = "ready"
        self.authority = AUTHORITY_A
        self.tenant_override: str | None = None
        self.store_override: str | None = None
        self.entity_ref = "entity-a"
        self.checked_at: list[datetime] = []

    def current(self, *, principal, store_ref, as_of):
        self.checked_at.append(as_of)
        return {
            "status": self.status,
            "tenant_ref": self.tenant_override or principal.tenant_ref,
            "entity_ref": self.entity_ref if self.status == "ready" else None,
            "store_ref": self.store_override or store_ref,
            "authority_sha256": self.authority,
        }


def principal(
    *,
    tenant_ref: str = "tenant-a",
    store_ref: str = "store-a",
) -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({store_ref}),
    )


def _citation_content(document: dict) -> bytes:
    return _canonical(
        {
            "citation_ref": document["citation_ref"],
            "claim_code": document["claim_code"],
            "search_text": document["search_text"],
        }
    ).encode()


def _seed(engine, *, authority: str = AUTHORITY_A):
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    exact_scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_grant_authority_sha256": authority,
    }
    gold = RetrievalGoldSet.load(FIXTURE)
    document = next(
        item
        for item in gold.documents
        if item["document_id"] == "fx-current-scope"
    )
    edge_sha256 = _sha(["bas173", "fx", "requires"])
    with Session(engine) as session, session.begin():
        session.add(
            GraphProjectRow(
                id="bas173-project",
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="store-a",
                title="BAS-173 retrieval benchmark",
                lifecycle="active",
                baseline_sha256="1" * 64,
                goal_contract_sha256="2" * 64,
                created_at=now - timedelta(days=2),
            )
        )
        session.flush()
        session.add_all(
            [
                GraphNodeRow(
                    id="node-fx-question",
                    project_id="bas173-project",
                    graph_kind="evidence",
                    stable_key="question:profit-fx-current-scope",
                    node_type="question",
                    label="profit FX requirement",
                    authority="declared",
                    source="BAS-173 gold set",
                    scope_json=exact_scope,
                    version="1",
                    content_sha256=_sha(["question", "fx"]),
                    artifact_ref=None,
                    created_at=now - timedelta(days=1),
                ),
                GraphNodeRow(
                    id="node-fx-claim",
                    project_id="bas173-project",
                    graph_kind="evidence",
                    stable_key="claim:profit_requires_current_fx",
                    node_type="claim",
                    label="current FX required",
                    authority="evidence",
                    source="Evidence",
                    scope_json=exact_scope,
                    version="1",
                    content_sha256=_sha(["claim", "fx"]),
                    artifact_ref=None,
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
    evidence = EvidenceService(engine)
    record = evidence.capture(
        content=_citation_content(document),
        filename="bas173-fx-citation.json",
        content_type="application/json",
        source="retrieval-benchmark-fixture",
        source_ref=document["citation_ref"],
        grade=EvidenceGrade.A,
        effective_at=(now - timedelta(days=1)).isoformat(),
        effective_until=(now + timedelta(days=1)).isoformat(),
        created_by="bas173-test",
        metadata={
            **exact_scope,
            "graph_edge_content_sha256": edge_sha256,
            "retrieval_source_contract_id": RetrievalGoldSet.CONTRACT_ID,
            "retrieval_gold_set_sha256": gold.content_sha256,
            "retention_class": "experiment",
        },
    )
    with Session(engine) as session, session.begin():
        session.add(
            GraphEdgeRow(
                id="edge-fx-requires",
                project_id="bas173-project",
                graph_kind="evidence",
                source_node_id="node-fx-question",
                target_node_id="node-fx-claim",
                edge_type="requires",
                derivation_method="evidence",
                confidence=100,
                evidence_ref=record.id,
                effective_from=now - timedelta(days=1),
                effective_until=now + timedelta(days=1),
                content_sha256=edge_sha256,
            )
        )
    return evidence, record


@pytest.fixture
def setup_workspace():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    evidence, record = _seed(engine)
    scope_grants = FakeScopeGrants()
    clock = [datetime.now(UTC)]
    workspace = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=scope_grants,
        agent_harness=AgentHarnessService(engine),
        evidence=evidence,
        gold_set_path=FIXTURE,
        clock=lambda: clock[0],
    )
    return workspace, scope_grants, clock, engine, record


def _evaluate(workspace, *, key="run-1", methods=("structured_sql",), **kwargs):
    return workspace.evaluate(
        principal=kwargs.pop("principal", principal()),
        store_ref=kwargs.pop("store_ref", "store-a"),
        project_id=kwargs.pop("project_id", "bas173-project"),
        as_of=kwargs.pop("as_of", DATA_AS_OF),
        gold_set_ref=kwargs.pop("gold_set_ref", workspace.gold_set_ref),
        method_ids=methods,
        idempotency_key=key,
        **kwargs,
    )


def _seal(payload: dict) -> dict:
    for document in payload["documents"]:
        document["citation_sha256"] = hashlib.sha256(
            _citation_content(document)
        ).hexdigest()
    for question in payload["questions"]:
        unsigned = {key: value for key, value in question.items() if key != "question_sha256"}
        question["question_sha256"] = hashlib.sha256(
            _canonical(unsigned).encode()
        ).hexdigest()
    unsigned_set = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = hashlib.sha256(
        _canonical(unsigned_set).encode()
    ).hexdigest()
    return payload


def test_gold_set_is_frozen_deduplicated_and_rejects_sensitive_or_tampered_input(tmp_path):
    gold = RetrievalGoldSet.load(FIXTURE)
    assert len(gold.questions) == 8
    assert len(gold.documents) == 13

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["questions"].append(dict(payload["questions"][0]))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(_seal(payload)), encoding="utf-8")
    with pytest.raises(RetrievalBenchmarkContractError, match="duplicate question_id"):
        RetrievalGoldSet.load(duplicate)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["documents"].append(dict(payload["documents"][0]))
    duplicate_document = tmp_path / "duplicate-document.json"
    duplicate_document.write_text(
        json.dumps(_seal(payload)),
        encoding="utf-8",
    )
    with pytest.raises(RetrievalBenchmarkContractError, match="duplicate document_id"):
        RetrievalGoldSet.load(duplicate_document)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["documents"][1]["citation_ref"] = payload["documents"][0][
        "citation_ref"
    ]
    duplicate_citation = tmp_path / "duplicate-citation.json"
    duplicate_citation.write_text(
        json.dumps(_seal(payload)),
        encoding="utf-8",
    )
    with pytest.raises(RetrievalBenchmarkContractError, match="duplicate citation_ref"):
        RetrievalGoldSet.load(duplicate_citation)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cross_scope = next(
        document
        for document in payload["documents"]
        if document["scope_binding"] == "tenant_other"
    )
    payload["questions"][0]["expected_claim_codes"] = [
        cross_scope["claim_code"]
    ]
    payload["questions"][0]["expected_citation_refs"] = [
        cross_scope["citation_ref"]
    ]
    cross_scope_answer = tmp_path / "cross-scope-answer.json"
    cross_scope_answer.write_text(
        json.dumps(_seal(payload)),
        encoding="utf-8",
    )
    with pytest.raises(
        RetrievalBenchmarkContractError,
        match="answer key cites non-exact-scope document",
    ):
        RetrievalGoldSet.load(cross_scope_answer)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["documents"][0]["search_text"] += " sk-fixture-secret-value"
    sensitive = tmp_path / "sensitive.json"
    sensitive.write_text(json.dumps(_seal(payload)), encoding="utf-8")
    with pytest.raises(RetrievalBenchmarkContractError, match="sensitive value"):
        RetrievalGoldSet.load(sensitive)

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["questions"][0]["query"] = "drifted"
    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RetrievalBenchmarkContractError, match="question hash drift"):
        RetrievalGoldSet.load(drifted)


def test_structured_sql_uses_exact_scope_effective_and_recorded_time_without_output_body(
    setup_workspace,
):
    workspace, _scope, _clock, engine, _record = setup_workspace
    inspector = inspect(engine)
    before = {
        table: engine.connect().execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        for table in inspector.get_table_names()
    }
    result = _evaluate(workspace)
    after = {
        table: engine.connect().execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
        for table in inspector.get_table_names()
    }
    assert after == before
    assert result["status"] == "ready"
    assert result["winner_status"] == "UNKNOWN"
    assert result["winner_method_id"] is None
    assert result["eligible_candidate_method_ids"] == ["structured_sql"]
    assert result["not_admitted_methods"] == ["pgvector", "GraphRAG"]
    assert {question["expected_outcome"] for question in result["questions"]} == {
        "answer",
        "UNKNOWN",
        "no_data",
    }
    assert all(
        question["results"][0]["eligible"] for question in result["questions"]
    )
    assert {
        question["results"][0]["corpus_sha256"]
        for question in result["questions"]
    } == {workspace.gold_set.content_sha256}
    serialized = json.dumps(result, sort_keys=True)
    assert "search_text" not in serialized
    assert "fixture-tenant-other" not in serialized
    assert "unsupported_cross_tenant_profit_claim" not in serialized
    assert "unsupported_future_backfill_agent_claim" not in serialized
    assert "future-recorded-agent" not in serialized
    assert result["formal_fact_allowed"] is False
    assert result["finance_entry_allowed"] is False
    assert result["outbox_allowed"] is False
    assert result["external_write_allowed"] is False
    for question in result["questions"]:
        metrics = question["results"][0]["metrics"]
        assert math.isfinite(metrics["latency_ms"])
        assert metrics["latency_ms"] >= 0
        assert float(metrics["cost_usd"]) == 0


def test_current_authority_is_rechecked_while_historical_data_as_of_cannot_rewind_revoke(
    setup_workspace,
):
    workspace, scope, clock, _engine, _record = setup_workspace
    first = _evaluate(workspace, key="authority-run")
    assert scope.checked_at[-1] == clock[0]
    assert scope.checked_at[-1] != DATA_AS_OF

    clock[0] += timedelta(minutes=1)
    replay = _evaluate(workspace, key="authority-run")
    assert replay == first
    assert scope.checked_at[-1] == clock[0]

    scope.authority = "b" * 64
    rotated = _evaluate(workspace, key="authority-run")
    assert rotated["run_id"] != first["run_id"]
    assert rotated["scope"]["scope_grant_authority_sha256"] == "b" * 64
    assert rotated["authority_checked_at"] == clock[0].isoformat()

    scope.status = "no_data"
    revoked = _evaluate(
        workspace,
        key="authority-run",
        as_of=DATA_AS_OF - timedelta(days=30),
    )
    assert revoked["status"] == "no_data"
    assert revoked["questions"] == []
    assert revoked["winner_status"] == "no_data"


def test_idempotency_drift_conflicts_only_inside_same_exact_authority(setup_workspace):
    workspace, _scope, _clock, _engine, _record = setup_workspace
    _evaluate(workspace, key="immutable", methods=("structured_sql",))
    with pytest.raises(RetrievalBenchmarkConflictError, match="idempotency key conflicts"):
        _evaluate(workspace, key="immutable", methods=("canonical_graph",))


def test_not_run_unknown_no_data_and_not_admitted_are_distinct_states(
    setup_workspace,
):
    workspace, _scope, _clock, _engine, _record = setup_workspace
    structured = _evaluate(workspace, key="state-structured")
    states = {
        question["question_id"]: question["results"][0]["status"]
        for question in structured["questions"]
    }
    assert states["unsigned-operating-thresholds"] == "UNKNOWN"
    assert states["causal-uplift-not-observed"] == "no_data"

    fts = _evaluate(
        workspace,
        key="state-fts",
        methods=("postgresql_fts",),
    )
    assert {
        question["results"][0]["status"] for question in fts["questions"]
    } == {"not_run"}
    assert fts["not_admitted_methods"] == ["pgvector", "GraphRAG"]
    assert fts["winner_status"] == "no_data"


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ("tenant", "no_data"),
        ("store", "no_data"),
        ("authority", "no_data"),
        ("blocked", "blocked"),
    ],
)
def test_scope_or_authority_drift_fails_closed_without_questions(
    setup_workspace,
    mutation,
    expected_status,
):
    workspace, scope, _clock, _engine, _record = setup_workspace
    if mutation == "tenant":
        scope.tenant_override = "tenant-b"
    elif mutation == "store":
        scope.store_override = "store-b"
    elif mutation == "authority":
        scope.authority = "invalid"
    else:
        scope.status = "blocked"
    result = _evaluate(workspace, key=f"scope-{mutation}")
    assert result["status"] == expected_status
    assert result["questions"] == []
    assert result["method_summary"] == []
    assert result["external_write_allowed"] is False


def test_graph_evidence_hash_scope_currentness_and_recorded_time_are_hard_gates(
    setup_workspace,
):
    workspace, _scope, _clock, engine, record = setup_workspace
    with engine.connect() as connection:
        before = {
            "nodes": connection.execute(
                text("SELECT id, content_sha256 FROM graph_nodes ORDER BY id")
            ).all(),
            "edges": connection.execute(
                text("SELECT id, content_sha256 FROM graph_edges ORDER BY id")
            ).all(),
            "evidence": connection.execute(
                text("SELECT id, blob_sha256 FROM evidence_records ORDER BY id")
            ).all(),
        }
    happy = _evaluate(workspace, key="graph-happy", methods=("canonical_graph",))
    fx = next(
        question
        for question in happy["questions"]
        if question["question_id"] == "profit-fx-current-scope"
    )
    assert fx["results"][0]["status"] == "answer"
    assert fx["results"][0]["metrics"]["citation_correctness"] == 1.0
    with engine.connect() as connection:
        after = {
            "nodes": connection.execute(
                text("SELECT id, content_sha256 FROM graph_nodes ORDER BY id")
            ).all(),
            "edges": connection.execute(
                text("SELECT id, content_sha256 FROM graph_edges ORDER BY id")
            ).all(),
            "evidence": connection.execute(
                text("SELECT id, blob_sha256 FROM evidence_records ORDER BY id")
            ).all(),
        }
    assert after == before

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        row.recorded_at = DATA_AS_OF + timedelta(seconds=1)
    future_recorded = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=FakeScopeGrants(),
        agent_harness=AgentHarnessService(engine),
        evidence=EvidenceService(engine),
        gold_set_path=FIXTURE,
    )
    blocked = _evaluate(
        future_recorded,
        key="future-recorded",
        methods=("canonical_graph",),
    )
    assert blocked["winner_status"] == "no_data"
    assert all(
        question["results"][0]["status"] == "blocked"
        for question in blocked["questions"]
    )

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        row.recorded_at = datetime.now(UTC) - timedelta(minutes=1)
        row.effective_until = DATA_AS_OF
    stale = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=FakeScopeGrants(),
        agent_harness=AgentHarnessService(engine),
        evidence=EvidenceService(engine),
        gold_set_path=FIXTURE,
    )
    blocked = _evaluate(
        stale,
        key="stale-evidence",
        methods=("causal_temporal_graph",),
    )
    assert blocked["winner_status"] == "no_data"
    assert all(not question["results"][0]["eligible"] for question in blocked["questions"])

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        row.effective_until = DATA_AS_OF + timedelta(days=1)
        row.metadata_json = {**row.metadata_json, "tenant_ref": "tenant-b"}
    wrong_scope = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=FakeScopeGrants(),
        agent_harness=AgentHarnessService(engine),
        evidence=EvidenceService(engine),
        gold_set_path=FIXTURE,
    )
    blocked = _evaluate(
        wrong_scope,
        key="wrong-evidence-scope",
        methods=("canonical_graph",),
    )
    assert blocked["winner_status"] == "no_data"
    assert all(not question["results"][0]["eligible"] for question in blocked["questions"])

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        row.metadata_json = {**row.metadata_json, "tenant_ref": "tenant-a"}
        blob = session.get(EvidenceBlobRow, row.blob_sha256)
        blob.content_bytes = b"tampered"
    tampered = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=FakeScopeGrants(),
        agent_harness=AgentHarnessService(engine),
        evidence=EvidenceService(engine),
        gold_set_path=FIXTURE,
    )
    blocked = _evaluate(tampered, key="tampered", methods=("causal_temporal_graph",))
    assert blocked["winner_status"] == "no_data"
    assert all(not question["results"][0]["eligible"] for question in blocked["questions"])


def test_graph_missing_evidence_and_ambiguous_cycle_never_produce_an_eligible_winner(
    setup_workspace,
):
    workspace, _scope, _clock, engine, _record = setup_workspace
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        edge = session.get(GraphEdgeRow, "edge-fx-requires")
        edge.evidence_ref = None
        session.add(
            GraphEdgeRow(
                id="edge-fx-cycle",
                project_id="bas173-project",
                graph_kind="evidence",
                source_node_id="node-fx-claim",
                target_node_id="node-fx-question",
                edge_type="requires",
                derivation_method="inferred",
                confidence=50,
                evidence_ref=None,
                effective_from=now - timedelta(minutes=1),
                effective_until=None,
                content_sha256=_sha(["cycle"]),
            )
        )
    result = _evaluate(
        workspace,
        key="ambiguous-cycle",
        methods=("canonical_graph", "causal_temporal_graph"),
    )
    assert result["winner_status"] == "no_data"
    assert result["eligible_candidate_method_ids"] == []
    assert all(
        not method["eligible"]
        for question in result["questions"]
        for method in question["results"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["source", "grade", "gold_hash", "edge_hash", "authority"],
)
def test_graph_evidence_declared_hard_gate_drift_has_zero_eligible_winner(
    setup_workspace,
    mutation,
):
    _workspace, _scope, _clock, engine, record = setup_workspace
    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        if mutation == "source":
            row.source = "wrong-source"
        elif mutation == "grade":
            row.grade = EvidenceGrade.B.value
        else:
            metadata = dict(row.metadata_json)
            key = {
                "gold_hash": "retrieval_gold_set_sha256",
                "edge_hash": "graph_edge_content_sha256",
                "authority": "scope_grant_authority_sha256",
            }[mutation]
            metadata[key] = "f" * 64
            row.metadata_json = metadata
    workspace = GovernedRetrievalBenchmarkWorkspace(
        engine=engine,
        scope_grants=FakeScopeGrants(),
        agent_harness=AgentHarnessService(engine),
        evidence=EvidenceService(engine),
        gold_set_path=FIXTURE,
    )
    result = _evaluate(
        workspace,
        key=f"graph-evidence-{mutation}",
        methods=("canonical_graph", "causal_temporal_graph"),
    )
    assert result["winner_status"] == "no_data"
    assert result["eligible_candidate_method_ids"] == []
    assert all(
        method["status"] == "blocked"
        and method["claims"] == []
        and method["citations"] == []
        and method["eligible"] is False
        for question in result["questions"]
        for method in question["results"]
    )


def test_latency_rejects_nan_and_negative_values(setup_workspace):
    workspace, _scope, _clock, _engine, _record = setup_workspace
    question = workspace.gold_set.questions[0]
    raw = {
        "status": "no_data",
        "reason": "test",
        "claims": [],
        "citations": [],
        "scope_isolated": True,
        "valid_time_current": True,
    }
    with pytest.raises(RuntimeError, match="finite and non-negative"):
        workspace._grade_result(
            method_id="structured_sql",
            question=question,
            raw=raw,
            latency_ms=math.nan,
        )
    with pytest.raises(RuntimeError, match="finite and non-negative"):
        workspace._grade_result(
            method_id="structured_sql",
            question=question,
            raw=raw,
            latency_ms=-1,
        )
    for cost in (math.nan, -1):
        with pytest.raises(RuntimeError, match="cost must be finite and non-negative"):
            workspace._grade_result(
                method_id="structured_sql",
                question=question,
                raw={**raw, "cost_usd": cost},
                latency_ms=0,
            )


DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")


@pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL FTS contract requires KJDS_DATABASE_URL",
)
def test_postgresql_fts_uses_same_frozen_corpus_and_quality_tie_is_not_a_winner(
    tmp_path,
):
    schema = f"bas173_test_{uuid4().hex}"
    admin = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    engine = create_engine(url.set(query=query), pool_pre_ping=True)
    try:
        evidence, _record = _seed(engine)
        workspace = GovernedRetrievalBenchmarkWorkspace(
            engine=engine,
            scope_grants=FakeScopeGrants(),
            agent_harness=AgentHarnessService(engine),
            evidence=evidence,
            gold_set_path=FIXTURE,
        )
        result = _evaluate(
            workspace,
            key="postgres-fts",
            methods=("structured_sql", "postgresql_fts"),
        )
        assert result["winner_status"] == "UNKNOWN"
        assert result["winner_method_id"] is None
        assert result["eligible_candidate_method_ids"] == [
            "structured_sql",
            "postgresql_fts",
        ]
        assert {
            method["corpus_sha256"]
            for question in result["questions"]
            for method in question["results"]
        } == {workspace.gold_set.content_sha256}
        assert all(
            method["metrics"]["citation_correctness"] == 1.0
            for question in result["questions"]
            for method in question["results"]
        )
        replay = _evaluate(
            workspace,
            key="postgres-fts",
            methods=("structured_sql", "postgresql_fts"),
        )
        assert replay["observation_sha256"] == result["observation_sha256"]

        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["questions"][0]["query"] = (
            "profit'); DROP TABLE bas173_retrieval_corpus; --"
        )
        injection_fixture = tmp_path / "fts-injection.json"
        injection_fixture.write_text(
            json.dumps(_seal(payload)),
            encoding="utf-8",
        )
        injection_workspace = GovernedRetrievalBenchmarkWorkspace(
            engine=engine,
            scope_grants=FakeScopeGrants(),
            agent_harness=AgentHarnessService(engine),
            evidence=evidence,
            gold_set_path=injection_fixture,
        )
        injection = _evaluate(
            injection_workspace,
            key="postgres-fts-injection",
            methods=("postgresql_fts",),
        )
        injected_question = injection["questions"][0]
        assert injected_question["results"][0]["status"] == "no_data"
        assert injected_question["results"][0]["eligible"] is False
        follow_up = _evaluate(
            workspace,
            key="postgres-fts-follow-up",
            methods=("postgresql_fts",),
        )
        assert follow_up["questions"][0]["results"][0]["status"] == "answer"
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
