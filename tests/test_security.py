import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.security import (
    ApiKeyAuthenticator,
    AuthenticationFailure,
    KillSwitchService,
    WritesDisabled,
    credential_profile,
)
from apps.control_plane.sql_repository import Base


def test_api_key_identity_and_roles_are_derived_from_configuration(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    monkeypatch.setenv(
        "KJDS_API_KEYS_JSON",
        json.dumps({"request-key": credential_profile("operator-1", ["operator"])}),
    )
    authenticator = ApiKeyAuthenticator.from_environment()

    principal = authenticator.authenticate("request-key")
    assert principal.actor_id == "operator-1"
    assert principal.roles == {"operator"}

    with pytest.raises(AuthenticationFailure) as missing:
        authenticator.authenticate(None)
    assert missing.value.status_code == 401

    with pytest.raises(AuthenticationFailure) as invalid:
        authenticator.authenticate("wrong-key")
    assert invalid.value.status_code == 403


def test_api_fails_closed_when_identity_is_not_configured(monkeypatch):
    monkeypatch.delenv("KJDS_API_KEYS_JSON", raising=False)
    monkeypatch.delenv("KJDS_API_KEY", raising=False)
    authenticator = ApiKeyAuthenticator.from_environment()
    with pytest.raises(AuthenticationFailure) as failure:
        authenticator.authenticate("anything")
    assert failure.value.status_code == 503


def test_kill_switch_is_append_only_and_blocks_writes():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = KillSwitchService(engine)

    assert service.current().engaged is False
    engaged = service.set_state(engaged=True, reason="incident exercise", actor_id="risk-owner")
    assert engaged.engaged is True
    with pytest.raises(WritesDisabled, match="incident exercise"):
        service.ensure_writes_allowed()

    released = service.set_state(engaged=False, reason="incident resolved", actor_id="admin-owner")
    assert released.sequence == engaged.sequence + 1
    service.ensure_writes_allowed()
