from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

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

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None = None,
        images: list[str] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if schema is not None:
            payload["format"] = schema
        if images:
            payload["images"] = images
        return self._request("POST", "/api/chat", json=payload)


class OpenAICompatibleProvider(JsonHttpProvider):
    """Minimal OpenAI-compatible chat adapter with a fail-closed URL boundary."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        base_url = base_url.strip().rstrip("/")
        api_key = api_key.strip()
        parsed = urlparse(base_url)
        loopback = (parsed.hostname or "").lower() in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenAI-compatible base URL must be absolute HTTP(S)")
        if not loopback and parsed.scheme != "https":
            raise ValueError("Non-loopback OpenAI-compatible base URL must use HTTPS")
        if not api_key:
            raise ValueError("OpenAI-compatible API key is required")
        super().__init__("openai-compatible", base_url, timeout=timeout)
        self._api_key = api_key

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not model.strip():
            raise ValueError("OpenAI-compatible model is required")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:255]
        payload: dict[str, Any] = {
            "model": model.strip(),
            "messages": messages,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "kjds_agent_artifact",
                    "strict": True,
                    "schema": schema,
                },
            }
        return self._request(
            "POST",
            "/chat/completions",
            headers=headers,
            json=payload,
        )


class ComfyUIProvider(JsonHttpProvider):
    def __init__(self, base_url: str = "http://127.0.0.1:8189") -> None:
        super().__init__("comfyui", base_url, timeout=30.0)

    def healthcheck(self) -> ProviderHealth:
        try:
            payload = self._request("GET", "/system_stats")
            system = payload.get("system", {}) if isinstance(payload, dict) else {}
            devices = payload.get("devices", []) if isinstance(payload, dict) else []
            version = str(system.get("comfyui_version", "")).strip()
            device = str(devices[0].get("name", "")).strip() if devices and isinstance(devices[0], dict) else ""
            detail = " · ".join(item for item in (version, device) if item) or None
            return ProviderHealth(self.name, "ok", detail)
        except ProviderUnavailableError as exc:
            return ProviderHealth(self.name, "unavailable", str(exc))

    def queue_workflow(self, *, workflow: dict[str, Any], client_id: str) -> dict:
        return self._request("POST", "/prompt", json={"prompt": workflow, "client_id": client_id})

    def upload_image(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        subfolder: str,
    ) -> dict:
        if not content or not content_type.startswith("image/"):
            raise ValueError("ComfyUI upload requires image content")
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError("ComfyUI upload filename must be a safe basename")
        if any(part in {"", ".", ".."} for part in subfolder.replace("\\", "/").split("/")):
            raise ValueError("ComfyUI upload subfolder must be a safe relative path")
        return self._request(
            "POST",
            "/upload/image",
            files={"image": (filename, content, content_type)},
            data={"type": "input", "subfolder": subfolder, "overwrite": "false"},
        )

    def history(self, prompt_id: str) -> dict:
        if not prompt_id.strip():
            raise ValueError("ComfyUI prompt_id is required")
        return self._request("GET", f"/history/{prompt_id.strip()}")

    def download_image(self, *, filename: str, subfolder: str, image_type: str) -> tuple[bytes, str]:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError("ComfyUI output filename must be a safe basename")
        if image_type not in {"output", "temp"}:
            raise ValueError("ComfyUI output type must be output or temp")
        if any(part in {".", ".."} for part in subfolder.replace("\\", "/").split("/") if part):
            raise ValueError("ComfyUI output subfolder must be a safe relative path")
        try:
            response = httpx.get(
                f"{self.base_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": image_type},
                timeout=self.timeout,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
            return response.content, content_type
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name} unavailable: {type(exc).__name__}") from exc


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


class Kuajing84Provider(JsonHttpProvider):
    """Read-only adapter for Kuajing84's published enterprise order API."""

    def __init__(
        self,
        *,
        client_secret: str,
        app_uid: str,
        access_token: str | None = None,
        base_url: str = "https://api.service.kuajing84.com",
    ) -> None:
        super().__init__("kuajing84", base_url, timeout=30.0)
        self.client_secret = client_secret.strip()
        self.app_uid = app_uid.strip()
        self.access_token = access_token.strip() if access_token else None
        if not self.client_secret or not self.app_uid:
            raise ValueError("Kuajing84 client_secret and app_uid are required")

    def fetch_access_token(self) -> str:
        payload = self._require_success(
            self._request("POST", "/erpapi/token/index", json={"client_secret": self.client_secret})
        )
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise ProviderUnavailableError("kuajing84 returned no access token")
        self.access_token = token
        return token

    def list_orders(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._post("/erpapi/orderlist/search", filters or {"page": 1, "limit": 10})
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ProviderUnavailableError("kuajing84 returned an invalid order list")
        return data

    def order_out_info(self, *, order_id: int | None = None, section_code: str | None = None) -> dict[str, Any]:
        if order_id is None and not (section_code or "").strip():
            raise ValueError("Kuajing84 order_id or section_code is required")
        body: dict[str, Any] = {}
        if order_id is not None:
            body["order_id"] = order_id
        if section_code:
            body["section_code"] = section_code.strip()
        payload = self._post("/erpapi/order/get_order_out_info", body)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderUnavailableError("kuajing84 returned invalid order out information")
        return data

    def warehouse_services(self, *, warehouse_id: int, platform_id: int) -> dict[str, Any]:
        if warehouse_id <= 0 or platform_id <= 0:
            raise ValueError("Kuajing84 warehouse_id and platform_id must be positive")
        payload = self._post(
            "/erpapi/storehouse/searchStorehouseSection",
            {"sid": warehouse_id, "section_id": platform_id},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderUnavailableError("kuajing84 returned invalid warehouse services")
        return data

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.access_token:
            raise ValueError("Kuajing84 access_token is required; call fetch_access_token first")
        return self._require_success(self._request("POST", path, headers=self._headers(), json=body))

    def _headers(self) -> dict[str, str]:
        return {
            "k-client-secret": self.client_secret,
            "authorization": self.access_token or "",
            "k-app-uid": self.app_uid,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _require_success(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("code") != 1:
            raise ProviderUnavailableError("kuajing84 returned a non-success response")
        return payload
