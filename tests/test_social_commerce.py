"""BAS-178 Social-Commerce Intelligence contract kernel tests (first slice)."""

from __future__ import annotations

import hashlib

import pytest

from apps.control_plane.social_commerce import (
    GovernedSocialCommerceIntelligenceWorkspace,
    SocialCommerceError,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _workspace() -> GovernedSocialCommerceIntelligenceWorkspace:
    return GovernedSocialCommerceIntelligenceWorkspace()


def _spec(**overrides) -> dict:
    spec = {
        "platform": "xiaohongshu",
        "account_ref": "acct-1",
        "objective": "research demand",
        "time_range": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-14T00:00:00Z"},
        "source_rank": "official_authorized_api",
    }
    spec.update(overrides)
    return spec


def _record(i: int) -> dict:
    return {
        "id": f"rec-{i}",
        "published_at": "2026-08-10T00:00:00Z",
        "captured_at": "2026-08-14T00:00:00Z",
        "source_url": f"https://example.com/note/{i}",
        "adapter_version": "synthetic-1.0.0",
        "raw_hash": _sha(f"raw:{i}"),
        "normalized": {"title": f"note {i}"},
    }


def _campaign_spec(**overrides) -> dict:
    spec = {
        "account_ref": "acct-1",
        "purpose": "launch",
        "audience": "sellers",
        "action_set": ["publish", "comment"],
        "budget": {"amount": "100", "currency": "CNY"},
        "stop_conditions": ["budget_exhausted", "manual_halt"],
        "expiry": "2026-08-21T00:00:00Z",
    }
    spec.update(overrides)
    return spec


def _grant(**overrides) -> dict:
    grant = {"grant_id": "grant-1", "grantor": "operator-1", "account_ref": "acct-1"}
    grant.update(overrides)
    return grant


def test_collect_without_adapter_is_not_admitted():
    batch = _workspace().collect(spec=_spec())
    assert batch.status == "NOT_ADMITTED"
    assert batch.conserved_total == 0
    assert "platform_adapter_not_admitted" in batch.gaps
    assert batch.adapter_version == "not_admitted"


def test_collect_conserves_all_records_no_sampling_cap():
    records = [_record(i) for i in range(50)]
    batch = _workspace().collect(spec=_spec(), records=records)
    assert batch.conserved_total == 50
    assert len(batch.records) == 50


def test_collect_deduplicates_content_addressed():
    records = [_record(1), _record(1), _record(2)]
    batch = _workspace().collect(spec=_spec(), records=records)
    assert batch.conserved_total == 2
    assert batch.dedup_count == 1


def test_collect_checkpoint_is_deterministic():
    records = [_record(1), _record(2)]
    first = _workspace().collect(spec=_spec(), records=records)
    second = _workspace().collect(spec=_spec(), records=records)
    assert first.checkpoint == second.checkpoint
    assert first.batch_sha256 == second.batch_sha256


def test_collect_unknown_platform_rejected():
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().collect(spec=_spec(platform="unknown"))
    assert "platform_not_recognized" in str(exc.value)


def test_collect_unknown_source_rank_rejected():
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().collect(spec=_spec(source_rank="crawler"))
    assert "source_rank_not_recognized" in str(exc.value)


def test_collect_sensitive_record_rejected():
    bad = _record(1)
    bad["normalized"] = {"body": "authorization: Bearer xyz"}
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().collect(spec=_spec(), records=[bad])
    assert "sensitive_value_rejected" in str(exc.value)


def test_collect_bad_raw_hash_rejected():
    bad = _record(1)
    bad["raw_hash"] = "not-hex"
    with pytest.raises(SocialCommerceError):
        _workspace().collect(spec=_spec(), records=[bad])


def test_collect_checkpoint_resume_identity():
    records = [_record(1)]
    batch = _workspace().collect(spec=_spec(), records=records, checkpoint="cp-1")
    assert batch.checkpoint != "cp-1"
    assert batch.records[0]["id"] == "rec-1"


def test_analyze_derives_patterns_never_overwrites_raw():
    records = [_record(1), _record(2)]
    batch = _workspace().collect(spec=_spec(), records=records)
    insight = _workspace().analyze(spec={"dimensions": ["actor", "content"]}, batch=batch)
    assert insight.status == "ADMITTED"
    assert insight.derived_only is True
    assert insight.raw_batch_sha256 == batch.batch_sha256
    assert len(insight.patterns) == 2
    assert {p["dimension"] for p in insight.patterns} == {"actor", "content"}


def test_analyze_unknown_dimension_rejected():
    batch = _workspace().collect(spec=_spec())
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().analyze(spec={"dimensions": ["profit"]}, batch=batch)
    assert "dimension_not_recognized" in str(exc.value)


def test_analyze_empty_dimensions_rejected():
    batch = _workspace().collect(spec=_spec())
    with pytest.raises(SocialCommerceError):
        _workspace().analyze(spec={"dimensions": []}, batch=batch)


def test_operate_is_not_admitted_no_external_write():
    receipt = _workspace().operate(spec=_campaign_spec(), grant=_grant(), idempotency_key="k1")
    assert receipt.status == "NOT_ADMITTED"
    assert receipt.external_write_allowed is False
    assert receipt.readback_state == "NOT_ATTEMPTED"
    assert receipt.kill_switch is False
    assert set(receipt.action_set) == {"publish", "comment"}


def test_operate_grant_account_mismatch_rejected():
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().operate(
            spec=_campaign_spec(),
            grant=_grant(account_ref="acct-2"),
            idempotency_key="k1",
        )
    assert "grant_account_mismatch" in str(exc.value)


def test_operate_unknown_action_rejected():
    with pytest.raises(SocialCommerceError) as exc:
        _workspace().operate(
            spec=_campaign_spec(action_set=["transfer_funds"]),
            grant=_grant(),
            idempotency_key="k1",
        )
    assert "action_not_recognized" in str(exc.value)


def test_operate_missing_stop_conditions_rejected():
    with pytest.raises(SocialCommerceError):
        _workspace().operate(
            spec=_campaign_spec(stop_conditions=[]),
            grant=_grant(),
            idempotency_key="k1",
        )


def test_operate_sensitive_spec_rejected():
    with pytest.raises(SocialCommerceError):
        _workspace().operate(
            spec=_campaign_spec(purpose="api_key=secret"),
            grant=_grant(),
            idempotency_key="k1",
        )


def test_readback_states():
    receipt = _workspace().operate(spec=_campaign_spec(), grant=_grant(), idempotency_key="k1")
    pending = _workspace().readback(receipt)
    assert pending["readback_state"] == "PENDING"
    assert pending["integrity_ok"] is True

    verified = _workspace().readback(receipt, observed=receipt.campaign_spec_sha256)
    assert verified["readback_state"] == "VERIFIED"

    invalidated = _workspace().readback(receipt, observed=_sha("other"))
    assert invalidated["readback_state"] == "INVALIDATED"
    assert invalidated["integrity_ok"] is False


def test_zero_authority_all_false():
    flags = _workspace().zero_authority()
    assert flags
    assert all(not value for value in flags.values())
