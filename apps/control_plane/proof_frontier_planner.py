"""Pure planning functions for the two-layer proof/business graph.

The canonical Harness graph already exposes nodes, edges and task
dependencies.  This module deliberately consumes that read projection rather
than opening a database or creating another authority.  It turns the graph
into a small, deterministic planning projection:

``PROVEN -> frontier -> blockers -> critical path``

The implementation accepts both the canonical ``nodes``/``edges`` shape and
the convenient ``theorem_nodes``/``business_nodes`` shape.  It never mutates
the supplied mapping and never performs an external action.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

PROVEN = "PROVEN"
BLOCKED = "BLOCKED"
STALE = "STALE"
NO_DATA = "NO_DATA"
PROOF_STATES = (PROVEN, BLOCKED, STALE, NO_DATA)
ProofState = Literal["PROVEN", "BLOCKED", "STALE", "NO_DATA"]


class ProofFrontierError(ValueError):
    """Raised when a graph cannot be interpreted as a graph projection."""


class ProofFrontierContractError(ProofFrontierError):
    """Raised for malformed graph input or an invalid public argument."""


_STATE_ALIASES: dict[str, ProofState] = {
    "proven": PROVEN,
    "proof": PROVEN,
    "verified": PROVEN,
    "passed": PROVEN,
    "succeeded": PROVEN,
    "success": PROVEN,
    "complete": PROVEN,
    "completed": PROVEN,
    "done": PROVEN,
    "ready": PROVEN,
    "admitted": PROVEN,
    "active": PROVEN,
    "blocked": BLOCKED,
    "failed": BLOCKED,
    "denied": BLOCKED,
    "rejected": BLOCKED,
    "conflicted": BLOCKED,
    "invalidated": BLOCKED,
    "error": BLOCKED,
    "stale": STALE,
    "expired": STALE,
    "outdated": STALE,
    "superseded": STALE,
    "no_data": NO_DATA,
    "nodata": NO_DATA,
    "unknown": NO_DATA,
    "unknown_outcome": NO_DATA,
    "pending": NO_DATA,
    "running": NO_DATA,
    "missing": NO_DATA,
    "not_started": NO_DATA,
    "not_visible": NO_DATA,
    "partial": NO_DATA,
    "unavailable": NO_DATA,
    "ready_for_dispatch": NO_DATA,
}

_GOVERNANCE_FIELDS = (
    "proof_state",
    "evidence_state",
    "operational_state",
    "economic_state",
    "rollback_available",
)
_PROOF_GATE_STATES = frozenset({"PROVED", "UNPROVED", "STALE", "BLOCKED", "NO_DATA"})
_EVIDENCE_GATE_STATES = frozenset(
    {"VALID", "PARTIAL", "STALE", "BLOCKED", "NO_DATA", "UNKNOWN_OUTCOME"}
)
_OPERATIONAL_GATE_STATES = frozenset({"LIVE", "SHADOW", "PAUSED", "BLOCKED", "UNKNOWN"})
_ECONOMIC_GATE_STATES = frozenset({"ALLOWED", "AT_RISK", "BLOCKED", "UNKNOWN"})

_THEOREM_KINDS = frozenset(
    {
        "theorem",
        "claim",
        "proof",
        "proof_obligation",
        "obligation",
        "requirement",
        "invariant",
        "gate",
        "goal",
        "hypothesis",
    }
)
_BUSINESS_KINDS = frozenset(
    {
        "business",
        "task",
        "action",
        "capability",
        "operation",
        "process",
        "workflow",
        "milestone",
        "listing",
        "order",
        "evidence",
        "fact",
    }
)

# Relations whose source is the prerequisite of the target.
_SOURCE_PREREQUISITE_RELATIONS = frozenset(
    {
        "precedes",
        "supports",
        "proves",
        "satisfies",
        "implements",
        "enables",
        "feeds",
        "parent_of",
        "contains",
        "upstream",
        "blocks",
        "blocked_by_source",
        "derived_from_source",
    }
)
# Relations whose source depends on the target.
_TARGET_PREREQUISITE_RELATIONS = frozenset(
    {
        "depends_on",
        "dependency",
        "depends",
        "requires",
        "needs",
        "uses",
        "based_on",
        "derived_from",
        "blocked_by",
        "downstream_of",
    }
)
_INVALIDATES_RELATIONS = frozenset({"invalidates", "invalidating", "supersedes"})
_INVALIDATED_BY_RELATIONS = frozenset({"invalidated_by", "superseded_by"})


@dataclass(frozen=True, slots=True)
class _Node:
    node_id: str
    layer: str
    raw: Mapping[str, Any]
    direct_state: ProofState
    direct_reasons: tuple[str, ...]
    weight: float
    priority: float
    governance: _GovernanceState | None = None


@dataclass(frozen=True, slots=True)
class _GovernanceState:
    """Optional four-state admission projection for a graph node.

    Legacy Harness nodes do not carry these fields and remain governed by the
    original proof-state planner.  Once any governance field is supplied, the
    node enters the explicit admission contract and missing gates fail closed.
    """

    proof_state: str | None
    evidence_state: str | None
    operational_state: str | None
    economic_state: str | None
    rollback_available: bool | None
    admission_state: str


@dataclass(frozen=True, slots=True)
class _Edge:
    edge_id: str
    source: str
    target: str
    relation: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _Graph:
    nodes: dict[str, _Node]
    edges: tuple[_Edge, ...]
    dependencies: dict[str, frozenset[str]]
    proof_dependencies: dict[str, frozenset[str]]
    invalidations: dict[str, frozenset[str]]
    errors: tuple[str, ...]
    root: Mapping[str, Any]
    as_of: datetime | None


def _jsonable(value: Any) -> Any:
    """Convert safe primitive graph values to deterministic JSON values."""

    if isinstance(value, datetime):
        parsed = _timestamp(value)
        return parsed.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    # Pydantic models are useful callers of this pure seam; model_dump is read-only.
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    raise ProofFrontierContractError(f"graph value {type(value).__name__} is not canonical JSON")


def _hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProofFrontierContractError("graph value is not hashable JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ProofFrontierContractError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        # Graph snapshots historically contain a few naïve fixture timestamps.
        # Treating them as UTC keeps replay deterministic while preserving the value.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_mapping(value: Any, *, field: str = "graph") -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise ProofFrontierContractError(f"{field} must be a mapping")


def _items(value: Any, *, field: str) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        # Accept either one node object or {id: node} registries.
        if any(key in value for key in ("id", "node_id", "stable_key", "ref")):
            return [_as_mapping(value, field=field)]
        result: list[Mapping[str, Any]] = []
        for key, item in value.items():
            mapping = dict(_as_mapping(item, field=field))
            mapping.setdefault("id", str(key))
            result.append(mapping)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_as_mapping(item, field=field) for item in value]
    raise ProofFrontierContractError(f"{field} must be a list or mapping")


def _node_id(value: Mapping[str, Any], *, fallback: str | None = None) -> str:
    for key in ("id", "node_id", "stable_key", "ref", "key"):
        candidate = _string(value.get(key))
        if candidate:
            return candidate
    if fallback:
        return fallback
    raise ProofFrontierContractError("graph node is missing an id")


def _normalise_layer(value: Mapping[str, Any], *, default: str = "business") -> str:
    raw = _string(
        value.get("layer") or value.get("graph_layer") or value.get("domain") or value.get("node_layer")
    ).lower()
    if raw in {"theorem", "proof", "truth", "claim"}:
        return "theorem"
    if raw in {"business", "operation", "execution", "commerce", "task"}:
        return "business"
    kind = _string(value.get("kind") or value.get("type") or value.get("node_type")).lower()
    if kind in _THEOREM_KINDS:
        return "theorem"
    if kind in _BUSINESS_KINDS:
        return "business"
    return default


def _normalise_state_name(value: Any) -> ProofState | None:
    if isinstance(value, bool):
        return PROVEN if value else NO_DATA
    text = _string(value).lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if text.upper() in PROOF_STATES:
        return text.upper()  # type: ignore[return-value]
    return _STATE_ALIASES.get(text)


def _governance_value(
    value: Any,
    *,
    allowed: frozenset[str],
    aliases: Mapping[str, str] | None = None,
) -> str | None:
    if value is None:
        return None
    text = _string(value).upper().replace("-", "_").replace(" ", "_")
    if aliases:
        text = aliases.get(text, text)
    return text if text in allowed else "INVALID"


def _governance_projection(
    value: Mapping[str, Any],
) -> tuple[_GovernanceState | None, tuple[str, ...]]:
    """Normalize optional four-state fields and derive admission state."""

    nested = value.get("governance")
    if isinstance(nested, Mapping):
        governance = nested
    else:
        model_dump = getattr(nested, "model_dump", None)
        dumped = model_dump(mode="json") if callable(model_dump) else None
        governance = dumped if isinstance(dumped, Mapping) else {}
    present = any(
        key in value or key in governance
        for key in _GOVERNANCE_FIELDS
    )
    if not present:
        return None, ()

    def pick(key: str) -> Any:
        return value[key] if key in value else governance.get(key)

    proof_state = _governance_value(
        pick("proof_state"),
        allowed=_PROOF_GATE_STATES,
        aliases={
            "PROVEN": "PROVED",
            "VERIFIED": "PROVED",
            "PASSED": "PROVED",
            "PASS": "PROVED",
            "SUCCESS": "PROVED",
        },
    )
    evidence_state = _governance_value(
        pick("evidence_state"),
        allowed=_EVIDENCE_GATE_STATES,
        aliases={
            "READY": "VALID",
            "CURRENT": "VALID",
            "FRESH": "VALID",
            "OK": "VALID",
            "UNKNOWN": "UNKNOWN_OUTCOME",
            "EXPIRED": "STALE",
            "OUTDATED": "STALE",
            "INVALID": "BLOCKED",
            "REVOKED": "BLOCKED",
        },
    )
    operational_state = _governance_value(
        pick("operational_state"),
        allowed=_OPERATIONAL_GATE_STATES,
        aliases={
            "RUNNING": "LIVE",
            "ACTIVE": "LIVE",
            "READY": "LIVE",
            "STOPPED": "PAUSED",
            "DISABLED": "PAUSED",
        },
    )
    economic_state = _governance_value(
        pick("economic_state"),
        allowed=_ECONOMIC_GATE_STATES,
        aliases={
            "OK": "ALLOWED",
            "PASS": "ALLOWED",
            "PASSED": "ALLOWED",
            "APPROVED": "ALLOWED",
            "RISK": "AT_RISK",
            "RISKY": "AT_RISK",
            "DENIED": "BLOCKED",
            "FAILED": "BLOCKED",
        },
    )
    rollback_raw = pick("rollback_available")
    rollback_available: bool | None
    rollback_invalid = False
    if rollback_raw is None:
        rollback_available = None
    elif isinstance(rollback_raw, bool):
        rollback_available = rollback_raw
    elif isinstance(rollback_raw, int) and rollback_raw in {0, 1}:
        rollback_available = bool(rollback_raw)
    elif isinstance(rollback_raw, str) and rollback_raw.strip().lower() in {"true", "false"}:
        rollback_available = rollback_raw.strip().lower() == "true"
    else:
        rollback_available = None
        rollback_invalid = True

    reasons: list[str] = []
    if proof_state is None:
        reasons.append("proof_state_missing")
    elif proof_state != "PROVED":
        reasons.append(f"proof_state_{proof_state.lower()}")
    if evidence_state is None:
        reasons.append("evidence_state_missing")
    elif evidence_state != "VALID":
        reasons.append(f"evidence_state_{evidence_state.lower()}")
    if operational_state is None:
        reasons.append("operational_state_missing")
    elif operational_state != "LIVE":
        reasons.append(f"operational_state_{operational_state.lower()}")
    if economic_state is None:
        reasons.append("economic_state_missing")
    elif economic_state != "ALLOWED":
        reasons.append(f"economic_state_{economic_state.lower()}")
    if rollback_invalid:
        reasons.append("rollback_available_invalid")
    elif rollback_available is None:
        reasons.append("rollback_available_missing")
    elif not rollback_available:
        reasons.append("rollback_missing")

    # Unknown external outcomes are surfaced distinctly so a caller cannot
    # interpret them as an ordinary failed or successful action.
    if evidence_state == "UNKNOWN_OUTCOME":
        admission = "UNKNOWN_OUTCOME"
    elif any(
        item in {"BLOCKED", "STALE", "INVALID"}
        for item in (proof_state, evidence_state, operational_state, economic_state)
    ) or rollback_available is False:
        admission = "BLOCKED"
    elif any(
        item in {None, "NO_DATA", "UNPROVED", "UNKNOWN", "PARTIAL", "AT_RISK", "SHADOW", "PAUSED"}
        for item in (proof_state, evidence_state, operational_state, economic_state)
    ) or rollback_available is None:
        admission = "HOLD"
    else:
        admission = "LIVE"
    return (
        _GovernanceState(
            proof_state=proof_state,
            evidence_state=evidence_state,
            operational_state=operational_state,
            economic_state=economic_state,
            rollback_available=rollback_available,
            admission_state=admission,
        ),
        tuple(sorted(set(reasons))),
    )


def _direct_state(value: Mapping[str, Any], *, as_of: datetime | None) -> tuple[ProofState, tuple[str, ...]]:
    reasons: list[str] = []
    verification = value.get("verification")
    verification_map = verification if isinstance(verification, Mapping) else {}

    if value.get("invalidated") is True or value.get("is_invalidated") is True:
        return BLOCKED, ("node_invalidated",)
    if value.get("blocked") is True:
        return BLOCKED, ("node_flagged_blocked",)
    for key in ("proven", "verified", "passed", "proof"):
        if value.get(key) is True:
            return PROVEN, (f"{key}_flag",)

    raw_state: Any = None
    for key in ("state", "status", "proof_state", "truth_state", "verification_state"):
        if key in value:
            raw_state = value[key]
            break
    if raw_state is None:
        for key in ("state", "status", "proof_state", "truth_state"):
            if key in verification_map:
                raw_state = verification_map[key]
                break
    state = _normalise_state_name(raw_state)
    if state is None:
        state = NO_DATA
        reasons.append("state_missing")
    elif state == NO_DATA and _string(raw_state).lower() == "partial":
        reasons.append("partial_state")

    freshness = _string(value.get("freshness") or verification_map.get("freshness")).lower()
    if freshness in {"stale", "expired", "outdated"}:
        state = STALE
        reasons.append("freshness_stale")

    if as_of is not None:
        expiry_value = next(
            (
                value.get(key)
                for key in ("fresh_until", "expires_at", "valid_until", "effective_until")
                if value.get(key) is not None
            ),
            None,
        )
        if expiry_value is not None:
            try:
                if _timestamp(expiry_value) < as_of:
                    state = STALE
                    reasons.append("freshness_expired_at_as_of")
            except ProofFrontierContractError:
                state = BLOCKED
                reasons.append("freshness_timestamp_invalid")

    # An explicit invalidation reason wins over an otherwise positive state.
    if value.get("invalidation_reason") or value.get("invalidated_by"):
        state = BLOCKED
        reasons.append("invalidation_recorded")
    return state, tuple(sorted(set(reasons)))


def _governance_effective_state(
    governance: _GovernanceState,
    direct_state: ProofState,
) -> ProofState:
    """Map the optional admission contract into the planner's proof states.

    ``PROVEN`` is deliberately reserved for a node whose independent
    admission gates all pass.  A gate failure must therefore survive graph
    propagation even when the raw proof field says ``PROVED``.  Explicit
    direct invalidation/freshness failures remain stronger than an otherwise
    green governance projection.
    """

    if direct_state == BLOCKED:
        return BLOCKED
    if direct_state == STALE:
        return STALE

    values = (
        governance.proof_state,
        governance.evidence_state,
        governance.operational_state,
        governance.economic_state,
    )
    # A hard failure wins over stale/unknown so that an invalid or explicitly
    # blocked gate cannot be mistaken for a refreshable state.
    if governance.rollback_available is False or any(
        value in {"BLOCKED", "INVALID"} for value in values
    ):
        return BLOCKED
    if governance.admission_state == "UNKNOWN_OUTCOME":
        return NO_DATA
    if any(value == "STALE" for value in values):
        return STALE
    if governance.admission_state == "LIVE":
        return PROVEN
    return NO_DATA


def _effective_state(
    value: Mapping[str, Any], *, as_of: datetime | None
) -> tuple[ProofState, tuple[str, ...], _GovernanceState | None]:
    """Return the planner state plus optional transparent governance data."""

    direct_state, direct_reasons = _direct_state(value, as_of=as_of)
    governance, governance_reasons = _governance_projection(value)
    if governance is None:
        return direct_state, direct_reasons, None
    state = _governance_effective_state(governance, direct_state)
    reasons = tuple(sorted(set((*direct_reasons, *governance_reasons))))
    return state, reasons, governance


def _admission_for_state(governance: _GovernanceState, state: ProofState) -> str:
    """Downgrade a green admission when graph propagation invalidates it."""

    admission = governance.admission_state
    if admission == "UNKNOWN_OUTCOME":
        return admission
    if state == BLOCKED:
        return "BLOCKED"
    if state == STALE:
        return "BLOCKED"
    if state == NO_DATA and admission == "LIVE":
        return "HOLD"
    return admission


def classify_state(value: Any, *, as_of: datetime | str | None = None) -> ProofState:
    """Classify a node/status into the four planner states.

    ``ready``/``passed``/``verified`` are treated as ``PROVEN`` only when they
    are explicit.  Missing, partial and unknown values remain ``NO_DATA``.
    """

    cutoff = _timestamp(as_of) if as_of is not None else None
    if isinstance(value, Mapping):
        return _effective_state(value, as_of=cutoff)[0]
    state = _normalise_state_name(value)
    return state or NO_DATA


def classify_node(value: Mapping[str, Any], *, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Return a transparent state assessment without changing ``value``."""

    node = _as_mapping(value, field="node")
    cutoff = _timestamp(as_of) if as_of is not None else None
    state, reasons, governance = _effective_state(node, as_of=cutoff)
    result: dict[str, Any] = {
        "state": state,
        "status": state,
        "reasons": list(reasons),
        "as_of": cutoff.isoformat() if cutoff else None,
    }
    if governance is not None:
        result.update(
            {
                "proof_state": governance.proof_state,
                "evidence_state": governance.evidence_state,
                "operational_state": governance.operational_state,
                "economic_state": governance.economic_state,
                "rollback_available": governance.rollback_available,
                "admission_state": _admission_for_state(governance, state),
            }
        )
    return result


