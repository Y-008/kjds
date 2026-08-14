"""BAS-178 social intelligence analysis contract tests (analysis slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.social_analysis import (
    GovernedSocialIntelligenceAnalysis,
    SocialAnalysisError,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _workspace() -> GovernedSocialIntelligenceAnalysis:
    return GovernedSocialIntelligenceAnalysis()


def _note(record_id: str, date: str, **overrides) -> dict:
    record = {
        "id": record_id,
        "published_at": f"{date}T10:00:00Z",
        "captured_at": "2026-08-14T09:00:00Z",
        "source_url": f"https://www.xiaohongshu.com/note/{record_id}",
        "adapter_version": "synthetic_fixture",
        "raw_hash": _sha(record_id),
        "normalized": {
            "actor": {
                "account_ref": "creator-alice",
                "account_type": "creator",
                "verification": True,
                "audience_total": 12000,
            },
            "content": {
                "format": "note",
                "hashtags": ["#skincare"],
                "topics": ["skincare", "niacinamide"],
                "product_mentions": ["sku-niacinamide"],
                "hook": "三周淡化痘印",
            },
            "conversation": [
                {"intent": "question", "sentiment": "neutral", "seller_response_status": False},
                {"intent": "pain_point", "sentiment": "negative", "seller_response_status": True},
            ],
            "seller_product": {"shop": "shop-1", "product_sku": "sku-niacinamide"},
        },
    }
    record.update(overrides)
    return record


def _rich_records() -> list[dict]:
    return [
        _note("note-1", "2026-08-10"),
        _note("note-2", "2026-08-10"),
        _note(
            "note-3",
            "2026-08-11",
            normalized={
                "actor": {"account_ref": "brand-b", "account_type": "brand", "verification": True, "audience_total": 99000},
                "content": {"format": "video", "hashtags": ["#makeup"], "topics": ["lipstick", "matte"], "product_mentions": ["sku-lipstick"], "hook": "不掉色哑光口红"},
                "seller_product": {"shop": "shop-2", "product_sku": "sku-lipstick"},
            },
        ),
    ]


def test_full_analysis_produces_six_outputs():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    assert bundle.status == "ADMITTED"
    assert bundle.record_count == 3
    assert bundle.derived_only is True
    assert bundle.seller_segments
    assert bundle.comment_intents
    assert bundle.content_structures
    assert bundle.product_demands
    assert bundle.calendar
    assert bundle.campaign_drafts
    assert len(bundle.bundle_sha256) == 64


def test_seller_segmentation_groups_distinct_actors():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    by_type = {item["account_type"]: item for item in bundle.seller_segments}
    assert set(by_type) == {"creator", "brand"}
    assert by_type["creator"]["actor_count"] == 1
    assert by_type["brand"]["actor_count"] == 1
    assert by_type["creator"]["verified_count"] == 1
    assert by_type["creator"]["audience_total_max"] == 12000


def test_comment_intent_clusters():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    by_intent = {item["intent"]: item for item in bundle.comment_intents}
    assert "question" in by_intent
    assert "pain_point" in by_intent
    assert by_intent["pain_point"]["comment_count"] == 2


def test_content_structure_format_counts():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    structure = bundle.content_structures[0]
    assert structure["content_count"] == 3
    assert structure["format_counts"]["note"] == 2
    assert structure["format_counts"]["video"] == 1
    assert structure["topic_frequency"]["skincare"] == 2
    assert structure["hook_present_count"] == 3


def test_product_demand_cooccurrence():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    demand = bundle.product_demands[0]
    assert demand["product_frequency"]["sku-niacinamide"] >= 1
    assert any(item["topic"] == "skincare" and item["product"] == "sku-niacinamide" for item in demand["topic_product_cooccurrence"])


def test_calendar_aggregates_dates():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    calendar = bundle.calendar[0]
    assert calendar["distinct_dates"] == 2
    assert calendar["total_posts"] == 3
    assert calendar["cadence_average_per_day"] == 1.5


def test_campaign_draft_is_derived_only_and_not_executable():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    drafts = bundle.campaign_drafts
    assert len(drafts) == 1
    assert drafts[0]["status"] == "DRAFT"
    assert drafts[0]["derived_from_observed_top_signals_only"] is True
    assert drafts[0]["execution_allowed"] is False


def test_replay_identity():
    first = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    second = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    assert first.bundle_sha256 == second.bundle_sha256


def test_empty_records_rejected():
    with pytest.raises(SocialAnalysisError) as exc:
        _workspace().analyze([], platform="xiaohongshu")
    assert "records_empty" in str(exc.value)


def test_unknown_platform_rejected():
    with pytest.raises(SocialAnalysisError) as exc:
        _workspace().analyze(_rich_records(), platform="facebook")
    assert "platform_not_recognized" in str(exc.value)


def test_missing_dimensions_produce_explicit_gaps():
    records = [
        {
            "id": "bare-1",
            "published_at": "2026-08-10T10:00:00Z",
            "captured_at": "2026-08-14T09:00:00Z",
            "source_url": "https://example.com/bare",
            "adapter_version": "synthetic_fixture",
            "raw_hash": _sha("bare-1"),
            "normalized": {},
        }
    ]
    bundle = _workspace().analyze(records, platform="douyin")
    assert "seller_segmentation_no_actor_data" in bundle.gaps
    assert "comment_intent_no_conversation_data" in bundle.gaps
    assert "content_structure_no_content_data" in bundle.gaps
    assert "product_demand_no_product_mentions" in bundle.gaps
    assert "campaign_draft_insufficient_data" in bundle.gaps
    assert bundle.seller_segments == ()
    assert bundle.campaign_drafts == ()


def test_missing_published_at_gap():
    records = [_note("note-1", "2026-08-10", published_at="")]
    bundle = _workspace().analyze(records, platform="xiaohongshu")
    assert "calendar_no_published_at" in bundle.gaps


def test_sensitive_record_rejected():
    records = [_note("note-1", "2026-08-10", source_url="https://example.com/x?api_key=secret")]
    with pytest.raises(SocialAnalysisError) as exc:
        _workspace().analyze(records, platform="xiaohongshu")
    assert "sensitive_value_rejected" in str(exc.value)


def test_readback_states():
    bundle = _workspace().analyze(_rich_records(), platform="xiaohongshu")
    pending = _workspace().readback(bundle)
    assert pending["readback_state"] == "PENDING"

    verified = _workspace().readback(bundle, observed=bundle.bundle_sha256)
    assert verified["readback_state"] == "VERIFIED"

    invalidated = _workspace().readback(bundle, observed=_sha("other"))
    assert invalidated["readback_state"] == "INVALIDATED"
    assert invalidated["integrity_ok"] is False


def test_zero_authority_all_false():
    flags = _workspace().zero_authority()
    assert flags
    assert all(not value for value in flags.values())
    assert flags["external_write"] is False
    assert flags["pilot"] is False
