from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Protocol

from .numeric_semantics import ascii_currency, finite_decimal

MONEY = Decimal("0.01")


class GrowthEventType(StrEnum):
    IMPRESSION = "impression"
    CLICK = "click"
    DEEP_LINK = "deep_link"
    CONVERSATION = "conversation"
    ADD_TO_CART = "add_to_cart"
    ORDER = "order"
    REFUND = "refund"
    SETTLEMENT = "settlement"
    CASH_CM3 = "cash_cm3"


FUNNEL_ORDER = (
    GrowthEventType.IMPRESSION,
    GrowthEventType.CLICK,
    GrowthEventType.DEEP_LINK,
    GrowthEventType.CONVERSATION,
    GrowthEventType.ADD_TO_CART,
    GrowthEventType.ORDER,
    GrowthEventType.REFUND,
    GrowthEventType.SETTLEMENT,
    GrowthEventType.CASH_CM3,
)
_FUNNEL_INDEX = {event_type: index for index, event_type in enumerate(FUNNEL_ORDER)}
_PREDECESSOR = {
    GrowthEventType.CLICK: GrowthEventType.IMPRESSION,
    GrowthEventType.DEEP_LINK: GrowthEventType.CLICK,
    GrowthEventType.CONVERSATION: GrowthEventType.DEEP_LINK,
    GrowthEventType.ADD_TO_CART: GrowthEventType.CONVERSATION,
    GrowthEventType.ORDER: GrowthEventType.ADD_TO_CART,
    GrowthEventType.REFUND: GrowthEventType.ORDER,
    GrowthEventType.SETTLEMENT: GrowthEventType.ORDER,
    GrowthEventType.CASH_CM3: GrowthEventType.SETTLEMENT,
}
_ORDER_EVENT_TYPES = {
    GrowthEventType.ORDER,
    GrowthEventType.REFUND,
    GrowthEventType.SETTLEMENT,
    GrowthEventType.CASH_CM3,
}
FRAUD_FLAGS = frozenset(
    {
        "self_buy",
        "device_reuse",
        "bulk_account",
        "refund_abuse",
        "cross_channel",
    }
)


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _money(value: Any, name: str) -> Decimal:
    return finite_decimal(value, name).quantize(MONEY, rounding=ROUND_HALF_UP)


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return _aware(value, "Datetime").isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(item) for item in value)
    return value


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ChannelCapabilities:
    channel: str
    operations: frozenset[str]
    supports_deep_links: bool
    supports_direct_messages: bool
    supports_broadcasts: bool
    requires_initiated_or_subscribed_message: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", _required(self.channel, "Channel").lower())
        operations = frozenset(_required(item, "Channel operation") for item in self.operations)
        if not operations:
            raise ValueError("Channel capabilities require at least one operation")
        object.__setattr__(self, "operations", operations)


VK_CAPABILITIES = ChannelCapabilities(
    channel="vk",
    operations=frozenset({"publish", "send_message", "create_deep_link", "pause_campaign"}),
    supports_deep_links=True,
    supports_direct_messages=True,
    supports_broadcasts=True,
    requires_initiated_or_subscribed_message=False,
)
TELEGRAM_CAPABILITIES = ChannelCapabilities(
    channel="telegram",
    operations=frozenset({"publish", "send_message", "create_deep_link", "pause_campaign"}),
    supports_deep_links=True,
    supports_direct_messages=True,
    supports_broadcasts=True,
    requires_initiated_or_subscribed_message=True,
)


@dataclass(frozen=True, slots=True)
class MessageEligibility:
    user_initiated: bool = False
    subscribed: bool = False
    blocked: bool = False

    @property
    def telegram_eligible(self) -> bool:
        return not self.blocked and (self.user_initiated or self.subscribed)


