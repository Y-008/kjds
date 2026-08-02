"""Pull Ozon finance (calendar months), analytics (both windows), attributes."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "market_recon"
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def save(name: str, payload) -> Path:
    target = OUT / name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    env = load_env()
    headers = {
        "Client-Id": env.get("OZON_CLIENT_ID", "").strip(),
        "Api-Key": env.get("OZON_API_KEY", "").strip(),
        "Content-Type": "application/json",
    }
    OUT.mkdir(parents=True, exist_ok=True)

    catalog = json.loads((OUT / "full_catalog.json").read_text(encoding="utf-8"))
    offer_ids = sorted({str(i.get("offer_id", "")) for i in catalog if i.get("offer_id")})

    with httpx.Client(base_url="https://api-seller.ozon.ru", headers=headers, timeout=60) as client:
        # --- finance: one calendar month per window ---
        finance_all: list[dict] = []
        cursor = datetime(2025, 8, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        while cursor < end:
            if cursor.month == 12:
                window_end = datetime(cursor.year + 1, 1, 1, tzinfo=UTC)
            else:
                window_end = datetime(cursor.year, cursor.month + 1, 1, tzinfo=UTC)
            body = {
                "filter": {
                    "date": {
                        "from": cursor.isoformat().replace("+00:00", "Z"),
                        "to": window_end.isoformat().replace("+00:00", "Z"),
                    },
                    "operation_type": [],
                    "posting_number": "",
                    "transaction_type": "all",
                },
                "page": 1,
                "page_size": 1000,
            }
            resp = client.post("/v3/finance/transaction/list", json=body)
            if resp.status_code == 200:
                value = resp.json()
                ops = value.get("result", {}).get("operations", [])
                finance_all.append({"month": cursor.strftime("%Y-%m"), "operation_count": len(ops), "operations": ops})
                print(f"finance {cursor.strftime('%Y-%m')}: {len(ops)} ops")
            else:
                finance_all.append({"month": cursor.strftime("%Y-%m"), "status": resp.status_code, "body": resp.text[:300]})
                print(f"finance {cursor.strftime('%Y-%m')}: HTTP {resp.status_code} {resp.text[:160]}")
            cursor = window_end
            time.sleep(0.6)
        save("finance_by_month.json", finance_all)

        # --- analytics both windows, rate-limit friendly ---
        analytics_all: list[dict] = []
        windows = [("2025-08-01", "2026-01-27"), ("2026-01-28", "2026-08-01")]
        metrics = [
            "ordered_units",
            "ordered_units_past",
            "revenue",
            "revenue_past",
            "adv_view_pdp_events",
            "adv_view_pdp_events_past",
            "conversion_to_order",
            "conversion_to_order_past",
            "position_category",
            "position_category_past",
            "cancelled_units",
            "cancelled_units_past",
        ]
        for window_from, window_to in windows:
            for attempt in range(6):
                resp = client.post(
                    "/v1/analytics/data",
                    json={
                        "date_from": window_from,
                        "date_to": window_to,
                        "metrics": metrics,
                        "dimension": ["sku"],
                        "filters": [],
                        "sort": [{"key": "sku", "order": "ASC"}],
                        "limit": 1000,
                        "offset": 0,
                    },
                )
                if resp.status_code == 200:
                    value = resp.json()
                    analytics_all.append({"window": [window_from, window_to], "response": value})
                    print(f"analytics {window_from}: data={len(value.get('result', {}).get('data', []))} errors={value.get('result', {}).get('errors')}")
                    break
                print(f"analytics {window_from} attempt {attempt}: HTTP {resp.status_code} {resp.text[:120]}")
                time.sleep(8)
            time.sleep(1.5)
        save("analytics_by_window.json", analytics_all)

        # --- attributes for all offer_ids ---
        attrs_all: list[dict] = []
        for start in range(0, len(offer_ids), 50):
            chunk = offer_ids[start : start + 50]
            resp = client.post(
                "/v4/product/info/attributes",
                json={"filter": {"offer_id": chunk, "visibility": "ALL"}, "limit": 1000, "sort_dir": "ASC"},
            )
            if resp.status_code == 200:
                value = resp.json()
                result = value.get("result")
                if isinstance(result, list):
                    items = result
                else:
                    items = result.get("items", []) if isinstance(result, dict) else []
                attrs_all.extend(items)
                print(f"attributes chunk {start}: {len(items)} items")
            else:
                print(f"attributes chunk {start}: HTTP {resp.status_code} {resp.text[:160]}")
            time.sleep(0.6)
        save("attributes_full.json", attrs_all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
