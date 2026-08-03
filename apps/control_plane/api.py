from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from . import api_contracts
from .api_contracts import API_SCHEMA_VERSION, APP_VERSION
from .correlation import correlation_id
from .routers import (
    accounts_payable,
    agent_control,
    ai_listing,
    channel_accounts,
    commerce_os,
    commercial_lifecycle,
    customer_service,
    decision_science,
    delivery_exceptions,
    erp_integration,
    evidence_governance,
    execution_operations,
    finance_control,
    finance_imports,
    growth_experiments,
    inventory,
    listing_lifecycle,
    marketplace_observation,
    media_connectors,
    native_parity_acceptance,
    oms,
    ozon_platform,
    pim,
    primary_source_intake,
    procurement_supply,
    product_content,
    profit_command,
    returns_aftersales,
    seller_erp_bridge,
    seller_strategy,
    sourcing_intelligence,
    system,
    warehouse_fulfillment,
)
from .runtime import runtime
from .security import AuthenticationFailure, WritesDisabled

app = FastAPI(title="KJDS Control Plane", version=APP_VERSION)
app.state.runtime = runtime

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
KILL_SWITCH_CONTROL_PATHS = {
    "/v1/browser-capture-inbox/preflight",
    "/v1/system/kill-switch/engage",
    "/v1/system/kill-switch/release",
    "/v1/loop-engineering/validate",
    "/v1/evidence/integrity-scan",
}


def is_write_safety_control_path(path: str) -> bool:
    limited_execution_bookkeeping = path.startswith(
        "/v1/limited-execution-commands/"
    ) and (
        path.endswith("/response-checkpoint")
        or path.endswith("/receipt")
    )
    agent_gate_observation = path.startswith(
        "/v1/agent-control/projects/"
    ) and path.endswith("/observe")
    return (
        path in KILL_SWITCH_CONTROL_PATHS
        or agent_gate_observation
        or path.startswith("/v1/operational-incidents")
        or path.startswith("/v1/operations-control")
        or limited_execution_bookkeeping
    )


def request_id_for(request: Request) -> str:
    """Return a bounded correlation id without trusting arbitrary header text."""
    return correlation_id(request.headers.get("X-Request-ID"), "req")


def trace_id_for(request: Request) -> str:
    return correlation_id(request.headers.get("X-Trace-ID"), "trace")


ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    423: "WRITES_LOCKED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def contract_error(
    *,
    status_code: int,
    detail: Any,
    request_id: str,
    trace_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    encoded_detail = jsonable_encoder(detail)
    error = {
        "code": ERROR_CODES.get(status_code, "INTERNAL_ERROR" if status_code >= 500 else "REQUEST_FAILED"),
        "message": detail if isinstance(detail, str) else "Request validation failed",
    }
    if not isinstance(detail, str):
        error["details"] = encoded_detail
    response = JSONResponse(
        status_code=status_code,
        content={
            "detail": encoded_detail,
            "error": error,
            "request_id": request_id,
            **({"trace_id": trace_id} if trace_id else {}),
            "schema_version": API_SCHEMA_VERSION,
        },
        headers=headers,
    )
    response.headers["X-Request-ID"] = request_id
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    response.headers["X-KJDS-Schema-Version"] = API_SCHEMA_VERSION
    return response


@app.exception_handler(HTTPException)
async def contract_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return contract_error(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=getattr(request.state, "request_id", request_id_for(request)),
        trace_id=getattr(request.state, "trace_id", trace_id_for(request)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def contract_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return contract_error(
        status_code=422,
        detail=exc.errors(),
        request_id=getattr(request.state, "request_id", request_id_for(request)),
        trace_id=getattr(request.state, "trace_id", trace_id_for(request)),
    )


@app.middleware("http")
async def enforce_control_plane_security(request: Request, call_next):
    request.state.request_id = request_id_for(request)
    request.state.trace_id = trace_id_for(request)
    if request.url.path.startswith("/v1/"):
        try:
            request.state.principal = runtime.authenticator.authenticate(request.headers.get("X-KJDS-API-Key"))
        except AuthenticationFailure as exc:
            return contract_error(
                status_code=exc.status_code,
                detail=str(exc),
                request_id=request.state.request_id,
                trace_id=request.state.trace_id,
            )

        if request.method in WRITE_METHODS and not is_write_safety_control_path(request.url.path):
            if not request.state.principal.has_any_role(
                "operator",
                "reviewer",
                "compliance",
                "approver",
                "risk",
                "executor",
                "monitor",
                "pilot_reader",
                "admin",
            ):
                return contract_error(
                    status_code=403,
                    detail="Authenticated actor has no write role",
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
            try:
                runtime.kill_switch.ensure_writes_allowed()
            except WritesDisabled as exc:
                return contract_error(
                    status_code=423,
                    detail=str(exc),
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
            except Exception:
                return contract_error(
                    status_code=503,
                    detail="Write safety state is unavailable; writes fail closed",
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Trace-ID"] = request.state.trace_id
    response.headers["X-KJDS-Schema-Version"] = API_SCHEMA_VERSION
    return response


_ROUTE_MODULES = (
    system,
    accounts_payable,
    agent_control,
    ai_listing,
    channel_accounts,
    evidence_governance,
    erp_integration,
    commerce_os,
    commercial_lifecycle,
    customer_service,
    delivery_exceptions,
    growth_experiments,
    decision_science,
    execution_operations,
    procurement_supply,
    ozon_platform,
    marketplace_observation,
    media_connectors,
    native_parity_acceptance,
    inventory,
    listing_lifecycle,
    oms,
    pim,
    product_content,
    primary_source_intake,
    profit_command,
    returns_aftersales,
    warehouse_fulfillment,
    seller_erp_bridge,
    seller_strategy,
    sourcing_intelligence,
    finance_control,
    finance_imports,
)
for _module in _ROUTE_MODULES:
    app.include_router(_module.router)


def control_plane_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "KjdsApiKey"
    ] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-KJDS-API-Key",
    }
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/v1/"):
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = [{"KjdsApiKey": []}]
    app.openapi_schema = schema
    return schema


app.openapi = control_plane_openapi


def registered_routes():
    """Expose domain routes without depending on FastAPI's internal nesting type."""
    for module in _ROUTE_MODULES:
        yield from module.router.routes


def __getattr__(name: str):
    """Keep the historical import surface while routes live with their domains."""
    if hasattr(api_contracts, name):
        return getattr(api_contracts, name)
    if hasattr(runtime, name):
        return getattr(runtime, name)
    for module in _ROUTE_MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)