def _extract_as_of(root: Mapping[str, Any], as_of: datetime | str | None) -> datetime | None:
    if as_of is not None:
        return _timestamp(as_of)
    for key in ("as_of", "checked_at", "observed_at", "data_as_of"):
        if root.get(key) is not None:
            return _timestamp(root[key])
    return None


def _relation(value: Mapping[str, Any]) -> str:
    raw = _string(value.get("relation") or value.get("edge_type") or value.get("type") or value.get("kind"))
    return raw.lower().replace("-", "_").replace(" ", "_")


def _edge_endpoints(value: Mapping[str, Any]) -> tuple[str, str]:
    source = _string(
        value.get("source")
        or value.get("source_id")
        or value.get("source_node_id")
        or value.get("source_ref")
        or value.get("from")
        or value.get("upstream")
    )
    target = _string(
        value.get("target")
        or value.get("target_id")
        or value.get("target_node_id")
        or value.get("target_ref")
        or value.get("to")
        or value.get("downstream")
    )
    if not source or not target:
        raise ProofFrontierContractError("graph edge requires source and target")
    return source, target


def _references(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        # A dependency object commonly uses id/ref/node_id.
        ref = _node_id(value)
        return [ref]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                result.append(_node_id(item))
            else:
                text = _string(item)
                if text:
                    result.append(text)
        return result
    raise ProofFrontierContractError("dependency references must be strings or lists")


def _numeric(value: Any, default: float = 1.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else default


def _normalise_graph(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> _Graph:
    root = _as_mapping(graph)
    # Some adapters wrap the canonical projection in ``graph``.
    if isinstance(root.get("graph"), Mapping) and not any(
        key in root for key in ("nodes", "theorem_nodes", "business_nodes", "tasks", "edges", "relations")
    ):
        root = _as_mapping(root["graph"], field="graph.graph")
    cutoff = _extract_as_of(root, as_of)
    errors: list[str] = []
    node_rows: list[tuple[Mapping[str, Any], str]] = []
    for key, default_layer in (
        ("theorem_nodes", "theorem"),
        ("business_nodes", "business"),
        ("nodes", "business"),
        ("tasks", "business"),
    ):
        for item in _items(root.get(key), field=key):
            node_rows.append((item, default_layer))

    nodes: dict[str, _Node] = {}
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for item, default_layer in node_rows:
        node_id = _node_id(item)
        if node_id in nodes:
            errors.append(f"duplicate_node_id:{node_id}")
            continue
        state, reasons, governance = _effective_state(item, as_of=cutoff)
        nodes[node_id] = _Node(
            node_id=node_id,
            layer=_normalise_layer(item, default=default_layer),
            raw=item,
            direct_state=state,
            direct_reasons=reasons,
            weight=_numeric(
                item.get("weight", item.get("duration", item.get("estimated_duration", 1))),
                1.0,
            ),
            priority=_numeric(item.get("priority", item.get("criticality", 0)), 0.0),
            governance=governance,
        )
        raw_by_id[node_id] = item

    edges: list[_Edge] = []
    edge_rows = []
    for key in ("edges", "relations", "graph_edges"):
        edge_rows.extend(_items(root.get(key), field=key))
    for index, item in enumerate(edge_rows):
        try:
            source, target = _edge_endpoints(item)
        except ProofFrontierContractError as exc:
            errors.append(f"invalid_edge:{index}:{exc}")
            continue
        relation = _relation(item)
        edge_id = (
            _string(item.get("id") or item.get("edge_id") or item.get("ref")) or f"edge:{source}:{relation}:{target}"
        )
        edges.append(_Edge(edge_id=edge_id, source=source, target=target, relation=relation, raw=item))

    dependencies: dict[str, set[str]] = defaultdict(set)
    proof_dependencies: dict[str, set[str]] = defaultdict(set)
    invalidations: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.relation in _INVALIDATES_RELATIONS:
            invalidations[edge.source].add(edge.target)
        elif edge.relation in _INVALIDATED_BY_RELATIONS:
            invalidations[edge.target].add(edge.source)
        elif edge.relation in _SOURCE_PREREQUISITE_RELATIONS:
            dependencies[edge.target].add(edge.source)
            if edge.relation in {"proves", "satisfies", "implements"}:
                proof_dependencies[edge.target].add(edge.source)
        elif edge.relation in _TARGET_PREREQUISITE_RELATIONS:
            dependencies[edge.source].add(edge.target)
        else:
            # An edge with an explicit dependency-looking name is safer to
            # interpret as a dependency than to silently drop it.
            if "depend" in edge.relation or "require" in edge.relation:
                dependencies[edge.source].add(edge.target)
            else:
                errors.append(f"unknown_edge_relation:{edge.edge_id}:{edge.relation or 'empty'}")

    for node_id, item in raw_by_id.items():
        for key in ("dependencies", "dependency_ids", "depends_on", "requires", "needs", "blocked_by", "upstream_ids"):
            if key in item:
                try:
                    dependencies[node_id].update(_references(item.get(key)))
                except ProofFrontierContractError as exc:
                    errors.append(f"invalid_dependencies:{node_id}:{key}:{exc}")
        # ``satisfies``/``proves`` are node shorthand for a reverse edge:
        # the theorem target depends on this business node.
        for key in ("satisfies", "proves", "implements", "enables"):
            if key in item:
                try:
                    for target in _references(item.get(key)):
                        dependencies[target].add(node_id)
                        proof_dependencies[target].add(node_id)
                except ProofFrontierContractError as exc:
                    errors.append(f"invalid_proof_links:{node_id}:{key}:{exc}")
        for key in ("invalidates",):
            if key in item:
                try:
                    invalidations[node_id].update(_references(item.get(key)))
                except ProofFrontierContractError as exc:
                    errors.append(f"invalid_invalidation_links:{node_id}:{key}:{exc}")
        for key in ("invalidated_by", "superseded_by"):
            if key in item:
                try:
                    for source in _references(item.get(key)):
                        invalidations[source].add(node_id)
                except ProofFrontierContractError as exc:
                    errors.append(f"invalid_invalidation_links:{node_id}:{key}:{exc}")

    known = set(nodes)
    for owner, refs in list(dependencies.items()) + list(invalidations.items()):
        if owner not in known:
            errors.append(f"missing_node:{owner}")
        for ref in sorted(refs):
            if ref not in known:
                errors.append(f"missing_node_reference:{owner}:{ref}")

    return _Graph(
        nodes=nodes,
        edges=tuple(sorted(edges, key=lambda item: (item.source, item.relation, item.target, item.edge_id))),
        dependencies={key: frozenset(value) for key, value in dependencies.items()},
        proof_dependencies={key: frozenset(value) for key, value in proof_dependencies.items()},
        invalidations={key: frozenset(value) for key, value in invalidations.items()},
        errors=tuple(sorted(set(errors))),
        root=root,
        as_of=cutoff,
    )


def _cycles(dependencies: Mapping[str, Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    colour: dict[str, int] = {}
    stack: list[str] = []
    found: set[tuple[str, ...]] = set()

    def visit(node_id: str) -> None:
        colour[node_id] = 1
        stack.append(node_id)
        for dependency in sorted(dependencies.get(node_id, ())):
            if colour.get(dependency, 0) == 0:
                visit(dependency)
            elif colour.get(dependency) == 1 and dependency in stack:
                start = stack.index(dependency)
                cycle = tuple(stack[start:] + [dependency])
                found.add(cycle)
        stack.pop()
        colour[node_id] = 2

    for node_id in sorted(set(dependencies) | {item for values in dependencies.values() for item in values}):
        if colour.get(node_id, 0) == 0:
            visit(node_id)
    return tuple(sorted(found))


def _state_rank(state: ProofState) -> int:
    return {PROVEN: 0, NO_DATA: 1, STALE: 2, BLOCKED: 3}[state]


def _evaluate_states(graph: _Graph) -> tuple[dict[str, ProofState], dict[str, set[str]], tuple[tuple[str, ...], ...]]:
    states = {node_id: node.direct_state for node_id, node in graph.nodes.items()}
    reasons = {node_id: set(graph.nodes[node_id].direct_reasons) for node_id in graph.nodes}
    cycles = _cycles(graph.dependencies)
    for cycle in cycles:
        for node_id in cycle:
            if node_id in states:
                states[node_id] = BLOCKED
                reasons[node_id].add("dependency_cycle")
    for owner, refs in graph.dependencies.items():
        if owner not in states:
            continue
        for ref in refs:
            if ref not in states:
                states[owner] = BLOCKED
                reasons[owner].add(f"missing_dependency:{ref}")
    # ``invalidations`` is indexed by source: source -> targets.  A missing
    # source or target is an integrity failure on the target, never a reason
    # to mark an unrelated source node as blocked.
    for source, targets in graph.invalidations.items():
        if source not in states:
            for target in targets:
                if target in states:
                    states[target] = BLOCKED
                    reasons[target].add(f"missing_invalidation_source:{source}")
            continue
        for target in targets:
            if target not in states:
                continue

    # Fixed-point propagation makes results independent of node ordering.
    for _ in range(max(1, len(states) + len(graph.edges) + 1)):
        changed = False
        for node_id in sorted(states):
            current = states[node_id]
            proof_dependencies = sorted(graph.proof_dependencies.get(node_id, ()))
            # A theorem explicitly marked as ``proves``/``satisfies`` is
            # proven once every proof-producing business node is proven.  A
            # generic prerequisite is intentionally insufficient: merely
            # completing a task does not assert the theorem it serves.
            if (
                current == NO_DATA
                and proof_dependencies
                and all(states.get(item, NO_DATA) == PROVEN for item in proof_dependencies)
                and (
                    graph.nodes[node_id].governance is None
                    or graph.nodes[node_id].governance.admission_state == "LIVE"
                )
            ):
                states[node_id] = PROVEN
                current = PROVEN
                reasons[node_id].add("derived_from_proven_dependencies")
                changed = True
            for source, targets in graph.invalidations.items():
                if node_id not in targets:
                    continue
                if source in states:
                    if current != BLOCKED:
                        states[node_id] = BLOCKED
                        current = BLOCKED
                        changed = True
                    reasons[node_id].add(f"invalidated_by:{source}")
            for dependency in sorted(graph.dependencies.get(node_id, ())):
                dependency_state = states.get(dependency, NO_DATA)
                if dependency_state == PROVEN:
                    continue
                if _state_rank(dependency_state) > _state_rank(current):
                    states[node_id] = dependency_state
                    current = dependency_state
                    changed = True
                reasons[node_id].add(f"upstream_{dependency_state.lower()}:{dependency}")
        if not changed:
            break
    return states, reasons, cycles


def _safe_node_view(
    node: _Node, state: ProofState, reasons: Sequence[str], dependencies: Sequence[str]
) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": node.node_id,
        "node_id": node.node_id,
        "layer": node.layer,
        "label": _string(node.raw.get("label") or node.raw.get("title") or node.raw.get("name") or node.node_id),
        "state": state,
        "status": state,
        "direct_state": node.direct_state,
        "reasons": sorted(set(reasons)),
        "dependencies": sorted(set(dependencies)),
        "weight": node.weight,
        "priority": node.priority,
        "evidence_refs": _safe_refs(
            node.raw.get("evidence_refs") or node.raw.get("evidence") or node.raw.get("source_refs")
        ),
    }
    # Keep the legacy projection byte-for-byte compatible for nodes that do
    # not opt into the four-state admission contract.  Governed nodes expose
    # each independent state and the derived admission decision explicitly so
    # callers can audit why a proof cannot become LIVE.
    if node.governance is not None:
        view.update(
            {
                "proof_state": node.governance.proof_state,
                "evidence_state": node.governance.evidence_state,
                "operational_state": node.governance.operational_state,
                "economic_state": node.governance.economic_state,
                "rollback_available": node.governance.rollback_available,
                "admission_state": _admission_for_state(node.governance, state),
            }
        )
    return view


def _safe_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        result: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                ref = _string(item.get("id") or item.get("ref") or item.get("evidence_id"))
            else:
                ref = _string(item)
            if ref:
                result.append(ref)
        return sorted(set(result))
    return []


def _frontier_details(
    graph: _Graph, states: Mapping[str, ProofState], reasons: Mapping[str, set[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actionable: list[dict[str, Any]] = []
    boundary: list[dict[str, Any]] = []
    for node_id in sorted(graph.nodes):
        state = states[node_id]
        dependencies = sorted(graph.dependencies.get(node_id, ()))
        unresolved = [ref for ref in dependencies if states.get(ref, NO_DATA) != PROVEN]
        if state == PROVEN:
            continue
        view = _safe_node_view(graph.nodes[node_id], state, reasons[node_id], dependencies)
        view["unresolved_dependencies"] = unresolved
        view["frontier_kind"] = "refresh" if state == STALE else "prove" if state == NO_DATA else "repair"
        if not dependencies or any(states.get(ref) == PROVEN for ref in dependencies):
            boundary.append(view)
        hard_reasons = reasons[node_id] & {"node_invalidated", "node_flagged_blocked", "dependency_cycle"}
        if state in {NO_DATA, STALE} and not unresolved and not hard_reasons:
            actionable.append(view)
    return actionable, boundary


def _blocker_details(
    graph: _Graph, states: Mapping[str, ProofState], reasons: Mapping[str, set[str]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node_id in sorted(graph.nodes):
        state = states[node_id]
        if state == PROVEN:
            continue
        dependencies = sorted(graph.dependencies.get(node_id, ()))
        upstream = [ref for ref in dependencies if states.get(ref, NO_DATA) != PROVEN]
        # A no-data node whose prerequisites are complete is the actionable
        # frontier, not a blocker.  Keep no-data in this list only when it is
        # itself waiting on an unresolved prerequisite (or has a direct
        # malformed-state reason).
        if state == NO_DATA and not upstream and not reasons[node_id]:
            continue
        view = _safe_node_view(graph.nodes[node_id], state, reasons[node_id], dependencies)
        view["upstream_blockers"] = upstream
        view["hard"] = state == BLOCKED
        result.append(view)
    for error in graph.errors:
        result.append(
            {
                "id": "__graph__",
                "node_id": "__graph__",
                "layer": "graph",
                "state": BLOCKED,
                "status": BLOCKED,
                "direct_state": BLOCKED,
                "reasons": [error],
                "dependencies": [],
                "upstream_blockers": [],
                "hard": True,
            }
        )
    return result


def _path_to(
    graph: _Graph, states: Mapping[str, ProofState], target: str, visiting: frozenset[str] = frozenset()
) -> tuple[tuple[str, ...], float]:
    if target in visiting:
        return ((target,), graph.nodes[target].weight if target in graph.nodes else 0.0)
    node = graph.nodes[target]
    dependencies = [ref for ref in sorted(graph.dependencies.get(target, ())) if ref in graph.nodes]
    if not dependencies:
        return ((target,), node.weight)
    best_path: tuple[str, ...] = ()
    best_weight = -1.0
    next_visiting = visiting | {target}
    for dependency in dependencies:
        path, weight = _path_to(graph, states, dependency, next_visiting)
        candidate = path + (target,) if path and path[-1] != target else path
        total = weight + node.weight
        key = (total, len(candidate), tuple(reversed(candidate)))
        best_key = (best_weight, len(best_path), tuple(reversed(best_path)))
        if not best_path or key > best_key:
            best_path, best_weight = candidate, total
    return best_path, best_weight


def _critical_detail(
    graph: _Graph, states: Mapping[str, ProofState], reasons: Mapping[str, set[str]]
) -> dict[str, Any]:
    unresolved = [node_id for node_id, state in states.items() if state != PROVEN]
    if not unresolved:
        return {
            "status": PROVEN,
            "target_id": None,
            "node_ids": [],
            "length": 0,
            "weight": 0.0,
            "blocked_by": [],
            "reason_codes": [],
        }
    explicit = (
        graph.root.get("critical_targets") or graph.root.get("critical_path_targets") or graph.root.get("targets")
    )
    explicit_ids = [item for item in _references(explicit)] if explicit is not None else []
    candidates = [item for item in explicit_ids if item in states and states[item] != PROVEN]
    if not candidates:
        unresolved_set = set(unresolved)
        dependents = {node_id: set() for node_id in unresolved}
        for owner, dependencies in graph.dependencies.items():
            for dependency in dependencies:
                if dependency in dependents and owner in unresolved_set:
                    dependents[dependency].add(owner)
        leaves = [node_id for node_id in unresolved if not (dependents[node_id] & unresolved_set)]
        candidates = leaves or unresolved

    def candidate_key(node_id: str) -> tuple[float, float, int, str]:
        return (
            1.0 if states[node_id] == BLOCKED else 0.0,
            graph.nodes[node_id].priority,
            graph.nodes[node_id].weight,
            node_id,
        )

    target = max(sorted(candidates), key=candidate_key)
    path, weight = _path_to(graph, states, target)
    blocked_by = sorted(
        {
            dependency
            for node_id in path
            for dependency in graph.dependencies.get(node_id, ())
            if states.get(dependency, NO_DATA) != PROVEN
        }
        | {source for node_id in path for source, targets in graph.invalidations.items() if node_id in targets}
    )
    reason_codes = sorted({reason for node_id in path for reason in reasons.get(node_id, set())})
    return {
        "status": states[target],
        "target_id": target,
        "node_ids": list(path),
        "length": len(path),
        "weight": weight,
        "blocked_by": blocked_by,
        "reason_codes": reason_codes,
    }


def _aggregate(states: Mapping[str, ProofState]) -> ProofState:
    if not states:
        return NO_DATA
    if BLOCKED in states.values():
        return BLOCKED
    if STALE in states.values():
        return STALE
    if NO_DATA in states.values():
        return NO_DATA
    return PROVEN


def _snapshot(graph: _Graph, states: Mapping[str, ProofState] | None = None) -> dict[str, Any]:
    nodes = []
    for node_id in sorted(graph.nodes):
        node = graph.nodes[node_id]
        snapshot_node: dict[str, Any] = {
            "id": node.node_id,
            "layer": node.layer,
            "label": _string(
                node.raw.get("label") or node.raw.get("title") or node.raw.get("name") or node.node_id
            ),
            "direct_state": node.direct_state,
            "dependencies": sorted(graph.dependencies.get(node_id, ())),
            "weight": node.weight,
            "priority": node.priority,
            "evidence_refs": _safe_refs(
                node.raw.get("evidence_refs") or node.raw.get("evidence") or node.raw.get("source_refs")
            ),
            "content_sha256": _string(node.raw.get("content_sha256") or node.raw.get("sha256")) or None,
        }
        if node.governance is not None:
            snapshot_node.update(
                {
                    "proof_state": node.governance.proof_state,
                    "evidence_state": node.governance.evidence_state,
                    "operational_state": node.governance.operational_state,
                    "economic_state": node.governance.economic_state,
                    "rollback_available": node.governance.rollback_available,
                    "admission_state": _admission_for_state(
                        node.governance, (states or {}).get(node_id, node.direct_state)
                    ),
                }
            )
        nodes.append(snapshot_node)
    edges = [
        {
            "id": edge.edge_id,
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
            "content_sha256": _string(edge.raw.get("content_sha256") or edge.raw.get("sha256")) or None,
        }
        for edge in graph.edges
    ]
    snapshot = {
        "contract_id": "kjds-proof-frontier-snapshot-v1",
        "as_of": graph.as_of.isoformat() if graph.as_of else None,
        "nodes": nodes,
        "edges": edges,
        "graph_errors": list(graph.errors),
    }
    snapshot["snapshot_sha256"] = _hash(snapshot)
    return snapshot


def snapshot_graph(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Return a stable, safe graph snapshot with a content hash."""

    return _snapshot(_normalise_graph(graph, as_of=as_of))


def _evaluate(
    graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None
) -> tuple[_Graph, dict[str, ProofState], dict[str, set[str]], tuple[tuple[str, ...], ...]]:
    normalised = _normalise_graph(graph, as_of=as_of)
    states, reasons, cycles = _evaluate_states(normalised)
    return normalised, states, reasons, cycles


def proof_frontier(
    graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None, detailed: bool = False
) -> list[Any]:
    """Return nodes that can be worked on after their prerequisites are proven.

    The default result is a deterministic list of node IDs.  Set ``detailed``
    to receive the transparent node projections used by :func:`plan_proof_frontier`.
    """

    normalised, states, reasons, _ = _evaluate(graph, as_of=as_of)
    actionable, _ = _frontier_details(normalised, states, reasons)
    return actionable if detailed else [item["id"] for item in actionable]


def frontier_nodes(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> list[dict[str, Any]]:
    return proof_frontier(graph, as_of=as_of, detailed=True)  # type: ignore[return-value]


def find_blockers(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> list[dict[str, Any]]:
    """Return direct and propagated blockers, including graph integrity errors."""

    normalised, states, reasons, _ = _evaluate(graph, as_of=as_of)
    return _blocker_details(normalised, states, reasons)


def critical_path_detail(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> dict[str, Any]:
    normalised, states, reasons, _ = _evaluate(graph, as_of=as_of)
    result = _critical_detail(normalised, states, reasons)
    if normalised.errors:
        result = {
            **result,
            "status": BLOCKED,
            "reason_codes": sorted(set(result["reason_codes"]) | set(normalised.errors)),
        }
    return result


def critical_path(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> list[str]:
    """Return the deterministic prerequisite-to-target critical path IDs."""

    return list(critical_path_detail(graph, as_of=as_of)["node_ids"])


def propagate_invalidation(
    graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None
) -> dict[str, dict[str, Any]]:
    """Return the fixed-point invalidation/blocked projection by node ID."""

    normalised, states, reasons, _ = _evaluate(graph, as_of=as_of)
    result: dict[str, dict[str, Any]] = {}
    for node_id in sorted(normalised.nodes):
        causes = sorted(
            {source for source, targets in normalised.invalidations.items() if node_id in targets}
            | {
                dependency
                for dependency in normalised.dependencies.get(node_id, ())
                if states.get(dependency, NO_DATA) != PROVEN
            }
        )
        propagated_reasons = sorted(
            reason
            for reason in reasons[node_id]
            if reason.startswith("invalidated_by:")
            or reason.startswith("upstream_")
            or reason in {"dependency_cycle", "node_invalidated"}
        )
        if causes or propagated_reasons:
            result[node_id] = {
                "id": node_id,
                "state": states[node_id],
                "status": states[node_id],
                "causes": causes,
                "reason_codes": propagated_reasons,
            }
    return result


def plan_proof_frontier(graph: Mapping[str, Any] | Any, *, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Compile the complete read-only proof frontier planning projection."""

    normalised, states, reasons, cycles = _evaluate(graph, as_of=as_of)
    actionable, boundary = _frontier_details(normalised, states, reasons)
    blockers = _blocker_details(normalised, states, reasons)
    snapshot = _snapshot(normalised, states)
    node_views = [
        _safe_node_view(
            normalised.nodes[node_id],
            states[node_id],
            reasons[node_id],
            sorted(normalised.dependencies.get(node_id, ())),
        )
        for node_id in sorted(normalised.nodes)
    ]
    invalidation = propagate_invalidation(graph, as_of=as_of)
    theorem_ids = [node_id for node_id, node in normalised.nodes.items() if node.layer == "theorem"]
    business_ids = [node_id for node_id, node in normalised.nodes.items() if node.layer == "business"]
    governed_nodes = {
        node_id: node.governance
        for node_id, node in normalised.nodes.items()
        if node.governance is not None
    }

    def layer_projection(ids: Sequence[str]) -> dict[str, Any]:
        layer_states = {node_id: states[node_id] for node_id in ids}
        layer_frontier = [item["id"] for item in actionable if item["id"] in ids]
        layer_blockers = [item["id"] for item in blockers if item.get("id") in ids]
        return {
            "status": _aggregate(layer_states),
            "node_ids": list(ids),
            "frontier_ids": layer_frontier,
            "blocker_ids": sorted(set(layer_blockers)),
        }

    overall_status = BLOCKED if normalised.errors else _aggregate(states)
    result = {
        "contract_id": "kjds-proof-frontier-planner-v1",
        "status": overall_status,
        "state": overall_status,
        "as_of": normalised.as_of.isoformat() if normalised.as_of else None,
        "states": {node_id: states[node_id] for node_id in sorted(states)},
        "nodes": node_views,
        "theorem": layer_projection(sorted(theorem_ids)),
        "business": layer_projection(sorted(business_ids)),
        "frontier": actionable,
        "frontier_ids": [item["id"] for item in actionable],
        "boundary_ids": [item["id"] for item in boundary],
        "proof_frontier": actionable,
        "blockers": blockers,
        "critical_path": _critical_detail(normalised, states, reasons),
        "invalidations": invalidation,
        "cycles": [list(item) for item in cycles],
        "graph_errors": list(normalised.errors),
        "snapshot": snapshot,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "external_write_allowed": False,
        "formal_fact_allowed": False,
        "model_self_certification_allowed": False,
    }
    if governed_nodes:
        # A separate map keeps the four independent gate states available to
        # project-manager consumers without forcing them to parse node views.
        result["admission_states"] = {
            node_id: _admission_for_state(governed_nodes[node_id], states[node_id])
            for node_id in sorted(governed_nodes)
        }
    result["plan_sha256"] = _hash(result)
    return result


class ProofFrontierPlanner:
    """Small object facade around the pure planner functions."""

    def __init__(self, graph: Mapping[str, Any] | Any) -> None:
        self.graph = graph

    def plan(self, *, as_of: datetime | str | None = None) -> dict[str, Any]:
        return plan_proof_frontier(self.graph, as_of=as_of)

    def evaluate(self, *, as_of: datetime | str | None = None) -> dict[str, Any]:
        return self.plan(as_of=as_of)

    def frontier(self, *, as_of: datetime | str | None = None, detailed: bool = False) -> list[Any]:
        return proof_frontier(self.graph, as_of=as_of, detailed=detailed)

    def blockers(self, *, as_of: datetime | str | None = None) -> list[dict[str, Any]]:
        return find_blockers(self.graph, as_of=as_of)

    def invalidations(self, *, as_of: datetime | str | None = None) -> dict[str, dict[str, Any]]:
        return propagate_invalidation(self.graph, as_of=as_of)


# Friendly aliases for callers using verb-first naming.
compute_proof_frontier = proof_frontier
compute_frontier = proof_frontier
compute_critical_path = critical_path_detail
invalidate_dependents = propagate_invalidation
build_proof_frontier_plan = plan_proof_frontier


__all__ = [
    "BLOCKED",
    "NO_DATA",
    "PROOF_STATES",
    "PROVEN",
    "STALE",
    "ProofFrontierContractError",
    "ProofFrontierError",
    "ProofFrontierPlanner",
    "ProofState",
    "build_proof_frontier_plan",
    "classify_node",
    "classify_state",
    "compute_critical_path",
    "compute_frontier",
    "compute_proof_frontier",
    "critical_path",
    "critical_path_detail",
    "find_blockers",
    "frontier_nodes",
    "invalidate_dependents",
    "plan_proof_frontier",
    "propagate_invalidation",
    "proof_frontier",
    "snapshot_graph",
]
