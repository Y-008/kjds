from __future__ import annotations

import json
import os

import httpx
from dotenv import dotenv_values


def main() -> None:
    values = {**dotenv_values(".env"), **os.environ}
    mapping = json.loads(str(values["KJDS_API_KEYS_JSON"]))
    allowed = next(
        key
        for key, profile in mapping.items()
        if "ozon-primary" in profile.get("stores", ["ozon-primary"])
    )
    denied = next(
        (
            key
            for key, profile in mapping.items()
            if "ozon-primary"
            not in profile.get("stores", ["ozon-primary"])
        ),
        None,
    )
    path = (
        "/v1/warehouse-fulfillment/workspace"
        "?store_ref=ozon-primary"
        "&warehouse_ref=warehouse-cn-1"
        "&as_of=2026-07-30T01:00:00%2B00:00"
    )
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=30,
    ) as client:
        anonymous = client.get(path)
        first = client.get(
            path,
            headers={"X-KJDS-API-Key": allowed},
        )
        second = client.get(
            path,
            headers={"X-KJDS-API-Key": allowed},
        )
        forbidden = (
            client.get(path, headers={"X-KJDS-API-Key": denied})
            if denied
            else client.get(
                "/v1/warehouse-fulfillment/workspace"
                "?store_ref=forbidden-store"
                "&warehouse_ref=warehouse-cn-1",
                headers={"X-KJDS-API-Key": allowed},
            )
        )
        readiness = client.get("/health/ready")
    payload = first.json() if first.status_code == 200 else {}
    replay = second.json() if second.status_code == 200 else {}
    result = {
        "anonymous": anonymous.status_code,
        "authenticated": first.status_code,
        "forbidden": forbidden.status_code,
        "readiness": readiness.status_code,
        "status": payload.get("status"),
        "total": payload.get("counts", {}).get("total"),
        "upstream_reads": payload.get("control_envelope", {}).get(
            "upstream_reads"
        ),
        "external_write_allowed": payload.get(
            "control_envelope",
            {},
        ).get("external_write_allowed"),
        "private_erp_interface_allowed": payload.get(
            "control_envelope",
            {},
        ).get("private_erp_interface_allowed"),
        "deterministic": payload.get("snapshot_sha256")
        == replay.get("snapshot_sha256"),
        "snapshot_sha256": payload.get("snapshot_sha256"),
    }
    expected = {
        "anonymous": 401,
        "authenticated": 200,
        "forbidden": 403,
        "readiness": 200,
        "status": "no_data",
        "total": 0,
        "upstream_reads": [],
        "external_write_allowed": False,
        "private_erp_interface_allowed": False,
        "deterministic": True,
    }
    if any(
        result.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeError(
            f"BAS-157 runtime boundary drifted: {result}"
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
