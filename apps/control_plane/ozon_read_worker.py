from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from .correlation import correlation_id
from .ozon_worker import OzonApiError, OzonCredentials, OzonSellerClient

MAX_BATCH_SIZE = 50
OFFICIAL_OZON_ORIGIN = "https://api-seller.ozon.ru"
PRODUCT_ATTRIBUTES_PATH = "/v4/product/info/attributes"
PLACEHOLDER_VALUES = {"missing", "replace-me", "replace-with-a-key", "changeme"}


def offline_preflight(
    *,
    pilot_id: str,
    offer_ids: list[str],
    idempotency_key: str,
    batch: bool = False,
    cursor: str | None = None,
    page_size: int = 10,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate the first live product Pilot without opening any client or socket."""
    env = os.environ if environment is None else environment
    pilot = _bounded_required(pilot_id, "Pilot id", 300)
    key = _bounded_required(idempotency_key, "Idempotency key", 200)
    targets = [_bounded_required(value, "Offer id", 200) for value in offer_ids]
    if batch or cursor not in (None, "") or len(targets) != 1:
        raise ValueError("Initial Ozon Pilot preflight requires exactly one non-batch target")
    if page_size != 10:
        raise ValueError("Initial Ozon Pilot preflight requires the default page size")

    environment_checks = validate_execution_environment(env)

    target = targets[0]
    return {
        "status": "ready_for_explicit_execution",
        "mode": "offline_preflight",
        "network_calls_performed": False,
        "operation": OzonReadOnlyWorker.OPERATION,
        "contract_version": OzonSellerClient.PRODUCT_READ_CONTRACT_VERSION,
        "target_count": 1,
        "target_sha256": hashlib.sha256(target.encode()).hexdigest(),
        "pilot_sha256": hashlib.sha256(pilot.encode()).hexdigest(),
        "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        **environment_checks,
        "explicit_execution_required": True,
    }


def offline_finance_preflight(
    *,
    pilot_id: str,
    date_from: str,
    date_to: str,
    idempotency_key: str,
    page: int = 1,
    page_size: int = 1000,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate one bounded finance page without opening any client or socket."""
    env = os.environ if environment is None else environment
    pilot = _bounded_required(pilot_id, "Pilot id", 300)
    key = _bounded_required(idempotency_key, "Idempotency key", 200)
    request = OzonSellerClient.finance_request_body(
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    query_hash = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "status": "ready_for_explicit_execution",
        "mode": "offline_preflight",
        "network_calls_performed": False,
        "operation": OzonFinanceReadOnlyWorker.OPERATION,
        "contract_version": OzonSellerClient.FINANCE_READ_CONTRACT_VERSION,
        "query_window_sha256": query_hash,
        "page": page,
        "page_size": page_size,
        "pilot_sha256": hashlib.sha256(pilot.encode()).hexdigest(),
        "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        **validate_execution_environment(env),
        "explicit_execution_required": True,
    }


def validate_execution_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fail closed on connection and credential configuration without opening a socket."""
    env = os.environ if environment is None else environment
    ozon_url = _safe_url(
        env.get("OZON_API_URL", OFFICIAL_OZON_ORIGIN),
        name="Ozon API URL",
        allowed_hosts={"api-seller.ozon.ru"},
        require_https=True,
    )
    if ozon_url != OFFICIAL_OZON_ORIGIN:
        raise ValueError("Initial Ozon Pilot must use the official Seller API origin")
    attributes_path = str(env.get("OZON_PRODUCT_ATTRIBUTES_PATH", PRODUCT_ATTRIBUTES_PATH)).strip()
    if attributes_path != PRODUCT_ATTRIBUTES_PATH:
        raise ValueError("Initial Ozon Pilot must use the fixed v4 product attributes path")
    _safe_url(
        env.get("KJDS_CONTROL_PLANE_URL", "http://127.0.0.1:8000"),
        name="Control plane URL",
        allowed_hosts=None,
        require_https=False,
        allow_http_hosts={"127.0.0.1", "localhost", "::1", "api"},
    )

    required_names = ("KJDS_PILOT_READER_API_KEY", "OZON_CLIENT_ID", "OZON_API_KEY")
    values = {name: _configured_value(env, name) for name in required_names}
    secrets = {
        "pilot_reader": values["KJDS_PILOT_READER_API_KEY"],
        "ozon_api": values["OZON_API_KEY"],
    }
    for name in ("KJDS_API_KEY", "KJDS_EXECUTOR_API_KEY"):
        value = str(env.get(name, "")).strip()
        if value and value.lower() not in PLACEHOLDER_VALUES:
            secrets[name] = value
    if len(set(secrets.values())) != len(secrets):
        raise ValueError("Pilot reader, Ozon, generic API, and executor credentials must be distinct")

    return {
        "ozon_origin_verified": True,
        "attributes_path_verified": True,
        "required_credentials_present": len(values),
        "credential_values_distinct": True,
    }


def _bounded_required(value: str, name: str, maximum: int) -> str:
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER_VALUES:
        raise ValueError(f"{name} is required")
    if len(cleaned) > maximum or any(char in cleaned for char in ("\r", "\n", "\0")):
        raise ValueError(f"{name} is invalid")
    return cleaned


def _configured_value(environment: Mapping[str, str], name: str) -> str:
    value = str(environment.get(name, "")).strip()
    if not value or value.lower() in PLACEHOLDER_VALUES:
        raise ValueError(f"{name} must be configured for Pilot execution")
    return value


def _safe_url(
    value: str,
    *,
    name: str,
    allowed_hosts: set[str] | None,
    require_https: bool,
    allow_http_hosts: set[str] | None = None,
) -> str:
    raw = str(value).strip().rstrip("/")
    parsed = urlsplit(raw)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError(f"{name} must be a safe origin without credentials, path, query, or fragment")
    if allowed_hosts is not None and parsed.hostname.lower() not in allowed_hosts:
        raise ValueError(f"{name} host is not allowed")
    if (
        parsed.scheme == "http"
        and allow_http_hosts is not None
        and parsed.hostname.lower() not in allow_http_hosts
    ):
        raise ValueError(f"{name} requires HTTPS outside local or Compose networking")
    return raw


class ControlPlanePilotReaderClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Pilot reader API key is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-KJDS-API-Key": api_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def start(
        self,
        pilot_id: str,
        *,
        idempotency_key: str,
        operation: str,
        target_ref: str,
        trace_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/read-only-pilots/{pilot_id}/runs",
            {
                "idempotency_key": idempotency_key,
                "operation": operation,
                "target_ref": target_ref,
            },
            trace_id=trace_id,
        )

    def complete(self, run_id: str, body: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/read-only-pilot-runs/{run_id}/complete",
            body,
            trace_id=trace_id,
        )

    def capture_response(
        self,
        run_id: str,
        *,
        content: bytes,
        response_sha256: str,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/v1/read-only-pilot-runs/{run_id}/response-evidence",
            data={"response_sha256": response_sha256},
            files={"file": (f"{run_id}-ozon-response.json", content, "application/json")},
            headers=self._correlation_headers(trace_id),
        )
        return self._object_response(response, "response evidence")

    def checkpoint_response(
        self,
        run_id: str,
        *,
        content: bytes,
        response_sha256: str,
        response_byte_size: int,
        record_count: int,
        summary: dict[str, Any],
        trace_id: str,
    ) -> dict[str, Any]:
        return self._idempotent_write(
            lambda: self._client.post(
                f"/v1/read-only-pilot-runs/{run_id}/response-checkpoint",
                data={
                    "response_sha256": response_sha256,
                    "response_byte_size": str(response_byte_size),
                    "record_count": str(record_count),
                    "summary_json": json.dumps(
                        summary,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
                files={"file": (f"{run_id}-ozon-response.json", content, "application/json")},
                headers=self._correlation_headers(trace_id),
            ),
            "response checkpoint",
        )

    def finalize(self, run_id: str, *, trace_id: str) -> dict[str, Any]:
        return self._idempotent_write(
            lambda: self._client.post(
                f"/v1/read-only-pilot-runs/{run_id}/finalize",
                headers=self._correlation_headers(trace_id),
            ),
            "pilot run finalization",
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        *,
        trace_id: str,
    ) -> dict[str, Any]:
        response = self._client.request(
            method,
            path,
            json=body,
            headers=self._correlation_headers(trace_id),
        )
        return self._object_response(response, "pilot run")

    def _idempotent_write(
        self,
        request: Callable[[], httpx.Response],
        description: str,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = request()
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < 2:
                    continue
                break
            if response.is_success:
                return self._object_response(response, description)
            if response.status_code < 500 or attempt == 2:
                return self._object_response(response, description)
        raise RuntimeError(f"Control plane {description} failed after bounded retries") from last_error

    @staticmethod
    def _correlation_headers(trace_id: str) -> dict[str, str]:
        return {
            "X-Request-ID": correlation_id(None, "req"),
            "X-Trace-ID": correlation_id(trace_id, "trace"),
        }

    @staticmethod
    def _object_response(response: httpx.Response, description: str) -> dict[str, Any]:
        if not response.is_success:
            raise RuntimeError(f"Control plane returned HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError(f"Control plane returned invalid {description}")
        return value


class OzonReadOnlyWorker:
    OPERATION = "ozon.product.read"

    def __init__(
        self,
        *,
        control_plane: ControlPlanePilotReaderClient,
        ozon: OzonSellerClient,
    ) -> None:
        self.control_plane = control_plane
        self.ozon = ozon

    def run_once(
        self,
        *,
        pilot_id: str,
        offer_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        trace_id = correlation_id(None, "trace")
        allocation = self.control_plane.start(
            pilot_id,
            idempotency_key=idempotency_key,
            operation=self.OPERATION,
            target_ref=offer_id,
            trace_id=trace_id,
        )
        if allocation.get("execution_granted") is not True:
            return allocation
        try:
            result = self.ozon.offer_state(offer_id)
            raw = result["response_evidence_bytes"]
            response_sha256 = hashlib.sha256(raw).hexdigest()
            info = result["state"].get("info", {})
            attributes = result["state"].get("attributes", {})
            summary = {
                "contract_version": result["contract_version"],
                "info_item_count": self._item_count(info),
                "attribute_item_count": self._item_count(attributes),
                "state_sha256": result["state_hash"],
            }
            self.control_plane.checkpoint_response(
                allocation["id"],
                content=raw,
                response_sha256=response_sha256,
                response_byte_size=len(raw),
                record_count=self._item_count(info) + self._item_count(attributes),
                summary=summary,
                trace_id=trace_id,
            )
            return self.control_plane.finalize(allocation["id"], trace_id=trace_id)
        except OzonApiError as exc:
            return self.control_plane.complete(
                allocation["id"],
                {
                    "outcome": "failed",
                    "response_sha256": None,
                    "response_byte_size": 0,
                    "record_count": 0,
                    "summary": {
                        "retryable": exc.retryable,
                        "connector_error_code": exc.code,
                        "circuit_state": self.ozon.circuit_status()["state"],
                    },
                    "error_code": exc.code,
                },
                trace_id=trace_id,
            )

    def run_batch(
        self,
        *,
        pilot_id: str,
        offer_ids: list[str],
        batch_idempotency_key: str,
        cursor: str | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """Read a bounded deterministic page and return an opaque continuation cursor.

        The control plane remains the source of truth for each run and its evidence;
        this method only provides deterministic paging and batch-level accounting.
        """
        if not isinstance(offer_ids, list) or not offer_ids:
            raise ValueError("At least one Ozon offer id is required")
        if len(offer_ids) > MAX_BATCH_SIZE:
            raise ValueError(f"Ozon read batch cannot exceed {MAX_BATCH_SIZE} targets")
        normalized = [self._required(value, "offer_id") for value in offer_ids]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Ozon read batch contains duplicate offer ids")
        batch_key = self._required(batch_idempotency_key, "Batch idempotency key")
        if len(batch_key) > 200:
            raise ValueError("Batch idempotency key is too long")
        if not 1 <= page_size <= MAX_BATCH_SIZE:
            raise ValueError(f"Ozon read page size must be between 1 and {MAX_BATCH_SIZE}")
        offset = self._cursor(cursor)
        if offset > len(normalized):
            raise ValueError("Ozon read cursor is beyond the batch")
        page = normalized[offset : offset + page_size]
        results: list[dict[str, Any]] = []
        for offer_id in page:
            result = self.run_once(
                pilot_id=pilot_id,
                offer_id=offer_id,
                idempotency_key=f"{batch_key}:{hashlib.sha256(offer_id.encode()).hexdigest()}",
            )
            results.append(
                {
                    "target_sha256": hashlib.sha256(offer_id.encode()).hexdigest(),
                    "run_id": result["id"],
                    "status": result["status"],
                    "outcome": result["outcome"],
                    "evidence_id": result.get("evidence_id"),
                    "raw_response_stored": bool(result.get("raw_response_stored")),
                }
            )
        next_offset = offset + len(page)
        return {
            "batch_idempotency_key": batch_key,
            "cursor": str(offset),
            "next_cursor": str(next_offset) if next_offset < len(normalized) else None,
            "requested_count": len(normalized),
            "page_count": len(page),
            "succeeded_count": sum(item["outcome"] == "succeeded" for item in results),
            "failed_count": sum(item["outcome"] == "failed" for item in results),
            "results": results,
            "raw_response_stored": all(
                item["outcome"] != "succeeded" or item["raw_response_stored"] for item in results
            ),
        }

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @staticmethod
    def _cursor(value: str | None) -> int:
        if value in (None, ""):
            return 0
        try:
            cursor = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Ozon read cursor must be a non-negative integer") from exc
        if cursor < 0:
            raise ValueError("Ozon read cursor must be a non-negative integer")
        return cursor

    @staticmethod
    def _item_count(value: Any) -> int:
        if not isinstance(value, dict):
            return 0
        items = value.get("items")
        if not isinstance(items, list):
            items = value.get("result")
        return len(items) if isinstance(items, list) else 0


class OzonFinanceReadOnlyWorker:
    OPERATION = "ozon.finance.read"

    def __init__(
        self,
        *,
        control_plane: ControlPlanePilotReaderClient,
        ozon: OzonSellerClient,
    ) -> None:
        self.control_plane = control_plane
        self.ozon = ozon

    def run_once(
        self,
        *,
        pilot_id: str,
        date_from: str,
        date_to: str,
        page: int,
        page_size: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = self.ozon.finance_request_body(
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
        target_ref = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        trace_id = correlation_id(None, "trace")
        allocation = self.control_plane.start(
            pilot_id,
            idempotency_key=idempotency_key,
            operation=self.OPERATION,
            target_ref=target_ref,
            trace_id=trace_id,
        )
        if allocation.get("execution_granted") is not True:
            return allocation
        try:
            result = self.ozon.finance_transactions(
                date_from=date_from,
                date_to=date_to,
                page=page,
                page_size=page_size,
            )
            raw = result["response_evidence_bytes"]
            response_sha256 = hashlib.sha256(raw).hexdigest()
            summary = {
                "contract_version": result["contract_version"],
                "query_window_sha256": result["query_window_sha256"],
                "page": result["page"],
                "page_size": result["page_size"],
                "page_count": result["page_count"],
                "operation_count": result["operation_count"],
            }
            self.control_plane.checkpoint_response(
                allocation["id"],
                content=raw,
                response_sha256=response_sha256,
                response_byte_size=len(raw),
                record_count=result["operation_count"],
                summary=summary,
                trace_id=trace_id,
            )
            return self.control_plane.finalize(allocation["id"], trace_id=trace_id)
        except OzonApiError as exc:
            return self.control_plane.complete(
                allocation["id"],
                {
                    "outcome": "failed",
                    "response_sha256": None,
                    "response_byte_size": 0,
                    "record_count": 0,
                    "summary": {
                        "retryable": exc.retryable,
                        "connector_error_code": exc.code,
                        "circuit_state": self.ozon.circuit_status()["state"],
                    },
                    "error_code": exc.code,
                },
                trace_id=trace_id,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated KJDS Ozon read-only pilot worker")
    parser.add_argument("--pilot-id", default=os.getenv("KJDS_READ_ONLY_PILOT_ID", ""))
    parser.add_argument(
        "--operation",
        choices=("ozon.product.read", "ozon.finance.read"),
        default=os.getenv("KJDS_READ_ONLY_OPERATION", "ozon.product.read"),
    )
    parser.add_argument("--offer-id", action="append", dest="offer_ids")
    parser.add_argument(
        "--idempotency-key",
        default=os.getenv("KJDS_READ_ONLY_IDEMPOTENCY_KEY", ""),
    )
    parser.add_argument("--batch", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="validate configuration locally without opening network clients",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="explicitly authorize this worker process to open read-only network clients",
    )
    parser.add_argument("--cursor", default=os.getenv("KJDS_READ_ONLY_CURSOR") or None)
    parser.add_argument("--page-size", type=int, default=int(os.getenv("KJDS_READ_ONLY_PAGE_SIZE", "10")))
    parser.add_argument("--date-from", default=os.getenv("KJDS_FINANCE_DATE_FROM", ""))
    parser.add_argument("--date-to", default=os.getenv("KJDS_FINANCE_DATE_TO", ""))
    parser.add_argument(
        "--finance-page",
        type=int,
        default=int(os.getenv("KJDS_FINANCE_PAGE", "1")),
    )
    parser.add_argument(
        "--finance-page-size",
        type=int,
        default=int(os.getenv("KJDS_FINANCE_PAGE_SIZE", "1000")),
    )
    args = parser.parse_args()
    offer_ids = args.offer_ids or [item.strip() for item in os.getenv("KJDS_READ_ONLY_OFFER_IDS", "").split(",") if item.strip()]
    if not offer_ids:
        fallback = os.getenv("KJDS_READ_ONLY_OFFER_ID", "").strip()
        offer_ids = [fallback] if fallback else []
    if not args.pilot_id or not args.idempotency_key:
        raise ValueError("Pilot id and idempotency key are required")
    if args.operation == "ozon.product.read" and not offer_ids:
        raise ValueError("Product read requires offer id(s)")
    if args.operation == "ozon.finance.read" and (
        offer_ids or args.batch or args.cursor is not None or not args.date_from or not args.date_to
    ):
        raise ValueError(
            "Finance read requires date-from/date-to and does not accept product batch options"
        )
    if args.preflight:
        if args.operation == "ozon.finance.read":
            report = offline_finance_preflight(
                pilot_id=args.pilot_id,
                date_from=args.date_from,
                date_to=args.date_to,
                idempotency_key=args.idempotency_key,
                page=args.finance_page,
                page_size=args.finance_page_size,
            )
        else:
            report = offline_preflight(
                pilot_id=args.pilot_id,
                offer_ids=offer_ids,
                idempotency_key=args.idempotency_key,
                batch=args.batch,
                cursor=args.cursor,
                page_size=args.page_size,
            )
        print(
            json.dumps(
                report,
                ensure_ascii=False,
            )
        )
        return
    if args.operation == "ozon.finance.read":
        offline_finance_preflight(
            pilot_id=args.pilot_id,
            date_from=args.date_from,
            date_to=args.date_to,
            idempotency_key=args.idempotency_key,
            page=args.finance_page,
            page_size=args.finance_page_size,
        )
    elif not args.batch and len(offer_ids) == 1 and args.cursor is None and args.page_size == 10:
        offline_preflight(
            pilot_id=args.pilot_id,
            offer_ids=offer_ids,
            idempotency_key=args.idempotency_key,
            batch=False,
            cursor=None,
            page_size=10,
        )
    else:
        validate_execution_environment()
    control = ControlPlanePilotReaderClient(
        base_url=os.getenv("KJDS_CONTROL_PLANE_URL", "http://127.0.0.1:8000"),
        api_key=os.environ.get("KJDS_PILOT_READER_API_KEY", ""),
    )
    ozon = OzonSellerClient(
        OzonCredentials.from_environment(),
        base_url=os.getenv("OZON_API_URL", "https://api-seller.ozon.ru"),
        attributes_path=os.getenv("OZON_PRODUCT_ATTRIBUTES_PATH", "/v4/product/info/attributes"),
    )
    try:
        if args.operation == "ozon.finance.read":
            worker = OzonFinanceReadOnlyWorker(control_plane=control, ozon=ozon)
            control_result = worker.run_once(
                pilot_id=args.pilot_id,
                date_from=args.date_from,
                date_to=args.date_to,
                page=args.finance_page,
                page_size=args.finance_page_size,
                idempotency_key=args.idempotency_key,
            )
            output = {
                "run_id": control_result["id"],
                "status": control_result["status"],
                "outcome": control_result["outcome"],
                "evidence_id": control_result.get("evidence_id"),
                "raw_response_stored": bool(control_result.get("raw_response_stored")),
            }
        else:
            worker = OzonReadOnlyWorker(control_plane=control, ozon=ozon)
        if args.operation == "ozon.product.read" and (
            args.batch or len(offer_ids) > 1 or args.cursor is not None
        ):
            output = worker.run_batch(
                pilot_id=args.pilot_id,
                offer_ids=offer_ids,
                batch_idempotency_key=args.idempotency_key,
                cursor=args.cursor,
                page_size=args.page_size,
            )
        elif args.operation == "ozon.product.read":
            control_result = worker.run_once(
                pilot_id=args.pilot_id,
                offer_id=offer_ids[0],
                idempotency_key=args.idempotency_key,
            )
            output = {
                "run_id": control_result["id"],
                "status": control_result["status"],
                "outcome": control_result["outcome"],
                "evidence_id": control_result["evidence_id"],
                "raw_response_stored": bool(control_result.get("raw_response_stored")),
            }
        print(json.dumps(output, ensure_ascii=False))
    finally:
        control.close()
        ozon.close()


if __name__ == "__main__":
    main()
