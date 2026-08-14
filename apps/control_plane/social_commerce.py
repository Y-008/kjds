"""Governed Social-Commerce Intelligence contract kernel (BAS-178 first slice).

Freezes the ``SocialCommerceIntelligenceWorkspace`` collect/analyze/operate
contract defined by ADR-0090. Real platform adapters, account bindings and
platform writes are not admitted in this slice: the workspace validates
acquisition/analysis/campaign envelopes and conserves records deterministically
without external collection or mutation. Cross-account credentials and raw
customer data never mix, and missing data is never fabricated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .social_analysis import GovernedSocialIntelligenceAnalysis

WORKSPACE_CONTRACT = "kjds-social-commerce-intelligence-workspace-v1"
WORKSPACE_VERSION = "1.0.0"
OBSERVATION_CONTRACT = "kjds-social-observation-batch-v1"
INSIGHT_CONTRACT = "kjds-social-insight-bundle-v1"
CAMPAIGN_SPEC_CONTRACT = "kjds-campaign-spec-v1"
CAMPAIGN_GRANT_CONTRACT = "kjds-campaign-grant-v1"
CAMPAIGN_RECEIPT_CONTRACT = "kjds-campaign-receipt-v1"

REAL_PLATFORM_ADAPTERS_ADMITTED = False

ALLOWED_PLATFORMS = frozenset({"xiaohongshu", "douyin"})
ALLOWED_SOURCE_RANKS = frozenset(
    {
        "official_authorized_api",
        "official_operator_export",
        "operator_cli_or_browser",
        "public_official_page",
        "manual_evidence",
    }
)
ALLOWED_ACTIONS = frozenset(
    {
        "publish",
        "update",
        "delete",
        "comment",
        "reply",
        "like",
        "favorite",
        "follow",
        "unfollow",
        "message",
        "download",
    }
)
ALLOWED_DIMENSIONS = frozenset(
    {"actor", "content", "engagement", "conversation", "seller_product", "time", "outcome"}
)

STATUSES = frozenset({"ADMITTED", "NOT_ADMITTED", "BLOCKED", "INVALIDATED", "STALE"})

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

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


class SocialCommerceError(ValueError):
    """Stable, non-sensitive contract failure for the social-commerce kernel."""


@dataclass(frozen=True)
class ObservationBatch:
    status: str
    platform: str
    contract_id: str
    source_rank: str
    adapter_version: str
    records: tuple[dict[str, Any], ...]
    conserved_total: int
    dedup_count: int
    checkpoint: str | None
    coverage: tuple[str, ...]
    gaps: tuple[str, ...]
    batch_sha256: str


@dataclass(frozen=True)
class InsightBundle:
    status: str
    contract_id: str
    dimensions: tuple[str, ...]
    patterns: tuple[dict[str, Any], ...]
    raw_batch_sha256: str
    derived_only: bool
    bundle_sha256: str


@dataclass(frozen=True)
class CampaignReceipt:
    status: str
    contract_id: str
    campaign_spec_sha256: str
    grant_sha256: str
    action_set: tuple[str, ...]
    idempotency_key: str
    readback_state: str
    kill_switch: bool
    external_write_allowed: bool


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise SocialCommerceError(f"{name}_invalid")
    if len(value) > maximum:
        raise SocialCommerceError(f"{name}_too_long")
    return value


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise SocialCommerceError(f"{name}_invalid")
    return text


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise SocialCommerceError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise SocialCommerceError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise SocialCommerceError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SocialCommerceError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise SocialCommerceError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedSocialCommerceIntelligenceWorkspace:
    """Deterministic social-commerce contract kernel (BAS-178 first slice)."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def _validate_acquisition_spec(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, Mapping):
            raise SocialCommerceError("acquisition_spec_invalid")
        platform = _text(spec.get("platform"), "platform", maximum=40)
        if platform not in ALLOWED_PLATFORMS:
            raise SocialCommerceError("platform_not_recognized")
        account_ref = _token(spec.get("account_ref"), "account_ref")
        objective = _text(spec.get("objective"), "objective", maximum=500)
        time_range = spec.get("time_range")
        if not isinstance(time_range, Mapping):
            raise SocialCommerceError("time_range_invalid")
        start = _text(time_range.get("start"), "time_range_start", maximum=40)
        end = _text(time_range.get("end"), "time_range_end", maximum=40)
        source_rank = _text(spec.get("source_rank"), "source_rank", maximum=60)
        if source_rank not in ALLOWED_SOURCE_RANKS:
            raise SocialCommerceError("source_rank_not_recognized")
        _safe_tree(dict(spec))
        return {
            "platform": platform,
            "account_ref": account_ref,
            "objective": objective,
            "time_range": {"start": start, "end": end},
            "source_rank": source_rank,
        }

    def _validate_record(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise SocialCommerceError("record_invalid")
        record_id = _token(raw.get("id"), "record_id")
        published_at = _text(raw.get("published_at"), "published_at", maximum=40)
        captured_at = _text(raw.get("captured_at"), "captured_at", maximum=40)
        source_url = _text(raw.get("source_url"), "source_url", maximum=500)
        adapter_version = _text(raw.get("adapter_version"), "adapter_version", maximum=80)
        raw_hash = _hex64(raw.get("raw_hash"), "raw_hash")
        _safe_tree(dict(raw))
        normalized = raw.get("normalized") or {}
        if not isinstance(normalized, Mapping):
            raise SocialCommerceError("normalized_invalid")
        _safe_tree(dict(normalized))
        return {
            "id": record_id,
            "published_at": published_at,
            "captured_at": captured_at,
            "source_url": source_url,
            "adapter_version": adapter_version,
            "raw_hash": raw_hash,
            "normalized": dict(normalized),
        }

    def collect(
        self,
        *,
        spec: dict[str, Any],
        records: list[dict[str, Any]] | None = None,
        checkpoint: str | None = None,
    ) -> ObservationBatch:
        normalized_spec = self._validate_acquisition_spec(spec)
        if checkpoint is not None:
            _token(checkpoint, "checkpoint")

        if records is None:
            # No admitted platform adapter in this slice: truthful not_admitted.
            batch_sha256 = _hash(
                {
                    "contract_id": OBSERVATION_CONTRACT,
                    "platform": normalized_spec["platform"],
                    "account_ref": normalized_spec["account_ref"],
                    "source_rank": normalized_spec["source_rank"],
                    "checkpoint": checkpoint,
                    "adapter_admitted": REAL_PLATFORM_ADAPTERS_ADMITTED,
                }
            )
            return ObservationBatch(
                status="NOT_ADMITTED",
                platform=normalized_spec["platform"],
                contract_id=OBSERVATION_CONTRACT,
                source_rank=normalized_spec["source_rank"],
                adapter_version="not_admitted",
                records=(),
                conserved_total=0,
                dedup_count=0,
                checkpoint=checkpoint,
                coverage=(),
                gaps=("platform_adapter_not_admitted",),
                batch_sha256=batch_sha256,
            )

        if not isinstance(records, list):
            raise SocialCommerceError("records_invalid")

        conserved: list[dict[str, Any]] = []
        seen: set[str] = set()
        dedup_count = 0
        for raw in records:
            record = self._validate_record(raw)
            # Conservation: every valid record retained; dedup is content-addressed
            # by raw hash, never a sampling cap.
            if record["raw_hash"] in seen:
                dedup_count += 1
                continue
            seen.add(record["raw_hash"])
            conserved.append(record)

        next_checkpoint = _hash(
            {
                "last_record_hash": conserved[-1]["raw_hash"] if conserved else None,
                "conserved_total": len(conserved),
            }
        ) if conserved else checkpoint

        batch_document = {
            "contract_id": OBSERVATION_CONTRACT,
            "platform": normalized_spec["platform"],
            "account_ref": normalized_spec["account_ref"],
            "objective": normalized_spec["objective"],
            "time_range": normalized_spec["time_range"],
            "source_rank": normalized_spec["source_rank"],
            "adapter_admitted": REAL_PLATFORM_ADAPTERS_ADMITTED,
            "records": conserved,
            "checkpoint": next_checkpoint,
        }
        batch_sha256 = _hash(batch_document)

        return ObservationBatch(
            status="ADMITTED" if REAL_PLATFORM_ADAPTERS_ADMITTED else "NOT_ADMITTED",
            platform=normalized_spec["platform"],
            contract_id=OBSERVATION_CONTRACT,
            source_rank=normalized_spec["source_rank"],
            adapter_version="synthetic_fixture",
            records=tuple(conserved),
            conserved_total=len(conserved),
            dedup_count=dedup_count,
            checkpoint=next_checkpoint,
            coverage=tuple(sorted(seen)),
            gaps=(),
            batch_sha256=batch_sha256,
        )

    def analyze(
        self,
        *,
        spec: dict[str, Any],
        batch: ObservationBatch,
    ) -> InsightBundle:
        if not isinstance(spec, Mapping):
            raise SocialCommerceError("analysis_spec_invalid")
        dimensions = spec.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise SocialCommerceError("dimensions_invalid")
        normalized_dimensions: list[str] = []
        for dimension in dimensions:
            text = _text(dimension, "dimension", maximum=40)
            if text not in ALLOWED_DIMENSIONS:
                raise SocialCommerceError("dimension_not_recognized")
            if text not in normalized_dimensions:
                normalized_dimensions.append(text)
        _safe_tree(dict(spec))

        # Derived-only analysis: delegate to the deep analyzer when conserved
        # records are available, otherwise keep the truthful placeholder.
        analysis = None
        if batch.records:
            analysis = GovernedSocialIntelligenceAnalysis().analyze(
                list(batch.records), platform=batch.platform
            )

        dimension_analysis = {
            "actor": analysis.seller_segments if analysis else (),
            "conversation": analysis.comment_intents if analysis else (),
            "content": analysis.content_structures if analysis else (),
            "seller_product": analysis.product_demands if analysis else (),
            "time": analysis.calendar if analysis else (),
            "engagement": (),
            "outcome": (),
        }

        patterns: list[dict[str, Any]] = []
        for dimension in normalized_dimensions:
            pattern: dict[str, Any] = {
                "dimension": dimension,
                "record_count": len(batch.records),
                "derived": True,
                "analysis": list(dimension_analysis.get(dimension, ())),
            }
            if analysis is not None:
                pattern["analysis_gaps"] = list(analysis.gaps)
            patterns.append(pattern)

        bundle_document = {
            "contract_id": INSIGHT_CONTRACT,
            "dimensions": normalized_dimensions,
            "patterns": patterns,
            "raw_batch_sha256": batch.batch_sha256,
            "derived_only": True,
        }
        return InsightBundle(
            status="ADMITTED",
            contract_id=INSIGHT_CONTRACT,
            dimensions=tuple(normalized_dimensions),
            patterns=tuple(patterns),
            raw_batch_sha256=batch.batch_sha256,
            derived_only=True,
            bundle_sha256=_hash(bundle_document),
        )

    def _validate_campaign_spec(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, Mapping):
            raise SocialCommerceError("campaign_spec_invalid")
        account_ref = _token(spec.get("account_ref"), "account_ref")
        purpose = _text(spec.get("purpose"), "purpose", maximum=500)
        audience = _text(spec.get("audience"), "audience", maximum=500)
        action_set = spec.get("action_set")
        if not isinstance(action_set, list) or not action_set:
            raise SocialCommerceError("action_set_invalid")
        normalized_actions: list[str] = []
        for action in action_set:
            text = _text(action, "action", maximum=40)
            if text not in ALLOWED_ACTIONS:
                raise SocialCommerceError("action_not_recognized")
            if text not in normalized_actions:
                normalized_actions.append(text)
        budget = spec.get("budget")
        if not isinstance(budget, Mapping):
            raise SocialCommerceError("budget_invalid")
        stop_conditions = spec.get("stop_conditions")
        if not isinstance(stop_conditions, list) or not stop_conditions:
            raise SocialCommerceError("stop_conditions_invalid")
        normalized_stops: list[str] = []
        for stop in stop_conditions:
            text = _text(stop, "stop_condition", maximum=200)
            if text not in normalized_stops:
                normalized_stops.append(text)
        expiry = _text(spec.get("expiry"), "expiry", maximum=40)
        _safe_tree(dict(spec))
        return {
            "account_ref": account_ref,
            "purpose": purpose,
            "audience": audience,
            "action_set": normalized_actions,
            "budget": dict(budget),
            "stop_conditions": normalized_stops,
            "expiry": expiry,
        }

    def _validate_campaign_grant(self, grant: Any) -> dict[str, Any]:
        if not isinstance(grant, Mapping):
            raise SocialCommerceError("campaign_grant_invalid")
        grant_id = _token(grant.get("grant_id"), "grant_id")
        grantor = _token(grant.get("grantor"), "grantor")
        account_ref = _token(grant.get("account_ref"), "account_ref")
        _safe_tree(dict(grant))
        return {"grant_id": grant_id, "grantor": grantor, "account_ref": account_ref}

    def operate(
        self,
        *,
        spec: dict[str, Any],
        grant: dict[str, Any],
        idempotency_key: str,
    ) -> CampaignReceipt:
        normalized_spec = self._validate_campaign_spec(spec)
        normalized_grant = self._validate_campaign_grant(grant)
        _token(idempotency_key, "idempotency_key")

        if normalized_grant["account_ref"] != normalized_spec["account_ref"]:
            raise SocialCommerceError("grant_account_mismatch")

        spec_sha256 = _hash(normalized_spec)
        grant_sha256 = _hash(normalized_grant)

        return CampaignReceipt(
            status="NOT_ADMITTED",
            contract_id=CAMPAIGN_RECEIPT_CONTRACT,
            campaign_spec_sha256=spec_sha256,
            grant_sha256=grant_sha256,
            action_set=tuple(normalized_spec["action_set"]),
            idempotency_key=idempotency_key,
            readback_state="NOT_ATTEMPTED",
            kill_switch=False,
            external_write_allowed=False,
        )

    def readback(self, receipt: CampaignReceipt, *, observed: str | None = None) -> dict[str, Any]:
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == receipt.campaign_spec_sha256
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "CampaignReceipt",
    "GovernedSocialCommerceIntelligenceWorkspace",
    "InsightBundle",
    "ObservationBatch",
    "SocialCommerceError",
    "WORKSPACE_CONTRACT",
]
