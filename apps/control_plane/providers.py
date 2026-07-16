from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class ProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    status: str
    detail: str | None = None


class JsonHttpProvider:
    def __init__(self, name: str, base_url: str, *, timeout: float = 10.0) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kwargs)
            response.raise_for_status()
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name} unavailable: {type(exc).__name__}") from exc


class OllamaProvider(JsonHttpProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        super().__init__("ollama", base_url, timeout=120.0)

    def healthcheck(self) -> ProviderHealth:
        try:
            payload = self._request("GET", "/api/tags")
            return ProviderHealth(self.name, "ok", f"{len(payload.get('models', []))} model(s)")
        except ProviderUnavailableError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))

    def list_models(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/tags")
        return payload.get("models", [])

    def chat(self, *, model: str, messages: list[dict[str, Any]], schema: dict[str, Any] | None = None) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if schema is not None:
            payload["format"] = schema
        return self._request("POST", "/api/chat", json=payload)


class ComfyUIProvider(JsonHttpProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:8189") -> None:
        super().__init__("comfyui", base_url, timeout=30.0)

    def healthcheck(self) -> ProviderHealth:
        try:
            self._request("GET", "/system_stats")
            return ProviderHealth(self.name, "ok")
        except ProviderUnavailableError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))

    def queue_workflow(self, *, workflow: dict[str, Any], client_id: str) -> dict:
        return self._request("POST", "/prompt", json={"prompt": workflow, "client_id": client_id})


class N8nProvider(JsonHttpProvider):
    """Internal-use-only automation adapter; see ADR-0002."""

    def __init__(self, base_url: str = "http://127.0.0.1:5678") -> None:
        super().__init__("n8n-internal", base_url, timeout=30.0)

    def healthcheck(self) -> ProviderHealth:
        try:
            self._request("GET", "/healthz")
            return ProviderHealth(self.name, "ok")
        except ProviderUnavailableError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))

    def trigger(self, *, webhook_path: str, payload: dict[str, Any]) -> Any:
        safe_path = webhook_path.strip("/")
        if not safe_path:
            raise ValueError("n8n webhook path is required")
        return self._request("POST", f"/webhook/{safe_path}", json=payload)


class FirecrawlProvider(JsonHttpProvider):
    """Self-hosted read-only web evidence collector."""

    def __init__(self, base_url: str = "http://127.0.0.1:3002", api_key: str | None = None) -> None:
        super().__init__("firecrawl", base_url, timeout=120.0)
        self.api_key = api_key

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def healthcheck(self) -> ProviderHealth:
        try:
            payload = self._request("GET", "/")
            detail = payload.get("message") if isinstance(payload, dict) else None
            return ProviderHealth(self.name, "ok", detail)
        except ProviderUnavailableError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))

    def scrape(self, url: str, *, formats: list[str] | None = None) -> dict:
        if not url.startswith(("http://", "https://")):
            raise ValueError("Firecrawl URL must be HTTP(S)")
        return self._request(
            "POST",
            "/v1/scrape",
            headers=self.headers,
            json={"url": url, "formats": formats or ["markdown"]},
        )
