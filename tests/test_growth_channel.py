from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.growth_channel import (
    AttributionIdentity,
    ChannelCommand,
    DryRunGrowthChannelAdapter,
    ExternalWritePermit,
    GrowthAttributionEvent,
    GrowthAttributionLedger,
    GrowthAttributionPolicy,
    GrowthEventType,
    MessageEligibility,
    TelegramChannelAdapter,
    VKChannelAdapter,
)

NOW = datetime(2026, 8, 2, 8, tzinfo=UTC)


class FakeTransport:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write(self, **request):
        self.writes.append(request)
        return {"external_ref": f"write-{len(self.writes)}"}


def identity(**overrides) -> AttributionIdentity:
    values = {
        "channel": "telegram",
        "campaign_ref": "back-to-school",
        "creative_ref": "video-a",
        "subject_ref": "buyer-7",
        "sku_ref": "sku-1",
        "offer_ref": "offer-1",
    }
    values.update(overrides)
    return AttributionIdentity(**values)


def event(
    identity_value: AttributionIdentity,
    event_type: GrowthEventType,
    index: int,
    **overrides,
) -> GrowthAttributionEvent:
    values = {
        "event_id": f"event-{identity_value.attribution_id}-{index}",
        "attribution_id": identity_value.attribution_id,
        "channel": identity_value.channel,
        "event_type": event_type,
        "occurred_at": NOW + timedelta(hours=index),
        "currency": "RUB",
        "account_ref": "buyer-account-7",
        "device_ref": "device-7",
    }
    if event_type in {
        GrowthEventType.ORDER,
        GrowthEventType.REFUND,
        GrowthEventType.SETTLEMENT,
        GrowthEventType.CASH_CM3,
    }:
        values["order_ref"] = "order-7"
    if event_type == GrowthEventType.ORDER:
        values["refund_window_ends_at"] = NOW + timedelta(days=7)
    values.update(overrides)
    return GrowthAttributionEvent(**values)


def ledger(**policy_overrides) -> GrowthAttributionLedger:
    values = {"currency": "RUB", "stop_loss": Decimal("100")}
    values.update(policy_overrides)
    return GrowthAttributionLedger(GrowthAttributionPolicy(**values))


def record_funnel(
    service: GrowthAttributionLedger,
    attribution: AttributionIdentity,
    *,
    reward: str = "50",
    channel_cost: str = "20",
    cash_cm3: str = "300",
    order_ref: str = "order-7",
) -> list[GrowthAttributionEvent]:
    rows = [
        event(attribution, GrowthEventType.IMPRESSION, 0, channel_cost=channel_cost),
        event(attribution, GrowthEventType.CLICK, 1),
        event(attribution, GrowthEventType.DEEP_LINK, 2),
        event(attribution, GrowthEventType.CONVERSATION, 3),
        event(attribution, GrowthEventType.ADD_TO_CART, 4),
        event(
            attribution,
            GrowthEventType.ORDER,
            5,
            order_ref=order_ref,
            reward_accrual=reward,
        ),
        event(attribution, GrowthEventType.SETTLEMENT, 8, order_ref=order_ref),
        event(
            attribution,
            GrowthEventType.CASH_CM3,
            9,
            order_ref=order_ref,
            amount=cash_cm3,
        ),
    ]
    for row in rows:
        service.record(row)
    return rows


def test_capabilities_and_dry_run_adapter_never_write() -> None:
    vk = VKChannelAdapter()
    telegram = TelegramChannelAdapter()
    assert vk.capabilities.supports_broadcasts is True
    assert vk.capabilities.requires_initiated_or_subscribed_message is False
    assert telegram.capabilities.requires_initiated_or_subscribed_message is True

    adapter = DryRunGrowthChannelAdapter("vk")
    command = ChannelCommand(
        idempotency_key="publish-1",
        operation="publish",
        attribution_id="gat-1",
        payload={"text": "preview"},
    )
    result = adapter.dispatch(command)
    replay = adapter.dispatch(command)
    assert result["external_write_performed"] is False
    assert result["mode"] == "dry_run"
    assert replay["idempotent"] is True
    with pytest.raises(PermissionError, match="cannot perform external writes"):
        adapter.dispatch(command, dry_run=False)


def test_telegram_requires_initiation_or_subscription_even_for_preview() -> None:
    adapter = TelegramChannelAdapter()
    command = ChannelCommand(
        idempotency_key="message-1",
        operation="send_message",
        attribution_id="gat-1",
        recipient_ref="telegram-user-1",
        payload={"text": "offer"},
    )
    with pytest.raises(PermissionError, match="user-initiated conversation"):
        adapter.dispatch(command)

    initiated = adapter.dispatch(
        command,
        eligibility=MessageEligibility(user_initiated=True),
    )
    assert initiated["external_write_performed"] is False
    subscribed = TelegramChannelAdapter().dispatch(
        command,
        eligibility=MessageEligibility(subscribed=True),
    )
    assert subscribed["mode"] == "dry_run"
    with pytest.raises(PermissionError, match="blocked"):
        TelegramChannelAdapter().dispatch(
            command,
            eligibility=MessageEligibility(user_initiated=True, blocked=True),
        )


