from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


class OzonApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, repr=False)
class OzonCredentials:
    client_id: str
    api_key: str

    @classmethod
    def from_environment(cls) -> OzonCredentials:
        client_id = os.getenv("OZON_CLIENT_ID", "").strip()
        api_key = os.getenv("OZON_API_KEY", "").strip()
        if not client_id or not api_key:
            raise ValueError("OZON_CLIENT_ID and OZON_API_KEY are required by the isolated worker")
        return cls(client_id=client_id, api_key=api_key)


class OzonSellerClient:
    def __init__(
        self,
        credentials: OzonCredentials,
        *,
        base_url: str = "https://api-seller.ozon.ru",
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
        allow_insecure_http: bool = False,
        attributes_path: str = "/v4/product/info/attributes",
    ) -> None:
        normalized = base_url.rstrip("/")
        if not allow_insecure_http and not normalized.startswith("https://"):
            raise ValueError("Ozon worker requires HTTPS for Seller API credentials")
        self._client = httpx.Client(
            base_url=normalized,
            headers={
                "Client-Id": credentials.client_id,
                "Api-Key": credentials.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "KJDS-Ozon-Worker/1.0",
            },
            timeout=timeout_seconds,
            transport=transport,
        )
        self._attributes_path = attributes_path

    def close(self) -> None:
        self._client.close()

    def offer_state(self, offer_id: str) -> dict[str, Any]:
        offer_id = self._required(offer_id, "offer_id")
        info = self._read(
            "/v3/product/info/list",
            {"offer_id": [offer_id]},
        )
        attributes_body = {
            "filter": {"offer_id": [offer_id], "visibility": "ALL"},
            "limit": 100,
            "sort_dir": "ASC",
        }
        try:
            attributes = self._read(self._attributes_path, attributes_body)
        except OzonApiError as exc:
            if exc.status_code != 404 or self._attributes_path == "/v3/products/info/attributes":
                raise
            attributes = self._read("/v3/products/info/attributes", attributes_body)
        state = {"offer_id": offer_id, "info": info, "attributes": attributes}
        return {"state": state, "state_hash": self.state_hash(state)}

    def import_product(self, item: dict[str, Any]) -> str:
        if not isinstance(item, dict) or not item.get("offer_id"):
            raise ValueError("Ozon product import requires a complete item with offer_id")
        response = self._write("/v3/product/import", {"items": [item]})
        result = response.get("result")
        task_id = result.get("task_id") if isinstance(result, dict) else None
        if task_id is None:
            raise OzonApiError("Ozon product import response did not contain task_id")
        return str(task_id)

    def import_status(self, task_id: str) -> dict[str, Any]:
        return self._read("/v1/product/import/info", {"task_id": task_id})

    def wait_for_import(
        self,
        task_id: str,
        *,
        attempts: int = 10,
        interval_seconds: float = 1,
    ) -> dict[str, Any]:
        if not 1 <= attempts <= 60:
            raise ValueError("Ozon import polling attempts must be between 1 and 60")
        last: dict[str, Any] = {}
        for index in range(attempts):
            last = self.import_status(task_id)
            statuses = self._import_statuses(last)
            if statuses and all(status == "imported" for status in statuses):
                return {"status": "succeeded", "response": last}
            if any(status in {"failed", "error", "declined"} for status in statuses):
                return {"status": "failed", "response": last}
            if index + 1 < attempts:
                time.sleep(interval_seconds)
        return {"status": "uncertain", "response": last}

    def _read(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        delay = 0.25
        for attempt in range(3):
            try:
                response = self._client.post(path, json=payload)
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise OzonApiError("Ozon read transport failure", retryable=True) from exc
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    raise self._response_error(response, retryable=True)
                retry_after = self._retry_after(response, delay)
                time.sleep(retry_after)
                delay = min(delay * 2, 2)
                continue
            return self._json_or_error(response)
        raise OzonApiError("Ozon read retry loop exhausted", retryable=True)

    def _write(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=payload)
        except httpx.TransportError as exc:
            raise OzonApiError(
                "Ozon write outcome is uncertain after transport failure",
                retryable=False,
            ) from exc
        return self._json_or_error(response)

    @classmethod
    def _json_or_error(cls, response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            raise cls._response_error(
                response,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            value = response.json()
        except ValueError as exc:
            raise OzonApiError("Ozon API returned non-JSON response") from exc
        if not isinstance(value, dict):
            raise OzonApiError("Ozon API returned an unexpected response shape")
        return value

    @staticmethod
    def _response_error(response: httpx.Response, *, retryable: bool) -> OzonApiError:
        request_id = response.headers.get("x-o3-trace-id") or response.headers.get("x-request-id")
        suffix = f" request_id={request_id}" if request_id else ""
        return OzonApiError(
            f"Ozon API returned HTTP {response.status_code}.{suffix}",
            status_code=response.status_code,
            retryable=retryable,
        )

    @staticmethod
    def _retry_after(response: httpx.Response, fallback: float) -> float:
        try:
            return min(max(float(response.headers.get("Retry-After", fallback)), 0), 2)
        except ValueError:
            return fallback

    @staticmethod
    def _import_statuses(response: dict[str, Any]) -> list[str]:
        result = response.get("result")
        items = result.get("items", []) if isinstance(result, dict) else []
        return [str(item.get("status", "")).casefold() for item in items if isinstance(item, dict)]

    @staticmethod
    def state_hash(state: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned


class ControlPlaneExecutorClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Executor API key is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-KJDS-API-Key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def list_commands(self) -> list[dict[str, Any]]:
        value = self._request("GET", "/v1/limited-execution-commands")
        if not isinstance(value, list):
            raise RuntimeError("Control plane returned an invalid command list")
        return value

    def claim(self, command_id: str, state_hash: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/limited-execution-commands/{command_id}/claim",
            {"current_state_hash": state_hash, "lease_seconds": 300},
        )

    def receipt(self, command_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/limited-execution-commands/{command_id}/receipt",
            body,
        )

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None):
        response = self._client.request(method, path, json=body)
        if not response.is_success:
            raise RuntimeError(f"Control plane returned HTTP {response.status_code}")
        return response.json()


class OzonExecutionWorker:
    ADAPTER_ID = "ozon.product.import.v3"

    def __init__(self, *, control_plane: ControlPlaneExecutorClient, ozon: OzonSellerClient) -> None:
        self.control_plane = control_plane
        self.ozon = ozon

    def process(self, command: dict[str, Any], *, evidence_ids: list[str]) -> dict[str, Any]:
        if command.get("adapter_id") != self.ADAPTER_ID:
            raise ValueError("Worker received a command for a different adapter")
        if command.get("status") != "queued":
            raise ValueError("Worker only processes queued commands")
        target = command.get("target", {})
        offer_id = str(target.get("offer_id", "")).strip()
        item = command.get("patch", {}).get("item")
        if not offer_id or not isinstance(item, dict) or item.get("offer_id") != offer_id:
            raise ValueError("Command target and full Ozon import item do not match")
        before = self.ozon.offer_state(offer_id)
        self.control_plane.claim(command["id"], before["state_hash"])
        try:
            task_id = self.ozon.import_product(item)
            import_result = self.ozon.wait_for_import(task_id)
        except OzonApiError as exc:
            return self.control_plane.receipt(
                command["id"],
                {
                    "outcome": "uncertain",
                    "remote_operation_id": None,
                    "resulting_state_hash": None,
                    "mutation_applied": False,
                    "error_code": "OZON_TRANSPORT_UNCERTAIN",
                    "error_detail": str(exc),
                    "evidence_ids": evidence_ids,
                },
            )
        if import_result["status"] == "succeeded":
            after = self.ozon.offer_state(offer_id)
            return self.control_plane.receipt(
                command["id"],
                {
                    "outcome": "succeeded",
                    "remote_operation_id": task_id,
                    "resulting_state_hash": after["state_hash"],
                    "mutation_applied": True,
                    "error_code": None,
                    "error_detail": None,
                    "evidence_ids": evidence_ids,
                },
            )
        return self.control_plane.receipt(
            command["id"],
            {
                "outcome": import_result["status"],
                "remote_operation_id": task_id,
                "resulting_state_hash": None,
                "mutation_applied": False,
                "error_code": "OZON_IMPORT_NOT_CONFIRMED",
                "error_detail": "Ozon import task did not confirm a completed mutation",
                "evidence_ids": evidence_ids,
            },
        )

    def run_once(self, *, evidence_ids: list[str]) -> dict[str, Any] | None:
        commands = self.control_plane.list_commands()
        command = next(
            (
                item
                for item in commands
                if item.get("status") == "queued" and item.get("adapter_id") == self.ADAPTER_ID
            ),
            None,
        )
        return self.process(command, evidence_ids=evidence_ids) if command else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated KJDS Ozon limited-execution worker")
    parser.add_argument("--evidence-id", action="append", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5)
    args = parser.parse_args()
    control = ControlPlaneExecutorClient(
        base_url=os.getenv("KJDS_CONTROL_PLANE_URL", "http://127.0.0.1:8000"),
        api_key=os.environ.get("KJDS_EXECUTOR_API_KEY", ""),
    )
    ozon = OzonSellerClient(
        OzonCredentials.from_environment(),
        base_url=os.getenv("OZON_API_URL", "https://api-seller.ozon.ru"),
        attributes_path=os.getenv(
            "OZON_PRODUCT_ATTRIBUTES_PATH",
            "/v4/product/info/attributes",
        ),
    )
    worker = OzonExecutionWorker(control_plane=control, ozon=ozon)
    try:
        while True:
            worker.run_once(evidence_ids=args.evidence_id)
            if args.once:
                break
            time.sleep(max(args.poll_seconds, 1))
    finally:
        control.close()
        ozon.close()


if __name__ == "__main__":
    main()
