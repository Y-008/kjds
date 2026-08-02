from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
STORE_REF = "ozon-primary"
WORKSPACE_PATH = "/v1/channel-accounts/workspace"
OPENAPI_SNAPSHOT = ROOT / "docs/project/contracts/openapi-v1.json"
DEFAULT_AS_OF = "2026-07-31T15:00:00+00:00"
PERMITTED_ROLES = frozenset(
    {
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    }
)
FALSE_CONTROL_FIELDS = (
    "secret_reference_returned",
    "plaintext_secret_stored",
    "cookie_allowed",
    "internal_token_allowed",
    "device_session_allowed",
    "private_endpoint_allowed",
    "captcha_bypass_allowed",
    "access_control_bypass_allowed",
    "external_write_allowed",
)
FALSE_AGENT_PERMISSION_FIELDS = (
    "secret_read_allowed",
    "authorization_change_allowed",
    "self_approval_allowed",
    "permit_issue_allowed",
    "external_verification_allowed",
    "platform_contact_allowed",
    "fictional_authority_allowed",
    "external_write_allowed",
)


def _profiles(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("KJDS_API_KEYS_JSON is required for BAS-158 runtime verification")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("KJDS_API_KEYS_JSON is not valid JSON") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError("KJDS_API_KEYS_JSON must be a non-empty identity map")
    profiles: dict[str, dict[str, Any]] = {}
    for key, profile in parsed.items():
        if not isinstance(key, str) or not key or not isinstance(profile, dict):
            raise RuntimeError("KJDS_API_KEYS_JSON contains an invalid identity profile")
        profiles[key] = profile
    return profiles


def _string_set(profile: dict[str, Any], field: str, default: list[str]) -> set[str]:
    value = profile.get(field, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError(f"KJDS_API_KEYS_JSON profile field {field} must be a string list")
    return {item.strip() for item in value if item.strip()}


def _as_of(value: object) -> str:
    text = str(value or DEFAULT_AS_OF).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("BAS158_RUNTIME_AS_OF must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("BAS158_RUNTIME_AS_OF must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _forbidden_store(allowed_stores: set[str]) -> str:
    candidate = "bas158-definitely-forbidden-store"
    suffix = 0
    while candidate in allowed_stores:
        suffix += 1
        candidate = f"bas158-definitely-forbidden-store-{suffix}"
    return candidate


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("BAS-158 authenticated runtime response is not JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("BAS-158 authenticated runtime response must be an object")
    return payload


def main() -> None:
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    profiles = _profiles(values.get("KJDS_API_KEYS_JSON"))

    allowed_key: str | None = None
    allowed_stores: set[str] = set()
    denied_key: str | None = None
    for key, profile in profiles.items():
        stores = _string_set(profile, "stores", [STORE_REF])
        roles = _string_set(profile, "roles", [])
        if allowed_key is None and STORE_REF in stores and roles & PERMITTED_ROLES:
            allowed_key = key
            allowed_stores = stores
        if denied_key is None and STORE_REF not in stores:
            denied_key = key
    if allowed_key is None:
        raise RuntimeError("KJDS_API_KEYS_JSON has no ozon-primary identity with a permitted BAS-158 read role")

    as_of = _as_of(values.get("BAS158_RUNTIME_AS_OF"))
    params = {"store_ref": STORE_REF, "as_of": as_of}
    base_url = str(values.get("BAS158_API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    allowed_headers = {"X-KJDS-API-Key": allowed_key}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        anonymous = client.get(WORKSPACE_PATH, params=params)
        first = client.get(WORKSPACE_PATH, params=params, headers=allowed_headers)
        second = client.get(WORKSPACE_PATH, params=params, headers=allowed_headers)
        if denied_key is not None:
            forbidden = client.get(
                WORKSPACE_PATH,
                params=params,
                headers={"X-KJDS-API-Key": denied_key},
            )
        else:
            forbidden = client.get(
                WORKSPACE_PATH,
                params={
                    "store_ref": _forbidden_store(allowed_stores),
                    "as_of": as_of,
                },
                headers=allowed_headers,
            )
        readiness = client.get("/health/ready")
        live_openapi_response = client.get("/openapi.json")

    if live_openapi_response.status_code != 200:
        raise RuntimeError("BAS-158 live OpenAPI is unavailable")
    live_openapi = live_openapi_response.json()
    snapshot_openapi = json.loads(
        OPENAPI_SNAPSHOT.read_text(encoding="utf-8")
    )
    canonical_live_openapi = json.dumps(
        live_openapi,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    canonical_snapshot_openapi = json.dumps(
        snapshot_openapi,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    live_openapi_sha256 = hashlib.sha256(
        canonical_live_openapi
    ).hexdigest()
    snapshot_openapi_sha256 = hashlib.sha256(
        canonical_snapshot_openapi
    ).hexdigest()
    channel_paths = {
        path: sorted(operations)
        for path, operations in live_openapi.get("paths", {}).items()
        if path.startswith("/v1/channel-accounts")
    }

    payload = _json_payload(first)
    replay = _json_payload(second)
    control = payload.get("control_envelope")
    agent = payload.get("agent_artifact")
    control = control if isinstance(control, dict) else {}
    agent = agent if isinstance(agent, dict) else {}
    snapshot = payload.get("snapshot_sha256")
    replay_snapshot = replay.get("snapshot_sha256")
    deterministic = (
        isinstance(snapshot, str)
        and re.fullmatch(r"[0-9a-f]{64}", snapshot) is not None
        and snapshot == replay_snapshot
    )
    false_controls = {field: control.get(field) for field in FALSE_CONTROL_FIELDS}
    false_agent_permissions = {field: agent.get(field) for field in FALSE_AGENT_PERMISSION_FIELDS}
    result = {
        "anonymous": anonymous.status_code,
        "authenticated": first.status_code,
        "forbidden": forbidden.status_code,
        "readiness": readiness.status_code,
        "status": payload.get("status"),
        "total": (payload.get("counts", {}).get("total") if isinstance(payload.get("counts"), dict) else None),
        "channel_accounts": payload.get("channel_accounts"),
        "verified_native": payload.get("verified_native"),
        "native_implementation_status": payload.get("native_implementation_status"),
        "read_only_projection": control.get("read_only_projection"),
        "control_envelope": false_controls,
        "agent_permissions": false_agent_permissions,
        "deterministic": deterministic,
        "snapshot_sha256": snapshot if isinstance(snapshot, str) else None,
        "openapi_live_sha256": live_openapi_sha256,
        "openapi_snapshot_sha256": snapshot_openapi_sha256,
        "openapi_channel_paths": channel_paths,
        "openapi_matches_snapshot": (
            canonical_live_openapi == canonical_snapshot_openapi
        ),
    }
    expected = {
        "anonymous": 401,
        "authenticated": 200,
        "forbidden": 403,
        "readiness": 200,
        "status": "no_data",
        "total": 0,
        "channel_accounts": [],
        "verified_native": False,
        "native_implementation_status": "implemented_unverified",
        "read_only_projection": True,
        "deterministic": True,
        "openapi_matches_snapshot": True,
        "openapi_channel_paths": {
            "/v1/channel-accounts/workspace": ["get"],
        },
    }
    drift = [key for key, value in expected.items() if result.get(key) != value]
    drift.extend(f"control_envelope.{field}" for field, value in false_controls.items() if value is not False)
    drift.extend(f"agent_artifact.{field}" for field, value in false_agent_permissions.items() if value is not False)
    if drift:
        raise RuntimeError("BAS-158 runtime boundary drifted at: " + ", ".join(sorted(drift)))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
