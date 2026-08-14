from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import text

from .agent_harness import AgentHarnessService
from .security import Principal

METHOD_IDS = (
    "structured_sql",
    "postgresql_fts",
    "canonical_graph",
    "causal_temporal_graph",
)
_GOLD_SET_FIELDS = {
    "contract_id",
    "gold_set_id",
    "version",
    "license_class",
    "contains_customer_data",
    "documents",
    "questions",
    "content_sha256",
}
_DOCUMENT_FIELDS = {
    "document_id",
    "scope_binding",
    "claim_code",
    "search_text",
    "citation_ref",
    "citation_sha256",
    "effective_from",
    "effective_until",
    "recorded_at",
    "evidence_state",
}
_QUESTION_FIELDS = {
    "question_id",
    "category",
    "query",
    "required_terms",
    "graph_edge_types",
    "expected_outcome",
    "expected_claim_codes",
    "expected_citation_refs",
    "question_sha256",
}
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "body",
        "prompt",
        "raw",
        "secret",
        "password",
        "api_key",
        "access_token",
        "email",
        "phone",
        "customer_name",
    }
)
_SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)


class RetrievalBenchmarkContractError(ValueError):
    pass


class RetrievalBenchmarkConflictError(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _timestamp(value: str | datetime, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RetrievalBenchmarkContractError(
                f"{field} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise RetrievalBenchmarkContractError(f"{field} must include timezone")
    return parsed.astimezone(UTC)


def _stored_timestamp(value: str, *, field: str) -> datetime:
    """Read UTC-normalized database timestamps (SQLite drops tz metadata)."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetrievalBenchmarkContractError(
            f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _assert_no_sensitive_payload(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                raise RetrievalBenchmarkContractError(
                    f"gold set contains prohibited field at {path}.{key}"
                )
            _assert_no_sensitive_payload(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_payload(item, path=f"{path}[{index}]")
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in _SENSITIVE_PATTERNS
    ):
        raise RetrievalBenchmarkContractError(
            f"gold set contains prohibited sensitive value at {path}"
        )


class RetrievalGoldSet:
    CONTRACT_ID = "kjds-retrieval-gold-set-v1"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.gold_set_id = payload["gold_set_id"]
        self.version = payload["version"]
        self.content_sha256 = payload["content_sha256"]
        self.documents = tuple(payload["documents"])
        self.questions = tuple(payload["questions"])
        self.citation_sha256_by_ref = {
            document["citation_ref"]: document["citation_sha256"]
            for document in self.documents
            if document["scope_binding"] == "exact"
        }

    @property
    def ref(self) -> str:
        return f"{self.gold_set_id}:{self.version}:{self.content_sha256}"

    @classmethod
    def load(cls, path: str | Path) -> RetrievalGoldSet:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RetrievalBenchmarkContractError(
                "gold set is unreadable or invalid JSON"
            ) from exc
        if not isinstance(payload, dict) or set(payload) != _GOLD_SET_FIELDS:
            raise RetrievalBenchmarkContractError("gold set fields do not match")
        if payload["contract_id"] != cls.CONTRACT_ID:
            raise RetrievalBenchmarkContractError("unknown gold set contract")
        if payload["license_class"] != "repository_owned_synthetic_contract_fixture":
            raise RetrievalBenchmarkContractError("gold set license is not permitted")
        if payload["contains_customer_data"] is not False:
            raise RetrievalBenchmarkContractError("customer data is prohibited")
        if not isinstance(payload["documents"], list) or not isinstance(
            payload["questions"], list
        ):
            raise RetrievalBenchmarkContractError(
                "gold set documents and questions must be lists"
            )
        if not payload["documents"] or not payload["questions"]:
            raise RetrievalBenchmarkContractError("gold set cannot be empty")
        _assert_no_sensitive_payload(payload)

        document_ids: set[str] = set()
        citation_refs: set[str] = set()
        exact_citation_refs: set[str] = set()
        for document in payload["documents"]:
            cls._validate_document(document)
            if document["document_id"] in document_ids:
                raise RetrievalBenchmarkContractError("duplicate document_id")
            if document["citation_ref"] in citation_refs:
                raise RetrievalBenchmarkContractError("duplicate citation_ref")
            document_ids.add(document["document_id"])
            citation_refs.add(document["citation_ref"])
            if document["scope_binding"] == "exact":
                exact_citation_refs.add(document["citation_ref"])

        question_ids: set[str] = set()
        for question in payload["questions"]:
            cls._validate_question(
                question,
                citation_refs=citation_refs,
                exact_citation_refs=exact_citation_refs,
            )
            if question["question_id"] in question_ids:
                raise RetrievalBenchmarkContractError("duplicate question_id")
            question_ids.add(question["question_id"])

        unsigned = dict(payload)
        unsigned.pop("content_sha256")
        if payload["content_sha256"] != _sha(unsigned):
            raise RetrievalBenchmarkContractError("gold set hash drift detected")
        return cls(payload)

    @staticmethod
    def _validate_document(document: Any) -> None:
        if not isinstance(document, dict) or set(document) != _DOCUMENT_FIELDS:
            raise RetrievalBenchmarkContractError("document fields do not match")
        required_text = (
            "document_id",
            "claim_code",
            "search_text",
            "citation_ref",
            "citation_sha256",
            "effective_from",
            "recorded_at",
            "evidence_state",
        )
        if any(not isinstance(document[field], str) or not document[field] for field in required_text):
            raise RetrievalBenchmarkContractError("document string field is empty")
        if document["scope_binding"] not in {
            "exact",
            "tenant_other",
            "entity_other",
            "store_other",
            "authority_other",
        }:
            raise RetrievalBenchmarkContractError("unknown document scope_binding")
        if document["evidence_state"] not in {"current", "stale", "revoked"}:
            raise RetrievalBenchmarkContractError("unknown document evidence_state")
        effective_from = _timestamp(document["effective_from"], field="effective_from")
        _timestamp(document["recorded_at"], field="recorded_at")
        effective_until = (
            _timestamp(document["effective_until"], field="effective_until")
            if document["effective_until"] is not None
            else None
        )
        if effective_until is not None and effective_until <= effective_from:
            raise RetrievalBenchmarkContractError("invalid document effective interval")
        citation_input = {
            "citation_ref": document["citation_ref"],
            "claim_code": document["claim_code"],
            "search_text": document["search_text"],
        }
        if document["citation_sha256"] != _sha(citation_input):
            raise RetrievalBenchmarkContractError("document citation hash drift")

    @staticmethod
    def _validate_question(
        question: Any,
        *,
        citation_refs: set[str],
        exact_citation_refs: set[str],
    ) -> None:
        if not isinstance(question, dict) or set(question) != _QUESTION_FIELDS:
            raise RetrievalBenchmarkContractError("question fields do not match")
        if any(
            not isinstance(question[field], str) or not question[field]
            for field in ("question_id", "category", "query", "expected_outcome")
        ):
            raise RetrievalBenchmarkContractError("question string field is empty")
        for field in (
            "required_terms",
            "graph_edge_types",
            "expected_claim_codes",
            "expected_citation_refs",
        ):
            values = question[field]
            if not isinstance(values, list) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise RetrievalBenchmarkContractError(
                    f"{field} must be a string list"
                )
            if len(values) != len(set(values)):
                raise RetrievalBenchmarkContractError(f"duplicate value in {field}")
        if question["expected_outcome"] not in {"answer", "UNKNOWN", "no_data"}:
            raise RetrievalBenchmarkContractError("unknown expected_outcome")
        if question["expected_outcome"] in {"answer", "UNKNOWN"} and (
            not question["expected_claim_codes"]
            or not question["expected_citation_refs"]
        ):
            raise RetrievalBenchmarkContractError(
                "answer question requires claims and citations"
            )
        if question["expected_outcome"] == "no_data" and (
            question["expected_claim_codes"]
            or question["expected_citation_refs"]
        ):
            raise RetrievalBenchmarkContractError(
                "no_data question cannot contain an answer key"
            )
        if not set(question["expected_citation_refs"]) <= citation_refs:
            raise RetrievalBenchmarkContractError("question cites unknown document")
        if not set(question["expected_citation_refs"]) <= exact_citation_refs:
            raise RetrievalBenchmarkContractError(
                "question answer key cites non-exact-scope document"
            )
        unsigned = dict(question)
        unsigned.pop("question_sha256")
        if question["question_sha256"] != _sha(unsigned):
            raise RetrievalBenchmarkContractError("question hash drift detected")


class GovernedRetrievalBenchmarkWorkspace:
    """Deep Module for exact-scope, citation-required retrieval evaluation."""

    CONTRACT_ID = "kjds-retrieval-benchmark-observation-v1"

    def __init__(
        self,
        *,
        engine,
        scope_grants,
        agent_harness: AgentHarnessService,
        evidence,
        gold_set_path: str | Path,
        clock=None,
    ) -> None:
        self.engine = engine
        self.scope_grants = scope_grants
        self.agent_harness = agent_harness
        self.evidence = evidence
        self.clock = clock or (lambda: datetime.now(UTC))
        self.gold_set = RetrievalGoldSet.load(gold_set_path)
        self._lock = threading.RLock()
        self._runs: dict[
            tuple[str, str, str, str, str, str],
            tuple[str, dict[str, Any]],
        ] = {}

    @property
    def gold_set_ref(self) -> str:
        return self.gold_set.ref

    def evaluate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        project_id: str,
        as_of: datetime,
        gold_set_ref: str,
        method_ids: tuple[str, ...] = METHOD_IDS,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "monitor", "admin", "reviewer"):
            raise PermissionError("retrieval benchmark read role required")
        if not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")
        cutoff = _timestamp(as_of, field="as_of")
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            raise RetrievalBenchmarkContractError("idempotency_key is required")
        if gold_set_ref != self.gold_set.ref:
            raise RetrievalBenchmarkContractError("gold_set_ref hash drift detected")
        selected_methods = tuple(dict.fromkeys(method_ids))
        if not selected_methods or any(method not in METHOD_IDS for method in selected_methods):
            raise RetrievalBenchmarkContractError("unknown retrieval method")
        if len(selected_methods) != len(method_ids):
            raise RetrievalBenchmarkContractError("duplicate retrieval method")

        authority_checked_at = _timestamp(
            self.clock(),
            field="authority_checked_at",
        )
        entity_scope = self.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=authority_checked_at,
        )
        scope_status = str(entity_scope.get("status", "no_data"))
        exact_scope = self._exact_scope(
            principal=principal,
            store_ref=store_ref,
            entity_scope=entity_scope,
        )
        entity_ref = entity_scope.get("entity_ref") if exact_scope else "unbound"
        scope_key = (
            principal.tenant_ref,
            str(entity_ref),
            store_ref,
            str(entity_scope.get("authority_sha256") or "unbound"),
            principal.actor_id,
            idempotency_key,
        )
        request = {
            "contract_id": self.CONTRACT_ID,
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_scope.get("entity_ref") if exact_scope else None,
            "store_ref": store_ref,
            "actor_id": principal.actor_id,
            "scope_grant_authority_sha256": (
                entity_scope.get("authority_sha256") if exact_scope else None
            ),
            "project_id": project_id,
            "as_of": cutoff.isoformat(),
            "authority_checked_at": authority_checked_at.isoformat(),
            "gold_set_ref": gold_set_ref,
            "method_ids": list(selected_methods),
            "idempotency_key_sha256": _sha(idempotency_key),
        }
        request_sha256 = _sha(
            {
                key: value
                for key, value in request.items()
                if key != "authority_checked_at"
            }
        )
        with self._lock:
            prior = self._runs.get(scope_key)
            if prior is not None:
                prior_sha256, prior_observation = prior
                if prior_sha256 != request_sha256:
                    raise RetrievalBenchmarkConflictError(
                        "idempotency key conflicts with immutable benchmark run"
                    )
                return json.loads(_canonical(prior_observation))

            if not exact_scope:
                observation = self._blocked_observation(
                    request=request,
                    request_sha256=request_sha256,
                    scope_status=scope_status,
                    reason="exact_current_scope_authority_required",
                )
            else:
                observation = self._evaluate_ready(
                    request=request,
                    request_sha256=request_sha256,
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    project_id=project_id,
                    as_of=cutoff,
                    method_ids=selected_methods,
                )
            self._runs[scope_key] = (request_sha256, observation)
            return json.loads(_canonical(observation))

    @staticmethod
    def _exact_scope(
        *,
        principal: Principal,
        store_ref: str,
        entity_scope: dict[str, Any],
    ) -> bool:
        authority = entity_scope.get("authority_sha256")
        entity_ref = entity_scope.get("entity_ref")
        return (
            entity_scope.get("status") == "ready"
            and entity_scope.get("tenant_ref") == principal.tenant_ref
            and entity_scope.get("store_ref") == store_ref
            and isinstance(entity_ref, str)
            and bool(entity_ref)
            and isinstance(authority, str)
            and len(authority) == 64
            and all(character in "0123456789abcdef" for character in authority.lower())
        )

    def _blocked_observation(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        scope_status: str,
        reason: str,
    ) -> dict[str, Any]:
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": "blocked" if scope_status == "blocked" else "no_data",
            "reason": reason,
            "run_id": f"rbr_{request_sha256[:32]}",
            "request_sha256": request_sha256,
            "scope": {
                "tenant_ref": request["tenant_ref"],
                "entity_ref": None,
                "store_ref": request["store_ref"],
                "scope_grant_authority_sha256": None,
            },
            "as_of": request["as_of"],
            "authority_checked_at": request["authority_checked_at"],
            "gold_set_ref": request["gold_set_ref"],
            "method_ids": request["method_ids"],
            "questions": [],
            "method_summary": [],
            "winner_status": "no_data",
            "winner_method_id": None,
            "human_review_seconds": None,
            "human_review_status": "UNKNOWN",
            "not_admitted_methods": ["pgvector", "GraphRAG"],
            "observation_only": True,
            "generated_edges_are_observations": True,
            "formal_fact_allowed": False,
            "finance_entry_allowed": False,
            "approval_allowed": False,
            "permit_allowed": False,
            "pilot_allowed": False,
            "outbox_allowed": False,
            "external_write_allowed": False,
        }
        observation["observation_sha256"] = _sha(observation)
        return observation

    def _evaluate_ready(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        project_id: str,
        as_of: datetime,
        method_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_scope["entity_ref"],
            "store_ref": store_ref,
            "scope_grant_authority_sha256": entity_scope["authority_sha256"],
        }
        graph_projection = None
        if {"canonical_graph", "causal_temporal_graph"}.intersection(method_ids):
            graph_projection = self.agent_harness.temporal_graph_projection(
                project_id,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
                graph_kind="evidence",
            )
            graph_projection = self._validate_graph_evidence(
                graph_projection,
                scope=scope,
                as_of=as_of,
            )

        documents = self._materialize_documents(scope)
        question_items: list[dict[str, Any]] = []
        sql_methods = {"structured_sql", "postgresql_fts"}.intersection(method_ids)
        connection_context = self.engine.begin() if sql_methods else None
        if connection_context is not None:
            connection = connection_context.__enter__()
            try:
                self._create_corpus(connection, documents)
                question_items = self._evaluate_questions(
                    connection=connection,
                    graph_projection=graph_projection,
                    method_ids=method_ids,
                    scope=scope,
                    as_of=as_of,
                )
                self._drop_corpus(connection)
            except BaseException:
                connection_context.__exit__(*__import__("sys").exc_info())
                raise
            else:
                connection_context.__exit__(None, None, None)
        else:
            question_items = self._evaluate_questions(
                connection=None,
                graph_projection=graph_projection,
                method_ids=method_ids,
                scope=scope,
                as_of=as_of,
            )

        summaries = [
            self._summarize_method(method_id, question_items)
            for method_id in method_ids
        ]
        globally_eligible = [
            summary for summary in summaries if summary["all_questions_eligible"]
        ]
        winner_status = "UNKNOWN" if globally_eligible else "no_data"
        winner_method_id = None
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready",
            "reason": None,
            "run_id": f"rbr_{request_sha256[:32]}",
            "request_sha256": request_sha256,
            "scope": scope,
            "as_of": request["as_of"],
            "authority_checked_at": request["authority_checked_at"],
            "gold_set_ref": request["gold_set_ref"],
            "method_ids": request["method_ids"],
            "questions": question_items,
            "method_summary": summaries,
            "winner_status": winner_status,
            "winner_method_id": winner_method_id,
            "winner_reason": (
                "signed_cost_latency_threshold_and_independent_review_missing"
                if globally_eligible
                else "no_method_passed_all_hard_gates"
            ),
            "eligible_candidate_method_ids": [
                item["method_id"] for item in globally_eligible
            ],
            "human_review_seconds": None,
            "human_review_status": "UNKNOWN",
            "not_admitted_methods": ["pgvector", "GraphRAG"],
            "observation_only": True,
            "generated_edges_are_observations": True,
            "formal_fact_allowed": False,
            "finance_entry_allowed": False,
            "approval_allowed": False,
            "permit_allowed": False,
            "pilot_allowed": False,
            "outbox_allowed": False,
            "external_write_allowed": False,
        }
        observation["observation_sha256"] = _sha(observation)
        return observation

    def _validate_graph_evidence(
        self,
        projection: dict[str, Any],
        *,
        scope: dict[str, str],
        as_of: datetime,
    ) -> dict[str, Any]:
        """Fail closed unless every eligible Graph edge has current exact Evidence."""

        validated = json.loads(_canonical(projection))
        if validated.get("status") != "ready":
            return validated
        valid_count = 0
        for edge in validated["edges"]:
            if not edge["eligible_for_retrieval"]:
                continue
            blockers = edge["blockers"]
            evidence_id = str(edge.get("evidence_ref") or "").strip()
            try:
                record, verification = self.evidence.inspect_integrity(evidence_id)
                effective_at = _stored_timestamp(
                    record.effective_at,
                    field="evidence.effective_at",
                )
                effective_until = (
                    _stored_timestamp(
                        record.effective_until,
                        field="evidence.effective_until",
                    )
                    if record.effective_until
                    else None
                )
                recorded_at = _stored_timestamp(
                    record.recorded_at,
                    field="evidence.recorded_at",
                )
                metadata = record.metadata
                exact_binding = (
                    record.source == "retrieval-benchmark-fixture"
                    and metadata.get("retrieval_source_contract_id")
                    == RetrievalGoldSet.CONTRACT_ID
                    and metadata.get("tenant_ref") == scope["tenant_ref"]
                    and metadata.get("entity_ref") == scope["entity_ref"]
                    and metadata.get("store_ref") == scope["store_ref"]
                    and metadata.get("scope_grant_authority_sha256")
                    == scope["scope_grant_authority_sha256"]
                    and metadata.get("graph_edge_content_sha256")
                    == edge["content_sha256"]
                    and metadata.get("retrieval_gold_set_sha256")
                    == self.gold_set.content_sha256
                )
                current = (
                    recorded_at <= as_of
                    and effective_at <= as_of
                    and (effective_until is None or as_of < effective_until)
                )
                grade = getattr(record.grade, "value", str(record.grade))
                if not verification.valid:
                    blockers.append("edge_evidence_hash_invalid")
                if not exact_binding:
                    blockers.append("edge_evidence_exact_scope_binding_invalid")
                if recorded_at > as_of:
                    blockers.append("edge_evidence_future_recorded")
                elif not current:
                    blockers.append("edge_evidence_not_current_as_of")
                if grade != "A":
                    blockers.append("edge_evidence_grade_a_required")
                if not blockers:
                    edge["evidence_sha256"] = record.sha256
                    edge["citation_ref"] = record.source_ref
                    edge["evidence_recorded_at"] = recorded_at.isoformat()
                    valid_count += 1
            except (KeyError, RuntimeError, ValueError, TypeError):
                blockers.append("edge_evidence_invalid")
            edge["eligible_for_retrieval"] = not blockers
        if valid_count == 0:
            validated["status"] = "blocked"
            validated["reason"] = "no_exact_current_evidence_backed_edge"
        validated["snapshot_sha256"] = _sha(
            {key: value for key, value in validated.items() if key != "snapshot_sha256"}
        )
        return validated

    def _evaluate_questions(
        self,
        *,
        connection,
        graph_projection: dict[str, Any] | None,
        method_ids: tuple[str, ...],
        scope: dict[str, str],
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for question in self.gold_set.questions:
            results: list[dict[str, Any]] = []
            for method_id in method_ids:
                started = perf_counter()
                if method_id == "structured_sql":
                    raw = self._structured_sql(
                        connection, question=question, scope=scope, as_of=as_of
                    )
                elif method_id == "postgresql_fts":
                    raw = self._postgresql_fts(
                        connection, question=question, scope=scope, as_of=as_of
                    )
                else:
                    raw = self._graph_retrieval(
                        graph_projection,
                        question=question,
                        causal=method_id == "causal_temporal_graph",
                    )
                latency_ms = (perf_counter() - started) * 1000
                result = self._grade_result(
                    method_id=method_id,
                    question=question,
                    raw=raw,
                    latency_ms=latency_ms,
                )
                results.append(result)
            eligible = [result for result in results if result["eligible"]]
            if len(eligible) == 1:
                winner = {
                    "status": "UNKNOWN",
                    "method_id": None,
                    "reason": "signed_cost_latency_threshold_and_independent_review_missing",
                }
            elif len(eligible) > 1:
                winner = {
                    "status": "UNKNOWN",
                    "method_id": None,
                    "reason": "quality_tie_requires_signed_cost_latency_threshold",
                }
            else:
                winner = {
                    "status": "no_data",
                    "method_id": None,
                    "reason": "no_eligible_method",
                }
            items.append(
                {
                    "question_id": question["question_id"],
                    "category": question["category"],
                    "question_sha256": question["question_sha256"],
                    "expected_outcome": question["expected_outcome"],
                    "results": results,
                    "winner": winner,
                }
            )
        return items

    def _materialize_documents(self, scope: dict[str, str]) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for source in self.gold_set.documents:
            row = {
                **source,
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
                "authority_sha256": scope["scope_grant_authority_sha256"],
            }
            binding = source["scope_binding"]
            if binding == "tenant_other":
                row["tenant_ref"] = "fixture-tenant-other"
            elif binding == "entity_other":
                row["entity_ref"] = "fixture-entity-other"
            elif binding == "store_other":
                row["store_ref"] = "fixture-store-other"
            elif binding == "authority_other":
                row["authority_sha256"] = "f" * 64
            documents.append(row)
        return documents

    @staticmethod
    def _create_corpus(connection, documents: list[dict[str, Any]]) -> None:
        suffix = " ON COMMIT DROP" if connection.dialect.name == "postgresql" else ""
        connection.execute(text("DROP TABLE IF EXISTS bas173_retrieval_corpus"))
        connection.execute(
            text(
                "CREATE TEMPORARY TABLE bas173_retrieval_corpus ("
                "document_id TEXT NOT NULL, tenant_ref TEXT NOT NULL, "
                "entity_ref TEXT NOT NULL, store_ref TEXT NOT NULL, "
                "authority_sha256 TEXT NOT NULL, claim_code TEXT NOT NULL, "
                "search_text TEXT NOT NULL, citation_ref TEXT NOT NULL, "
                "citation_sha256 TEXT NOT NULL, effective_from TEXT NOT NULL, "
                "effective_until TEXT NULL, recorded_at TEXT NOT NULL, "
                "evidence_state TEXT NOT NULL)"
                + suffix
            )
        )
        connection.execute(
            text(
                "INSERT INTO bas173_retrieval_corpus ("
                "document_id, tenant_ref, entity_ref, store_ref, authority_sha256, "
                "claim_code, search_text, citation_ref, citation_sha256, "
                "effective_from, effective_until, recorded_at, evidence_state) VALUES ("
                ":document_id, :tenant_ref, :entity_ref, :store_ref, :authority_sha256, "
                ":claim_code, :search_text, :citation_ref, :citation_sha256, "
                ":effective_from, :effective_until, :recorded_at, :evidence_state)"
            ),
            documents,
        )

    @staticmethod
    def _drop_corpus(connection) -> None:
        connection.execute(text("DROP TABLE IF EXISTS bas173_retrieval_corpus"))

    @staticmethod
    def _scope_predicate() -> str:
        return (
            "tenant_ref = :tenant_ref AND entity_ref = :entity_ref "
            "AND store_ref = :store_ref AND authority_sha256 = :authority_sha256 "
            "AND effective_from <= :as_of "
            "AND (effective_until IS NULL OR effective_until > :as_of) "
            "AND recorded_at <= :as_of "
            "AND evidence_state = 'current'"
        )

    def _structured_sql(
        self,
        connection,
        *,
        question: dict[str, Any],
        scope: dict[str, str],
        as_of: datetime,
    ) -> dict[str, Any]:
        params = {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "authority_sha256": scope["scope_grant_authority_sha256"],
            "as_of": as_of.isoformat(),
        }
        terms = []
        for index, term in enumerate(question["required_terms"]):
            key = f"term_{index}"
            params[key] = f"%{term.lower()}%"
            terms.append(f"lower(search_text) LIKE :{key}")
        term_sql = " AND ".join(terms) if terms else "1 = 1"
        rows = connection.execute(
            text(
                "SELECT document_id, claim_code, citation_ref, citation_sha256, "
                "effective_from, effective_until FROM bas173_retrieval_corpus WHERE "
                + self._scope_predicate()
                + " AND "
                + term_sql
                + " ORDER BY document_id"
            ),
            params,
        ).mappings()
        return self._rows_result(list(rows))

    def _postgresql_fts(
        self,
        connection,
        *,
        question: dict[str, Any],
        scope: dict[str, str],
        as_of: datetime,
    ) -> dict[str, Any]:
        if connection.dialect.name != "postgresql":
            return {
                "status": "not_run",
                "reason": "postgresql_fts_unavailable",
                "claims": [],
                "citations": [],
                "scope_isolated": True,
                "valid_time_current": True,
            }
        params = {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "authority_sha256": scope["scope_grant_authority_sha256"],
            "as_of": as_of.isoformat(),
            "query": question["query"],
        }
        rows = connection.execute(
            text(
                "SELECT document_id, claim_code, citation_ref, citation_sha256, "
                "effective_from, effective_until, "
                "ts_rank_cd(to_tsvector('simple', search_text), "
                "plainto_tsquery('simple', :query)) AS rank "
                "FROM bas173_retrieval_corpus WHERE "
                + self._scope_predicate()
                + " AND to_tsvector('simple', search_text) @@ "
                "plainto_tsquery('simple', :query) "
                "ORDER BY rank DESC, document_id"
            ),
            params,
        ).mappings()
        return self._rows_result(list(rows))

    @staticmethod
    def _rows_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
        claims = sorted({str(row["claim_code"]) for row in rows})
        citations = sorted(
            (
                {
                    "ref": str(row["citation_ref"]),
                    "sha256": str(row["citation_sha256"]),
                    "effective_from": str(row["effective_from"]),
                    "effective_until": (
                        str(row["effective_until"])
                        if row["effective_until"] is not None
                        else None
                    ),
                }
                for row in rows
            ),
            key=lambda item: item["ref"],
        )
        if not rows:
            status = "no_data"
        elif claims and all(claim.startswith("UNKNOWN:") for claim in claims):
            status = "UNKNOWN"
        else:
            status = "answer"
        return {
            "status": status,
            "reason": None if rows else "no_exact_current_citation",
            "claims": claims,
            "citations": citations,
            "scope_isolated": True,
            "valid_time_current": True,
        }

    @staticmethod
    def _graph_retrieval(
        projection: dict[str, Any] | None,
        *,
        question: dict[str, Any],
        causal: bool,
    ) -> dict[str, Any]:
        if projection is None:
            return {
                "status": "no_data",
                "reason": "canonical_graph_projection_missing",
                "claims": [],
                "citations": [],
                "scope_isolated": False,
                "valid_time_current": False,
            }
        if projection["status"] != "ready":
            return {
                "status": projection["status"],
                "reason": projection["reason"],
                "claims": [],
                "citations": [],
                "scope_isolated": projection["status"] != "blocked",
                "valid_time_current": projection["reason"]
                not in {"no_valid_edges_as_of"},
            }
        nodes = {node["id"]: node for node in projection["nodes"]}
        claims: set[str] = set()
        citations: dict[str, dict[str, Any]] = {}
        for edge in projection["edges"]:
            if not edge["eligible_for_retrieval"]:
                continue
            if edge["type"] not in question["graph_edge_types"]:
                continue
            if causal and edge["derivation"] not in {
                "declared",
                "runtime",
                "evidence",
            }:
                continue
            target = nodes.get(edge["target"])
            if target is None or not target["stable_key"].startswith("claim:"):
                continue
            claim_code = target["stable_key"].removeprefix("claim:")
            claims.add(claim_code)
            citations[str(edge["citation_ref"])] = {
                "ref": str(edge["citation_ref"]),
                "sha256": edge["evidence_sha256"],
                "effective_from": edge["effective_from"],
                "effective_until": edge["effective_until"],
            }
        if not claims:
            status = "no_data"
        elif all(claim.startswith("UNKNOWN:") for claim in claims):
            status = "UNKNOWN"
        else:
            status = "answer"
        return {
            "status": status,
            "reason": None if claims else "no_exact_current_citation",
            "claims": sorted(claims),
            "citations": [citations[key] for key in sorted(citations)],
            "scope_isolated": True,
            "valid_time_current": True,
        }

    def _grade_result(
        self,
        *,
        method_id: str,
        question: dict[str, Any],
        raw: dict[str, Any],
        latency_ms: float,
    ) -> dict[str, Any]:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise RuntimeError("retrieval latency must be finite and non-negative")
        cost_usd = float(raw.get("cost_usd", 0.0))
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise RuntimeError("retrieval cost must be finite and non-negative")
        claims = set(raw["claims"])
        expected_claims = set(question["expected_claim_codes"])
        citation_pairs = {
            (item["ref"], item["sha256"]) for item in raw["citations"]
        }
        expected_citations = set(question["expected_citation_refs"])
        expected_pairs = {
            (ref, self.gold_set.citation_sha256_by_ref[ref])
            for ref in expected_citations
        }
        unsupported = claims - expected_claims
        wrong_citations = citation_pairs - expected_pairs
        citation_correctness = (
            (len(citation_pairs) - len(wrong_citations)) / len(citation_pairs)
            if citation_pairs
            else (1.0 if not expected_pairs else 0.0)
        )
        citation_completeness = (
            len(citation_pairs & expected_pairs) / len(expected_pairs)
            if expected_pairs
            else 1.0
        )
        unsupported_rate = len(unsupported) / len(claims) if claims else 0.0
        expected_outcome = question["expected_outcome"]
        abstention_correct = raw["status"] == expected_outcome
        outcome_correct = (
            raw["status"] == expected_outcome
            and claims == expected_claims
            and citation_pairs == expected_pairs
        )
        eligible = (
            outcome_correct
            and citation_correctness == 1.0
            and citation_completeness == 1.0
            and unsupported_rate == 0.0
            and raw["scope_isolated"] is True
            and raw["valid_time_current"] is True
        )
        return {
            "method_id": method_id,
            "corpus_sha256": self.gold_set.content_sha256,
            "status": raw["status"],
            "reason": raw["reason"],
            "claims": sorted(claims),
            "citations": raw["citations"],
            "metrics": {
                "citation_correctness": round(citation_correctness, 6),
                "citation_completeness": round(citation_completeness, 6),
                "exact_scope_isolation": raw["scope_isolated"],
                "valid_time_currentness": raw["valid_time_current"],
                "abstention_correct": abstention_correct,
                "unsupported_claim_rate": round(unsupported_rate, 6),
                "latency_ms": round(latency_ms, 6),
                "cost_usd": f"{cost_usd:.6f}",
                "cost_basis": "deterministic_local_retrieval_no_provider_charge",
                "human_review_seconds": None,
                "human_review_status": "UNKNOWN",
            },
            "eligible": eligible,
            "generated_edges": [],
            "observation_only": True,
        }

    @staticmethod
    def _summarize_method(
        method_id: str,
        questions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        results = [
            next(result for result in question["results"] if result["method_id"] == method_id)
            for question in questions
        ]
        count = len(results)
        return {
            "method_id": method_id,
            "question_count": count,
            "eligible_question_count": sum(result["eligible"] for result in results),
            "all_questions_eligible": all(result["eligible"] for result in results),
            "citation_correctness": round(
                sum(result["metrics"]["citation_correctness"] for result in results) / count,
                6,
            ),
            "citation_completeness": round(
                sum(result["metrics"]["citation_completeness"] for result in results) / count,
                6,
            ),
            "unsupported_claim_rate": round(
                sum(result["metrics"]["unsupported_claim_rate"] for result in results) / count,
                6,
            ),
            "total_latency_ms": round(
                sum(result["metrics"]["latency_ms"] for result in results),
                6,
            ),
            "total_cost_usd": "0.000000",
            "human_review_seconds": None,
            "human_review_status": "UNKNOWN",
        }