def test_production_adapter_requires_exact_explicit_one_time_permit() -> None:
    transport = FakeTransport()
    adapter = VKChannelAdapter(transport=transport)
    command = ChannelCommand(
        idempotency_key="pause-loss-1",
        operation="pause_campaign",
        attribution_id="gat-1",
        payload={"campaign_ref": "campaign-1"},
    )
    with pytest.raises(PermissionError, match="explicit Permit"):
        adapter.dispatch(command, dry_run=False, now=NOW)
    assert transport.writes == []

    permit = ExternalWritePermit(
        permit_id="permit-1",
        channel="vk",
        operation="pause_campaign",
        command_sha256=command.fingerprint,
        expires_at=NOW + timedelta(minutes=5),
    )
    first = adapter.dispatch(command, permit=permit, dry_run=False, now=NOW)
    replay = adapter.dispatch(command, permit=permit, dry_run=False, now=NOW)
    assert first["external_write_performed"] is True
    assert replay["idempotent"] is True
    assert len(transport.writes) == 1

    changed = ChannelCommand(
        idempotency_key="pause-loss-1",
        operation="pause_campaign",
        attribution_id="gat-1",
        payload={"campaign_ref": "changed"},
    )
    with pytest.raises(ValueError, match="idempotency conflict"):
        adapter.dispatch(changed, permit=permit, dry_run=False, now=NOW)


def test_attribution_id_is_stable_and_event_chain_rejects_gaps() -> None:
    first = identity()
    assert first.attribution_id == identity().attribution_id
    assert first.attribution_id != identity(creative_ref="video-b").attribution_id
    service = ledger()
    assert service.register(first)["idempotent"] is False
    assert service.register(first)["idempotent"] is True

    with pytest.raises(ValueError, match="requires a prior impression"):
        service.record(event(first, GrowthEventType.CLICK, 1))


def test_full_funnel_keeps_one_id_and_optimizes_incremental_cash_cm3() -> None:
    attribution = identity()
    service = ledger()
    service.register(attribution, baseline_cash_cm3=Decimal("100"))
    rows = record_funnel(service, attribution)

    projection = service.project(attribution.attribution_id, as_of=NOW + timedelta(days=8))
    assert {row.attribution_id for row in rows} == {attribution.attribution_id}
    assert projection["stage"] == "cash_cm3"
    assert projection["event_counts"] == {
        "impression": 1,
        "click": 1,
        "deep_link": 1,
        "conversation": 1,
        "add_to_cart": 1,
        "order": 1,
        "refund": 0,
        "settlement": 1,
        "cash_cm3": 1,
    }
    assert projection["economics"] == {
        "cash_cm3_after_refunds": "300.00",
        "baseline_cash_cm3": "100.00",
        "channel_cost": "20.00",
        "reward_cost_exposure": "50.00",
        "total_growth_cost": "70.00",
        "incremental_cash_cm3": "130.00",
        "optimization_objective": "incremental_cash_cm3",
    }
    assert projection["reward"]["status"] == "confirmed"
    assert projection["decision"] == "continue"
    assert projection["external_write_allowed"] is False


def test_reward_is_only_accrued_until_settlement_and_refund_window_close() -> None:
    attribution = identity()
    service = ledger()
    service.register(attribution)
    record_funnel(service, attribution)

    before_window = service.project(
        attribution.attribution_id,
        as_of=NOW + timedelta(hours=10),
    )
    assert before_window["reward"]["status"] == "accrued"
    assert before_window["reward"]["confirmed"] == "0.00"
    assert before_window["decision"] == "hold"
    assert before_window["reason_codes"] == ["refund_window_open"]

    after_window = service.project(
        attribution.attribution_id,
        as_of=NOW + timedelta(days=8),
    )
    assert after_window["reward"]["status"] == "confirmed"
    assert after_window["reward"]["confirmed"] == "50.00"


def test_refund_forfeits_reward_and_stops_growth() -> None:
    attribution = identity()
    service = ledger()
    service.register(attribution)
    for index, event_type in enumerate(
        (
            GrowthEventType.IMPRESSION,
            GrowthEventType.CLICK,
            GrowthEventType.DEEP_LINK,
            GrowthEventType.CONVERSATION,
            GrowthEventType.ADD_TO_CART,
        )
    ):
        service.record(event(attribution, event_type, index))
    service.record(event(attribution, GrowthEventType.ORDER, 5, reward_accrual="50"))
    service.record(event(attribution, GrowthEventType.REFUND, 6, amount="180"))

    projection = service.project(attribution.attribution_id, as_of=NOW + timedelta(days=8))
    assert projection["reward"]["status"] == "forfeited"
    assert projection["economics"]["reward_cost_exposure"] == "0.00"
    assert projection["economics"]["cash_cm3_after_refunds"] == "-180.00"
    assert projection["decision"] == "stop"


