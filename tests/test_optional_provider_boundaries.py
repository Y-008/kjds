import pytest
from fastapi import HTTPException

from apps.control_plane.providers import ProviderHealth
from apps.control_plane.routers import system
from apps.control_plane.runtime import build_runtime
from apps.control_plane.security import KillSwitchState, Principal


def test_optional_providers_exist_only_when_configured(monkeypatch):
    monkeypatch.setenv("KJDS_REPOSITORY", "memory")
    for name in ("KJDS_OLLAMA_URL", "KJDS_N8N_URL", "FIRECRAWL_API_URL"):
        monkeypatch.delenv(name, raising=False)

    assert set(build_runtime().providers) == {"comfyui"}

    monkeypatch.setenv("KJDS_OLLAMA_URL", "http://ollama.test")
    monkeypatch.setenv("KJDS_N8N_URL", "http://n8n.test")
    monkeypatch.setenv("FIRECRAWL_API_URL", "http://firecrawl.test")
    assert set(build_runtime().providers) == {"comfyui", "ollama", "n8n", "firecrawl"}


def test_model_discovery_fails_cleanly_without_ollama(monkeypatch):
    monkeypatch.delitem(system.runtime.providers, "ollama", raising=False)
    principal = Principal(actor_id="operator", roles=frozenset({"operator"}))

    with pytest.raises(HTTPException) as exc_info:
        system.discover_models(principal)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "ollama is not configured"


def test_core_readiness_ignores_optional_health_checks(monkeypatch):
    class OptionalProvider:
        calls = 0

        def healthcheck(self):
            self.calls += 1
            return ProviderHealth("configured", "ok")

    provider = OptionalProvider()
    monkeypatch.setattr(system.runtime, "providers", {"configured": provider})
    monkeypatch.setattr(system, "database_health", lambda: {"status": "ok"})
    monkeypatch.setattr(type(system.runtime.repo), "event_count", lambda self: 0)
    monkeypatch.setattr(
        type(system.runtime.kill_switch),
        "current",
        lambda self: KillSwitchState(
            engaged=False,
            reason=None,
            actor_id=None,
            changed_at=None,
            sequence=0,
        ),
    )
    principal = Principal(actor_id="monitor", roles=frozenset({"monitor"}))

    assert "status" in system.ready()
    assert provider.calls == 0
    assert set(system.integration_health(principal)) == {"configured"}
    assert provider.calls == 1
