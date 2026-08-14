"""Governed Social-Commerce source adoption evaluator (BAS-178 first slice).

Freezes the ADR-0090 source ladder and deterministic adapter evaluation. A
candidate adapter is validated against the ladder and its declared decision,
and reports an exact unauthenticated state. No adapter runtime is installed or
executed here, and cross-account credentials never mix.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SOURCE_ADOPTION_CONTRACT = "kjds-social-source-adoption-evaluator-v1"
SOURCE_ADOPTION_VERSION = "1.0.0"

SOURCE_LADDER = (
    "official_authorized_api",
    "official_operator_export",
    "operator_cli_or_browser",
    "public_official_page",
    "manual_evidence",
)
SOURCE_LADDER_RANK = {rank: position for position, rank in enumerate(SOURCE_LADDER)}

DECISIONS = frozenset(
    {"preferred_path", "adopt_pattern", "pilot_isolated", "watch", "reject_runtime"}
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
    }
)


class SourceAdoptionError(ValueError):
    """Stable, non-sensitive contract failure for source adoption evaluation."""


@dataclass(frozen=True)
class SourceAdoptionDecision:
    candidate_ref: str
    source_rank: str
    decision: str
    authenticated: bool
    external_write_allowed: bool
    reasons: tuple[str, ...]
    decision_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise SourceAdoptionError(f"{name}_invalid")
    if len(value) > maximum:
        raise SourceAdoptionError(f"{name}_too_long")
    return value


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise SourceAdoptionError(f"{name}_invalid")
    return text


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if TOKEN.fullmatch(text) is None:
        raise SourceAdoptionError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise SourceAdoptionError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise SourceAdoptionError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SourceAdoptionError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise SourceAdoptionError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedSourceAdoptionEvaluator:
    """Deterministic source-adoption evaluator for ADR-0090 acceptance #3."""

    def evaluate(self, candidate: Any) -> SourceAdoptionDecision:
        if not isinstance(candidate, Mapping):
            raise SourceAdoptionError("candidate_invalid")
        candidate_ref = _token(candidate.get("candidate_ref"), "candidate_ref")
        version = _text(candidate.get("version"), "version", maximum=80)
        license_id = _text(candidate.get("license_id"), "license_id", maximum=80)
        commit_sha256 = _hex64(candidate.get("commit_sha256"), "commit_sha256")
        source_rank = _text(candidate.get("source_rank"), "source_rank", maximum=60)
        if source_rank not in SOURCE_LADDER_RANK:
            raise SourceAdoptionError("source_rank_not_recognized")
        decision = _text(candidate.get("decision"), "decision", maximum=40)
        if decision not in DECISIONS:
            raise SourceAdoptionError("decision_not_recognized")
        authenticated = candidate.get("authenticated")
        if not isinstance(authenticated, bool):
            raise SourceAdoptionError("authenticated_invalid")
        _safe_tree(dict(candidate))

        reasons: list[str] = []
        # Deterministic consistency guards, never subjective judgment.
        if decision == "preferred_path" and source_rank != "official_authorized_api":
            raise SourceAdoptionError("preferred_path_requires_official_api")
        if decision == "reject_runtime" and license_id.lower() in {"apache-2.0", "mit", "bsd-3-clause"}:
            raise SourceAdoptionError("reject_runtime_license_conflict")
        if decision == "preferred_path" and not authenticated:
            reasons.append("preferred_path_unauthenticated")

        document = {
            "contract_id": SOURCE_ADOPTION_CONTRACT,
            "contract_version": SOURCE_ADOPTION_VERSION,
            "candidate_ref": candidate_ref,
            "version": version,
            "license_id": license_id,
            "commit_sha256": commit_sha256,
            "source_rank": source_rank,
            "decision": decision,
            "authenticated": authenticated,
            "reasons": sorted(set(reasons)),
        }
        return SourceAdoptionDecision(
            candidate_ref=candidate_ref,
            source_rank=source_rank,
            decision=decision,
            authenticated=authenticated,
            external_write_allowed=False,
            reasons=tuple(sorted(set(reasons))),
            decision_sha256=_hash(document),
        )

    def readback(
        self,
        decision: SourceAdoptionDecision,
        *,
        observed: str | None = None,
    ) -> dict[str, Any]:
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == decision.decision_sha256
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "GovernedSourceAdoptionEvaluator",
    "SourceAdoptionDecision",
    "SourceAdoptionError",
    "SOURCE_ADOPTION_CONTRACT",
    "SOURCE_LADDER",
]
