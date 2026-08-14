"""Governed Social-Commerce campaign authority (BAS-178 campaign authority slice).

Freezes the campaign-grant lifecycle for ADR-0090 platform operations: issue,
activate, expire, revoke and kill-switch. A grant binds an account to a set of
authorized actions inside an envelope; the authority evaluator decides, purely
from frozen grant state and a caller-supplied clock, whether an action is
authorized. No platform write, credential mix or external mutation is implied.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CAMPAIGN_AUTHORITY_CONTRACT = "kjds-campaign-authority-v1"
CAMPAIGN_AUTHORITY_VERSION = "1.0.0"

ALLOWED_ACTIONS = frozenset(
    {
        "publish",
        "update",
        "delete",
        "comment",
        "reply",
        "like",
        "favorite",
        "follow",
        "unfollow",
        "message",
        "download",
    }
)

GRANT_STATUSES = frozenset(
    {"ACTIVE", "EXPIRED", "REVOKED", "KILL_SWITCHED", "NOT_YET_ACTIVE"}
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")

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


class CampaignAuthorityError(ValueError):
    """Stable, non-sensitive contract failure for campaign authority."""


@dataclass(frozen=True)
class CampaignGrant:
    grant_id: str
    grantor: str
    account_ref: str
    authorized_actions: tuple[str, ...]
    purpose: str
    audience: str
    budget: tuple[tuple[str, Any], ...]
    stop_conditions: tuple[str, ...]
    not_before: str
    expiry: str
    revoked: bool
    kill_switched: bool
    grant_sha256: str


@dataclass(frozen=True)
class GrantStatus:
    grant_id: str
    status: str
    authorization_ok: bool
    reasons: tuple[str, ...]
    status_sha256: str


@dataclass(frozen=True)
class AuthorizationDecision:
    grant_id: str
    action: str
    authorized: bool
    status: str
    reasons: tuple[str, ...]
    decision_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise CampaignAuthorityError(f"{name}_invalid")
    if len(value) > maximum:
        raise CampaignAuthorityError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if TOKEN.fullmatch(text) is None:
        raise CampaignAuthorityError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise CampaignAuthorityError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise CampaignAuthorityError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise CampaignAuthorityError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CampaignAuthorityError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CampaignAuthorityError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_iso(value: str, name: str) -> datetime:
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:  # noqa: BLE001 - stable non-sensitive reason
        raise CampaignAuthorityError(f"{name}_invalid_iso") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _budget(value: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, Mapping):
        raise CampaignAuthorityError("budget_invalid")
    _safe_tree(dict(value))
    return tuple(sorted((str(key), item) for key, item in value.items()))


class GovernedCampaignAuthority:
    """Deterministic campaign-grant authority for ADR-0090 platform operations."""

    def issue(self, grant: Any) -> CampaignGrant:
        if not isinstance(grant, Mapping):
            raise CampaignAuthorityError("grant_invalid")
        grant_id = _token(grant.get("grant_id"), "grant_id")
        grantor = _token(grant.get("grantor"), "grantor")
        account_ref = _token(grant.get("account_ref"), "account_ref")
        purpose = _text(grant.get("purpose"), "purpose", maximum=500)
        audience = _text(grant.get("audience"), "audience", maximum=500)

        authorized_actions = grant.get("authorized_actions")
        if not isinstance(authorized_actions, list) or not authorized_actions:
            raise CampaignAuthorityError("authorized_actions_invalid")
        normalized_actions: list[str] = []
        for action in authorized_actions:
            text = _text(action, "action", maximum=40)
            if text not in ALLOWED_ACTIONS:
                raise CampaignAuthorityError("action_not_recognized")
            if text not in normalized_actions:
                normalized_actions.append(text)

        stop_conditions = grant.get("stop_conditions")
        if not isinstance(stop_conditions, list) or not stop_conditions:
            raise CampaignAuthorityError("stop_conditions_invalid")
        normalized_stops: list[str] = []
        for stop in stop_conditions:
            text = _text(stop, "stop_condition", maximum=200)
            if text not in normalized_stops:
                normalized_stops.append(text)

        not_before_raw = _text(grant.get("not_before"), "not_before", maximum=40)
        expiry_raw = _text(grant.get("expiry"), "expiry", maximum=40)
        not_before = _parse_iso(not_before_raw, "not_before").isoformat()
        expiry = _parse_iso(expiry_raw, "expiry").isoformat()
        if _parse_iso(expiry_raw, "expiry") <= _parse_iso(not_before_raw, "not_before"):
            raise CampaignAuthorityError("expiry_not_after_not_before")

        revoked = grant.get("revoked")
        if not isinstance(revoked, bool):
            raise CampaignAuthorityError("revoked_invalid")
        kill_switched = grant.get("kill_switched")
        if not isinstance(kill_switched, bool):
            raise CampaignAuthorityError("kill_switched_invalid")

        _safe_tree(dict(grant))

        document = {
            "contract_id": CAMPAIGN_AUTHORITY_CONTRACT,
            "grant_id": grant_id,
            "grantor": grantor,
            "account_ref": account_ref,
            "authorized_actions": normalized_actions,
            "purpose": purpose,
            "audience": audience,
            "budget": list(_budget(grant.get("budget"))),
            "stop_conditions": normalized_stops,
            "not_before": not_before,
            "expiry": expiry,
            "revoked": revoked,
            "kill_switched": kill_switched,
        }
        return CampaignGrant(
            grant_id=grant_id,
            grantor=grantor,
            account_ref=account_ref,
            authorized_actions=tuple(normalized_actions),
            purpose=purpose,
            audience=audience,
            budget=_budget(grant.get("budget")),
            stop_conditions=tuple(normalized_stops),
            not_before=not_before,
            expiry=expiry,
            revoked=revoked,
            kill_switched=kill_switched,
            grant_sha256=_hash(document),
        )

    def status(self, grant: CampaignGrant, *, now: str) -> GrantStatus:
        now_iso = _parse_iso(_text(now, "now", maximum=40), "now")
        reasons: list[str] = []
        if grant.revoked:
            state = "REVOKED"
            reasons.append("grant_revoked")
        elif grant.kill_switched:
            state = "KILL_SWITCHED"
            reasons.append("grant_kill_switched")
        elif _parse_iso(grant.expiry, "expiry") <= now_iso:
            state = "EXPIRED"
            reasons.append("grant_expired")
        elif _parse_iso(grant.not_before, "not_before") > now_iso:
            state = "NOT_YET_ACTIVE"
            reasons.append("grant_not_yet_active")
        else:
            state = "ACTIVE"
        authorization_ok = state == "ACTIVE"
        status_document = {
            "contract_id": CAMPAIGN_AUTHORITY_CONTRACT,
            "grant_id": grant.grant_id,
            "grant_sha256": grant.grant_sha256,
            "now": now_iso.isoformat(),
            "status": state,
            "authorization_ok": authorization_ok,
            "reasons": reasons,
        }
        return GrantStatus(
            grant_id=grant.grant_id,
            status=state,
            authorization_ok=authorization_ok,
            reasons=tuple(reasons),
            status_sha256=_hash(status_document),
        )

    def authorize(
        self,
        grant: CampaignGrant,
        action: str,
        *,
        now: str,
    ) -> AuthorizationDecision:
        action = _text(action, "action", maximum=40)
        if action not in ALLOWED_ACTIONS:
            raise CampaignAuthorityError("action_not_recognized")
        current = self.status(grant, now=now)
        reasons: list[str] = list(current.reasons)
        if not current.authorization_ok:
            authorized = False
        elif action not in grant.authorized_actions:
            authorized = False
            reasons.append("action_not_authorized")
        else:
            authorized = True

        decision_document = {
            "contract_id": CAMPAIGN_AUTHORITY_CONTRACT,
            "grant_id": grant.grant_id,
            "action": action,
            "authorized": authorized,
            "status": current.status,
            "reasons": sorted(set(reasons)),
        }
        return AuthorizationDecision(
            grant_id=grant.grant_id,
            action=action,
            authorized=authorized,
            status=current.status,
            reasons=tuple(sorted(set(reasons))),
            decision_sha256=_hash(decision_document),
        )

    def readback(
        self,
        value: CampaignGrant | GrantStatus | AuthorizationDecision,
        *,
        observed: str | None = None,
    ) -> dict[str, Any]:
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        if isinstance(value, CampaignGrant):
            expected = value.grant_sha256
        elif isinstance(value, GrantStatus):
            expected = value.status_sha256
        else:
            expected = value.decision_sha256
        integrity_ok = observed_hash == expected
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "AuthorizationDecision",
    "CampaignAuthorityError",
    "CampaignGrant",
    "GovernedCampaignAuthority",
    "GrantStatus",
    "CAMPAIGN_AUTHORITY_CONTRACT",
]
