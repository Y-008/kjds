"""Governed Social-Commerce Intelligence analysis (BAS-178 analysis slice).

Derives deterministic, read-only intelligence from conserved observation
records. This fills ADR-0090 acceptance #4 (actor/content/comment/time
analysis) and the BAS-178 acceptance outputs: seller segmentation, comment
intent, content structure, product demand, calendar and campaign drafts.

Every output is derived-only (never mutates raw records), content-addressed,
and missing data is reported as an explicit gap instead of being fabricated.
No platform adapter, account binding or external write is implied here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ANALYSIS_CONTRACT = "kjds-social-intelligence-analysis-v1"
ANALYSIS_VERSION = "1.0.0"

ALLOWED_PLATFORMS = frozenset({"xiaohongshu", "douyin"})
ALLOWED_ACCOUNT_TYPES = frozenset({"brand", "creator", "retailer", "unknown"})
ALLOWED_INTENTS = frozenset(
    {"question", "pain_point", "objection", "request", "praise", "unclassified"}
)
ALLOWED_SENTIMENTS = frozenset({"positive", "negative", "neutral", "unclassified"})
ALLOWED_FORMATS = frozenset({"note", "video", "live", "unspecified"})

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")

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


class SocialAnalysisError(ValueError):
    """Stable, non-sensitive contract failure for social intelligence analysis."""


@dataclass(frozen=True)
class SocialAnalysisBundle:
    status: str
    contract_id: str
    platform: str
    record_count: int
    seller_segments: tuple[dict[str, Any], ...]
    comment_intents: tuple[dict[str, Any], ...]
    content_structures: tuple[dict[str, Any], ...]
    product_demands: tuple[dict[str, Any], ...]
    calendar: tuple[dict[str, Any], ...]
    campaign_drafts: tuple[dict[str, Any], ...]
    gaps: tuple[str, ...]
    derived_only: bool
    bundle_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise SocialAnalysisError(f"{name}_invalid")
    if len(value) > maximum:
        raise SocialAnalysisError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if TOKEN.fullmatch(text) is None:
        raise SocialAnalysisError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise SocialAnalysisError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise SocialAnalysisError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise SocialAnalysisError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SocialAnalysisError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise SocialAnalysisError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _norm_enum(value: Any, allowed: frozenset[str], fallback: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    if isinstance(value, str) and value.strip() in allowed:
        return value.strip()
    return fallback


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item)
    return out


def _sub(record: Mapping[str, Any], key: str) -> Any:
    normalized = record.get("normalized")
    if not isinstance(normalized, Mapping):
        return None
    return normalized.get(key)


def _sub_map(record: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = _sub(record, key)
    return value if isinstance(value, Mapping) else None


class GovernedSocialIntelligenceAnalysis:
    """Deterministic, read-only social intelligence analyzer (BAS-178 analysis)."""

    def _validate_records(self, records: Any) -> list[dict[str, Any]]:
        if not isinstance(records, (list, tuple, Sequence)):
            raise SocialAnalysisError("records_invalid")
        if not records:
            raise SocialAnalysisError("records_empty")
        validated: list[dict[str, Any]] = []
        for raw in records:
            if not isinstance(raw, Mapping):
                raise SocialAnalysisError("record_invalid")
            _safe_tree(dict(raw))
            validated.append(dict(raw))
        return validated

    def _seller_segments(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        segments: dict[str, dict[str, Any]] = {}
        seen_actors: set[str] = set()
        for record in records:
            actor = _sub_map(record, "actor")
            if actor is None:
                continue
            account_ref = actor.get("account_ref") or actor.get("account_id") or actor.get("id")
            if not isinstance(account_ref, str) or not account_ref:
                continue
            if account_ref in seen_actors:
                continue
            seen_actors.add(account_ref)
            account_type = _norm_enum(actor.get("account_type"), ALLOWED_ACCOUNT_TYPES, "unknown")
            verification = actor.get("verification")
            audience = _as_non_negative_int(actor.get("audience_total"))
            bucket = segments.setdefault(
                account_type,
                {
                    "account_type": account_type,
                    "actor_count": 0,
                    "verified_count": 0,
                    "unverified_count": 0,
                    "unknown_verification_count": 0,
                    "audience_total_sum": 0,
                    "audience_total_max": 0,
                },
            )
            bucket["actor_count"] += 1
            if verification is True:
                bucket["verified_count"] += 1
            elif verification is False:
                bucket["unverified_count"] += 1
            else:
                bucket["unknown_verification_count"] += 1
            if audience is not None:
                bucket["audience_total_sum"] += audience
                bucket["audience_total_max"] = max(bucket["audience_total_max"], audience)
        gaps: list[str] = []
        if not segments:
            gaps.append("seller_segmentation_no_actor_data")
        ordered = sorted(segments.values(), key=lambda item: (item["account_type"], item["actor_count"]))
        return ordered, gaps

    def _comment_intents(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        intents: dict[str, dict[str, Any]] = {}
        for record in records:
            conversation = _sub(record, "conversation")
            items: list[Any] = []
            if isinstance(conversation, Mapping):
                items = [conversation]
            elif isinstance(conversation, (list, tuple)):
                items = list(conversation)
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                intent = _norm_enum(item.get("intent"), ALLOWED_INTENTS, "unclassified")
                sentiment = _norm_enum(item.get("sentiment"), ALLOWED_SENTIMENTS, "unclassified")
                responded = item.get("seller_response_status")
                bucket = intents.setdefault(
                    intent,
                    {
                        "intent": intent,
                        "comment_count": 0,
                        "sentiment_counts": {},
                        "seller_responded_count": 0,
                        "seller_unresponded_count": 0,
                    },
                )
                bucket["comment_count"] += 1
                bucket["sentiment_counts"][sentiment] = bucket["sentiment_counts"].get(sentiment, 0) + 1
                if responded is True or (isinstance(responded, str) and responded.lower() in {"responded", "true"}):
                    bucket["seller_responded_count"] += 1
                else:
                    bucket["seller_unresponded_count"] += 1
        gaps: list[str] = []
        if not intents:
            gaps.append("comment_intent_no_conversation_data")
        ordered: list[dict[str, Any]] = []
        for item in sorted(intents.values(), key=lambda item: item["intent"]):
            item = dict(item)
            item["sentiment_counts"] = dict(sorted(item["sentiment_counts"].items()))
            ordered.append(item)
        return ordered, gaps

    def _content_structures(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        format_counts: Counter[str] = Counter()
        hashtag_counts: Counter[str] = Counter()
        topic_counts: Counter[str] = Counter()
        hook_present = 0
        content_count = 0
        for record in records:
            content = _sub_map(record, "content")
            if content is None:
                continue
            content_count += 1
            fmt = _norm_enum(content.get("format"), ALLOWED_FORMATS, "unspecified")
            format_counts[fmt] += 1
            for hashtag in _as_str_list(content.get("hashtags")):
                hashtag_counts[hashtag] += 1
            for topic in _as_str_list(content.get("topics")):
                topic_counts[topic] += 1
            hook = content.get("hook")
            if isinstance(hook, str) and hook:
                hook_present += 1
        gaps: list[str] = []
        if content_count == 0:
            gaps.append("content_structure_no_content_data")
        result = [
            {
                "content_count": content_count,
                "format_counts": dict(sorted(format_counts.items())),
                "hashtag_frequency": dict(sorted(hashtag_counts.items())),
                "topic_frequency": dict(sorted(topic_counts.items())),
                "hook_present_count": hook_present,
            }
        ]
        return result, gaps

    def _product_demands(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        product_counts: Counter[str] = Counter()
        topic_counts: Counter[str] = Counter()
        topic_product: Counter[tuple[str, str]] = Counter()
        product_seen = False
        for record in records:
            content = _sub_map(record, "content")
            seller_product = _sub_map(record, "seller_product")
            mentions = _as_str_list((content or {}).get("product_mentions"))
            product_refs: list[str] = []
            if mentions:
                product_refs.extend(mentions)
                product_seen = True
            for key in ("product_sku", "product_ref", "shop"):
                value = (seller_product or {}).get(key)
                if isinstance(value, str) and value:
                    product_refs.append(value)
                    product_seen = True
            topics = _as_str_list((content or {}).get("topics"))
            for product in product_refs:
                product_counts[product] += 1
                for topic in topics:
                    topic_counts[topic] += 1
                    topic_product[(topic, product)] += 1
        gaps: list[str] = []
        if not product_seen:
            gaps.append("product_demand_no_product_mentions")
        result = [
            {
                "product_frequency": dict(sorted(product_counts.items())),
                "topic_frequency": dict(sorted(topic_counts.items())),
                "topic_product_cooccurrence": [
                    {"topic": topic, "product": product, "count": count}
                    for (topic, product), count in sorted(topic_product.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
                ],
            }
        ]
        return result, gaps

    def _calendar(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        date_counts: Counter[str] = Counter()
        for record in records:
            published = record.get("published_at")
            if not isinstance(published, str) or not published:
                continue
            match = DATE_PREFIX.match(published.strip())
            if match:
                date_counts[match.group(0)] += 1
        gaps: list[str] = []
        if not date_counts:
            gaps.append("calendar_no_published_at")
        dates = sorted(date_counts.keys())
        posts_per_date = [{"date": date, "post_count": date_counts[date]} for date in dates]
        total = sum(date_counts.values())
        cadence_average = round(total / len(dates), 4) if dates else 0.0
        result = [
            {
                "distinct_dates": len(dates),
                "total_posts": total,
                "cadence_average_per_day": cadence_average,
                "posts_per_date": posts_per_date,
            }
        ]
        return result, gaps

    def _campaign_drafts(self, records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        product_counts: Counter[str] = Counter()
        topic_counts: Counter[str] = Counter()
        audience_types: Counter[str] = Counter()
        for record in records:
            content = _sub_map(record, "content")
            seller_product = _sub_map(record, "seller_product")
            actor = _sub_map(record, "actor")
            mentions = _as_str_list((content or {}).get("product_mentions"))
            for product in mentions:
                product_counts[product] += 1
            for key in ("product_sku", "product_ref", "shop"):
                value = (seller_product or {}).get(key)
                if isinstance(value, str) and value:
                    product_counts[value] += 1
            for topic in _as_str_list((content or {}).get("topics")):
                topic_counts[topic] += 1
            if actor is not None:
                audience_types[_norm_enum(actor.get("account_type"), ALLOWED_ACCOUNT_TYPES, "unknown")] += 1

        gaps: list[str] = []
        if not product_counts or not topic_counts or not audience_types:
            gaps.append("campaign_draft_insufficient_data")
            return [], gaps

        top_product = product_counts.most_common(1)[0][0]
        top_topic = topic_counts.most_common(1)[0][0]
        top_audience = audience_types.most_common(1)[0][0]
        draft = {
            "status": "DRAFT",
            "objective": f"demand_discovery_for_{top_topic}",
            "product_refs": [top_product],
            "content_themes": [top_topic],
            "audience_segment": top_audience,
            "derived_from_observed_top_signals_only": True,
            "execution_allowed": False,
        }
        return [draft], gaps

    def analyze(
        self,
        records: Any,
        *,
        platform: str,
    ) -> SocialAnalysisBundle:
        platform = _text(platform, "platform", maximum=40)
        if platform not in ALLOWED_PLATFORMS:
            raise SocialAnalysisError("platform_not_recognized")
        validated = self._validate_records(records)

        seller_segments, seller_gaps = self._seller_segments(validated)
        comment_intents, comment_gaps = self._comment_intents(validated)
        content_structures, content_gaps = self._content_structures(validated)
        product_demands, product_gaps = self._product_demands(validated)
        calendar, calendar_gaps = self._calendar(validated)
        campaign_drafts, campaign_gaps = self._campaign_drafts(validated)

        gaps = sorted(set(seller_gaps + comment_gaps + content_gaps + product_gaps + calendar_gaps + campaign_gaps))

        document = {
            "contract_id": ANALYSIS_CONTRACT,
            "contract_version": ANALYSIS_VERSION,
            "platform": platform,
            "record_count": len(validated),
            "seller_segments": seller_segments,
            "comment_intents": comment_intents,
            "content_structures": content_structures,
            "product_demands": product_demands,
            "calendar": calendar,
            "campaign_drafts": campaign_drafts,
            "gaps": gaps,
            "derived_only": True,
        }
        return SocialAnalysisBundle(
            status="ADMITTED",
            contract_id=ANALYSIS_CONTRACT,
            platform=platform,
            record_count=len(validated),
            seller_segments=tuple(seller_segments),
            comment_intents=tuple(comment_intents),
            content_structures=tuple(content_structures),
            product_demands=tuple(product_demands),
            calendar=tuple(calendar),
            campaign_drafts=tuple(campaign_drafts),
            gaps=tuple(gaps),
            derived_only=True,
            bundle_sha256=_hash(document),
        )

    def readback(
        self,
        bundle: SocialAnalysisBundle,
        *,
        observed: str | None = None,
    ) -> dict[str, Any]:
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == bundle.bundle_sha256
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "GovernedSocialIntelligenceAnalysis",
    "SocialAnalysisBundle",
    "SocialAnalysisError",
    "ANALYSIS_CONTRACT",
]
