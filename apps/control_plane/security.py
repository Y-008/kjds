from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sql_repository import Base

ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "production"})
ALLOWED_ROLES = frozenset(
    {"operator", "reviewer", "compliance", "approver", "risk", "admin", "pilot_reader", "executor", "monitor"}
)


class AuthenticationFailure(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class WritesDisabled(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: str
    roles: frozenset[str]

    def has_any_role(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


@dataclass(frozen=True, slots=True, repr=False)
class _Credential:
    api_key: str
    principal: Principal


class ApiKeyAuthenticator:
    def __init__(self, credentials: list[_Credential], *, environment: str, legacy_mode: bool) -> None:
        self._credentials = credentials
        self.environment = environment
        self.legacy_mode = legacy_mode

    @classmethod
    def from_environment(cls) -> ApiKeyAuthenticator:
        environment = os.getenv("KJDS_ENVIRONMENT", "development").strip().lower()
        if environment not in ALLOWED_ENVIRONMENTS:
            raise RuntimeError(f"KJDS_ENVIRONMENT must be one of: {', '.join(sorted(ALLOWED_ENVIRONMENTS))}")
        raw_mapping = os.getenv("KJDS_API_KEYS_JSON", "").strip()
        credentials: list[_Credential] = []
        mapping: dict[str, Any] = {}
        if raw_mapping:
            try:
                mapping = json.loads(raw_mapping)
            except json.JSONDecodeError as exc:
                raise RuntimeError("KJDS_API_KEYS_JSON is not valid JSON") from exc
            if not isinstance(mapping, dict):
                raise RuntimeError("KJDS_API_KEYS_JSON must be an object keyed by API key")
        if mapping:
            for api_key, profile in mapping.items():
                if not isinstance(api_key, str) or not api_key.strip() or not isinstance(profile, dict):
                    raise RuntimeError("Every API credential requires a non-empty key and profile object")
                cls._validate_key(api_key, environment)
                actor = str(profile.get("actor", "")).strip()
                roles_value = profile.get("roles", [])
                if not actor or not isinstance(roles_value, list) or not all(isinstance(item, str) for item in roles_value):
                    raise RuntimeError("Every API credential requires an actor and string role list")
                roles = frozenset(item.strip() for item in roles_value if item.strip())
                if not roles:
                    raise RuntimeError("Every API credential requires at least one role")
                unknown_roles = roles - ALLOWED_ROLES
                if unknown_roles:
                    raise RuntimeError(f"Unknown API roles: {', '.join(sorted(unknown_roles))}")
                if "admin" not in roles and {"operator", "approver"}.issubset(roles):
                    raise RuntimeError("A non-admin API identity cannot combine operator and approver roles")
                credentials.append(_Credential(api_key, Principal(actor, roles)))
            web_key = os.getenv("KJDS_API_KEY", "").strip()
            if web_key:
                cls._validate_key(web_key, environment)
                if web_key not in mapping:
                    raise RuntimeError("KJDS_API_KEY must appear in KJDS_API_KEYS_JSON when multi-identity mode is used")
        else:
            if environment == "production":
                raise RuntimeError("Production requires a non-empty KJDS_API_KEYS_JSON identity map")
            api_key = os.getenv("KJDS_API_KEY", "").strip()
            if api_key:
                cls._validate_key(api_key, environment)
                actor = os.getenv("KJDS_API_ACTOR", "local-operator").strip() or "local-operator"
                roles = frozenset(
                    item.strip() for item in os.getenv("KJDS_API_ROLES", "operator").split(",") if item.strip()
                )
                unknown_roles = roles - ALLOWED_ROLES
                if unknown_roles:
                    raise RuntimeError(f"Unknown API roles: {', '.join(sorted(unknown_roles))}")
                credentials.append(_Credential(api_key, Principal(actor, roles or frozenset({"operator"}))))
        return cls(credentials, environment=environment, legacy_mode=not bool(mapping))

    @staticmethod
    def _validate_key(api_key: str, environment: str) -> None:
        if api_key.lower().startswith(("replace-", "change-me", "changeme")):
            raise RuntimeError("Placeholder API credentials are not allowed")
        if environment == "production" and len(api_key) < 32:
            raise RuntimeError("Production API credentials must contain at least 32 characters")

    @property
    def configured(self) -> bool:
        return bool(self._credentials)

    def safe_summary(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "identity_count": len(self._credentials),
            "legacy_mode": self.legacy_mode,
            "role_profiles": sorted([sorted(item.principal.roles) for item in self._credentials]),
        }

    def authenticate(self, presented_key: str | None) -> Principal:
        if not self._credentials:
            raise AuthenticationFailure("API identity is not configured", 503)
        if not presented_key:
            raise AuthenticationFailure("X-KJDS-API-Key is required", 401)
        matched: Principal | None = None
        for credential in self._credentials:
            if hmac.compare_digest(presented_key, credential.api_key):
                matched = credential.principal
        if matched is None:
            raise AuthenticationFailure("API credential is invalid", 403)
        return matched


class KillSwitchEventRow(Base):
    __tablename__ = "kill_switch_events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engaged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    engaged: bool
    reason: str | None
    actor_id: str | None
    changed_at: str | None
    sequence: int | None


class KillSwitchService:
    def __init__(self, engine) -> None:
        self.engine = engine

    def current(self) -> KillSwitchState:
        with Session(self.engine) as session:
            row = session.scalar(select(KillSwitchEventRow).order_by(KillSwitchEventRow.sequence.desc()).limit(1))
        if row is None:
            return KillSwitchState(False, None, None, None, None)
        return KillSwitchState(row.engaged, row.reason, row.actor_id, row.created_at.isoformat(), row.sequence)

    def set_state(self, *, engaged: bool, reason: str, actor_id: str) -> KillSwitchState:
        reason = reason.strip()
        if not reason:
            raise ValueError("Kill switch state changes require a reason")
        with Session(self.engine) as session, session.begin():
            row = KillSwitchEventRow(
                engaged=engaged,
                reason=reason,
                actor_id=actor_id,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            sequence = row.sequence
            changed_at = row.created_at.isoformat()
        return KillSwitchState(engaged, reason, actor_id, changed_at, sequence)

    def ensure_writes_allowed(self) -> None:
        state = self.current()
        if state.engaged:
            raise WritesDisabled(f"Production writes are disabled: {state.reason}")


def require_any_role(principal: Principal, *roles: str) -> None:
    if not principal.has_any_role(*roles):
        raise PermissionError(f"Actor {principal.actor_id!r} requires one of roles: {', '.join(roles)}")


def credential_profile(actor: str, roles: list[str]) -> dict[str, Any]:
    """Builds a non-secret profile payload for configuration tooling and tests."""
    return {"actor": actor, "roles": roles}


if __name__ == "__main__":
    print(json.dumps(ApiKeyAuthenticator.from_environment().safe_summary(), sort_keys=True))
