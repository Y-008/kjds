from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

CommercialState = Literal["active", "grace", "read_only", "closed"]

ALLOWED_METRICS = frozenset(
    {
        "api_calls",
        "requests",
        "seats",
        "storage_gib",
    }
)

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
        payload = {key: value for key, value in event.items() if key != "kind"}
        return _sha256({"kind": kind, "payload": payload})
