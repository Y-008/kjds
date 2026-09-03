from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.control_plane.agent_inference import (
    AgentInferenceService,
    AgentTaskRegistry,
    InferenceAttemptError,
    InferenceResponse,
    OllamaInferenceAdapter,
    _effective_prompt,
)
from apps.control_plane.providers import OllamaProvider


def test_effective_prompt_appends_exact_evidence_ids() -> None:
    contract = {"prompt": "Normalize only what is explicitly present."}
    result = _effective_prompt(contract, ("evd-one", "evd-two"))
    assert result.startswith("Normalize only what is explicitly present.")
    assert "evd-one" in result
    assert "evd-two" in result
    assert "field_evidence" in result


def test_effective_prompt_is_identity_without_evidence_ids() -> None:
    contract = {"prompt": "Base prompt."}
    assert _effective_prompt(contract, ()) == "Base prompt."


def test_effective_prompt_deduplicates_and_sorts_evidence_ids() -> None:
    contract = {"prompt": "P."}
    result = _effective_prompt(contract, ("evd-b", "evd-a", "evd-b"))
    assert result.index("evd-a") < result.index("evd-b")
    assert result.count("evd-b") == 1


class _FakeOllamaProvider:
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url
        self.calls: list[dict] = []

    def chat(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}


class _RecordingOllamaProvider(OllamaProvider):
    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:11434")
        self.sent: dict = {}

    def _request(self, method: str, path: str, **kwargs: object) -> object:  # type: ignore[override]
        self.sent = {"method": method, "path": path, **kwargs}
        return {"message": {"content": "ok"}, "prompt_eval_count": 0, "eval_count": 0}


def _adapter(
    provider: object | None = None,
    *,
    vision_model: str | None = None,
) -> OllamaInferenceAdapter:
    return OllamaInferenceAdapter(
        provider or _FakeOllamaProvider(),
        model="llama3.2",
        capabilities={"text"},
        vision_model=vision_model,
    )


def _infer(adapter: OllamaInferenceAdapter, *, image_inputs: tuple[str, ...]) -> InferenceResponse:
    return adapter.infer(
        prompt="p",
        model_input={"a": 1},
        output_schema={"type": "object"},
        max_output_tokens=100,
        timeout_seconds=5,
        idempotency_key="k",
        image_inputs=image_inputs,
    )


def test_model_for_uses_vision_model_when_images_present() -> None:
    assert _adapter(vision_model="llava").model_for(("data:image/png;base64,AAA",)) == "llava"


def test_model_for_falls_back_to_text_model_without_images() -> None:
    adapter = _adapter(vision_model="llava")
    assert adapter.model_for(()) == "llama3.2"


def test_ollama_image_strips_data_uri_prefix() -> None:
    assert OllamaInferenceAdapter._ollama_image("data:image/png;base64,QUJD") == "QUJD"


def test_ollama_image_passthrough_without_base64_marker() -> None:
    assert OllamaInferenceAdapter._ollama_image("http://host/img.png") == "http://host/img.png"


def test_infer_raises_vision_capability_missing_without_vision_model() -> None:
    with pytest.raises(InferenceAttemptError) as excinfo:
        _infer(_adapter(), image_inputs=("data:image/png;base64,QUJD",))
    assert excinfo.value.code == "local_vision_capability_missing"


def test_infer_routes_images_to_vision_model_and_sends_stripped_payload() -> None:
    provider = _FakeOllamaProvider()
    response = _infer(_adapter(provider, vision_model="llava"), image_inputs=("data:image/png;base64,QUJD",))
    assert provider.calls[0]["model"] == "llava"
    assert provider.calls[0]["images"] == ["QUJD"]
    assert response.content == "ok"


def test_ollama_provider_chat_embeds_images_and_deterministic_sampling() -> None:
    provider = _RecordingOllamaProvider()
    result = provider.chat(
        model="llava",
        messages=[{"role": "user", "content": "x"}],
        schema={"type": "object"},
        images=["QUJD"],
    )
    assert result["message"]["content"] == "ok"
    assert provider.sent["method"] == "POST"
    assert provider.sent["path"] == "/api/chat"
    payload = provider.sent["json"]
    assert payload["model"] == "llava"
    # Grammar-constrained `format=schema` is intentionally not sent to Ollama:
    # it crashes large local models during GBNF compilation and is ignored by
    # others; the governed adapter injects the schema into the prompt instead.
    assert "format" not in payload
    assert payload["options"] == {"temperature": 0}
    assert payload["images"] == ["QUJD"]
    assert payload["stream"] is False


class _RouteAdapter:
    def __init__(self, name: str, capabilities: frozenset[str] = frozenset({"text"})) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.capabilities = capabilities
        self.config_sha256 = "a" * 64

    def model_for(self, image_inputs: tuple[str, ...]) -> str:
        del image_inputs
        return self.model


def _route_service(*, preferred_provider: str) -> AgentInferenceService:
    return AgentInferenceService(
        engine=None,
        evidence=None,
        registry=AgentTaskRegistry(),
        local_adapter=_RouteAdapter("local"),
        cloud_adapter=_RouteAdapter("cloud"),
        enabled=True,
        preferred_provider=preferred_provider,
    )


def test_cloud_preference_routes_cloud_before_private_fallback() -> None:
    service = _route_service(preferred_provider="cloud")
    task = SimpleNamespace(required_capabilities=("text",), max_attempts=2)
    contract = {"cloud_fallback_allowed": True}
    assert [adapter.name for adapter in service._route(contract, task)] == ["cloud", "local"]


def test_cloud_preference_does_not_override_contract_that_disallows_cloud() -> None:
    service = _route_service(preferred_provider="cloud")
    task = SimpleNamespace(required_capabilities=("text",), max_attempts=2)
    contract = {"cloud_fallback_allowed": False}
    assert [adapter.name for adapter in service._route(contract, task)] == ["local"]


def test_private_preference_routes_private_before_cloud_fallback() -> None:
    service = _route_service(preferred_provider="local")
    task = SimpleNamespace(required_capabilities=("text",), max_attempts=2)
    contract = {"cloud_fallback_allowed": True}
    assert [adapter.name for adapter in service._route(contract, task)] == ["local", "cloud"]
