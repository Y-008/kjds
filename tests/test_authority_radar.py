from datetime import UTC, datetime

from scripts.authority_radar.analyze import validate_analysis
from scripts.authority_radar.collect import Event, is_due, normalize_url, parse_feed
from scripts.authority_radar.evaluate import evaluate_quality_gate, score_candidate
from scripts.authority_radar.report import render_report


def test_normalize_url_removes_tracking_and_fragment() -> None:
    value = "https://Example.com/news/?utm_source=x&id=42#section"
    assert normalize_url(value) == "https://example.com/news?id=42"


def test_parse_atom_feed_preserves_source_metadata() -> None:
    payload = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Important release</title>
        <link href="https://example.com/release?utm_campaign=test" />
        <updated>2026-07-16T01:02:03Z</updated>
        <summary>&lt;p&gt;Evidence first.&lt;/p&gt;</summary>
      </entry>
    </feed>"""
    source = {
        "id": "example",
        "category": "ai_frontier",
        "source_tier": "official",
        "confidence": 0.95,
        "impact": 4,
    }
    events = parse_feed(payload, source)
    assert len(events) == 1
    assert events[0].url == "https://example.com/release"
    assert events[0].published_at == datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC).isoformat()
    assert events[0].excerpt == "Evidence first."


def test_event_key_is_stable_across_tracking_parameters() -> None:
    base = {
        "source_id": "source",
        "category": "ai_frontier",
        "title": "A release",
        "published_at": None,
        "source_tier": "official",
        "confidence": 0.95,
        "impact": 3,
        "requires_review": False,
        "excerpt": "",
        "raw": {},
    }
    left = Event(url="https://example.com/a?utm_source=x", **base)
    right = Event(url="https://example.com/a", **base)
    assert left.key == right.key


def test_report_separates_failures_from_events() -> None:
    import sqlite3

    from scripts.authority_radar.collect import init_database

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_database(connection)
    connection.execute(
        "INSERT INTO runs(started_at, finished_at, status, sources_checked, events_new) VALUES (?, ?, ?, ?, ?)",
        ("2026-07-16T00:00:00+00:00", "2026-07-16T00:01:00+00:00", "success_with_errors", 2, 1),
    )
    connection.execute(
        "INSERT INTO source_state(source_id, last_checked_at, last_error) VALUES (?, ?, ?)",
        ("blocked_source", "2026-07-16T00:00:00+00:00", "HTTP 403"),
    )
    connection.commit()
    report = render_report(connection)
    assert "最近实际采集：success_with_errors" in report
    assert "`blocked_source`：HTTP 403" in report


def test_analysis_gate_rejects_invented_year_version_and_missing_citations() -> None:
    evidence = "2026 event_id: " + "a" * 64 + " event_id: " + "b" * 64 + " OpenClaw 2026.7.1"
    candidate = """## Executive Signal
## AI 前沿
## 企业端 AI
## 跨境电商与国内平台
## Agent 基建
## 实验与审批
2024 年 GPT-5.6 已发布。
"""
    reasons = validate_analysis(evidence, candidate)
    assert any("years absent" in reason for reason in reasons)
    assert any("versions absent" in reason for reason in reasons)
    assert any("event_ids" in reason for reason in reasons)


def test_failed_source_waits_until_retry_time() -> None:
    state = {
        "last_checked_at": "2026-07-16T00:00:00+00:00",
        "last_error": "timeout",
        "next_retry_at": "2026-07-16T00:15:00+00:00",
    }
    source = {"interval_minutes": 120}
    assert not is_due(state, source, datetime(2026, 7, 16, 0, 14, tzinfo=UTC))
    assert is_due(state, source, datetime(2026, 7, 16, 0, 15, tzinfo=UTC))


def test_gold_scorer_rejects_invented_fact_and_missing_approval() -> None:
    case = {
        "evidence": "2026 年修改价格属于 L3。",
        "expected_approval": "L3",
        "must_include_any_groups": [["人工批准"]],
    }
    score = score_candidate(case, "2024 年可以自动执行。")
    assert not score["passed"]
    assert any("invented years" in failure for failure in score["failures"])
    assert any("missing approval" in failure for failure in score["failures"])


def test_quality_gate_rejects_regression_and_missing_provider_results() -> None:
    results = [
        {"provider": "local", "status": "evaluated", "passed": True},
        {"provider": "local", "status": "evaluated", "passed": False},
    ]
    regression = evaluate_quality_gate(results, ["local"], min_evaluated=2, min_pass_rate=0.75)
    assert not regression["passed"]
    assert regression["providers"]["local"]["pass_rate"] == 0.5

    missing = evaluate_quality_gate(results, ["local", "zhipu"], min_evaluated=2, min_pass_rate=0.5)
    assert not missing["passed"]
    assert not missing["providers"]["zhipu"]["gate_passed"]
