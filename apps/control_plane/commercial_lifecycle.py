from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

CommercialState = Literal["active", "grace", "read_only", "closed"]

CommercialLifecycleKind = Literal[
    "plan",
    "subscription",
    "entitlement",
    "invoice",
    "payment_attempt",
    "refund",
    "tax_evidence",
]

CommercialLifecycleState = Literal[
    "draft",
    "approved",
    "frozen",
    "pending",
    "active",
    "past_due",
    "canceled",
    "issued",
    "partially_paid",
    "paid",
    "void",
    "closed",
    "submitted",
    "succeeded",
    "failed",
    "settled",
    "requested",
    "rejected",
    "verified",
    "recorded",
    "grace",
    "read_only",
]

ALLOWED_METRICS = frozenset(
    {
        "api_calls",
        "requests",
        "seats",
        "storage_gib",
    }
)

ALLOWED_COMMERICAL_CURRENCIES = frozenset({"CNY", "RUB"})
PLAN_STATE_ORDER = {"draft": 0, "approved": 1, "frozen": 2, "closed": 3}
SUBSCRIPTION_STATE_ORDER = {"pending": 0, "active": 1, "past_due": 2, "canceled": 3, "closed": 4}
INVOICE_STATE_ORDER = {"draft": 0, "issued": 1, "partially_paid": 2, "paid": 3, "void": 4, "closed": 5}
PAYMENT_STATE_ORDER = {"pending": 0, "submitted": 1, "succeeded": 2, "failed": 3, "settled": 4}
REFUND_STATE_ORDER = {"requested": 0, "approved": 1, "paid": 2, "rejected": 3, "reversed": 4}
REFUND_STATE_TRANSITIONS = {
    "requested": frozenset({"approved", "paid", "rejected"}),
    "approved": frozenset({"paid", "rejected"}),
    "paid": frozenset({"reversed"}),
    "rejected": frozenset(),
    "reversed": frozenset(),
}
TAX_STATE_ORDER = {"recorded": 0, "verified": 1, "rejected": 2}
COLLECTIBLE_INVOICE_STATES = frozenset({"issued", "partially_paid", "paid"})

STATE_ORDER: dict[CommercialState, int] = {
    "active": 0,
    "grace": 1,
    "read_only": 2,
    "closed": 3,
}

FORBIDDEN_ENTITLEMENT_FIELDS = frozenset(
    {
        "icp",
        "plan_fit",
        "plan_recommendation",
        "recommended_plan",
        "seller_tier",
    }
)
HEX64 = frozenset(string.hexdigits.lower())


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _request_hash(kind: str, event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "kind"}
    return _sha256({"kind": kind, "payload": payload})


def _text(value: Any, field: str, *, maximum: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True, slots=True)
class CommercialScope:
    customer_ref: str
    deployment_ref: str
    tenant_ref: str
    entity_ref: str
    store_ref: str

    def as_dict(self) -> dict[str, str]:
        return {
            "customer_ref": self.customer_ref,
            "deployment_ref": self.deployment_ref,
            "tenant_ref": self.tenant_ref,
            "entity_ref": self.entity_ref,
            "store_ref": self.store_ref,
        }

    @property
    def scope_hash(self) -> str:
        return _sha256(self.as_dict())


@dataclass(frozen=True, slots=True)
class MetricLimit:
    metric: str
    limit: Decimal
    grace_limit: Decimal

    def as_dict(self) -> dict[str, str]:
        return {
            "metric": self.metric,
            "limit": str(self.limit),
            "grace_limit": str(self.grace_limit),
        }


@dataclass(slots=True)
class UsageLedgerEntry:
    metric: str
    amount: Decimal
    window_start: datetime
    window_end: datetime
    occurred_at: datetime
    idempotency_key: str
    request_sha256: str
    decision_sha256: str
    recorded_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "amount": str(self.amount),
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "occurred_at": self.occurred_at.isoformat(),
            "idempotency_key": self.idempotency_key,
            "request_sha256": self.request_sha256,
            "decision_sha256": self.decision_sha256,
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(slots=True)
class CommercialEntitlement:
    entitlement_id: str
    scope: CommercialScope
    accepted_at: datetime
    billing_window_start: datetime
    billing_window_end: datetime
    metrics: dict[str, MetricLimit]
    state: CommercialState = "active"
    closed_reason: str | None = None
    usage_totals: dict[str, Decimal] = field(default_factory=dict)
    ledger: list[UsageLedgerEntry] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def limit_for(self, metric: str) -> MetricLimit:
        try:
            return self.metrics[metric]
        except KeyError as exc:
            raise KeyError("metric is not allowlisted for this entitlement") from exc

    def used_for(self, metric: str) -> Decimal:
        return self.usage_totals.get(metric, Decimal("0"))

    def snapshot(self) -> dict[str, Any]:
        metrics = {}
        for metric, limit in sorted(self.metrics.items()):
            used = self.used_for(metric)
            remaining = max(limit.limit - used, Decimal("0"))
            metrics[metric] = {
                "limit": str(limit.limit),
                "grace_limit": str(limit.grace_limit),
                "used": str(used),
                "remaining": str(remaining),
                "state": self.state,
            }
        return {
            "entitlement_id": self.entitlement_id,
            "scope": self.scope.as_dict(),
            "scope_hash": self.scope.scope_hash,
            "state": self.state,
            "closed_reason": self.closed_reason,
            "accepted_at": self.accepted_at.isoformat(),
            "billing_window_start": self.billing_window_start.isoformat(),
            "billing_window_end": self.billing_window_end.isoformat(),
            "metrics": metrics,
            "ledger": [entry.as_dict() for entry in self.ledger],
            "history": list(self.history),
        }


