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
PATH = "/v1/native-parity-acceptance/workspace"
STORE = "ozon-primary"
ROLES = {"operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin"}
FALSE_CONTROLS = {
    "client_can_recalculate_or_promote",
    "mapping_is_implementation",
    "engineering_done_is_verified_native",
    "self_certification_allowed",
    "business_fact_created",
    "approval_created",
    "permit_created",
    "credential_created_or_read",
    "external_write_allowed",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _profiles(raw: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, str):
        raise RuntimeError("KJDS_API_KEYS_JSON is required")
    value = json.loads(raw)
    if not isinstance(value, dict) or not value:
        raise RuntimeError("KJDS_API_KEYS_JSON must be a non-empty object")
    return value


def _stores(profile: dict[str, Any]) -> set[str]:
    value = profile.get("stores", [STORE])
    return {str(item) for item in value} if isinstance(value, list) else set()


def _roles(profile: dict[str, Any]) -> set[str]:
    value = profile.get("roles", [])
    return {str(item) for item in value} if isinstance(value, list) else set()


def _payload(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        return {}
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("BAS-159 runtime response must be an object")
    return value


def main() -> None:
    values = {**dotenv_values(ROOT / ".env"), **os.environ}
    profiles = _profiles(values.get("KJDS_API_KEYS_JSON"))
    allowed = next(
        (key for key, profile in profiles.items() if STORE in _stores(profile) and _roles(profile) & ROLES),
        None,
    )
    if allowed is None:
        raise RuntimeError("No permitted BAS-159 exact-store identity")
    denied = next((key for key, profile in profiles.items() if STORE not in _stores(profile)), None)
    as_of = str(values.get("BAS159_RUNTIME_AS_OF") or "2026-08-01T12:00:00+00:00")
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise RuntimeError("BAS159_RUNTIME_AS_OF must include timezone")
    params = {"store_ref": STORE, "as_of": cutoff.astimezone(UTC).isoformat()}
    base_url = str(values.get("BAS159_API_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    headers = {"X-KJDS-API-Key": allowed}
    with httpx.Client(base_url=base_url, timeout=30) as client:
        anonymous = client.get(PATH, params=params)
        first = client.get(PATH, params=params, headers=headers)
        second = client.get(PATH, params=params, headers=headers)
        forbidden = client.get(
            PATH,
            params={"store_ref": "bas159-forbidden-store", "as_of": params["as_of"]},
            headers={"X-KJDS-API-Key": denied or allowed},
        )
        ready = client.get("/health/ready")
        live_openapi = client.get("/openapi.json")

    payload = _payload(first)
    replay = _payload(second)
    snapshot = payload.get("snapshot_sha256")
    control = payload.get("control_envelope") if isinstance(payload.get("control_envelope"), dict) else {}
    live_schema = live_openapi.json()
    snapshot_schema = json.loads((ROOT / "docs/project/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    paths = {
        path: sorted(operations)
        for path, operations in live_schema.get("paths", {}).items()
        if path.startswith("/v1/native-parity-acceptance")
    }
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    states = counts.get("states") if isinstance(counts.get("states"), dict) else {}
    result = {
        "anonymous": anonymous.status_code,
        "authenticated": first.status_code,
        "forbidden": forbidden.status_code,
        "readiness": ready.status_code,
        "status": payload.get("status"),
        "entity_ref": payload.get("scope", {}).get("entity_ref"),
        "items": counts.get("items"),
        "verified_native": states.get("verified_native"),
        "deterministic": snapshot == replay.get("snapshot_sha256")
        and bool(re.fullmatch(r"[0-9a-f]{64}", str(snapshot))),
        "snapshot_sha256": snapshot,
        "control_envelope": {field: control.get(field) for field in sorted(FALSE_CONTROLS)},
        "openapi_paths": paths,
        "openapi_matches_snapshot": _canonical(live_schema) == _canonical(snapshot_schema),
        "openapi_sha256": hashlib.sha256(_canonical(live_schema)).hexdigest(),
    }
    expected = {
        "anonymous": 401,
        "authenticated": 200,
        "forbidden": 403,
        "readiness": 200,
        "status": "no_data",
        "entity_ref": None,
        "items": 0,
        "verified_native": 0,
        "deterministic": True,
        "openapi_paths": {PATH: ["get"]},
        "openapi_matches_snapshot": True,
    }
    drift = [key for key, value in expected.items() if result.get(key) != value]
    drift.extend(field for field in FALSE_CONTROLS if control.get(field) is not False)
    if drift:
        raise RuntimeError("BAS-159 runtime drift: " + ", ".join(sorted(drift)))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