@dataclass(frozen=True, slots=True)
class ChannelCommand:
    idempotency_key: str
    operation: str
    attribution_id: str
    payload: Mapping[str, Any]
    recipient_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "idempotency_key",
            _required(self.idempotency_key, "Command idempotency key"),
        )
        object.__setattr__(self, "operation", _required(self.operation, "Channel operation"))
        object.__setattr__(self, "attribution_id", _required(self.attribution_id, "Attribution ID"))
        if self.recipient_ref is not None:
            object.__setattr__(
                self,
                "recipient_ref",
                _required(self.recipient_ref, "Recipient reference"),
            )
        object.__setattr__(self, "payload", dict(self.payload))

    @property
    def fingerprint(self) -> str:
        return _sha256(
            {
                "idempotency_key": self.idempotency_key,
                "operation": self.operation,
                "attribution_id": self.attribution_id,
                "recipient_ref": self.recipient_ref,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, slots=True)
class ExternalWritePermit:
    permit_id: str
    channel: str
    operation: str
    command_sha256: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "permit_id", _required(self.permit_id, "Permit ID"))
        object.__setattr__(self, "channel", _required(self.channel, "Permit channel").lower())
        object.__setattr__(self, "operation", _required(self.operation, "Permit operation"))
        if len(self.command_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.command_sha256.lower()
        ):
            raise ValueError("Permit command SHA256 must be a hexadecimal digest")
        object.__setattr__(self, "command_sha256", self.command_sha256.lower())
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "Permit expiry"))


