"""Server-side admission for commercial entitlements.

The usage and finance ledgers intentionally store accounting facts, while the
commercial lifecycle ledger is the authority that decides whether a customer
may consume a paid capability.  This adapter keeps that decision in one place
and binds it to the complete commercial scope.  Callers may continue to use
the legacy, unbound usage endpoint during migration, but any request that
declares an entitlement must pass this exact-scope check.

No payment provider or external platform is contacted here.  The returned
mapping is an auditable, read-only admission receipt that can be attached to a
usage event or an invoice preview.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .commercial_lifecycle import CommercialScope

ACTIVE_ENTITLEMENT_STATES = frozenset({"active", "grace"})
_MAX_ID = 240
_MAX_SCOPE = 160


class CommercialEntitlementAdmissionError(ValueError):
    """A declared entitlement cannot be admitted for the requested scope."""

    # ``api_contracts.run`` maps this to a client-visible forbidden response.
    http_status_code = 403


def _text(value: Any, field: str, *, maximum: int = _MAX_SCOPE) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CommercialEntitlementAdmissionError(f"{field} is required")
    if len(normalized) > maximum:
        raise CommercialEntitlementAdmissionError(
            f"{field} must be at most {maximum} characters"
        )
    return normalized


def _aware(value: datetime | str, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise CommercialEntitlementAdmissionError(
                f"{field} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommercialEntitlementAdmissionError(
            f"{field} must include a timezone"
        )
    try:
        return parsed.astimezone(UTC)
    except OverflowError as exc:
        raise CommercialEntitlementAdmissionError(
            f"{field} is outside the supported range"
        ) from exc


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommercialEntitlementAdmissionError(f"{field} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise CommercialEntitlementAdmissionError(f"{field} must be finite and non-negative")
    return parsed


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_entitlement_id(
    *,
    tenant_id: str,
    customer_id: str,
    deployment_ref: str,
    entity_ref: str,
    store_ref: str,
) -> str:
    """Return the stable entitlement identifier for one exact scope.

    The SQL lifecycle projection currently stores its derived entitlement with
    ``record_ref=entitlement``.  A caller-facing identifier must nevertheless
    be stable across workers and restarts, so it is derived from the same
    canonical :class:`CommercialScope` hash used by the lifecycle kernel.
    """

    scope = CommercialScope(
        customer_ref=_text(customer_id, "customer_id"),
        deployment_ref=_text(deployment_ref, "deployment_ref"),
        tenant_ref=_text(tenant_id, "tenant_id"),
        entity_ref=_text(entity_ref, "entity_ref"),
        store_ref=_text(store_ref, "store_ref"),
    )
    return f"cl_{scope.scope_hash[:24]}"


class CommercialEntitlementAuthority:
    """Resolve and admit a declared entitlement from the lifecycle ledger."""

    CONTRACT_ID = "kjds-commercial-entitlement-authority-v1"

    def __init__(self, lifecycle_service: Any) -> None:
        self.lifecycle = lifecycle_service

    def resolve(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        entitlement_id: str,
        deployment_ref: str,
        entity_ref: str,
        store_ref: str,
        metric: str | None = None,
        occurred_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Resolve an entitlement and return a signed-by-hash admission receipt.

        The method performs all checks before any usage or finance row is
        written.  Missing rows, malformed projections, cross-scope IDs,
        inactive states, expired windows, and unknown metrics fail closed with
        the same authorization error so callers cannot use this endpoint as a
        cross-tenant existence oracle.
        """

        tenant_id = _text(tenant_id, "tenant_id")
        customer_id = _text(customer_id, "customer_id")
        deployment_ref = _text(deployment_ref, "deployment_ref")
        entity_ref = _text(entity_ref, "entity_ref")
        store_ref = _text(store_ref, "store_ref")
        supplied_id = _text(entitlement_id, "entitlement_id", maximum=_MAX_ID)
        scope = CommercialScope(
            customer_ref=customer_id,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_id,
            entity_ref=entity_ref,
            store_ref=store_ref,
        )
        expected_id = f"cl_{scope.scope_hash[:24]}"
        if supplied_id != expected_id:
            raise CommercialEntitlementAdmissionError(
                "entitlement_id does not match the exact commercial scope"
            )

        now = datetime.now(UTC)
        cutoff = _aware(as_of, "as_of") if as_of is not None else now
        if cutoff > now:
            raise CommercialEntitlementAdmissionError("as_of cannot be in the future")
        event_time = _aware(occurred_at, "occurred_at") if occurred_at is not None else now
        if event_time > now:
            raise CommercialEntitlementAdmissionError("occurred_at cannot be in the future")

        try:
            snapshot = self.lifecycle.snapshot(
                customer_ref=customer_id,
                deployment_ref=deployment_ref,
                tenant_ref=tenant_id,
                entity_ref=entity_ref,
                store_ref=store_ref,
                as_of=cutoff,
            )
        except Exception as exc:
            # Do not leak whether another tenant or customer has a lifecycle
            # row.  Preserve the original exception as the cause for logs.
            if isinstance(exc, CommercialEntitlementAdmissionError):
                raise
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement is not admitted for the exact scope"
            ) from exc

        if not isinstance(snapshot, dict) or snapshot.get("scope") != scope.as_dict():
            raise CommercialEntitlementAdmissionError(
                "commercial lifecycle scope does not match the authenticated request"
            )
        if snapshot.get("scope_hash") != scope.scope_hash:
            raise CommercialEntitlementAdmissionError(
                "commercial lifecycle scope hash does not match the authenticated request"
            )
        entitlement = snapshot.get("entitlement")
        if not isinstance(entitlement, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement is not admitted for the exact scope"
            )
        if entitlement.get("record_ref") != "entitlement":
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement projection has an invalid record reference"
            )
        entitlement_payload = entitlement.get("payload")
        if not isinstance(entitlement_payload, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement projection is malformed"
            )
        state = str(entitlement.get("state") or "")
        if state not in ACTIVE_ENTITLEMENT_STATES:
            raise CommercialEntitlementAdmissionError(
                f"commercial entitlement state {state or 'unknown'} does not permit usage"
            )

        plan = snapshot.get("plan")
        if not isinstance(plan, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement has no authoritative plan"
            )
        plan_payload = plan.get("payload")
        if not isinstance(plan_payload, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement plan projection is malformed"
            )
        plan_state = str(plan.get("state") or "")
        if plan_state not in {"approved", "frozen"}:
            raise CommercialEntitlementAdmissionError(
                f"commercial plan state {plan_state or 'unknown'} does not permit usage"
            )
        subscription = snapshot.get("subscription")
        if not isinstance(subscription, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement has no authoritative subscription"
            )
        subscription_payload = subscription.get("payload")
        if not isinstance(subscription_payload, dict):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement subscription projection is malformed"
            )
        if subscription.get("record_ref") != entitlement_payload.get("subscription_ref"):
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement subscription lineage does not match"
            )

        window_start = _aware(plan_payload.get("billing_window_start"), "billing_window_start")
        window_end = _aware(plan_payload.get("billing_window_end"), "billing_window_end")
        if window_end <= window_start:
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement billing window is invalid"
            )
        if event_time < window_start or event_time >= window_end:
            raise CommercialEntitlementAdmissionError(
                "occurred_at is outside the commercial entitlement billing window"
            )
        effective_raw = plan_payload.get("effective_at")
        if effective_raw is not None and event_time < _aware(effective_raw, "plan_effective_at"):
            raise CommercialEntitlementAdmissionError(
                "occurred_at precedes the commercial plan effective time"
            )
        subscription_effective = _aware(
            subscription_payload.get("effective_at"), "subscription_effective_at"
        )
        if event_time < subscription_effective:
            raise CommercialEntitlementAdmissionError(
                "occurred_at precedes the commercial subscription effective time"
            )
        expires_raw = subscription_payload.get("expires_at")
        if expires_raw is not None and event_time >= _aware(expires_raw, "subscription_expires_at"):
            raise CommercialEntitlementAdmissionError(
                "occurred_at is outside the commercial subscription validity window"
            )

        raw_limits = plan_payload.get("metric_limits")
        if not isinstance(raw_limits, list) or not raw_limits:
            raise CommercialEntitlementAdmissionError(
                "commercial entitlement has no authoritative metric limits"
            )
        limits: dict[str, dict[str, str]] = {}
        for item in raw_limits:
            if not isinstance(item, dict):
                raise CommercialEntitlementAdmissionError(
                    "commercial entitlement metric limits are malformed"
                )
            name = _text(item.get("metric"), "metric", maximum=80)
            if name in limits:
                raise CommercialEntitlementAdmissionError(
                    "commercial entitlement contains duplicate metrics"
                )
            limit = _decimal(item.get("limit"), f"{name}.limit")
            grace = _decimal(item.get("grace_limit", item.get("limit")), f"{name}.grace_limit")
            if grace > limit:
                raise CommercialEntitlementAdmissionError(
                    f"{name}.grace_limit cannot exceed {name}.limit"
                )
            limits[name] = {"limit": str(limit), "grace_limit": str(grace)}

        selected_metric = _text(metric, "metric", maximum=80) if metric is not None else None
        if selected_metric is None:
            if len(limits) != 1:
                raise CommercialEntitlementAdmissionError(
                    "metric is required when an entitlement has multiple limits"
                )
            selected_metric = next(iter(limits))
        if selected_metric not in limits:
            raise CommercialEntitlementAdmissionError(
                "metric is not allowlisted for this commercial entitlement"
            )

        receipt = {
            "contract_id": self.CONTRACT_ID,
            "entitlement_id": expected_id,
            "scope": scope.as_dict(),
            "scope_hash": scope.scope_hash,
            "state": state,
            "plan_ref": plan.get("record_ref"),
            "subscription_ref": entitlement_payload.get("subscription_ref"),
            "metric": selected_metric,
            "metric_limit": limits[selected_metric]["limit"],
            "metric_grace_limit": limits[selected_metric]["grace_limit"],
            "metric_limits": limits,
            "billing_window_start": window_start.isoformat(),
            "billing_window_end": window_end.isoformat(),
            "event_time": event_time.isoformat(),
            "as_of": cutoff.isoformat(),
            "lifecycle_event_id": entitlement.get("id"),
            "lifecycle_decision_sha256": entitlement.get("decision_sha256"),
        }
        receipt["receipt_sha256"] = _fingerprint(receipt)
        return receipt


__all__ = [
    "ACTIVE_ENTITLEMENT_STATES",
    "CommercialEntitlementAdmissionError",
    "CommercialEntitlementAuthority",
    "canonical_entitlement_id",
]