class CommercialLifecycleKernel:
    """Pure domain kernel for exact-scope commercial billing and usage control."""

    CONTRACT_ID = "kjds-commercial-lifecycle-kernel-v1"
    ACCEPTED_EVENT_KIND = "commercial_authorization_accepted"
    USAGE_EVENT_KIND = "usage_recorded"
    TRANSITION_EVENT_KIND = "lifecycle_transition"
    ALLOWED_TRANSITIONS: dict[CommercialState, frozenset[CommercialState]] = {
        "active": frozenset({"grace", "read_only", "closed"}),
        "grace": frozenset({"read_only", "closed"}),
        "read_only": frozenset({"closed"}),
        "closed": frozenset(),
    }

    def __init__(self) -> None:
        self._entitlements: dict[str, CommercialEntitlement] = {}
        self._idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        kind = _text(event.get("kind"), "kind", maximum=80)
        idempotency_key = _text(event.get("idempotency_key"), "idempotency_key", maximum=160)
        if kind == self.ACCEPTED_EVENT_KIND:
            scope = self._scope(
                customer_ref=event.get("customer_ref"),
                deployment_ref=event.get("deployment_ref"),
                tenant_ref=event.get("tenant_ref"),
                entity_ref=event.get("entity_ref"),
                store_ref=event.get("store_ref"),
            )
            request_hash = self._request_hash(kind=kind, event=event)
            cached = self._idempotency.get((scope.scope_hash, kind, idempotency_key))
            if cached is not None:
                if cached[0] != request_hash:
                    raise ValueError("idempotency key conflicts with a different commercial request")
                return {**_copy(cached[1]), "idempotent": True}
            result = self._accept_authorization(event, scope=scope, request_hash=request_hash)
        elif kind == self.USAGE_EVENT_KIND:
            scope = self._scope(
                customer_ref=event.get("customer_ref"),
                deployment_ref=event.get("deployment_ref"),
                tenant_ref=event.get("tenant_ref"),
                entity_ref=event.get("entity_ref"),
                store_ref=event.get("store_ref"),
            )
            request_hash = self._request_hash(kind=kind, event=event)
            cached = self._idempotency.get((scope.scope_hash, kind, idempotency_key))
            if cached is not None:
                if cached[0] != request_hash:
                    raise ValueError("idempotency key conflicts with a different commercial request")
                return {**_copy(cached[1]), "idempotent": True}
            result = self._record_usage(
                event,
                scope=scope,
                request_hash=request_hash,
            )
        elif kind == self.TRANSITION_EVENT_KIND:
            scope = self._scope(
                customer_ref=event.get("customer_ref"),
                deployment_ref=event.get("deployment_ref"),
                tenant_ref=event.get("tenant_ref"),
                entity_ref=event.get("entity_ref"),
                store_ref=event.get("store_ref"),
            )
            request_hash = self._request_hash(kind=kind, event=event)
            cached = self._idempotency.get((scope.scope_hash, kind, idempotency_key))
            if cached is not None:
                if cached[0] != request_hash:
                    raise ValueError("idempotency key conflicts with a different commercial request")
                return {**_copy(cached[1]), "idempotent": True}
            result = self._transition(
                event,
                scope=scope,
                request_hash=request_hash,
            )
        else:
            raise ValueError("unknown commercial lifecycle event kind")

        self._idempotency[(scope.scope_hash, kind, idempotency_key)] = (request_hash, _copy(result))
        return result

    def snapshot(self, *, customer_ref: str, deployment_ref: str, tenant_ref: str, entity_ref: str, store_ref: str) -> dict[str, Any]:
        scope = self._scope(
            customer_ref=customer_ref,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
        )
        entitlement = self._entitlement_for(scope)
        return entitlement.snapshot()

    def _accept_authorization(
        self,
        event: dict[str, Any],
        *,
        scope: CommercialScope,
        request_hash: str,
    ) -> dict[str, Any]:
        forbidden = sorted(key for key in FORBIDDEN_ENTITLEMENT_FIELDS if key in event and event.get(key) is not None)
        if forbidden:
            raise ValueError("commercial entitlement must be created from an accepted commercial authorization event, not plan fit or seller intelligence")
        authorization_ref = _text(event.get("authorization_ref"), "authorization_ref", maximum=200)
        authorization_sha256 = _text(event.get("authorization_sha256"), "authorization_sha256", maximum=64)
        if len(authorization_sha256) != 64 or any(ch not in HEX64 for ch in authorization_sha256):
            raise ValueError("authorization_sha256 must be a 64-character lowercase hex digest")
        authorization_status = _text(event.get("authorization_status"), "authorization_status", maximum=40)
        if authorization_status != "accepted":
            raise ValueError("authorization_status must be accepted")
        authorization_source_kind = _text(
            event.get("authorization_source_kind"),
            "authorization_source_kind",
            maximum=80,
        )
        if authorization_source_kind != "commercial_contract_authorization":
            raise ValueError("authorization_source_kind must be commercial_contract_authorization")
        accepted_at = _timestamp(event.get("accepted_at"), "accepted_at")
        billing_window_start = _timestamp(event.get("billing_window_start"), "billing_window_start")
        billing_window_end = _timestamp(event.get("billing_window_end"), "billing_window_end")
        if billing_window_end <= billing_window_start:
            raise ValueError("billing_window_end must be after billing_window_start")
        limit_rows = event.get("metric_limits")
        if not isinstance(limit_rows, list) or not limit_rows:
            raise ValueError("metric_limits must contain at least one allowlisted metric")
        metrics: dict[str, MetricLimit] = {}
        for item in limit_rows:
            if not isinstance(item, dict):
                raise ValueError("metric_limits must be objects")
            metric = _text(item.get("metric"), "metric", maximum=80)
            if metric not in ALLOWED_METRICS:
                raise ValueError("metric is not allowlisted")
            if metric in metrics:
                raise ValueError("metric_limits must not contain duplicate metrics")
            limit = _decimal(item.get("limit"), f"{metric}.limit")
            if limit <= 0:
                raise ValueError("metric limits must be positive")
            grace_raw = item.get("grace_limit")
            grace_limit = _decimal(grace_raw, f"{metric}.grace_limit") if grace_raw is not None else limit
            if grace_limit < 0 or grace_limit > limit:
                raise ValueError("grace_limit must be between zero and limit")
            metrics[metric] = MetricLimit(metric=metric, limit=limit, grace_limit=grace_limit)
        if not metrics:
            raise ValueError("metric_limits must contain at least one allowlisted metric")
        if scope.scope_hash in self._entitlements:
            entitlement = self._entitlements[scope.scope_hash]
            if entitlement.state == "closed":
                return self._decision(
                    request_hash=request_hash,
                    kind=self.ACCEPTED_EVENT_KIND,
                    scope=scope,
                    state="closed",
                    reason="entitlement_closed",
                    limit=Decimal("0"),
                    used=Decimal("0"),
                    remaining=Decimal("0"),
                    as_of=accepted_at,
                    idempotent=False,
                )
            raise ValueError("commercial entitlement already exists for exact scope")

        entitlement = CommercialEntitlement(
            entitlement_id=f"cl_{scope.scope_hash[:24]}",
            scope=scope,
            accepted_at=accepted_at,
            billing_window_start=billing_window_start,
            billing_window_end=billing_window_end,
            metrics=metrics,
        )
        self._entitlements[scope.scope_hash] = entitlement
        entitlement.history.append(
            {
                "event": self.ACCEPTED_EVENT_KIND,
                "request_sha256": request_hash,
                "accepted_at": accepted_at.isoformat(),
                "authorization_ref": authorization_ref,
                "authorization_sha256": authorization_sha256,
            }
        )
        primary_metric = sorted(metrics)[0]
        limit = metrics[primary_metric].limit
        used = entitlement.used_for(primary_metric)
        return self._decision(
            request_hash=request_hash,
            kind=self.ACCEPTED_EVENT_KIND,
            scope=scope,
            state=entitlement.state,
            reason="commercial_authorization_accepted",
            limit=limit,
            used=used,
            remaining=max(limit - used, Decimal("0")),
            as_of=accepted_at,
            idempotent=False,
            metric=primary_metric,
        )

    def _record_usage(
        self,
        event: dict[str, Any],
        *,
        scope: CommercialScope,
        request_hash: str,
    ) -> dict[str, Any]:
        entitlement = self._entitlement_for(scope)
        if entitlement.state == "closed":
            return self._decision(
                request_hash=request_hash,
                kind=self.USAGE_EVENT_KIND,
                scope=scope,
                state="closed",
                reason="entitlement_closed",
                limit=Decimal("0"),
                used=Decimal("0"),
                remaining=Decimal("0"),
                as_of=_timestamp(event.get("occurred_at"), "occurred_at"),
                idempotent=False,
                metric=_text(event.get("metric"), "metric", maximum=80),
            )
        metric = _text(event.get("metric"), "metric", maximum=80)
        if metric not in ALLOWED_METRICS:
            raise ValueError("metric is not allowlisted")
        if metric not in entitlement.metrics:
            raise ValueError("metric is not allowlisted for this entitlement")
        if entitlement.state == "read_only":
            occurred_at = _timestamp(event.get("occurred_at"), "occurred_at")
            return self._decision(
                request_hash=request_hash,
                kind=self.USAGE_EVENT_KIND,
                scope=scope,
                state="read_only",
                reason="entitlement_read_only",
                limit=entitlement.limit_for(metric).limit,
                used=entitlement.used_for(metric),
                remaining=max(entitlement.limit_for(metric).limit - entitlement.used_for(metric), Decimal("0")),
                as_of=occurred_at,
                idempotent=False,
                metric=metric,
            )
        amount = _decimal(event.get("amount"), f"{metric}.amount")
        if amount < 0:
            raise ValueError("usage amount must be non-negative")
        occurred_at = _timestamp(event.get("occurred_at"), "occurred_at")
        window_start = _timestamp(event.get("window_start"), "window_start")
        window_end = _timestamp(event.get("window_end"), "window_end")
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        if window_start != entitlement.billing_window_start or window_end != entitlement.billing_window_end:
            raise ValueError("usage window must match the accepted billing window exactly")
        if not (window_start <= occurred_at < window_end):
            raise ValueError("occurred_at must fall inside the explicit usage window")

        limit = entitlement.limit_for(metric).limit
        grace_limit = entitlement.limit_for(metric).grace_limit
        current = entitlement.used_for(metric)
        projected = current + amount
        if projected > limit:
            entitlement.state = "read_only"
            entitlement.history.append(
                {
                    "event": self.USAGE_EVENT_KIND,
                    "metric": metric,
                    "request_sha256": request_hash,
                    "decision": "deny",
                    "reason": "quota_exceeded",
                    "projected": str(projected),
                }
            )
            return self._decision(
                request_hash=request_hash,
                kind=self.USAGE_EVENT_KIND,
                scope=scope,
                state="read_only",
                reason="quota_exceeded",
                limit=limit,
                used=current,
                remaining=max(limit - current, Decimal("0")),
                as_of=occurred_at,
                idempotent=False,
                metric=metric,
            )

        entitlement.usage_totals[metric] = projected
        decision_state: CommercialState
        if projected >= limit:
            decision_state = "read_only"
        elif projected >= grace_limit:
            decision_state = "grace"
        else:
            decision_state = "active"
        entitlement.state = self._more_restrictive(entitlement.state, decision_state)
        recorded_at = datetime.now(UTC)
        provisional = self._decision(
            request_hash=request_hash,
            kind=self.USAGE_EVENT_KIND,
            scope=scope,
            state=entitlement.state,
            reason="usage_recorded",
            limit=limit,
            used=projected,
            remaining=max(limit - projected, Decimal("0")),
            as_of=occurred_at,
            idempotent=False,
            metric=metric,
        )
        entitlement.ledger.append(
            UsageLedgerEntry(
                metric=metric,
                amount=amount,
                window_start=window_start,
                window_end=window_end,
                occurred_at=occurred_at,
                idempotency_key=_text(event.get("idempotency_key"), "idempotency_key", maximum=160),
                request_sha256=request_hash,
                decision_sha256=provisional["decision_sha256"],
                recorded_at=recorded_at,
            )
        )
        entitlement.history.append(
            {
                "event": self.USAGE_EVENT_KIND,
                "metric": metric,
                "request_sha256": request_hash,
                "decision": "allow",
                "state": entitlement.state,
                "used": str(projected),
            }
        )
        return provisional

    def _transition(
        self,
        event: dict[str, Any],
        *,
        scope: CommercialScope,
        request_hash: str,
    ) -> dict[str, Any]:
        entitlement = self._entitlement_for(scope)
        target = _text(event.get("target_state"), "target_state", maximum=32)
        reason = _text(event.get("reason"), "reason", maximum=200)
        as_of = _timestamp(event.get("as_of"), "as_of")
        if target not in STATE_ORDER:
            entitlement.state = "closed"
            entitlement.closed_reason = "invalid_transition"
            entitlement.history.append(
                {
                    "event": self.TRANSITION_EVENT_KIND,
                    "request_sha256": request_hash,
                    "target_state": target,
                    "decision": "deny",
                    "reason": "invalid_transition",
                }
            )
            return self._decision(
                request_hash=request_hash,
                kind=self.TRANSITION_EVENT_KIND,
                scope=scope,
                state="closed",
                reason="invalid_transition",
                limit=Decimal("0"),
                used=Decimal("0"),
                remaining=Decimal("0"),
                as_of=as_of,
                idempotent=False,
            )
        if entitlement.state == "closed":
            return self._decision(
                request_hash=request_hash,
                kind=self.TRANSITION_EVENT_KIND,
                scope=scope,
                state="closed",
                reason="entitlement_closed",
                limit=Decimal("0"),
                used=Decimal("0"),
                remaining=Decimal("0"),
                as_of=as_of,
                idempotent=False,
            )
        if target == entitlement.state:
            return self._decision(
                request_hash=request_hash,
                kind=self.TRANSITION_EVENT_KIND,
                scope=scope,
                state=entitlement.state,
                reason=reason,
                limit=self._primary_limit(entitlement),
                used=self._primary_used(entitlement),
                remaining=self._primary_remaining(entitlement),
                as_of=as_of,
                idempotent=False,
            )
        if target not in self.ALLOWED_TRANSITIONS[entitlement.state]:
            entitlement.state = "closed"
            entitlement.closed_reason = "invalid_transition"
            entitlement.history.append(
                {
                    "event": self.TRANSITION_EVENT_KIND,
                    "request_sha256": request_hash,
                    "target_state": target,
                    "decision": "deny",
                    "reason": "invalid_transition",
                }
            )
            return self._decision(
                request_hash=request_hash,
                kind=self.TRANSITION_EVENT_KIND,
                scope=scope,
                state="closed",
                reason="invalid_transition",
                limit=self._primary_limit(entitlement),
                used=self._primary_used(entitlement),
                remaining=self._primary_remaining(entitlement),
                as_of=as_of,
                idempotent=False,
            )
        entitlement.state = target
        if target == "closed":
            entitlement.closed_reason = reason
        entitlement.history.append(
            {
                "event": self.TRANSITION_EVENT_KIND,
                "request_sha256": request_hash,
                "target_state": target,
                "decision": "allow",
                "reason": reason,
                "state": entitlement.state,
            }
        )
        return self._decision(
            request_hash=request_hash,
            kind=self.TRANSITION_EVENT_KIND,
            scope=scope,
            state=entitlement.state,
            reason=reason,
            limit=self._primary_limit(entitlement),
            used=self._primary_used(entitlement),
            remaining=self._primary_remaining(entitlement),
            as_of=as_of,
            idempotent=False,
        )

    def _decision(
        self,
        *,
        request_hash: str,
        kind: str,
        scope: CommercialScope,
        state: CommercialState,
        reason: str,
        limit: Decimal,
        used: Decimal,
        remaining: Decimal,
        as_of: datetime,
        idempotent: bool,
        metric: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "kind": kind,
            "request_sha256": request_hash,
            "scope": scope.as_dict(),
            "scope_hash": scope.scope_hash,
            "state": state,
            "reason": reason,
            "limit": str(limit),
            "used": str(used),
            "remaining": str(remaining),
            "as_of": as_of.astimezone(UTC).isoformat(),
        }
        if metric is not None:
            payload["metric"] = metric
        payload["decision_sha256"] = _sha256(payload)
        payload["idempotent"] = idempotent
        return payload

    def _primary_limit(self, entitlement: CommercialEntitlement) -> Decimal:
        metric = sorted(entitlement.metrics)[0]
        return entitlement.metrics[metric].limit

    def _primary_used(self, entitlement: CommercialEntitlement) -> Decimal:
        metric = sorted(entitlement.metrics)[0]
        return entitlement.used_for(metric)

    def _primary_remaining(self, entitlement: CommercialEntitlement) -> Decimal:
        metric = sorted(entitlement.metrics)[0]
        limit = entitlement.metrics[metric].limit
        return max(limit - entitlement.used_for(metric), Decimal("0"))

    def _scope(
        self,
        *,
        customer_ref: Any,
        deployment_ref: Any,
        tenant_ref: Any,
        entity_ref: Any,
        store_ref: Any,
    ) -> CommercialScope:
        return CommercialScope(
            customer_ref=_text(customer_ref, "customer_ref"),
            deployment_ref=_text(deployment_ref, "deployment_ref"),
            tenant_ref=_text(tenant_ref, "tenant_ref"),
            entity_ref=_text(entity_ref, "entity_ref"),
            store_ref=_text(store_ref, "store_ref"),
        )

    def _entitlement_for(self, scope: CommercialScope) -> CommercialEntitlement:
        try:
            return self._entitlements[scope.scope_hash]
        except KeyError as exc:
            raise LookupError("commercial entitlement not found for exact scope") from exc

    def _more_restrictive(self, current: CommercialState, candidate: CommercialState) -> CommercialState:
        return current if STATE_ORDER[current] >= STATE_ORDER[candidate] else candidate

    def _request_hash(self, *, kind: str, event: dict[str, Any]) -> str:
        return _request_hash(kind, event)


