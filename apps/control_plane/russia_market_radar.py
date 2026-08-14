"""Governed Russia market demand & hot-event radar contract kernel (BAS-179 prep-only slice).

Freezes ADR-0091 acceptance #3: Russian morphology/query expansion, cross-source
content-addressed deduplication, event-time ordering and decomposed hot-event
scoring, plus decomposed demand projection with source lineage. No marketplace
adapter, account binding, search identity or external write is admitted here;
missing data is reported as UNKNOWN, never fabricated, and no signal becomes a
Fact, FinanceEntry, Purchase, Campaign or Profit write.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

RADAR_CONTRACT = "kjds-russia-market-radar-v1"
RADAR_VERSION = "1.0.0"
QUERY_TAXONOMY_CONTRACT = "kjds-russia-demand-query-taxonomy-v1"
EVENT_TAXONOMY_CONTRACT = "kjds-russia-hot-event-taxonomy-v1"
OBSERVATION_CONTRACT = "kjds-russia-market-observation-v1"

REAL_SOURCE_ADAPTERS_ADMITTED = False

ALLOWED_MARKETS = frozenset({"ru"})

ALLOWED_SIGNAL_DOMAINS = frozenset(
    {
        "marketplace_search_and_funnel",
        "search_engine_demand",
        "price_promotion_stock_and_review",
        "public_social_and_creator_conversation",
        "platform_product_and_policy_change",
        "currency_inflation_and_financing",
        "trade_customs_logistics_and_regulation",
        "seasonal_calendar_and_breaking_event",
    }
)

ALLOWED_SOURCE_CLASSES = frozenset(
    {
        "official_authorized_marketplace",
        "official_authorized_search_demand",
        "official_authorized_public_social",
        "official_public_economic",
        "official_public_platform_change",
    }
)

ALLOWED_QUERY_DIMENSIONS = frozenset(
    {"word_form", "synonym", "category", "question", "scenario", "brand"}
)

DEMAND_DIMENSIONS = (
    "search_volume",
    "marketplace_funnel",
    "price_change",
    "review_sentiment",
    "stock_change",
    "social_spread",
    "macro_or_policy_signal",
)

SOURCE_CLASS_BY_ID = {
    "ozon_seller_analytics": "official_authorized_marketplace",
    "wildberries_seller_analytics": "official_authorized_marketplace",
    "yandex_market_partner": "official_authorized_marketplace",
    "yandex_wordstat": "official_authorized_search_demand",
    "telegram_public_market_conversation": "official_authorized_public_social",
    "vk_public_and_owned_community": "official_authorized_public_social",
    "bank_of_russia_macro_events": "official_public_economic",
    "platform_release_and_policy_events": "official_public_platform_change",
}

ALLOWED_SOURCE_IDS = frozenset(SOURCE_CLASS_BY_ID)

SOURCE_AUTHORITY_WEIGHTS = {
    "official_authorized_marketplace": 1.0,
    "official_authorized_search_demand": 0.9,
    "official_public_economic": 0.8,
    "official_public_platform_change": 0.8,
    "official_authorized_public_social": 0.7,
}

SCORING_INPUTS = (
    "source_authority",
    "recency",
    "velocity",
    "cross_source_count",
    "entity_relevance",
    "profit_or_supply_exposure",
    "observed_market_response",
)

SCORING_WEIGHTS = {
    "source_authority": 1.0,
    "recency": 1.0,
    "velocity": 1.0,
    "cross_source_count": 1.0,
    "entity_relevance": 1.0,
    "profit_or_supply_exposure": 1.0,
    "observed_market_response": 2.0,
}

CROSS_SOURCE_ESCALATION_MIN = 2

STATUSES = frozenset({"ADMITTED", "NOT_ADMITTED", "STALE", "INVALIDATED"})

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

# Frozen, clearly synthetic demo lexicon for the Russian query taxonomy. It is
# a contract fixture only, never a claim about real Russian search demand.
SYNTHETIC_MORPHOLOGY: dict[str, tuple[tuple[str, str], ...]] = {
    "платье": (
        ("word_form", "платье"),
        ("word_form", "платья"),
        ("word_form", "платью"),
        ("word_form", "платьем"),
        ("word_form", "платьев"),
        ("synonym", "сарафан"),
        ("synonym", "вечернее платье"),
        ("category", "женская одежда"),
        ("question", "как выбрать платье"),
        ("question", "какое платье купить"),
        ("scenario", "выпускной"),
        ("scenario", "свадьба"),
    ),
    "наушники": (
        ("word_form", "наушники"),
        ("word_form", "наушников"),
        ("word_form", "наушникам"),
        ("word_form", "наушниками"),
        ("word_form", "наушниках"),
        ("synonym", "гарнитура"),
        ("synonym", "tws наушники"),
        ("category", "электроника"),
        ("question", "какие наушники купить"),
        ("scenario", "спорт"),
        ("scenario", "игры"),
    ),
}


class RussiaRadarError(ValueError):
    """Stable, non-sensitive contract failure for the Russia market radar."""


@dataclass(frozen=True)
class QueryVariant:
    term: str
    dimension: str
    seed: str
    provenance: str


@dataclass(frozen=True)
class ExpandedQuerySet:
    status: str
    contract_id: str
    market: str
    seeds: tuple[str, ...]
    variants: tuple[QueryVariant, ...]
    distinct_terms: int
    dedup_count: int
    gaps: tuple[str, ...]
    query_sha256: str


@dataclass(frozen=True)
class RussiaRadarObservation:
    status: str
    contract_id: str
    market: str
    records: tuple[dict[str, Any], ...]
    conserved_total: int
    quarantined_total: int
    dedup_count: int
    source_total: int
    conservation_ok: bool
    cross_source_links: tuple[dict[str, Any], ...]
    checkpoint: str | None
    gaps: tuple[str, ...]
    batch_sha256: str


@dataclass(frozen=True)
class DemandSignal:
    status: str
    contract_id: str
    signal_id: str
    domain: str
    entity_ref: str | None
    region: str | None
    observed_at: str
    effective_at: str
    as_of: str
    exact_scope: str
    authority: str
    source_ids: tuple[str, ...]
    dimensions: tuple[dict[str, Any], ...]
    unknowns: tuple[str, ...]
    signal_sha256: str


@dataclass(frozen=True)
class HotEventCandidate:
    status: str
    contract_id: str
    event_id: str
    score: float | None
    components: tuple[dict[str, Any], ...]
    source_ids: tuple[str, ...]
    first_seen_at: str
    last_seen_at: str
    effective_at: str
    expiry_or_review_at: str | None
    unknowns: tuple[str, ...]
    escalation_eligible: bool
    external_action_allowed: bool
    event_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise RussiaRadarError(f"{name}_invalid")
    if len(value) > maximum:
        raise RussiaRadarError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise RussiaRadarError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise RussiaRadarError(f"{name}_invalid")
    return text


def _norm_enum(value: Any, allowed: frozenset[str], name: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    raise RussiaRadarError(f"{name}_not_recognized")


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _as_unit_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 0.0 <= value <= 1.0:
        return float(value)
    return None


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise RussiaRadarError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise RussiaRadarError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise RussiaRadarError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise RussiaRadarError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normalize_ru_term(value: Any) -> str:
    text = value.strip().lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RussiaRadarError("time_invalid") from exc


class GovernedRussiaMarketRadar:
    """Deterministic Russia market demand & hot-event radar contract kernel."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def _validate_market(self, market: Any) -> str:
        market = _text(market, "market", maximum=8)
        if market not in ALLOWED_MARKETS:
            raise RussiaRadarError("market_not_recognized")
        return market

    # ---- query taxonomy / Russian morphology ----

    def expand_queries(
        self,
        *,
        seeds: list[str] | tuple[str, ...],
        expansion: dict[str, Any] | None = None,
        market: str = "ru",
    ) -> ExpandedQuerySet:
        market = self._validate_market(market)
        if not isinstance(seeds, (list, tuple)) or not seeds:
            raise RussiaRadarError("seeds_invalid")

        normalized_seeds: list[str] = []
        for seed in seeds:
            seed_text = _text(seed, "seed", maximum=200)
            _safe_tree(seed_text)
            normalized_seed = _normalize_ru_term(seed_text)
            if not normalized_seed:
                raise RussiaRadarError("seed_invalid")
            if normalized_seed not in normalized_seeds:
                normalized_seeds.append(normalized_seed)

        variants: list[QueryVariant] = []
        seen_pairs: set[tuple[str, str]] = set()
        distinct_terms: set[str] = set()
        dedup_count = 0
        gaps: list[str] = []

        def _append(seed: str, term: str, dimension: str, provenance: str) -> None:
            nonlocal dedup_count
            normalized = _normalize_ru_term(term)
            if not normalized:
                return
            pair = (normalized, dimension)
            if pair in seen_pairs:
                dedup_count += 1
                return
            seen_pairs.add(pair)
            distinct_terms.add(normalized)
            variants.append(QueryVariant(term=normalized, dimension=dimension, seed=seed, provenance=provenance))

        for normalized_seed in normalized_seeds:
            if normalized_seed in SYNTHETIC_MORPHOLOGY:
                for dimension, term in SYNTHETIC_MORPHOLOGY[normalized_seed]:
                    _append(normalized_seed, term, dimension, "synthetic_lexicon")

        caller_seeds: set[str] = set()
        if expansion is not None:
            if not isinstance(expansion, Mapping):
                raise RussiaRadarError("expansion_invalid")
            _safe_tree(dict(expansion))
            for seed, entries in expansion.items():
                normalized_seed = _normalize_ru_term(_text(seed, "expansion_seed", maximum=200))
                if normalized_seed not in normalized_seeds:
                    raise RussiaRadarError("expansion_seed_unknown")
                if not isinstance(entries, list):
                    raise RussiaRadarError("expansion_entries_invalid")
                for entry in entries:
                    if not isinstance(entry, Mapping):
                        raise RussiaRadarError("expansion_entry_invalid")
                    dimension = _norm_enum(entry.get("dimension"), ALLOWED_QUERY_DIMENSIONS, "dimension")
                    term = _text(entry.get("term"), "expansion_term", maximum=200)
                    _append(normalized_seed, term, dimension, "caller_expansion")
                    caller_seeds.add(normalized_seed)

        for normalized_seed in normalized_seeds:
            if normalized_seed not in SYNTHETIC_MORPHOLOGY and normalized_seed not in caller_seeds:
                gaps.append(f"no_known_expansion:{normalized_seed}")

        document = {
            "contract_id": QUERY_TAXONOMY_CONTRACT,
            "market": market,
            "seeds": normalized_seeds,
            "variants": [
                {"term": v.term, "dimension": v.dimension, "seed": v.seed, "provenance": v.provenance}
                for v in variants
            ],
            "distinct_terms": len(distinct_terms),
            "dedup_count": dedup_count,
            "gaps": sorted(gaps),
        }
        return ExpandedQuerySet(
            status="ADMITTED",
            contract_id=QUERY_TAXONOMY_CONTRACT,
            market=market,
            seeds=tuple(normalized_seeds),
            variants=tuple(variants),
            distinct_terms=len(distinct_terms),
            dedup_count=dedup_count,
            gaps=tuple(sorted(gaps)),
            query_sha256=_hash(document),
        )

    # ---- collection / cross-source dedup ----

    def _validate_collection_spec(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, Mapping):
            raise RussiaRadarError("collection_spec_invalid")
        market = self._validate_market(spec.get("market"))
        objective = _text(spec.get("objective"), "objective", maximum=500)
        time_range = spec.get("time_range")
        if not isinstance(time_range, Mapping):
            raise RussiaRadarError("time_range_invalid")
        start = _text(time_range.get("start"), "time_range_start", maximum=40)
        end = _text(time_range.get("end"), "time_range_end", maximum=40)
        exact_scope = _text(spec.get("exact_scope"), "exact_scope", maximum=200)
        authority = _text(spec.get("authority"), "authority", maximum=200)
        source_total = spec.get("source_total")
        if source_total is not None and _as_non_negative_int(source_total) is None:
            raise RussiaRadarError("source_total_invalid")
        _safe_tree(dict(spec))
        return {
            "market": market,
            "objective": objective,
            "time_range": {"start": start, "end": end},
            "exact_scope": exact_scope,
            "authority": authority,
            "source_total": _as_non_negative_int(source_total) if source_total is not None else None,
        }

    def _validate_observation(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise RussiaRadarError("observation_invalid")
        observation_id = _token(raw.get("id"), "observation_id")
        source_id = _norm_enum(raw.get("source_id"), ALLOWED_SOURCE_IDS, "source_id")
        source_class = _norm_enum(raw.get("source_class"), ALLOWED_SOURCE_CLASSES, "source_class")
        if SOURCE_CLASS_BY_ID[source_id] != source_class:
            raise RussiaRadarError("source_class_mismatch")
        domain = _norm_enum(raw.get("domain"), ALLOWED_SIGNAL_DOMAINS, "domain")
        content_hash = _hex64(raw.get("content_hash"), "content_hash")
        observed_at = _text(raw.get("observed_at"), "observed_at", maximum=40)
        effective_at = _text(raw.get("effective_at"), "effective_at", maximum=40)
        entity_ref = raw.get("entity_ref")
        if entity_ref is not None:
            entity_ref = _text(entity_ref, "entity_ref", maximum=200)
        region = raw.get("region")
        if region is not None:
            region = _text(region, "region", maximum=80)
        payload = raw.get("payload") or {}
        if not isinstance(payload, Mapping):
            raise RussiaRadarError("payload_invalid")
        _safe_tree(dict(raw))
        return {
            "id": observation_id,
            "source_id": source_id,
            "source_class": source_class,
            "domain": domain,
            "content_hash": content_hash,
            "observed_at": observed_at,
            "effective_at": effective_at,
            "entity_ref": entity_ref,
            "region": region,
            "payload": dict(payload),
        }

    def collect(
        self,
        *,
        spec: dict[str, Any],
        observations: list[dict[str, Any]] | None = None,
        checkpoint: str | None = None,
    ) -> RussiaRadarObservation:
        normalized_spec = self._validate_collection_spec(spec)
        if checkpoint is not None:
            _token(checkpoint, "checkpoint")

        if observations is None:
            document = {
                "contract_id": OBSERVATION_CONTRACT,
                "market": normalized_spec["market"],
                "checkpoint": checkpoint,
                "adapter_admitted": REAL_SOURCE_ADAPTERS_ADMITTED,
            }
            return RussiaRadarObservation(
                status="NOT_ADMITTED",
                contract_id=OBSERVATION_CONTRACT,
                market=normalized_spec["market"],
                records=(),
                conserved_total=0,
                quarantined_total=0,
                dedup_count=0,
                source_total=0,
                conservation_ok=True,
                cross_source_links=(),
                checkpoint=checkpoint,
                gaps=("source_adapter_not_admitted",),
                batch_sha256=_hash(document),
            )

        if not isinstance(observations, list):
            raise RussiaRadarError("observations_invalid")

        conserved_by_content: dict[str, dict[str, Any]] = {}
        conserved_order: list[str] = []
        quarantined_total = 0
        dedup_count = 0

        for raw in observations:
            try:
                observation = self._validate_observation(raw)
            except RussiaRadarError:
                quarantined_total += 1
                continue
            key = observation["content_hash"]
            if key in conserved_by_content:
                existing = conserved_by_content[key]
                if observation["source_id"] not in existing["source_ids"]:
                    existing["source_ids"].append(observation["source_id"])
                    existing["source_classes"].add(observation["source_class"])
                dedup_count += 1
                continue
            conserved_by_content[key] = {
                "id": observation["id"],
                "content_hash": key,
                "domain": observation["domain"],
                "source_ids": [observation["source_id"]],
                "source_classes": {observation["source_class"]},
                "observed_at": observation["observed_at"],
                "effective_at": observation["effective_at"],
                "entity_ref": observation["entity_ref"],
                "region": observation["region"],
                "payload": observation["payload"],
            }
            conserved_order.append(key)

        conserved_records: list[dict[str, Any]] = []
        for key in conserved_order:
            rec = conserved_by_content[key]
            conserved_records.append(
                {
                    "id": rec["id"],
                    "content_hash": rec["content_hash"],
                    "domain": rec["domain"],
                    "source_ids": tuple(rec["source_ids"]),
                    "source_classes": tuple(sorted(rec["source_classes"])),
                    "observed_at": rec["observed_at"],
                    "effective_at": rec["effective_at"],
                    "entity_ref": rec["entity_ref"],
                    "region": rec["region"],
                    "payload": dict(rec["payload"]),
                }
            )

        observed_total = len(observations)
        reported_total = normalized_spec["source_total"]
        source_total = reported_total if reported_total is not None else observed_total

        conserved_total = len(conserved_order)
        accepted_total = conserved_total + dedup_count
        conservation_ok = accepted_total + quarantined_total == source_total

        gaps: list[str] = []
        if reported_total is not None and reported_total != observed_total:
            gaps.append("failed_or_pending_pages")

        cross_source_links = [
            {
                "content_hash": key,
                "source_ids": tuple(conserved_by_content[key]["source_ids"]),
                "cross_source_count": len(conserved_by_content[key]["source_ids"]),
            }
            for key in conserved_order
            if len(conserved_by_content[key]["source_ids"]) > 1
        ]

        next_checkpoint = (
            _hash(
                {
                    "last_content_hash": conserved_order[-1],
                    "conserved_total": conserved_total,
                }
            )
            if conserved_order
            else checkpoint
        )

        document = {
            "contract_id": OBSERVATION_CONTRACT,
            "market": normalized_spec["market"],
            "objective": normalized_spec["objective"],
            "time_range": normalized_spec["time_range"],
            "exact_scope": normalized_spec["exact_scope"],
            "authority": normalized_spec["authority"],
            "adapter_admitted": REAL_SOURCE_ADAPTERS_ADMITTED,
            "records": conserved_records,
            "conserved_total": conserved_total,
            "quarantined_total": quarantined_total,
            "dedup_count": dedup_count,
            "source_total": source_total,
            "conservation_ok": conservation_ok,
            "cross_source_links": cross_source_links,
            "checkpoint": next_checkpoint,
            "gaps": sorted(gaps),
        }

        return RussiaRadarObservation(
            status="ADMITTED" if REAL_SOURCE_ADAPTERS_ADMITTED else "NOT_ADMITTED",
            contract_id=OBSERVATION_CONTRACT,
            market=normalized_spec["market"],
            records=tuple(conserved_records),
            conserved_total=conserved_total,
            quarantined_total=quarantined_total,
            dedup_count=dedup_count,
            source_total=source_total,
            conservation_ok=conservation_ok,
            cross_source_links=tuple(cross_source_links),
            checkpoint=next_checkpoint,
            gaps=tuple(sorted(gaps)),
            batch_sha256=_hash(document),
        )

    # ---- decomposed demand projection ----

    def project_demand(
        self,
        *,
        observation: RussiaRadarObservation,
        spec: dict[str, Any],
    ) -> tuple[DemandSignal, ...]:
        if not isinstance(spec, Mapping):
            raise RussiaRadarError("demand_spec_invalid")
        exact_scope = _text(spec.get("exact_scope"), "exact_scope", maximum=200)
        authority = _text(spec.get("authority"), "authority", maximum=200)
        as_of = _text(spec.get("as_of"), "as_of", maximum=40)
        _safe_tree(dict(spec))

        signals: list[DemandSignal] = []
        for record in observation.records:
            dimensions, unknowns = self._decompose_dimensions(record)
            document = {
                "contract_id": RADAR_CONTRACT,
                "signal_id": record["id"],
                "domain": record["domain"],
                "entity_ref": record["entity_ref"],
                "region": record["region"],
                "observed_at": record["observed_at"],
                "effective_at": record["effective_at"],
                "as_of": as_of,
                "exact_scope": exact_scope,
                "authority": authority,
                "source_ids": list(record["source_ids"]),
                "dimensions": dimensions,
                "unknowns": unknowns,
                "derived_only": True,
            }
            signals.append(
                DemandSignal(
                    status="ADMITTED",
                    contract_id=RADAR_CONTRACT,
                    signal_id=record["id"],
                    domain=record["domain"],
                    entity_ref=record["entity_ref"],
                    region=record["region"],
                    observed_at=record["observed_at"],
                    effective_at=record["effective_at"],
                    as_of=as_of,
                    exact_scope=exact_scope,
                    authority=authority,
                    source_ids=record["source_ids"],
                    dimensions=tuple(dimensions),
                    unknowns=tuple(unknowns),
                    signal_sha256=_hash(document),
                )
            )
        return tuple(signals)

    def _decompose_dimensions(self, record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        payload = record["payload"]
        dimensions: list[dict[str, Any]] = []
        unknowns: list[str] = []
        for dimension in DEMAND_DIMENSIONS:
            value = payload.get(dimension)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                dimensions.append({"dimension": dimension, "value": value, "status": "PRESENT"})
            else:
                dimensions.append({"dimension": dimension, "value": None, "status": "UNKNOWN"})
                unknowns.append(dimension)
        return dimensions, unknowns

    # ---- hot-event scoring / ordering ----

    def _validate_event(self, event: Any) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise RussiaRadarError("event_invalid")
        event_id = _token(event.get("event_id"), "event_id")
        source_ids = event.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise RussiaRadarError("source_ids_invalid")
        normalized_source_ids: list[str] = []
        for source_id in source_ids:
            sid = _norm_enum(source_id, ALLOWED_SOURCE_IDS, "source_id")
            if sid not in normalized_source_ids:
                normalized_source_ids.append(sid)
        first_seen_at = _text(event.get("first_seen_at"), "first_seen_at", maximum=40)
        last_seen_at = _text(event.get("last_seen_at"), "last_seen_at", maximum=40)
        effective_at = _text(event.get("effective_at"), "effective_at", maximum=40)
        expiry_or_review_at = event.get("expiry_or_review_at")
        if expiry_or_review_at is not None:
            expiry_or_review_at = _text(expiry_or_review_at, "expiry_or_review_at", maximum=40)
        components = event.get("components")
        if not isinstance(components, Mapping):
            raise RussiaRadarError("components_invalid")
        for key in components:
            if key not in SCORING_INPUTS:
                raise RussiaRadarError("component_not_recognized")
        _safe_tree(dict(event))
        return {
            "event_id": event_id,
            "source_ids": normalized_source_ids,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "effective_at": effective_at,
            "expiry_or_review_at": expiry_or_review_at,
            "components": dict(components),
        }

    def score_event(self, *, event: dict[str, Any], now: str | None = None) -> HotEventCandidate:
        normalized = self._validate_event(event)

        source_authority = max(
            SOURCE_AUTHORITY_WEIGHTS[SOURCE_CLASS_BY_ID[sid]] for sid in normalized["source_ids"]
        )
        cross_source_count = len(normalized["source_ids"])

        raw_values: dict[str, Any] = {
            "source_authority": source_authority,
            "cross_source_count": cross_source_count,
        }
        component_values: dict[str, float | None] = {
            "source_authority": source_authority,
            "cross_source_count": min(cross_source_count / CROSS_SOURCE_ESCALATION_MIN, 1.0),
        }
        for name in SCORING_INPUTS:
            if name in ("source_authority", "cross_source_count"):
                continue
            raw = normalized["components"].get(name)
            raw_values[name] = raw
            if raw is None or raw == "UNKNOWN":
                component_values[name] = None
                continue
            unit = _as_unit_float(raw)
            if unit is None:
                raise RussiaRadarError(f"{name}_invalid")
            component_values[name] = unit

        present = [name for name in SCORING_INPUTS if component_values[name] is not None]
        if present:
            weighted_sum = sum(SCORING_WEIGHTS[name] * (component_values[name] or 0.0) for name in present)
            total_weight = sum(SCORING_WEIGHTS[name] for name in present)
            score = round(weighted_sum / total_weight, 6)
        else:
            score = None

        components: list[dict[str, Any]] = []
        for name in SCORING_INPUTS:
            components.append(
                {
                    "input": name,
                    "raw": raw_values.get(name),
                    "normalized": component_values[name],
                    "status": "PRESENT" if component_values[name] is not None else "UNKNOWN",
                    "weight": SCORING_WEIGHTS[name],
                }
            )

        unknowns = [name for name in SCORING_INPUTS if component_values[name] is None]
        stale = False
        if now is not None and normalized["expiry_or_review_at"] is not None:
            try:
                stale = _parse_time(normalized["expiry_or_review_at"]) < _parse_time(now)
            except RussiaRadarError:
                stale = False
        if stale:
            unknowns.append("stale_or_review_due")
        unknowns = sorted(set(unknowns))

        escalation_eligible = (
            score is not None
            and cross_source_count >= CROSS_SOURCE_ESCALATION_MIN
            and component_values["observed_market_response"] is not None
        )

        document = {
            "contract_id": EVENT_TAXONOMY_CONTRACT,
            "event_id": normalized["event_id"],
            "score": score,
            "components": components,
            "source_ids": normalized["source_ids"],
            "first_seen_at": normalized["first_seen_at"],
            "last_seen_at": normalized["last_seen_at"],
            "effective_at": normalized["effective_at"],
            "expiry_or_review_at": normalized["expiry_or_review_at"],
            "unknowns": unknowns,
            "escalation_eligible": escalation_eligible,
            "external_action_allowed": False,
        }
        return HotEventCandidate(
            status="STALE" if stale else "ADMITTED",
            contract_id=EVENT_TAXONOMY_CONTRACT,
            event_id=normalized["event_id"],
            score=score,
            components=tuple(components),
            source_ids=tuple(normalized["source_ids"]),
            first_seen_at=normalized["first_seen_at"],
            last_seen_at=normalized["last_seen_at"],
            effective_at=normalized["effective_at"],
            expiry_or_review_at=normalized["expiry_or_review_at"],
            unknowns=tuple(unknowns),
            escalation_eligible=escalation_eligible,
            external_action_allowed=False,
            event_sha256=_hash(document),
        )

    def order_events(
        self,
        *,
        events: list[dict[str, Any]],
        now: str | None = None,
    ) -> tuple[HotEventCandidate, ...]:
        if not isinstance(events, list):
            raise RussiaRadarError("events_invalid")
        scored = [self.score_event(event=event, now=now) for event in events]
        return tuple(
            sorted(
                scored,
                key=lambda candidate: (
                    _parse_time(candidate.effective_at),
                    _parse_time(candidate.first_seen_at),
                    candidate.event_id,
                ),
            )
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if isinstance(obj, ExpandedQuerySet):
            digest = obj.query_sha256
        elif isinstance(obj, RussiaRadarObservation):
            digest = obj.batch_sha256
        elif isinstance(obj, DemandSignal):
            digest = obj.signal_sha256
        elif isinstance(obj, HotEventCandidate):
            digest = obj.event_sha256
        else:
            raise RussiaRadarError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == digest
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "DemandSignal",
    "ExpandedQuerySet",
    "GovernedRussiaMarketRadar",
    "HotEventCandidate",
    "QueryVariant",
    "RussiaRadarError",
    "RussiaRadarObservation",
    "EVENT_TAXONOMY_CONTRACT",
    "QUERY_TAXONOMY_CONTRACT",
    "RADAR_CONTRACT",
]