class GrowthChannelTransport(Protocol):
    def write(
        self,
        *,
        channel: str,
        operation: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...


class GrowthChannelPort(Protocol):
    capabilities: ChannelCapabilities

    def dispatch(
        self,
        command: ChannelCommand,
        *,
        eligibility: MessageEligibility | None = None,
        permit: ExternalWritePermit | None = None,
        dry_run: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


class _GovernedChannelAdapter:
    """Keep channel SDKs behind an injected transport and fail closed on writes."""

    def __init__(
        self,
        capabilities: ChannelCapabilities,
        *,
        transport: GrowthChannelTransport | None,
    ) -> None:
        self.capabilities = capabilities
        self._transport = transport
        self._requests: dict[tuple[bool, str], tuple[str, dict[str, Any]]] = {}
        self._used_permits: dict[str, str] = {}

    def dispatch(
        self,
        command: ChannelCommand,
        *,
        eligibility: MessageEligibility | None = None,
        permit: ExternalWritePermit | None = None,
        dry_run: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if command.operation not in self.capabilities.operations:
            raise ValueError(f"{self.capabilities.channel} does not support {command.operation}")
        self._require_message_eligibility(command, eligibility)
        replay_key = (dry_run, command.idempotency_key)
        prior = self._requests.get(replay_key)
        if prior is not None:
            fingerprint, receipt = prior
            if fingerprint != command.fingerprint:
                raise ValueError("Channel command idempotency conflict")
            return {**receipt, "idempotent": True}

        evaluated_at = _aware(now or datetime.now(UTC), "Dispatch time")
        if dry_run:
            receipt = self._receipt(
                command,
                mode="dry_run",
                external_write_performed=False,
                transport_result=None,
            )
        else:
            self._require_permit(command, permit, evaluated_at)
            if self._transport is None:
                raise RuntimeError("Production channel write requires an injected transport")
            transport_result = dict(
                self._transport.write(
                    channel=self.capabilities.channel,
                    operation=command.operation,
                    payload=dict(command.payload),
                    idempotency_key=command.idempotency_key,
                )
            )
            receipt = self._receipt(
                command,
                mode="permitted_write",
                external_write_performed=True,
                transport_result=transport_result,
            )
            assert permit is not None
            self._used_permits[permit.permit_id] = command.fingerprint
        self._requests[replay_key] = (command.fingerprint, receipt)
        return receipt

    def _require_message_eligibility(
        self,
        command: ChannelCommand,
        eligibility: MessageEligibility | None,
    ) -> None:
        if command.operation != "send_message":
            return
        if command.recipient_ref is None:
            raise ValueError("Direct messages require a recipient reference")
        state = eligibility or MessageEligibility()
        if state.blocked:
            raise PermissionError("Recipient has blocked channel messaging")
        if self.capabilities.requires_initiated_or_subscribed_message and not state.telegram_eligible:
            raise PermissionError("Telegram messages require a user-initiated conversation or active subscription")

    def _require_permit(
        self,
        command: ChannelCommand,
        permit: ExternalWritePermit | None,
        now: datetime,
    ) -> None:
        if permit is None:
            raise PermissionError("External channel writes require an explicit Permit")
        if (
            permit.channel != self.capabilities.channel
            or permit.operation != command.operation
            or permit.command_sha256 != command.fingerprint
        ):
            raise PermissionError("External write Permit does not match the exact command")
        if now >= permit.expires_at:
            raise PermissionError("External write Permit has expired")
        prior_fingerprint = self._used_permits.get(permit.permit_id)
        if prior_fingerprint is not None:
            raise PermissionError("External write Permit has already been consumed")

    def _receipt(
        self,
        command: ChannelCommand,
        *,
        mode: str,
        external_write_performed: bool,
        transport_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "channel": self.capabilities.channel,
            "operation": command.operation,
            "attribution_id": command.attribution_id,
            "idempotency_key": command.idempotency_key,
            "command_sha256": command.fingerprint,
            "mode": mode,
            "external_write_performed": external_write_performed,
            "transport_result": dict(transport_result) if transport_result is not None else None,
            "idempotent": False,
        }


class VKChannelAdapter(_GovernedChannelAdapter):
    def __init__(self, *, transport: GrowthChannelTransport | None = None) -> None:
        super().__init__(VK_CAPABILITIES, transport=transport)


class TelegramChannelAdapter(_GovernedChannelAdapter):
    def __init__(self, *, transport: GrowthChannelTransport | None = None) -> None:
        super().__init__(TELEGRAM_CAPABILITIES, transport=transport)


class DryRunGrowthChannelAdapter(_GovernedChannelAdapter):
    """Safe adapter for previews and tests; it can never call a transport."""

    def __init__(self, channel: str) -> None:
        channel = channel.strip().lower()
        declarations = {"vk": VK_CAPABILITIES, "telegram": TELEGRAM_CAPABILITIES}
        try:
            capabilities = declarations[channel]
        except KeyError as exc:
            raise ValueError(f"Unsupported dry-run growth channel: {channel}") from exc
        super().__init__(capabilities, transport=None)

    def dispatch(
        self,
        command: ChannelCommand,
        *,
        eligibility: MessageEligibility | None = None,
        permit: ExternalWritePermit | None = None,
        dry_run: bool = True,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not dry_run:
            raise PermissionError("Dry-run channel adapter cannot perform external writes")
        return super().dispatch(
            command,
            eligibility=eligibility,
            permit=permit,
            dry_run=True,
            now=now,
        )


@dataclass(frozen=True, slots=True)
class AttributionIdentity:
    channel: str
    campaign_ref: str
    creative_ref: str
    subject_ref: str
    sku_ref: str
    offer_ref: str
    attribution_id: str = field(init=False)

    def __post_init__(self) -> None:
        values = {
            "channel": _required(self.channel, "Attribution channel").lower(),
            "campaign_ref": _required(self.campaign_ref, "Campaign reference"),
            "creative_ref": _required(self.creative_ref, "Creative reference"),
            "subject_ref": _required(self.subject_ref, "Attribution subject"),
            "sku_ref": _required(self.sku_ref, "SKU reference"),
            "offer_ref": _required(self.offer_ref, "Offer reference"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "attribution_id", f"gat_{_sha256(values)[:32]}")


@dataclass(frozen=True, slots=True)
class GrowthAttributionEvent:
    event_id: str
    attribution_id: str
    channel: str
    event_type: GrowthEventType
    occurred_at: datetime
    currency: str
    amount: Decimal = Decimal("0")
    channel_cost: Decimal = Decimal("0")
    reward_accrual: Decimal = Decimal("0")
    order_ref: str | None = None
    account_ref: str | None = None
    device_ref: str | None = None
    seller_account_ref: str | None = None
    refund_window_ends_at: datetime | None = None
    explicit_fraud_flags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required(self.event_id, "Growth event ID"))
        object.__setattr__(
            self,
            "attribution_id",
            _required(self.attribution_id, "Growth event attribution ID"),
        )
        object.__setattr__(self, "channel", _required(self.channel, "Growth event channel").lower())
        try:
            event_type = GrowthEventType(self.event_type)
        except ValueError as exc:
            raise ValueError("Unknown growth event type") from exc
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "Event occurrence"))
        object.__setattr__(self, "currency", ascii_currency(self.currency))
        amount = _money(self.amount, "Growth event amount")
        cost = _money(self.channel_cost, "Growth channel cost")
        reward = _money(self.reward_accrual, "Growth reward accrual")
        if cost < 0 or reward < 0:
            raise ValueError("Growth costs and reward accruals cannot be negative")
        if event_type == GrowthEventType.REFUND and amount < 0:
            raise ValueError("Refund amount must be an unsigned loss amount")
        if event_type not in {GrowthEventType.REFUND, GrowthEventType.CASH_CM3} and amount != 0:
            raise ValueError("Only refund and cash_cm3 events may carry an amount")
        if event_type != GrowthEventType.ORDER and reward != 0:
            raise ValueError("Rewards can only accrue on an order event")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "channel_cost", cost)
        object.__setattr__(self, "reward_accrual", reward)
        if event_type in _ORDER_EVENT_TYPES:
            if self.order_ref is None:
                raise ValueError(f"{event_type.value} events require an order reference")
            object.__setattr__(self, "order_ref", _required(self.order_ref, "Order reference"))
        elif self.order_ref is not None:
            raise ValueError("Pre-order growth events cannot carry an order reference")
        for name in ("account_ref", "device_ref", "seller_account_ref"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _required(value, name.replace("_", " ").title()))
        if self.refund_window_ends_at is not None:
            window = _aware(self.refund_window_ends_at, "Refund window end")
            if event_type != GrowthEventType.ORDER:
                raise ValueError("Only order events define the refund window")
            if window <= self.occurred_at:
                raise ValueError("Refund window must end after the order")
            object.__setattr__(self, "refund_window_ends_at", window)
        if event_type == GrowthEventType.ORDER and self.refund_window_ends_at is None:
            raise ValueError("Order events require a refund-window end")
        flags = frozenset(self.explicit_fraud_flags)
        unknown = flags - FRAUD_FLAGS
        if unknown:
            raise ValueError(f"Unknown growth fraud flags: {', '.join(sorted(unknown))}")
        object.__setattr__(self, "explicit_fraud_flags", flags)

    @property
    def fingerprint(self) -> str:
        return _sha256(
            {
                "event_id": self.event_id,
                "attribution_id": self.attribution_id,
                "channel": self.channel,
                "event_type": self.event_type,
                "occurred_at": self.occurred_at,
                "currency": self.currency,
                "amount": self.amount,
                "channel_cost": self.channel_cost,
                "reward_accrual": self.reward_accrual,
                "order_ref": self.order_ref,
                "account_ref": self.account_ref,
                "device_ref": self.device_ref,
                "seller_account_ref": self.seller_account_ref,
                "refund_window_ends_at": self.refund_window_ends_at,
                "explicit_fraud_flags": self.explicit_fraud_flags,
            }
        )


@dataclass(frozen=True, slots=True)
class GrowthAttributionPolicy:
    currency: str
    stop_loss: Decimal
    minimum_incremental_cash_cm3: Decimal = Decimal("0")
    device_account_limit: int = 2
    account_attribution_limit: int = 3
    refund_abuse_count: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", ascii_currency(self.currency))
        stop_loss = _money(self.stop_loss, "Growth stop loss")
        minimum = _money(
            self.minimum_incremental_cash_cm3,
            "Minimum incremental cash CM3",
        )
        if stop_loss <= 0:
            raise ValueError("Growth stop loss must be positive")
        for name in (
            "device_account_limit",
            "account_attribution_limit",
            "refund_abuse_count",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least one")
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "minimum_incremental_cash_cm3", minimum)


class GrowthAttributionLedger:
    """Project one deterministic, conservative profit journey per attribution ID."""

    def __init__(self, policy: GrowthAttributionPolicy) -> None:
        self.policy = policy
        self._identities: dict[str, AttributionIdentity] = {}
        self._baselines: dict[str, Decimal] = {}
        self._events: dict[str, list[GrowthAttributionEvent]] = {}
        self._event_fingerprints: dict[str, str] = {}
        self._order_owners: dict[str, str] = {}
        self._device_accounts: dict[str, set[str]] = {}
        self._account_attributions: dict[str, set[str]] = {}
        self._account_refunds: dict[str, int] = {}
        self._fraud_flags: dict[str, set[str]] = {}

    def register(
        self,
        identity: AttributionIdentity,
        *,
        baseline_cash_cm3: Decimal = Decimal("0"),
    ) -> dict[str, Any]:
        baseline = _money(baseline_cash_cm3, "Baseline cash CM3")
        prior = self._identities.get(identity.attribution_id)
        if prior is not None:
            if prior != identity or self._baselines[identity.attribution_id] != baseline:
                raise ValueError("Attribution registration idempotency conflict")
            return {
                "attribution_id": identity.attribution_id,
                "baseline_cash_cm3": str(baseline),
                "currency": self.policy.currency,
                "idempotent": True,
            }
        self._identities[identity.attribution_id] = identity
        self._baselines[identity.attribution_id] = baseline
        self._events[identity.attribution_id] = []
        self._fraud_flags[identity.attribution_id] = set()
        return {
            "attribution_id": identity.attribution_id,
            "baseline_cash_cm3": str(baseline),
            "currency": self.policy.currency,
            "idempotent": False,
        }

    def record(
        self,
        event: GrowthAttributionEvent,
        *,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._identity(event.attribution_id)
        prior_fingerprint = self._event_fingerprints.get(event.event_id)
        if prior_fingerprint is not None:
            if prior_fingerprint != event.fingerprint:
                raise ValueError("Growth event idempotency conflict")
            return {
                "idempotent": True,
                "projection": self.project(
                    event.attribution_id,
                    as_of=as_of or max(item.occurred_at for item in self._events[event.attribution_id]),
                ),
            }
        if event.channel != identity.channel:
            raise ValueError("Growth event channel does not match its attribution identity")
        if event.currency != self.policy.currency:
            raise ValueError("Growth event currency does not match the attribution policy")
        events = self._events[event.attribution_id]
        if events and event.occurred_at < events[-1].occurred_at:
            raise ValueError("Growth events must be recorded in occurrence order")
        self._require_predecessor(events, event)
        self._require_order_consistency(events, event)

        self._events[event.attribution_id].append(event)
        self._event_fingerprints[event.event_id] = event.fingerprint
        self._apply_fraud_signals(event)
        return {
            "idempotent": False,
            "projection": self.project(event.attribution_id, as_of=as_of or event.occurred_at),
        }

    def project(self, attribution_id: str, *, as_of: datetime) -> dict[str, Any]:
        identity = self._identity(attribution_id)
        evaluated_at = _aware(as_of, "Attribution evaluation time")
        events = [event for event in self._events[attribution_id] if event.occurred_at <= evaluated_at]
        counts = {
            event_type.value: sum(event.event_type == event_type for event in events) for event_type in FUNNEL_ORDER
        }
        order = next(
            (event for event in events if event.event_type == GrowthEventType.ORDER),
            None,
        )
        refunds = [event for event in events if event.event_type == GrowthEventType.REFUND]
        settlements = [event for event in events if event.event_type == GrowthEventType.SETTLEMENT]
        cash_events = [event for event in events if event.event_type == GrowthEventType.CASH_CM3]
        channel_cost = sum((event.channel_cost for event in events), Decimal("0"))
        reward_accrued = order.reward_accrual if order is not None else Decimal("0")
        refund_loss = sum((event.amount for event in refunds), Decimal("0"))
        cash_cm3 = sum((event.amount for event in cash_events), Decimal("0")) - refund_loss
        flags = sorted(self._fraud_flags[attribution_id])
        reward_status = self._reward_status(
            order=order,
            has_refund=bool(refunds),
            has_settlement=bool(settlements),
            fraud_flags=flags,
            as_of=evaluated_at,
        )
        reward_cost = reward_accrued if reward_status != "forfeited" else Decimal("0")
        total_growth_cost = channel_cost + reward_cost
        baseline = self._baselines[attribution_id]
        incremental = cash_cm3 - baseline - total_growth_cost
        decision, reason_codes = self._decision(
            events=events,
            fraud_flags=flags,
            reward_status=reward_status,
            incremental_cash_cm3=incremental,
            has_refund=bool(refunds),
            has_settlement=bool(settlements),
            has_cash=bool(cash_events),
        )
        stage = (
            max(events, key=lambda item: _FUNNEL_INDEX[item.event_type]).event_type.value if events else "registered"
        )
        return {
            "attribution_id": attribution_id,
            "channel": identity.channel,
            "campaign_ref": identity.campaign_ref,
            "creative_ref": identity.creative_ref,
            "subject_ref": identity.subject_ref,
            "sku_ref": identity.sku_ref,
            "offer_ref": identity.offer_ref,
            "stage": stage,
            "event_counts": counts,
            "currency": self.policy.currency,
            "economics": {
                "cash_cm3_after_refunds": str(_money(cash_cm3, "Cash CM3")),
                "baseline_cash_cm3": str(baseline),
                "channel_cost": str(_money(channel_cost, "Channel cost")),
                "reward_cost_exposure": str(_money(reward_cost, "Reward cost")),
                "total_growth_cost": str(_money(total_growth_cost, "Total growth cost")),
                "incremental_cash_cm3": str(_money(incremental, "Incremental cash CM3")),
                "optimization_objective": "incremental_cash_cm3",
            },
            "reward": {
                "status": reward_status,
                "accrued": str(_money(reward_accrued, "Reward accrual")),
                "confirmed": (
                    str(_money(reward_accrued, "Confirmed reward")) if reward_status == "confirmed" else "0.00"
                ),
                "refund_window_ends_at": (
                    order.refund_window_ends_at.isoformat()
                    if order is not None and order.refund_window_ends_at is not None
                    else None
                ),
            },
            "fraud_flags": flags,
            "decision": decision,
            "reason_codes": reason_codes,
            "manual_review_required": decision == "manual_review",
            "external_write_allowed": False,
            "evaluated_at": evaluated_at.isoformat(),
        }

    def optimize(
        self,
        attribution_ids: list[str] | None = None,
        *,
        as_of: datetime,
    ) -> dict[str, Any]:
        ids = attribution_ids or sorted(self._identities)
        if len(ids) != len(set(ids)):
            raise ValueError("Attribution optimization contains duplicate IDs")
        rows = [self.project(attribution_id, as_of=as_of) for attribution_id in ids]
        rows.sort(
            key=lambda row: (
                -Decimal(row["economics"]["incremental_cash_cm3"]),
                row["attribution_id"],
            )
        )
        return {
            "optimization_objective": "incremental_cash_cm3",
            "currency": self.policy.currency,
            "attributions": rows,
            "totals": {
                "incremental_cash_cm3": str(
                    _money(
                        sum(
                            (Decimal(row["economics"]["incremental_cash_cm3"]) for row in rows),
                            Decimal("0"),
                        ),
                        "Portfolio incremental cash CM3",
                    )
                ),
                "stop": sum(row["decision"] == "stop" for row in rows),
                "hold": sum(row["decision"] == "hold" for row in rows),
                "manual_review": sum(row["decision"] == "manual_review" for row in rows),
                "continue": sum(row["decision"] == "continue" for row in rows),
            },
            "external_write_allowed": False,
        }

    def _identity(self, attribution_id: str) -> AttributionIdentity:
        try:
            return self._identities[attribution_id]
        except KeyError as exc:
            raise KeyError(f"Unknown attribution ID: {attribution_id}") from exc

    @staticmethod
    def _require_predecessor(
        events: list[GrowthAttributionEvent],
        event: GrowthAttributionEvent,
    ) -> None:
        predecessor = _PREDECESSOR.get(event.event_type)
        if predecessor is not None and not any(item.event_type == predecessor for item in events):
            raise ValueError(f"{event.event_type.value} requires a prior {predecessor.value} event")
        if event.event_type in {
            GrowthEventType.ORDER,
            GrowthEventType.REFUND,
            GrowthEventType.SETTLEMENT,
            GrowthEventType.CASH_CM3,
        } and any(item.event_type == event.event_type for item in events):
            raise ValueError(f"Attribution journey already has a {event.event_type.value} event")

    @staticmethod
    def _require_order_consistency(
        events: list[GrowthAttributionEvent],
        event: GrowthAttributionEvent,
    ) -> None:
        prior_order_ref = next(
            (item.order_ref for item in events if item.order_ref is not None),
            None,
        )
        if prior_order_ref is not None and event.order_ref is not None and prior_order_ref != event.order_ref:
            raise ValueError("Growth journey order reference cannot change")

    def _apply_fraud_signals(self, event: GrowthAttributionEvent) -> None:
        attribution_id = event.attribution_id
        flags = self._fraud_flags[attribution_id]
        flags.update(event.explicit_fraud_flags)
        if (
            event.account_ref is not None
            and event.seller_account_ref is not None
            and event.account_ref == event.seller_account_ref
        ):
            flags.add("self_buy")
        if event.account_ref is not None:
            account_attributions = self._account_attributions.setdefault(event.account_ref, set())
            account_attributions.add(attribution_id)
            if len(account_attributions) > self.policy.account_attribution_limit:
                for linked_id in account_attributions:
                    self._fraud_flags[linked_id].add("bulk_account")
        if event.device_ref is not None and event.account_ref is not None:
            device_accounts = self._device_accounts.setdefault(event.device_ref, set())
            device_accounts.add(event.account_ref)
            if len(device_accounts) > self.policy.device_account_limit:
                for linked_id, linked_events in self._events.items():
                    if any(item.device_ref == event.device_ref for item in linked_events):
                        self._fraud_flags[linked_id].add("device_reuse")
        if event.event_type == GrowthEventType.ORDER and event.order_ref is not None:
            prior_owner = self._order_owners.get(event.order_ref)
            if prior_owner is None:
                self._order_owners[event.order_ref] = attribution_id
            elif prior_owner != attribution_id:
                flags.add("cross_channel")
                self._fraud_flags[prior_owner].add("cross_channel")
        if event.event_type == GrowthEventType.REFUND and event.account_ref is not None:
            count = self._account_refunds.get(event.account_ref, 0) + 1
            self._account_refunds[event.account_ref] = count
            if count >= self.policy.refund_abuse_count:
                for linked_id in self._account_attributions.get(event.account_ref, set()):
                    self._fraud_flags[linked_id].add("refund_abuse")

    @staticmethod
    def _reward_status(
        *,
        order: GrowthAttributionEvent | None,
        has_refund: bool,
        has_settlement: bool,
        fraud_flags: list[str],
        as_of: datetime,
    ) -> str:
        if order is None or order.reward_accrual == 0:
            return "not_applicable"
        if has_refund:
            return "forfeited"
        if fraud_flags:
            return "held"
        assert order.refund_window_ends_at is not None
        if not has_settlement or as_of < order.refund_window_ends_at:
            return "accrued"
        return "confirmed"

    def _decision(
        self,
        *,
        events: list[GrowthAttributionEvent],
        fraud_flags: list[str],
        reward_status: str,
        incremental_cash_cm3: Decimal,
        has_refund: bool,
        has_settlement: bool,
        has_cash: bool,
    ) -> tuple[str, list[str]]:
        if fraud_flags:
            return "manual_review", [f"fraud_{flag}" for flag in fraud_flags]
        if has_refund:
            return "stop", ["refund_recorded"]
        if not events:
            return "hold", ["no_growth_events"]
        if not has_settlement:
            return "hold", ["settlement_pending"]
        if reward_status == "accrued":
            return "hold", ["refund_window_open"]
        if not has_cash:
            return "hold", ["cash_cm3_pending"]
        if incremental_cash_cm3 <= -self.policy.stop_loss:
            return "stop", ["incremental_cash_cm3_stop_loss"]
        if incremental_cash_cm3 <= self.policy.minimum_incremental_cash_cm3:
            return "hold", ["incremental_cash_cm3_below_minimum"]
        return "continue", ["positive_incremental_cash_cm3"]
