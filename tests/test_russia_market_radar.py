"""BAS-179 Russia market demand & hot-event radar contract tests (prep-only slice)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apps.control_plane.russia_market_radar import (
    ALLOWED_SIGNAL_DOMAINS,
    ALLOWED_SOURCE_IDS,
    SCORING_INPUTS,
    SOURCE_CLASS_BY_ID,
    ZERO_AUTHORITY_KEYS,
    GovernedRussiaMarketRadar,
    RussiaRadarError,
)

ROOT = Path(__file__).parents[1]
SOURCE_REGISTRY = ROOT / "docs" / "project" / "registries" / "russia_market_intelligence_sources.json"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _radar() -> GovernedRussiaMarketRadar:
    return GovernedRussiaMarketRadar()


def _spec(**overrides) -> dict:
    spec = {
        "market": "ru",
        "objective": "research demand",
        "time_range": {"start": "2026-07-01T00:00:00Z", "end": "2026-08-14T00:00:00Z"},
        "exact_scope": "ru_market_demand_research",
        "authority": "russia_market_intelligence_owner",
    }
    spec.update(overrides)
    return spec


def _observation(i: int, *, source_id: str = "ozon_seller_analytics", content: str | None = None, **overrides) -> dict:
    obs = {
        "id": f"obs-{i}",
        "source_id": source_id,
        "source_class": SOURCE_CLASS_BY_ID[source_id],
        "domain": "marketplace_search_and_funnel",
        "content_hash": _sha(content or f"content:{i}"),
        "observed_at": "2026-08-14T00:00:00Z",
        "effective_at": "2026-08-10T00:00:00Z",
        "entity_ref": "sku-1",
        "region": "RU-MOW",
        "payload": {"search_volume": 1200, "price_change": -0.03},
    }
    obs.update(overrides)
    return obs


def _event(
    event_id: str,
    *,
    effective_at: str = "2026-08-10T00:00:00Z",
    source_ids: list[str] | None = None,
    components: dict | None = None,
    **overrides,
) -> dict:
    ev = {
        "event_id": event_id,
        "source_ids": source_ids or ["ozon_seller_analytics"],
        "first_seen_at": "2026-08-08T00:00:00Z",
        "last_seen_at": "2026-08-10T00:00:00Z",
        "effective_at": effective_at,
        "expiry_or_review_at": None,
        "components": components
        if components is not None
        else {
            "recency": 0.9,
            "velocity": 0.7,
            "entity_relevance": 0.6,
            "profit_or_supply_exposure": None,
            "observed_market_response": None,
        },
    }
    ev.update(overrides)
    return ev


# ---- query taxonomy / Russian morphology ----


def test_expand_queries_normalizes_cyrillic_case_and_yo():
    result = _radar().expand_queries(seeds=["Платьё"])
    assert result.seeds == ("платье",)
    assert any(v.dimension == "word_form" and v.term == "платье" for v in result.variants)
    assert any(v.term == "вечернее платье" for v in result.variants)
    assert result.status == "ADMITTED"


def test_expand_queries_covers_all_dimensions():
    result = _radar().expand_queries(seeds=["платье"])
    dims = {v.dimension for v in result.variants}
    assert {"word_form", "synonym", "category", "question", "scenario"} <= dims


def test_expand_queries_dedups_and_is_deterministic():
    first = _radar().expand_queries(seeds=["платье", "Платье"])
    second = _radar().expand_queries(seeds=["платье", "Платье"])
    assert first.query_sha256 == second.query_sha256
    assert first.seeds == ("платье",)


def test_expand_queries_caller_expansion_merges():
    expansion = {"платье": [{"dimension": "brand", "term": "бренд"}]}
    result = _radar().expand_queries(seeds=["платье"], expansion=expansion)
    assert any(v.dimension == "brand" and v.provenance == "caller_expansion" for v in result.variants)


def test_expand_queries_unknown_seed_reports_gap():
    result = _radar().expand_queries(seeds=["неизвестныйтермин"])
    assert any("no_known_expansion" in gap for gap in result.gaps)


def test_expand_queries_unknown_dimension_rejected():
    expansion = {"платье": [{"dimension": "profit", "term": "x"}]}
    with pytest.raises(RussiaRadarError):
        _radar().expand_queries(seeds=["платье"], expansion=expansion)


def test_expand_queries_unknown_expansion_seed_rejected():
    with pytest.raises(RussiaRadarError):
        _radar().expand_queries(seeds=["платье"], expansion={"чужое": []})


def test_expand_queries_sensitive_rejected():
    with pytest.raises(RussiaRadarError):
        _radar().expand_queries(seeds=["api_key=secret"])


# ---- collection / cross-source dedup ----


def test_collect_without_adapter_is_not_admitted():
    batch = _radar().collect(spec=_spec())
    assert batch.status == "NOT_ADMITTED"
    assert batch.conserved_total == 0
    assert "source_adapter_not_admitted" in batch.gaps


def test_collect_conserves_and_dedups_cross_source():
    same = "same-content"
    obs = [
        _observation(1, source_id="ozon_seller_analytics", content=same),
        _observation(2, source_id="yandex_wordstat", content=same),
        _observation(3, source_id="bank_of_russia_macro_events", content="other"),
    ]
    batch = _radar().collect(spec=_spec(), observations=obs)
    assert batch.conserved_total == 2
    assert batch.dedup_count == 1
    assert batch.source_total == 3
    assert batch.conservation_ok is True
    assert len(batch.cross_source_links) == 1
    link = batch.cross_source_links[0]
    assert link["cross_source_count"] == 2
    assert set(link["source_ids"]) == {"ozon_seller_analytics", "yandex_wordstat"}


def test_collect_three_source_corroboration():
    same = "same-content"
    obs = [
        _observation(1, source_id="ozon_seller_analytics", content=same),
        _observation(2, source_id="yandex_wordstat", content=same),
        _observation(3, source_id="telegram_public_market_conversation", content=same),
    ]
    batch = _radar().collect(spec=_spec(), observations=obs)
    assert batch.conserved_total == 1
    assert batch.dedup_count == 2
    assert batch.cross_source_links[0]["cross_source_count"] == 3


def test_collect_quarantines_invalid_record():
    bad = _observation(9)
    bad["content_hash"] = "not-hex"
    batch = _radar().collect(spec=_spec(), observations=[_observation(1), bad])
    assert batch.conserved_total == 1
    assert batch.quarantined_total == 1
    assert batch.source_total == 2
    assert batch.conservation_ok is True


def test_collect_source_class_mismatch_quarantined():
    bad = _observation(1, source_id="ozon_seller_analytics")
    bad["source_class"] = "official_public_economic"
    batch = _radar().collect(spec=_spec(), observations=[bad])
    assert batch.quarantined_total == 1


def test_collect_sensitive_payload_quarantined():
    bad = _observation(1)
    bad["payload"] = {"note": "api_key=secret"}
    batch = _radar().collect(spec=_spec(), observations=[bad])
    assert batch.quarantined_total == 1


def test_collect_partial_pages_gap():
    batch = _radar().collect(spec=_spec(source_total=10), observations=[_observation(1)])
    assert batch.source_total == 10
    assert "failed_or_pending_pages" in batch.gaps


def test_collect_checkpoint_deterministic():
    obs = [_observation(1), _observation(2)]
    first = _radar().collect(spec=_spec(), observations=obs)
    second = _radar().collect(spec=_spec(), observations=obs)
    assert first.checkpoint == second.checkpoint
    assert first.batch_sha256 == second.batch_sha256


# ---- decomposed demand projection ----


def test_project_demand_decomposes_dimensions():
    batch = _radar().collect(spec=_spec(), observations=[_observation(1)])
    signals = _radar().project_demand(
        observation=batch,
        spec={"exact_scope": "ru_market_demand_research", "authority": "owner", "as_of": "2026-08-14T00:00:00Z"},
    )
    assert len(signals) == 1
    signal = signals[0]
    dims = {d["dimension"]: d for d in signal.dimensions}
    assert dims["search_volume"]["status"] == "PRESENT"
    assert dims["review_sentiment"]["status"] == "UNKNOWN"
    assert "review_sentiment" in signal.unknowns
    assert signal.source_ids == ("ozon_seller_analytics",)


def test_project_demand_is_derived_not_fact():
    batch = _radar().collect(spec=_spec(), observations=[_observation(1)])
    signal = _radar().project_demand(
        observation=batch,
        spec={"exact_scope": "ru_market_demand_research", "authority": "owner", "as_of": "2026-08-14T00:00:00Z"},
    )[0]
    assert signal.status == "ADMITTED"
    assert signal.signal_sha256
    assert _radar().zero_authority()["formal_fact"] is False
    assert _radar().zero_authority()["finance_entry"] is False
    assert _radar().zero_authority()["external_write"] is False


# ---- hot-event scoring / ordering ----


def test_score_event_decomposed_and_escalation():
    event = _event(
        "ev-1",
        source_ids=["ozon_seller_analytics", "yandex_wordstat"],
        components={
            "recency": 0.9,
            "velocity": 0.7,
            "entity_relevance": 0.6,
            "profit_or_supply_exposure": 0.5,
            "observed_market_response": 0.8,
        },
    )
    candidate = _radar().score_event(event=event)
    assert candidate.status == "ADMITTED"
    assert candidate.score is not None
    assert {c["input"] for c in candidate.components} == set(SCORING_INPUTS)
    by_input = {c["input"]: c for c in candidate.components}
    assert by_input["source_authority"]["status"] == "PRESENT"
    assert by_input["cross_source_count"]["raw"] == 2
    assert candidate.escalation_eligible is True
    assert candidate.external_action_allowed is False


def test_score_event_unknowns_reported_not_zero():
    event = _event("ev-1", source_ids=["telegram_public_market_conversation"])
    candidate = _radar().score_event(event=event)
    assert "observed_market_response" in candidate.unknowns
    assert "profit_or_supply_exposure" in candidate.unknowns
    assert candidate.escalation_eligible is False
    by_input = {c["input"]: c for c in candidate.components}
    assert by_input["observed_market_response"]["normalized"] is None


def test_score_event_single_source_not_escalation():
    event = _event(
        "ev-1",
        source_ids=["telegram_public_market_conversation"],
        components={
            "recency": 0.9,
            "velocity": 0.7,
            "entity_relevance": 0.6,
            "profit_or_supply_exposure": 0.5,
            "observed_market_response": 0.8,
        },
    )
    candidate = _radar().score_event(event=event)
    assert candidate.escalation_eligible is False
    assert candidate.score is not None


def test_score_event_unknown_component_rejected():
    with pytest.raises(RussiaRadarError):
        _radar().score_event(event=_event("ev-1", components={"not_a_component": 0.5}))


def test_score_event_component_out_of_range_rejected():
    with pytest.raises(RussiaRadarError):
        _radar().score_event(event=_event("ev-1", components={"recency": 1.5}))


def test_score_event_stale_when_expired():
    event = _event("ev-1", expiry_or_review_at="2026-08-01T00:00:00Z")
    candidate = _radar().score_event(event=event, now="2026-08-14T00:00:00Z")
    assert candidate.status == "STALE"
    assert "stale_or_review_due" in candidate.unknowns


def test_order_events_sorts_by_effective_at():
    events = [
        _event("ev-late", effective_at="2026-08-12T00:00:00Z"),
        _event("ev-early", effective_at="2026-08-05T00:00:00Z"),
        _event("ev-mid", effective_at="2026-08-08T00:00:00Z"),
    ]
    ordered = _radar().order_events(events=events)
    assert [c.event_id for c in ordered] == ["ev-early", "ev-mid", "ev-late"]


def test_order_events_invalid_time_rejected():
    with pytest.raises(RussiaRadarError):
        _radar().order_events(events=[_event("ev-1", effective_at="not-a-time")])


# ---- readback / zero authority ----


def test_readback_roundtrip():
    result = _radar().expand_queries(seeds=["платье"])
    assert _radar().readback(result)["readback_state"] == "PENDING"
    assert _radar().readback(result, observed=result.query_sha256)["readback_state"] == "VERIFIED"
    assert _radar().readback(result, observed=_sha("other"))["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    flags = _radar().zero_authority()
    assert set(flags) == ZERO_AUTHORITY_KEYS
    assert all(not value for value in flags.values())


# ---- registry anti-drift ----


def test_source_registry_aligns_with_module():
    registry = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    registry_source_ids = {s["id"] for s in registry["sources"]}
    registry_classes = {s["source_class"] for s in registry["sources"]}
    registry_domains = set(registry["signal_domains"])
    assert registry_source_ids == set(ALLOWED_SOURCE_IDS)
    assert registry_classes == set(SOURCE_CLASS_BY_ID.values())
    assert registry_domains == set(ALLOWED_SIGNAL_DOMAINS)
    for source in registry["sources"]:
        assert SOURCE_CLASS_BY_ID[source["id"]] == source["source_class"]
