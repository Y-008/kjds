from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values
from sqlalchemy import text

from apps.control_plane.database import create_database_engine


def main() -> None:
    values = {
        **dotenv_values(Path(__file__).resolve().parents[1] / ".env"),
        **os.environ,
    }
    api_key = str(values.get("KJDS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("KJDS_API_KEY is unavailable for runtime verification")
    base_url = str(
        values.get("KJDS_API_BASE_URL") or "http://127.0.0.1:8000"
    ).rstrip("/")
    headers = {"X-KJDS-API-Key": api_key}
    with httpx.Client(base_url=base_url, timeout=15) as client:
        anonymous = client.get("/v1/customer-service/workspace")
        authenticated = client.get(
            "/v1/customer-service/workspace",
            headers=headers,
        )
        forbidden = client.get(
            "/v1/customer-service/workspace",
            params={"store_ref": "__bas154_forbidden_store__"},
            headers=headers,
        )
        readiness = client.get("/health/ready")
    if anonymous.status_code != 401:
        raise RuntimeError("Anonymous customer-service request did not return 401")
    if authenticated.status_code != 200:
        raise RuntimeError(
            "Authenticated customer-service request did not return 200"
        )
    if forbidden.status_code != 403:
        raise RuntimeError("Cross-store customer-service request did not return 403")
    if readiness.status_code != 200:
        raise RuntimeError("API readiness did not return 200")
    payload = authenticated.json()
    if (
        payload.get("contract_id")
        != "kjds-native-exact-scope-customer-service-v1"
        or payload.get("status") != "no_data"
        or payload.get("cases") != []
        or payload.get("counts", {}).get("total_cases") != 0
        or payload.get("control_envelope", {}).get("scoped_input_read")
        is not False
        or payload.get("control_envelope", {}).get(
            "message_adapter_enabled"
        )
        is not False
        or payload.get("control_envelope", {}).get(
            "external_write_allowed"
        )
        is not False
        or payload.get("control_envelope", {}).get(
            "private_erp_interface_allowed"
        )
        is not False
        or payload.get("privacy_envelope", {}).get(
            "raw_message_body_exposed"
        )
        is not False
        or payload.get("agent_artifact", {}).get("self_approval_allowed")
        is not False
        or payload.get("agent_artifact", {}).get("permit_issue_allowed")
        is not False
    ):
        raise RuntimeError(
            "Customer-service runtime truth or control envelope drifted"
        )
    engine = create_database_engine()
    with engine.connect() as connection:
        database = dict(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(1) FROM customer_service_cases) AS cases, "
                    "(SELECT count(1) FROM customer_service_events) AS events, "
                    "(SELECT version_num FROM alembic_version) AS head"
                )
            )
            .mappings()
            .one()
        )
    if database != {
        "cases": 0,
        "events": 0,
        "head": "20260730_0079",
    }:
        raise RuntimeError("BAS-154 PostgreSQL runtime state drifted")
    print(
        json.dumps(
            {
                "anonymous": anonymous.status_code,
                "authenticated": authenticated.status_code,
                "forbidden": forbidden.status_code,
                "readiness": readiness.status_code,
                "status": payload["status"],
                "total_cases": payload["counts"]["total_cases"],
                "scoped_input_read": payload["control_envelope"][
                    "scoped_input_read"
                ],
                "message_adapter_enabled": payload["control_envelope"][
                    "message_adapter_enabled"
                ],
                "external_write_allowed": payload["control_envelope"][
                    "external_write_allowed"
                ],
                "private_erp_interface_allowed": payload["control_envelope"][
                    "private_erp_interface_allowed"
                ],
                "raw_message_body_exposed": payload["privacy_envelope"][
                    "raw_message_body_exposed"
                ],
                "database": database,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