def test_exact_event_replay_is_idempotent_and_drift_conflicts() -> None:
    attribution = identity()
    service = ledger()
    service.register(attribution)
    impression = event(attribution, GrowthEventType.IMPRESSION, 0, channel_cost="10")
    first = service.record(impression)
    replay = service.record(impression)
    assert first["idempotent"] is False
    assert replay["idempotent"] is True
    assert replay["projection"]["event_counts"]["impression"] == 1

    changed = event(
        attribution,
        GrowthEventType.IMPRESSION,
        0,
        event_id=impression.event_id,
        channel_cost="11",
    )
    with pytest.raises(ValueError, match="idempotency conflict"):
        service.record(changed)


def test_cross_channel_order_conflict_holds_both_for_manual_review() -> None:
    telegram = identity(channel="telegram", subject_ref="buyer-telegram")
    vk = identity(channel="vk", subject_ref="buyer-vk")
    service = ledger()
    for attribution in (telegram, vk):
        service.register(attribution)
        for index, event_type in enumerate(
            (
                GrowthEventType.IMPRESSION,
                GrowthEventType.CLICK,
                GrowthEventType.DEEP_LINK,
                GrowthEventType.CONVERSATION,
                GrowthEventType.ADD_TO_CART,
            )
        ):
            service.record(
                event(
                    attribution,
                    event_type,
                    index,
                    account_ref=f"account-{attribution.channel}",
                    device_ref=f"device-{attribution.channel}",
                )
            )
        service.record(
            event(
                attribution,
                GrowthEventType.ORDER,
                5,
                order_ref="same-order",
                account_ref=f"account-{attribution.channel}",
                device_ref=f"device-{attribution.channel}",
            )
        )

    for attribution in (telegram, vk):
        projection = service.project(
            attribution.attribution_id,
            as_of=NOW + timedelta(days=8),
        )
        assert projection["fraud_flags"] == ["cross_channel"]
        assert projection["decision"] == "manual_review"


def test_self_buy_device_account_and_refund_abuse_flags_fail_closed() -> None:
    service = ledger(
        device_account_limit=1,
        account_attribution_limit=1,
        refund_abuse_count=1,
    )
    first = identity(subject_ref="first")
    second = identity(subject_ref="second", creative_ref="video-b")
    service.register(first)
    service.register(second)
    service.record(
        event(
            first,
            GrowthEventType.IMPRESSION,
            0,
            account_ref="same-account",
            device_ref="same-device",
            seller_account_ref="same-account",
        )
    )
    service.record(
        event(
            second,
            GrowthEventType.IMPRESSION,
            0,
            account_ref="other-account",
            device_ref="same-device",
        )
    )
    service.record(
        event(
            second,
            GrowthEventType.CLICK,
            1,
            account_ref="same-account",
            device_ref="same-device",
        )
    )

    first_projection = service.project(first.attribution_id, as_of=NOW + timedelta(hours=2))
    second_projection = service.project(second.attribution_id, as_of=NOW + timedelta(hours=2))
    assert {"self_buy", "device_reuse", "bulk_account"} <= set(first_projection["fraud_flags"])
    assert {"device_reuse", "bulk_account"} <= set(second_projection["fraud_flags"])
    assert first_projection["decision"] == "manual_review"


def test_negative_incremental_cash_cm3_triggers_stop_loss_and_portfolio_ranking() -> None:
    profitable = identity(subject_ref="profitable")
    losing = identity(subject_ref="losing", creative_ref="video-loss")
    service = ledger(stop_loss=Decimal("100"))
    service.register(profitable)
    service.register(losing)
    record_funnel(service, profitable, reward="10", channel_cost="10", cash_cm3="200")
    record_funnel(
        service,
        losing,
        reward="50",
        channel_cost="100",
        cash_cm3="20",
        order_ref="order-loss",
    )

    result = service.optimize(as_of=NOW + timedelta(days=8))
    assert result["optimization_objective"] == "incremental_cash_cm3"
    assert [row["attribution_id"] for row in result["attributions"]] == [
        profitable.attribution_id,
        losing.attribution_id,
    ]
    assert result["attributions"][1]["decision"] == "stop"
    assert result["attributions"][1]["reason_codes"] == ["incremental_cash_cm3_stop_loss"]
    assert result["totals"]["incremental_cash_cm3"] == "50.00"
    assert result["external_write_allowed"] is False


def test_currency_and_exact_order_identity_fail_closed() -> None:
    attribution = identity()
    service = ledger()
    service.register(attribution)
    with pytest.raises(ValueError, match="currency"):
        service.record(event(attribution, GrowthEventType.IMPRESSION, 0, currency="CNY"))

    service.record(event(attribution, GrowthEventType.IMPRESSION, 0))
    service.record(event(attribution, GrowthEventType.CLICK, 1))
    service.record(event(attribution, GrowthEventType.DEEP_LINK, 2))
    service.record(event(attribution, GrowthEventType.CONVERSATION, 3))
    service.record(event(attribution, GrowthEventType.ADD_TO_CART, 4))
    service.record(event(attribution, GrowthEventType.ORDER, 5, order_ref="order-a"))
    with pytest.raises(ValueError, match="order reference cannot change"):
        service.record(
            event(
                attribution,
                GrowthEventType.SETTLEMENT,
                8,
                order_ref="order-b",
            )
        )