class CommercialLifecycleEventRow(Base):
    __tablename__ = "commercial_lifecycle_events"
    __table_args__ = (
        CheckConstraint(
            "customer_ref IS NOT NULL AND length(customer_ref) > 0 "
            "AND deployment_ref IS NOT NULL AND length(deployment_ref) > 0 "
            "AND tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0",
            name="ck_commercial_lifecycle_events_scope_required",
        ),
        CheckConstraint(
            "length(request_sha256) = 64 AND length(decision_sha256) = 64",
            name="ck_commercial_lifecycle_events_hashes",
        ),
        CheckConstraint(
            "currency IS NULL OR (length(currency) = 3)",
            name="ck_commercial_lifecycle_events_currency",
        ),
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_commercial_lifecycle_events_amount",
        ),
        Index(
            "uq_commercial_lifecycle_scope_kind_idempotency",
            "customer_ref",
            "deployment_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "lifecycle_kind",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_commercial_lifecycle_scope_recorded",
            "customer_ref",
            "deployment_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "recorded_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    lifecycle_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    deployment_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    record_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    parent_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 12), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommercialLifecycleEvidenceRow(Base):
    __tablename__ = "commercial_lifecycle_evidence"
    __table_args__ = (
        CheckConstraint(
            "length(evidence_id) > 0 AND length(evidence_sha256) = 64 "
            "AND length(evidence_kind) > 0 AND length(authority) > 0 "
            "AND length(source_kind) > 0",
            name="ck_commercial_lifecycle_evidence_required",
        ),
        Index(
            "uq_commercial_lifecycle_evidence_event",
            "event_id",
            "evidence_id",
            unique=True,
        ),
        Index(
            "ix_commercial_lifecycle_evidence_scope",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "recorded_at",
            "event_id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("commercial_lifecycle_events.id"),
        nullable=False,
    )
    customer_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    deployment_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    authority: Mapped[str] = mapped_column(String(300), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(120), nullable=False)
    purposes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommercialLifecycleService:
    """Append-only internal commercial lifecycle ledger."""

    CONTRACT_ID = "kjds-commercial-lifecycle-db-v1"
    PLAN_EVENT_KIND = "commercial_plan_recorded"
    SUBSCRIPTION_EVENT_KIND = "commercial_subscription_recorded"
    ENTITLEMENT_EVENT_KIND = "commercial_entitlement_recorded"
    INVOICE_EVENT_KIND = "commercial_invoice_recorded"
    PAYMENT_EVENT_KIND = "commercial_payment_attempt_recorded"
    REFUND_EVENT_KIND = "commercial_refund_recorded"
    TAX_EVENT_KIND = "commercial_tax_evidence_recorded"

    def __init__(self, engine) -> None:
        self.engine = engine

    def record_plan(
        self,
        *,
        scope: dict[str, Any],
        plan_ref: str,
        state: str,
        currency: str,
        gross_amount: Decimal,
        effective_at: datetime,
        billing_window_start: datetime,
        billing_window_end: datetime,
        metric_limits: list[dict[str, Any]],
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_plan(
                    session,
                    scope=scoped,
                    plan_ref=plan_ref,
                    state=state,
                    currency=currency,
                    gross_amount=gross_amount,
                    effective_at=effective_at,
                    billing_window_start=billing_window_start,
                    billing_window_end=billing_window_end,
                    metric_limits=metric_limits,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def record_subscription(
        self,
        *,
        scope: dict[str, Any],
        subscription_ref: str,
        plan_ref: str,
        state: str,
        currency: str,
        amount: Decimal,
        effective_at: datetime,
        expires_at: datetime | None,
        settlement_evidence: dict[str, Any],
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_subscription(
                    session,
                    scope=scoped,
                    subscription_ref=subscription_ref,
                    plan_ref=plan_ref,
                    state=state,
                    currency=currency,
                    amount=amount,
                    effective_at=effective_at,
                    expires_at=expires_at,
                    settlement_evidence=settlement_evidence,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def record_invoice(
        self,
        *,
        scope: dict[str, Any],
        invoice_ref: str,
        subscription_ref: str,
        state: str,
        currency: str,
        net_amount: Decimal,
        tax_amount: Decimal,
        gross_amount: Decimal,
        issued_at: datetime,
        due_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_invoice(
                    session,
                    scope=scoped,
                    invoice_ref=invoice_ref,
                    subscription_ref=subscription_ref,
                    state=state,
                    currency=currency,
                    net_amount=net_amount,
                    tax_amount=tax_amount,
                    gross_amount=gross_amount,
                    issued_at=issued_at,
                    due_at=due_at,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def record_payment_attempt(
        self,
        *,
        scope: dict[str, Any],
        payment_attempt_ref: str,
        invoice_ref: str,
        state: str,
        currency: str,
        amount: Decimal,
        occurred_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_payment_attempt(
                    session,
                    scope=scoped,
                    payment_attempt_ref=payment_attempt_ref,
                    invoice_ref=invoice_ref,
                    state=state,
                    currency=currency,
                    amount=amount,
                    occurred_at=occurred_at,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def record_refund(
        self,
        *,
        scope: dict[str, Any],
        refund_ref: str,
        invoice_ref: str,
        payment_attempt_ref: str | None,
        state: str,
        currency: str,
        amount: Decimal,
        occurred_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_refund(
                    session,
                    scope=scoped,
                    refund_ref=refund_ref,
                    invoice_ref=invoice_ref,
                    payment_attempt_ref=payment_attempt_ref,
                    state=state,
                    currency=currency,
                    amount=amount,
                    occurred_at=occurred_at,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def record_tax_evidence(
        self,
        *,
        scope: dict[str, Any],
        tax_evidence_ref: str,
        invoice_ref: str,
        refund_ref: str | None,
        state: str,
        currency: str,
        amount: Decimal,
        observed_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        try:
            with Session(self.engine) as session, session.begin():
                scoped = self._scope(**scope)
                self._lock_scope_write(session, scope=scoped)
                response = self._record_tax_evidence(
                    session,
                    scope=scoped,
                    tax_evidence_ref=tax_evidence_ref,
                    invoice_ref=invoice_ref,
                    refund_ref=refund_ref,
                    state=state,
                    currency=currency,
                    amount=amount,
                    observed_at=observed_at,
                    evidence=evidence,
                    idempotency_key=idempotency_key,
                )
                return response
        except IntegrityError as exc:
            raise ValueError("commercial lifecycle write conflicts with an existing record") from exc

    def snapshot(
        self,
        *,
        customer_ref: str,
        deployment_ref: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        scope = self._scope(
            customer_ref=customer_ref,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
        )
        with Session(self.engine) as session:
            events = self._events(session, scope=scope, as_of=as_of)
            if not events:
                raise KeyError("commercial lifecycle not found for exact scope")
            snapshot = self._snapshot_from_events(events, scope=scope, as_of=as_of)
            return snapshot

    def _record_plan(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        plan_ref: str,
        state: str,
        currency: str,
        gross_amount: Decimal,
        effective_at: datetime,
        billing_window_start: datetime,
        billing_window_end: datetime,
        metric_limits: list[dict[str, Any]],
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in PLAN_STATE_ORDER:
            raise ValueError("plan state is not allowlisted")
        self._currency(currency)
        amount = _decimal(gross_amount, "gross_amount")
        if amount < 0:
            raise ValueError("gross_amount must be non-negative")
        effective_at = _timestamp(effective_at, "effective_at")
        billing_window_start = _timestamp(billing_window_start, "billing_window_start")
        billing_window_end = _timestamp(billing_window_end, "billing_window_end")
        if billing_window_end <= billing_window_start:
            raise ValueError("billing_window_end must be after billing_window_start")
        if not isinstance(metric_limits, list) or not metric_limits:
            raise ValueError("metric_limits must contain at least one item")
        for item in metric_limits:
            if not isinstance(item, dict):
                raise ValueError("metric_limits must be objects")
            metric = _text(item.get("metric"), "metric", maximum=80)
            if metric not in ALLOWED_METRICS:
                raise ValueError("metric is not allowlisted")
            limit = _decimal(item.get("limit"), f"{metric}.limit")
            if limit <= 0:
                raise ValueError("metric limits must be positive")
            grace_raw = item.get("grace_limit", limit)
            grace_limit = _decimal(grace_raw, f"{metric}.grace_limit")
            if grace_limit < 0 or grace_limit > limit:
                raise ValueError("grace_limit must be between zero and limit")
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="plan",
            event_kind=self.PLAN_EVENT_KIND,
            state=state,
            record_ref=_text(plan_ref, "plan_ref", maximum=240),
            parent_ref=None,
            currency=self._currency(currency),
            amount=amount,
            occurred_at=effective_at,
            payload={
                "plan_ref": plan_ref,
                "state": state,
                "currency": self._currency(currency),
                "gross_amount": str(amount),
                "effective_at": effective_at.isoformat(),
                "billing_window_start": billing_window_start.isoformat(),
                "billing_window_end": billing_window_end.isoformat(),
                "metric_limits": _copy(metric_limits),
                "evidence": _copy(evidence),
                "kind": self.PLAN_EVENT_KIND,
            },
            evidence_inputs=[evidence],
            idempotency_key=idempotency_key,
        )

    def _record_subscription(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        subscription_ref: str,
        plan_ref: str,
        state: str,
        currency: str,
        amount: Decimal,
        effective_at: datetime,
        expires_at: datetime | None,
        settlement_evidence: dict[str, Any],
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in SUBSCRIPTION_STATE_ORDER:
            raise ValueError("subscription state is not allowlisted")
        amount = _decimal(amount, "amount")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        currency = self._currency(currency)
        effective_at = _timestamp(effective_at, "effective_at")
        if expires_at is not None:
            expires_at = _timestamp(expires_at, "expires_at")
            if expires_at <= effective_at:
                raise ValueError("expires_at must be after effective_at")
        plan = self._latest_event(session, scope=scope, lifecycle_kind="plan", record_ref=plan_ref)
        if plan is None:
            raise KeyError("subscription requires an existing commercial plan")
        if plan.state == "draft":
            raise ValueError("subscription requires an approved or frozen plan")
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="subscription",
            event_kind=self.SUBSCRIPTION_EVENT_KIND,
            state=state,
            record_ref=_text(subscription_ref, "subscription_ref", maximum=240),
            parent_ref=_text(plan_ref, "plan_ref", maximum=240),
            currency=currency,
            amount=amount,
            occurred_at=effective_at,
            payload={
                "subscription_ref": subscription_ref,
                "plan_ref": plan_ref,
                "state": state,
                "currency": currency,
                "amount": str(amount),
                "effective_at": effective_at.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "settlement_evidence": _copy(settlement_evidence),
                "evidence": _copy(evidence),
                "kind": self.SUBSCRIPTION_EVENT_KIND,
            },
            evidence_inputs=[evidence, settlement_evidence],
            idempotency_key=idempotency_key,
        )

    def _record_invoice(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        invoice_ref: str,
        subscription_ref: str,
        state: str,
        currency: str,
        net_amount: Decimal,
        tax_amount: Decimal,
        gross_amount: Decimal,
        issued_at: datetime,
        due_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in INVOICE_STATE_ORDER:
            raise ValueError("invoice state is not allowlisted")
        currency = self._currency(currency)
        net_amount = _decimal(net_amount, "net_amount")
        tax_amount = _decimal(tax_amount, "tax_amount")
        gross_amount = _decimal(gross_amount, "gross_amount")
        if net_amount < 0 or tax_amount < 0 or gross_amount <= 0:
            raise ValueError("invoice amounts must be non-negative and gross_amount must be positive")
        if net_amount + tax_amount != gross_amount:
            raise ValueError("gross_amount must equal net_amount plus tax_amount")
        issued_at = _timestamp(issued_at, "issued_at")
        due_at = _timestamp(due_at, "due_at")
        if due_at < issued_at:
            raise ValueError("due_at must be on or after issued_at")
        normalized_invoice_ref = _text(invoice_ref, "invoice_ref", maximum=240)
        normalized_subscription_ref = _text(subscription_ref, "subscription_ref", maximum=240)
        payload = {
            "invoice_ref": normalized_invoice_ref,
            "subscription_ref": normalized_subscription_ref,
            "state": state,
            "currency": currency,
            "net_amount": str(net_amount),
            "tax_amount": str(tax_amount),
            "gross_amount": str(gross_amount),
            "issued_at": issued_at.isoformat(),
            "due_at": due_at.isoformat(),
            "evidence": _copy(evidence),
            "kind": self.INVOICE_EVENT_KIND,
        }
        replay = self._idempotent_replay(
            session,
            scope=scope,
            lifecycle_kind="invoice",
            event_kind=self.INVOICE_EVENT_KIND,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        self._preflight_existing_record(
            session,
            scope=scope,
            lifecycle_kind="invoice",
            state=state,
            record_ref=normalized_invoice_ref,
            parent_ref=normalized_subscription_ref,
            currency=currency,
            amount=gross_amount,
            payload={
                "subscription_ref": normalized_subscription_ref,
                "net_amount": str(net_amount),
                "tax_amount": str(tax_amount),
                "gross_amount": str(gross_amount),
            },
        )
        subscription = self._latest_event(
            session,
            scope=scope,
            lifecycle_kind="subscription",
            record_ref=normalized_subscription_ref,
        )
        if subscription is None:
            raise KeyError("invoice requires an existing subscription")
        if subscription.currency is None or subscription.currency != currency:
            raise ValueError("invoice currency must match the subscription currency")
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="invoice",
            event_kind=self.INVOICE_EVENT_KIND,
            state=state,
            record_ref=normalized_invoice_ref,
            parent_ref=normalized_subscription_ref,
            currency=currency,
            amount=gross_amount,
            occurred_at=issued_at,
            payload=payload,
            evidence_inputs=[evidence],
            idempotency_key=idempotency_key,
        )

    def _record_payment_attempt(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        payment_attempt_ref: str,
        invoice_ref: str,
        state: str,
        currency: str,
        amount: Decimal,
        occurred_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in PAYMENT_STATE_ORDER:
            raise ValueError("payment attempt state is not allowlisted")
        currency = self._currency(currency)
        amount = _decimal(amount, "amount")
        if amount <= 0:
            raise ValueError("payment attempt amount must be positive")
        occurred_at = _timestamp(occurred_at, "occurred_at")
        normalized_payment_ref = _text(payment_attempt_ref, "payment_attempt_ref", maximum=240)
        normalized_invoice_ref = _text(invoice_ref, "invoice_ref", maximum=240)
        payload = {
            "payment_attempt_ref": normalized_payment_ref,
            "invoice_ref": normalized_invoice_ref,
            "state": state,
            "currency": currency,
            "amount": str(amount),
            "occurred_at": occurred_at.isoformat(),
            "evidence": _copy(evidence),
            "kind": self.PAYMENT_EVENT_KIND,
        }
        replay = self._idempotent_replay(
            session,
            scope=scope,
            lifecycle_kind="payment_attempt",
            event_kind=self.PAYMENT_EVENT_KIND,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        self._preflight_existing_record(
            session,
            scope=scope,
            lifecycle_kind="payment_attempt",
            state=state,
            record_ref=normalized_payment_ref,
            parent_ref=normalized_invoice_ref,
            currency=currency,
            amount=amount,
            payload={"invoice_ref": normalized_invoice_ref, "amount": str(amount)},
        )
        invoice = self._latest_event(
            session,
            scope=scope,
            lifecycle_kind="invoice",
            record_ref=normalized_invoice_ref,
        )
        if invoice is None:
            raise KeyError("payment attempt requires an existing invoice")
        self._require_collectible_invoice(invoice)
        self._require_invoice_money(invoice, expected_currency=currency)
        self._ensure_payment_capacity(
            session,
            scope=scope,
            invoice_ref=normalized_invoice_ref,
            amount=amount,
        )
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="payment_attempt",
            event_kind=self.PAYMENT_EVENT_KIND,
            state=state,
            record_ref=normalized_payment_ref,
            parent_ref=normalized_invoice_ref,
            currency=currency,
            amount=amount,
            occurred_at=occurred_at,
            payload=payload,
            evidence_inputs=[evidence],
            idempotency_key=idempotency_key,
        )

    def _record_refund(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        refund_ref: str,
        invoice_ref: str,
        payment_attempt_ref: str | None,
        state: str,
        currency: str,
        amount: Decimal,
        occurred_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in REFUND_STATE_ORDER:
            raise ValueError("refund state is not allowlisted")
        currency = self._currency(currency)
        amount = _decimal(amount, "amount")
        if amount <= 0:
            raise ValueError("refund amount must be positive")
        occurred_at = _timestamp(occurred_at, "occurred_at")
        normalized_refund_ref = _text(refund_ref, "refund_ref", maximum=240)
        normalized_invoice_ref = _text(invoice_ref, "invoice_ref", maximum=240)
        normalized_payment_ref = (
            _text(payment_attempt_ref, "payment_attempt_ref", maximum=240)
            if payment_attempt_ref is not None
            else None
        )
        refund_parent_ref = normalized_payment_ref or normalized_invoice_ref
        payload = {
            "refund_ref": normalized_refund_ref,
            "invoice_ref": normalized_invoice_ref,
            "payment_attempt_ref": normalized_payment_ref,
            "state": state,
            "currency": currency,
            "amount": str(amount),
            "occurred_at": occurred_at.isoformat(),
            "evidence": _copy(evidence),
            "kind": self.REFUND_EVENT_KIND,
        }
        replay = self._idempotent_replay(
            session,
            scope=scope,
            lifecycle_kind="refund",
            event_kind=self.REFUND_EVENT_KIND,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            return replay
        self._preflight_existing_record(
            session,
            scope=scope,
            lifecycle_kind="refund",
            state=state,
            record_ref=normalized_refund_ref,
            parent_ref=refund_parent_ref,
            currency=currency,
            amount=amount,
            payload={
                "invoice_ref": normalized_invoice_ref,
                "payment_attempt_ref": normalized_payment_ref,
                "amount": str(amount),
            },
        )
        invoice = self._latest_event(
            session,
            scope=scope,
            lifecycle_kind="invoice",
            record_ref=normalized_invoice_ref,
        )
        if invoice is None:
            raise KeyError("refund requires an existing invoice")
        self._require_collectible_invoice(invoice)
        self._require_invoice_money(invoice, expected_currency=currency)
        payment: CommercialLifecycleEventRow | None = None
        if payment_attempt_ref is not None:
            payment = self._latest_event(
                session,
                scope=scope,
                lifecycle_kind="payment_attempt",
                record_ref=normalized_payment_ref,
            )
            if payment is None or payment.parent_ref != normalized_invoice_ref:
                raise ValueError("refund payment_attempt_ref must match the exact-scope invoice")
            if payment.currency != currency:
                raise ValueError("refund currency must match the settled payment currency")
        if state == "paid":
            if payment is None or payment.state != "settled":
                raise ValueError("paid refund requires an exact settled payment attempt")
            if payment.amount is None or payment.amount <= 0:
                raise ValueError("settled payment amount must be positive")
            payment_refunded = self._refund_total_for_payment(
                session,
                scope=scope,
                payment_attempt_ref=payment.record_ref,
                expected_currency=currency,
            )
            if payment_refunded + amount > payment.amount:
                raise ValueError("paid refunds must not exceed the exact settled payment")
        if state == "paid":
            settled = self._payment_total(
                session,
                scope=scope,
                invoice_ref=normalized_invoice_ref,
                expected_currency=currency,
            )
            refunded = self._refund_total(
                session,
                scope=scope,
                invoice_ref=normalized_invoice_ref,
                expected_currency=currency,
            )
            if refunded + amount > settled:
                raise ValueError("refund amount must not exceed collected payment")
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="refund",
            event_kind=self.REFUND_EVENT_KIND,
            state=state,
            record_ref=normalized_refund_ref,
            parent_ref=refund_parent_ref,
            currency=currency,
            amount=amount,
            occurred_at=occurred_at,
            payload=payload,
            evidence_inputs=[evidence],
            idempotency_key=idempotency_key,
        )

    def _record_tax_evidence(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        tax_evidence_ref: str,
        invoice_ref: str,
        refund_ref: str | None,
        state: str,
        currency: str,
        amount: Decimal,
        observed_at: datetime,
        evidence: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if state not in TAX_STATE_ORDER:
            raise ValueError("tax evidence state is not allowlisted")
        currency = self._currency(currency)
        amount = _decimal(amount, "amount")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        observed_at = _timestamp(observed_at, "observed_at")
        invoice = self._latest_event(session, scope=scope, lifecycle_kind="invoice", record_ref=invoice_ref)
        if invoice is None:
            raise KeyError("tax evidence requires an existing invoice")
        if refund_ref:
            refund = self._latest_event(session, scope=scope, lifecycle_kind="refund", record_ref=refund_ref)
            if refund is None:
                raise KeyError("tax evidence refund_ref does not match an existing refund")
        return self._append_event(
            session,
            scope=scope,
            lifecycle_kind="tax_evidence",
            event_kind=self.TAX_EVENT_KIND,
            state=state,
            record_ref=_text(tax_evidence_ref, "tax_evidence_ref", maximum=240),
            parent_ref=_text(refund_ref, "refund_ref", maximum=240) if refund_ref else _text(invoice_ref, "invoice_ref", maximum=240),
            currency=currency,
            amount=amount,
            occurred_at=observed_at,
            payload={
                "tax_evidence_ref": tax_evidence_ref,
                "invoice_ref": invoice_ref,
                "refund_ref": refund_ref,
                "state": state,
                "currency": currency,
                "amount": str(amount),
                "observed_at": observed_at.isoformat(),
                "evidence": _copy(evidence),
                "kind": self.TAX_EVENT_KIND,
            },
            evidence_inputs=[evidence],
            idempotency_key=idempotency_key,
        )

    def _append_event(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        event_kind: str,
        state: str,
        record_ref: str,
        parent_ref: str | None,
        currency: str | None,
        amount: Decimal | None,
        occurred_at: datetime,
        payload: dict[str, Any],
        evidence_inputs: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        request_hash = _request_hash(event_kind, payload | {"scope": scope.as_dict(), "idempotency_key": idempotency_key})
        existing = self._idempotent_event(
            session,
            scope=scope,
            lifecycle_kind=lifecycle_kind,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.request_sha256 != request_hash:
                raise ValueError("idempotency key conflicts with a different commercial request")
            response = _copy(existing.response_json)
            response["idempotent"] = True
            return response

        previous = self._latest_event(session, scope=scope, lifecycle_kind=lifecycle_kind, record_ref=record_ref)
        self._require_record_identity(
            lifecycle_kind=lifecycle_kind,
            previous=previous,
            parent_ref=parent_ref,
            currency=currency,
            amount=amount,
            payload=payload,
        )
        self._enforce_forward_transition(lifecycle_kind=lifecycle_kind, previous=previous.state if previous else None, current=state)

        if lifecycle_kind == "subscription":
            self._require_settlement_evidence(evidence_inputs)

        now = self._next_recorded_at(session, scope=scope)
        event_id = new_id("commercial_event")
        response = self._make_response(
            scope=scope,
            lifecycle_kind=lifecycle_kind,
            event_kind=event_kind,
            state=state,
            record_ref=record_ref,
            parent_ref=parent_ref,
            currency=currency,
            amount=amount,
            occurred_at=occurred_at,
            request_sha256=request_hash,
            evidence_inputs=evidence_inputs,
            idempotent=False,
            recorded_at=now,
        )
        event = CommercialLifecycleEventRow(
            id=event_id,
            lifecycle_kind=lifecycle_kind,
            event_kind=event_kind,
            state=state,
            customer_ref=scope.customer_ref,
            deployment_ref=scope.deployment_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            record_ref=record_ref,
            parent_ref=parent_ref,
            currency=currency,
            amount=amount,
            payload_json=_copy(payload),
            response_json=_copy(response),
            request_sha256=request_hash,
            decision_sha256=response["decision_sha256"],
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            recorded_at=now,
        )
        session.add(event)
        for entry in evidence_inputs:
            self._append_evidence(
                session,
                event_id=event_id,
                scope=scope,
                evidence=entry,
                recorded_at=now,
        )
        entitlement = self._recompute_entitlement(session, scope=scope, trigger_event=event, trigger_payload=payload, recorded_at=now)
        if entitlement is not None:
            session.add(entitlement)
        session.flush()
        return response

    def _next_recorded_at(
        self,
        session: Session,
        *,
        scope: CommercialScope,
    ) -> datetime:
        latest = session.scalar(
            select(func.max(CommercialLifecycleEventRow.recorded_at)).where(
                CommercialLifecycleEventRow.customer_ref == scope.customer_ref,
                CommercialLifecycleEventRow.deployment_ref == scope.deployment_ref,
                CommercialLifecycleEventRow.tenant_ref == scope.tenant_ref,
                CommercialLifecycleEventRow.entity_ref == scope.entity_ref,
                CommercialLifecycleEventRow.store_ref == scope.store_ref,
            )
        )
        now = datetime.now(UTC)
        if latest is None:
            return now
        latest_utc = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest.astimezone(UTC)
        return max(now, latest_utc + timedelta(microseconds=1))

    @staticmethod
    def _lock_scope_write(session: Session, *, scope: CommercialScope) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:scope_hash))"),
                {"scope_hash": scope.scope_hash},
            )

    def _recompute_entitlement(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        trigger_event: CommercialLifecycleEventRow,
        trigger_payload: dict[str, Any],
        recorded_at: datetime,
    ) -> CommercialLifecycleEventRow | None:
        state, reason, derived = self._derive_entitlement(session, scope=scope, as_of=trigger_event.recorded_at)
        latest = self._latest_event(session, scope=scope, lifecycle_kind="entitlement", record_ref="entitlement")
        entitlement_payload = {"reason": reason, **derived}
        if latest is not None and latest.state == state and latest.payload_json == entitlement_payload:
            return None
        response = self._make_response(
            scope=scope,
            lifecycle_kind="entitlement",
            event_kind=self.ENTITLEMENT_EVENT_KIND,
            state=state,
            record_ref="entitlement",
            parent_ref=trigger_event.record_ref,
            currency=derived.get("currency"),
            amount=_decimal(derived.get("outstanding_total"), "outstanding_total"),
            occurred_at=trigger_event.occurred_at,
            request_sha256=_sha256(
                {
                    "kind": self.ENTITLEMENT_EVENT_KIND,
                    "scope": scope.as_dict(),
                    "trigger": trigger_payload,
                    "state": state,
                    "reason": reason,
                }
            ),
            evidence_inputs=[],
            idempotent=False,
            recorded_at=recorded_at,
            extra={"reason": reason, **derived},
        )
        return CommercialLifecycleEventRow(
            id=new_id("commercial_entitlement"),
            lifecycle_kind="entitlement",
            event_kind=self.ENTITLEMENT_EVENT_KIND,
            state=state,
            customer_ref=scope.customer_ref,
            deployment_ref=scope.deployment_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            record_ref="entitlement",
            parent_ref=trigger_event.record_ref,
            currency=derived.get("currency"),
            amount=derived.get("outstanding_total"),
            payload_json=entitlement_payload,
            response_json=response,
            request_sha256=response["request_sha256"],
            decision_sha256=response["decision_sha256"],
            idempotency_key=f"{trigger_event.idempotency_key}:entitlement",
            occurred_at=trigger_event.occurred_at,
            recorded_at=recorded_at,
        )

    def _derive_entitlement(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        as_of: datetime,
    ) -> tuple[str, str, dict[str, Any]]:
        subscription = self._latest_event(session, scope=scope, lifecycle_kind="subscription")
        if subscription is None:
            return "closed", "missing_subscription", {"subscription_ref": None, "plan_ref": None, "invoice_refs": [], "invoice_total": "0", "payment_total": "0", "refund_total": "0", "outstanding_total": "0", "currency": None}
        if subscription.state in {"canceled", "closed"}:
            return "closed", "subscription_closed", self._entitlement_payload(session, scope=scope, subscription=subscription)
        if subscription.payload_json.get("settlement_evidence") is None:
            return "closed", "missing_settlement_evidence", self._entitlement_payload(session, scope=scope, subscription=subscription)
        payload = self._entitlement_payload(session, scope=scope, subscription=subscription)
        outstanding = Decimal(payload["outstanding_total"])
        invoice_due = _timestamp(payload["invoice_due"], "invoice_due") if payload["invoice_due"] else None
        if outstanding <= 0:
            return "active", "subscription_and_settlement_confirmed", payload
        if invoice_due and invoice_due < as_of:
            return "read_only", "invoice_overdue", payload
        if subscription.state == "past_due":
            return "read_only", "subscription_past_due", payload
        return "grace", "outstanding_balance", payload

    def _entitlement_payload(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        subscription: CommercialLifecycleEventRow,
    ) -> dict[str, Any]:
        invoice_refs = []
        invoice_total = Decimal("0")
        payment_total = Decimal("0")
        refund_total = Decimal("0")
        invoice_due: datetime | None = None
        currency = subscription.currency
        if currency is None:
            raise ValueError("subscription currency is required for entitlement settlement")
        invoices = self._latest_events_by_record_ref(
            session,
            scope=scope,
            lifecycle_kind="invoice",
        )
        for invoice in invoices:
            if invoice.parent_ref != subscription.record_ref:
                continue
            if invoice.state not in COLLECTIBLE_INVOICE_STATES:
                continue
            gross_amount = self._require_invoice_money(invoice, expected_currency=currency)
            invoice_refs.append(invoice.record_ref)
            settled = self._payment_total(
                session,
                scope=scope,
                invoice_ref=invoice.record_ref,
                expected_currency=currency,
            )
            refunded = self._refund_total(
                session,
                scope=scope,
                invoice_ref=invoice.record_ref,
                expected_currency=currency,
            )
            invoice_outstanding = gross_amount - settled + refunded
            if invoice_outstanding < 0:
                raise ValueError("invoice settlement conservation failed")
            invoice_total += gross_amount
            payment_total += settled
            refund_total += refunded
            due_raw = invoice.payload_json.get("due_at")
            if invoice_outstanding > 0 and due_raw:
                due_at = _timestamp(due_raw, "due_at")
                if invoice_due is None or due_at < invoice_due:
                    invoice_due = due_at
        outstanding = invoice_total - payment_total + refund_total
        return {
            "subscription_ref": subscription.record_ref,
            "plan_ref": subscription.parent_ref,
            "invoice_refs": invoice_refs,
            "invoice_total": _decimal_text(invoice_total),
            "payment_total": _decimal_text(payment_total),
            "refund_total": _decimal_text(refund_total),
            "outstanding_total": _decimal_text(outstanding),
            "currency": currency,
            "invoice_due": invoice_due.isoformat() if invoice_due else None,
        }

    def _snapshot_from_events(
        self,
        events: list[CommercialLifecycleEventRow],
        *,
        scope: CommercialScope,
        as_of: datetime | None,
    ) -> dict[str, Any]:
        by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in ("plan", "subscription", "entitlement", "invoice", "payment_attempt", "refund", "tax_evidence")}
        for event in events:
            by_kind[event.lifecycle_kind].append(self._event_dict(event))
        entitlement = by_kind["entitlement"][-1] if by_kind["entitlement"] else None
        latest_plan = by_kind["plan"][-1] if by_kind["plan"] else None
        latest_subscription = by_kind["subscription"][-1] if by_kind["subscription"] else None
        latest_invoice = by_kind["invoice"][-1] if by_kind["invoice"] else None
        return {
            "contract_id": self.CONTRACT_ID,
            "scope": scope.as_dict(),
            "scope_hash": scope.scope_hash,
            "as_of": as_of.astimezone(UTC).isoformat() if as_of else None,
            "plan": latest_plan,
            "subscription": latest_subscription,
            "entitlement": entitlement,
            "invoice": latest_invoice,
            "payment_attempts": by_kind["payment_attempt"],
            "refunds": by_kind["refund"],
            "tax_evidence": by_kind["tax_evidence"],
            "events": [self._event_dict(event) for event in events],
        }

    def _make_response(
        self,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        event_kind: str,
        state: str,
        record_ref: str,
        parent_ref: str | None,
        currency: str | None,
        amount: Decimal | None,
        occurred_at: datetime,
        request_sha256: str,
        evidence_inputs: list[dict[str, Any]],
        idempotent: bool,
        recorded_at: datetime,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "kind": event_kind,
            "lifecycle_kind": lifecycle_kind,
            "state": state,
            "scope": scope.as_dict(),
            "record_ref": record_ref,
            "parent_ref": parent_ref,
            "currency": currency,
            "amount": str(amount) if amount is not None else None,
            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "recorded_at": recorded_at.astimezone(UTC).isoformat(),
            "request_sha256": request_sha256,
            "evidence_lineage": [
                {
                    "evidence_id": item["evidence_id"],
                    "evidence_sha256": item["evidence_sha256"],
                    "evidence_kind": item["evidence_kind"],
                    "authority": item["authority"],
                    "source_kind": item["source_kind"],
                    "purposes": list(item.get("purposes", [])),
                }
                for item in evidence_inputs
            ],
        }
        if extra:
            payload.update(extra)
        payload["decision_sha256"] = _sha256(payload)
        payload["idempotent"] = idempotent
        return payload

    def _append_evidence(
        self,
        session: Session,
        *,
        event_id: str,
        scope: CommercialScope,
        evidence: dict[str, Any],
        recorded_at: datetime,
    ) -> None:
        evidence_id = _text(evidence.get("evidence_id"), "evidence_id", maximum=240)
        evidence_sha256 = _text(evidence.get("evidence_sha256"), "evidence_sha256", maximum=64)
        if len(evidence_sha256) != 64 or any(ch not in HEX64 for ch in evidence_sha256.lower()):
            raise ValueError("evidence_sha256 must be a 64-character lowercase hex digest")
        row = CommercialLifecycleEvidenceRow(
            id=new_id("commercial_evidence"),
            event_id=event_id,
            customer_ref=scope.customer_ref,
            deployment_ref=scope.deployment_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            evidence_id=evidence_id,
            evidence_sha256=evidence_sha256.lower(),
            evidence_kind=_text(evidence.get("evidence_kind"), "evidence_kind", maximum=120),
            authority=_text(evidence.get("authority"), "authority", maximum=300),
            source_kind=_text(evidence.get("source_kind"), "source_kind", maximum=120),
            purposes_json=list(evidence.get("purposes") or []),
            recorded_at=recorded_at,
        )
        session.add(row)

    def _events(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        as_of: datetime | None,
        lifecycle_kind: str | None = None,
    ) -> list[CommercialLifecycleEventRow]:
        query = select(CommercialLifecycleEventRow).where(
            CommercialLifecycleEventRow.customer_ref == scope.customer_ref,
            CommercialLifecycleEventRow.deployment_ref == scope.deployment_ref,
            CommercialLifecycleEventRow.tenant_ref == scope.tenant_ref,
            CommercialLifecycleEventRow.entity_ref == scope.entity_ref,
            CommercialLifecycleEventRow.store_ref == scope.store_ref,
        )
        if lifecycle_kind is not None:
            query = query.where(CommercialLifecycleEventRow.lifecycle_kind == lifecycle_kind)
        if as_of is not None:
            query = query.where(CommercialLifecycleEventRow.recorded_at <= as_of)
        query = query.order_by(CommercialLifecycleEventRow.recorded_at, CommercialLifecycleEventRow.id)
        return list(session.scalars(query))

    def _latest_event(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        record_ref: str | None = None,
    ) -> CommercialLifecycleEventRow | None:
        query = select(CommercialLifecycleEventRow).where(
            CommercialLifecycleEventRow.customer_ref == scope.customer_ref,
            CommercialLifecycleEventRow.deployment_ref == scope.deployment_ref,
            CommercialLifecycleEventRow.tenant_ref == scope.tenant_ref,
            CommercialLifecycleEventRow.entity_ref == scope.entity_ref,
            CommercialLifecycleEventRow.store_ref == scope.store_ref,
            CommercialLifecycleEventRow.lifecycle_kind == lifecycle_kind,
        )
        if record_ref is not None:
            query = query.where(CommercialLifecycleEventRow.record_ref == record_ref)
        query = query.order_by(CommercialLifecycleEventRow.recorded_at.desc(), CommercialLifecycleEventRow.id.desc())
        return session.scalars(query).first()

    def _idempotent_event(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        idempotency_key: str,
    ) -> CommercialLifecycleEventRow | None:
        query = select(CommercialLifecycleEventRow).where(
            CommercialLifecycleEventRow.customer_ref == scope.customer_ref,
            CommercialLifecycleEventRow.deployment_ref == scope.deployment_ref,
            CommercialLifecycleEventRow.tenant_ref == scope.tenant_ref,
            CommercialLifecycleEventRow.entity_ref == scope.entity_ref,
            CommercialLifecycleEventRow.store_ref == scope.store_ref,
            CommercialLifecycleEventRow.lifecycle_kind == lifecycle_kind,
            CommercialLifecycleEventRow.idempotency_key == idempotency_key,
        )
        return session.scalars(query).first()

    def _idempotent_replay(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        event_kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        request_hash = _request_hash(
            event_kind,
            payload | {"scope": scope.as_dict(), "idempotency_key": idempotency_key},
        )
        existing = self._idempotent_event(
            session,
            scope=scope,
            lifecycle_kind=lifecycle_kind,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            return None
        if existing.request_sha256 != request_hash:
            raise ValueError("idempotency key conflicts with a different commercial request")
        response = _copy(existing.response_json)
        response["idempotent"] = True
        return response

    def _latest_events_by_record_ref(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
    ) -> list[CommercialLifecycleEventRow]:
        latest: dict[str, CommercialLifecycleEventRow] = {}
        for row in self._events(session, scope=scope, as_of=None, lifecycle_kind=lifecycle_kind):
            latest[row.record_ref] = row
        return [latest[record_ref] for record_ref in sorted(latest)]

    def _payment_total(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        invoice_ref: str,
        expected_currency: str,
    ) -> Decimal:
        total = Decimal("0")
        for row in self._latest_events_by_record_ref(
            session,
            scope=scope,
            lifecycle_kind="payment_attempt",
        ):
            if row.parent_ref != invoice_ref:
                continue
            if row.currency != expected_currency:
                raise ValueError("payment currency must match the invoice currency")
            if row.state == "settled":
                if row.amount is None or row.amount <= 0:
                    raise ValueError("settled payment amount must be positive")
                total += row.amount
        return total

    def _refund_total(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        invoice_ref: str,
        expected_currency: str,
    ) -> Decimal:
        total = Decimal("0")
        for row in self._latest_events_by_record_ref(
            session,
            scope=scope,
            lifecycle_kind="refund",
        ):
            if row.payload_json.get("invoice_ref") != invoice_ref:
                continue
            if row.currency != expected_currency:
                raise ValueError("refund currency must match the invoice currency")
            if row.state == "paid":
                if row.amount is None or row.amount <= 0:
                    raise ValueError("paid refund amount must be positive")
                total += row.amount
        return total

    def _refund_total_for_payment(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        payment_attempt_ref: str,
        expected_currency: str,
    ) -> Decimal:
        total = Decimal("0")
        for row in self._latest_events_by_record_ref(
            session,
            scope=scope,
            lifecycle_kind="refund",
        ):
            if row.payload_json.get("payment_attempt_ref") != payment_attempt_ref:
                continue
            if row.currency != expected_currency:
                raise ValueError("refund currency must match the settled payment currency")
            if row.state == "paid":
                if row.amount is None or row.amount <= 0:
                    raise ValueError("paid refund amount must be positive")
                total += row.amount
        return total

    def _require_collectible_invoice(self, invoice: CommercialLifecycleEventRow) -> None:
        if invoice.state not in COLLECTIBLE_INVOICE_STATES:
            raise ValueError("invoice state is not collectible")

    def _require_invoice_money(
        self,
        invoice: CommercialLifecycleEventRow,
        *,
        expected_currency: str,
    ) -> Decimal:
        if invoice.currency is None or invoice.currency != expected_currency:
            raise ValueError("invoice currency does not match the settlement currency")
        if invoice.amount is None or invoice.amount <= 0:
            raise ValueError("invoice gross amount must be positive")
        return invoice.amount

    def _ensure_payment_capacity(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        invoice_ref: str,
        amount: Decimal,
    ) -> None:
        invoice = self._latest_event(session, scope=scope, lifecycle_kind="invoice", record_ref=invoice_ref)
        if invoice is None:
            raise KeyError("invoice not found for exact scope")
        self._require_collectible_invoice(invoice)
        if invoice.currency is None:
            raise ValueError("invoice currency is required")
        invoice_amount = self._require_invoice_money(invoice, expected_currency=invoice.currency)
        payment_total = self._payment_total(
            session,
            scope=scope,
            invoice_ref=invoice_ref,
            expected_currency=invoice.currency,
        )
        refund_total = self._refund_total(
            session,
            scope=scope,
            invoice_ref=invoice_ref,
            expected_currency=invoice.currency,
        )
        outstanding = invoice_amount - payment_total + refund_total
        if amount > max(outstanding, Decimal("0")):
            raise ValueError("payment attempt amount must not exceed the outstanding invoice balance")

    def _require_settlement_evidence(self, evidence_inputs: list[dict[str, Any]]) -> None:
        if len(evidence_inputs) < 2:
            raise ValueError("subscription requires both subscription evidence and settlement evidence")
        first = _text(evidence_inputs[0].get("evidence_id"), "subscription_evidence_id", maximum=240)
        second = _text(evidence_inputs[1].get("evidence_id"), "settlement_evidence_id", maximum=240)
        if first == second:
            raise ValueError("subscription evidence and settlement evidence must be distinct")

    def _enforce_forward_transition(self, *, lifecycle_kind: str, previous: str | None, current: str) -> None:
        if previous is None:
            return
        if lifecycle_kind in {"invoice", "payment_attempt", "refund"} and current == previous:
            raise ValueError(f"{lifecycle_kind} state replay requires the original idempotency key")
        if lifecycle_kind == "refund":
            if current not in REFUND_STATE_TRANSITIONS[previous]:
                raise ValueError("refund state transition is not allowed")
            return
        if lifecycle_kind == "plan":
            order = PLAN_STATE_ORDER
        elif lifecycle_kind == "subscription":
            order = SUBSCRIPTION_STATE_ORDER
        elif lifecycle_kind == "invoice":
            order = INVOICE_STATE_ORDER
        elif lifecycle_kind == "payment_attempt":
            order = PAYMENT_STATE_ORDER
        elif lifecycle_kind == "refund":
            order = REFUND_STATE_ORDER
        elif lifecycle_kind == "tax_evidence":
            order = TAX_STATE_ORDER
        else:
            return
        if order[current] < order[previous]:
            raise ValueError(f"{lifecycle_kind} state cannot move backwards")

    def _preflight_existing_record(
        self,
        session: Session,
        *,
        scope: CommercialScope,
        lifecycle_kind: str,
        state: str,
        record_ref: str,
        parent_ref: str | None,
        currency: str | None,
        amount: Decimal | None,
        payload: dict[str, Any],
    ) -> None:
        previous = self._latest_event(
            session,
            scope=scope,
            lifecycle_kind=lifecycle_kind,
            record_ref=record_ref,
        )
        self._require_record_identity(
            lifecycle_kind=lifecycle_kind,
            previous=previous,
            parent_ref=parent_ref,
            currency=currency,
            amount=amount,
            payload=payload,
        )
        self._enforce_forward_transition(
            lifecycle_kind=lifecycle_kind,
            previous=previous.state if previous else None,
            current=state,
        )

    def _require_record_identity(
        self,
        *,
        lifecycle_kind: str,
        previous: CommercialLifecycleEventRow | None,
        parent_ref: str | None,
        currency: str | None,
        amount: Decimal | None,
        payload: dict[str, Any],
    ) -> None:
        if previous is None or lifecycle_kind not in {"invoice", "payment_attempt", "refund"}:
            return
        if (
            previous.parent_ref != parent_ref
            or previous.currency != currency
            or previous.amount != amount
        ):
            raise ValueError(f"{lifecycle_kind} record identity and money tuple are immutable")
        stable_payload_fields = {
            "invoice": ("subscription_ref", "net_amount", "tax_amount", "gross_amount"),
            "payment_attempt": ("invoice_ref", "amount"),
            "refund": ("invoice_ref", "payment_attempt_ref", "amount"),
        }[lifecycle_kind]
        if any(previous.payload_json.get(field) != payload.get(field) for field in stable_payload_fields):
            raise ValueError(f"{lifecycle_kind} record identity and money tuple are immutable")

    def _event_dict(self, row: CommercialLifecycleEventRow) -> dict[str, Any]:
        reason = row.payload_json.get("reason")
        return {
            "id": row.id,
            "lifecycle_kind": row.lifecycle_kind,
            "event_kind": row.event_kind,
            "state": row.state,
            "record_ref": row.record_ref,
            "parent_ref": row.parent_ref,
            "currency": row.currency,
            "amount": str(row.amount) if row.amount is not None else None,
            "reason": reason,
            "payload": _copy(row.payload_json),
            "response": _copy(row.response_json),
            "request_sha256": row.request_sha256,
            "decision_sha256": row.decision_sha256,
            "idempotency_key": row.idempotency_key,
            "occurred_at": row.occurred_at.astimezone(UTC).isoformat(),
            "recorded_at": row.recorded_at.astimezone(UTC).isoformat(),
        }

    def _currency(self, value: str) -> str:
        currency = _text(value, "currency", maximum=3).upper()
        if currency not in ALLOWED_COMMERICAL_CURRENCIES:
            raise ValueError("currency is not allowlisted")
        return currency

    def _scope(self, **scope: Any) -> CommercialScope:
        return CommercialScope(
            customer_ref=_text(scope.get("customer_ref"), "customer_ref"),
            deployment_ref=_text(scope.get("deployment_ref"), "deployment_ref"),
            tenant_ref=_text(scope.get("tenant_ref"), "tenant_ref"),
            entity_ref=_text(scope.get("entity_ref"), "entity_ref"),
            store_ref=_text(scope.get("store_ref"), "store_ref"),
        )
