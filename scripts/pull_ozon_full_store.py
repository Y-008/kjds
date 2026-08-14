"""Pull the full Ozon store picture (read-only): catalog, info, analytics, finance."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
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
    client_id = env.get("OZON_CLIENT_ID", "").strip()
    api_key = env.get("OZON_API_KEY", "").strip()
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }
    OUT.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url="https://api-seller.ozon.ru", headers=headers, timeout=60) as client:
        # 1) Full catalog list
        catalog: list[dict] = []
        last_id = ""
        for _round in range(50):
            resp = client.post("/v3/product/list", json={"filter": {}, "limit": 1000, "last_id": last_id})
            if resp.status_code != 200:
                print(f"/v3/product/list round {_round}: HTTP {resp.status_code} {resp.text[:200]}")
                break
            value = resp.json()
            items = value.get("result", {}).get("items", [])
            catalog.extend(items)
            last_id = value.get("result", {}).get("last_id") or ""
            if not items or not last_id:
                break
            time.sleep(0.25)
        save("full_catalog.json", catalog)
        print(f"full_catalog: {len(catalog)} items")

        offer_ids = sorted({str(i.get("offer_id", "")) for i in catalog if i.get("offer_id")})
        print(f"unique offer_ids: {len(offer_ids)}")

        # 2) Full product info in chunks
        info_all: list[dict] = []
        for start in range(0, len(offer_ids), 100):
            chunk = offer_ids[start : start + 100]
            resp = client.post(
                "/v3/product/info/list",
                json={"offer_id": chunk, "product_id": [], "sku": [], "limit": 100},
            )
            if resp.status_code != 200:
                print(f"/v3/product/info/list chunk {start}: HTTP {resp.status_code} {resp.text[:200]}")
                continue
            info_all.extend(resp.json().get("items", []))
            time.sleep(0.25)
        save("full_product_info.json", info_all)
        print(f"full_product_info: {len(info_all)} items")

        # sample field inspection
        if info_all:
            sample = info_all[0]
            print("sample info keys:", sorted(sample.keys()))
            for key in ("price", "old_price", "min_price", "price_index", "stocks", "status", "errors", "images", "sources", "vat"):
                if key in sample:
                    print(f"  {key}: {json.dumps(sample[key], ensure_ascii=False)[:200]}")

        # 3) Full analytics with totals+errors
        analytics_raw: list[dict] = []
        windows = [
            ("2025-08-01", "2026-01-27"),
            ("2026-01-28", "2026-08-01"),
        ]
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
            if resp.status_code != 200:
                print(f"/v1/analytics/data {window_from}: HTTP {resp.status_code} {resp.text[:300]}")
                continue
            value = resp.json()
            analytics_raw.append({"window": [window_from, window_to], "response": value})
            print(f"analytics {window_from}: data={len(value.get('result', {}).get('data', []))} errors={value.get('result', {}).get('errors')}")
            time.sleep(0.25)
        save("full_analytics.json", analytics_raw)

        # 4) Finance all months with raw bodies
        finance_raw: list[dict] = []
        cursor = datetime(2025, 8, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        while cursor < end:
            window_end = min(cursor + timedelta(days=31), end)
            resp = client.post(
                "/v3/finance/transaction/list",
                json={
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
                },
            )
            if resp.status_code != 200:
                finance_raw.append({"window": [cursor.isoformat(), window_end.isoformat()], "status": resp.status_code, "body": resp.text[:500]})
                print(f"finance {cursor.date()}: HTTP {resp.status_code} {resp.text[:200]}")
                cursor = window_end
                time.sleep(0.3)
                continue
            value = resp.json()
            ops = value.get("result", {}).get("operations", [])
            finance_raw.append({"window": [cursor.isoformat(), window_end.isoformat()], "status": 200, "operation_count": len(ops), "result": value.get("result")})
            print(f"finance {cursor.date()}: {len(ops)} operations")
            cursor = window_end
            time.sleep(0.3)
        save("full_finance.json", finance_raw)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
