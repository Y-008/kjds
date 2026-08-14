"""Read-only full Ozon Seller API probe for market reconnaissance (KJDS).

Pulls every read-only data class the official Seller API exposes for the
store: product list, prices (+ price index), offer state, product info,
attributes, content rating, analytics metrics, warehouse stock, finance
transactions.  Never prints or stores Client-Id / Api-Key material.  Writes
raw JSON artifacts under output/market_recon/.

Usage:
  uv run python scripts/probe_ozon_full_market.py
"""

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

from apps.control_plane.ozon_worker import (  # noqa: E402
    OzonApiError,
    OzonCredentials,
    OzonSellerClient,
)


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


def _summary_label(value: dict) -> str:
    keys = list(value.keys())[:8]
    return ",".join(keys)


def _save(name: str, payload) -> Path:
    target = OUT / name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def probe(path: str, body: dict, client: OzonSellerClient, name: str) -> dict:
    started = time.time()
    try:
        value, capture = client._read_with_capture(path, body)
        _save(f"raw_{name}.json", {"path": path, "response": value})
        return {
            "name": name,
            "path": path,
            "status": "ok",
            "elapsed_s": round(time.time() - started, 2),
            "keys": _summary_label(value),
            "capture_status": capture.get("status_code"),
        }
    except OzonApiError as exc:
        return {
            "name": name,
            "path": path,
            "status": "error",
            "elapsed_s": round(time.time() - started, 2),
            "code": exc.code,
            "http_status": getattr(exc, "status_code", None),
            "message": str(exc)[:240],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "path": path,
            "status": "exception",
            "elapsed_s": round(time.time() - started, 2),
            "message": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def paginate_list(path: str, body: dict, client: OzonSellerClient, limit_key: str = "limit") -> list[dict]:
    items: list[dict] = []
    last_id = None
    for _round in range(20):
        payload = dict(body)
        payload[limit_key] = 1000
        if last_id is not None:
            payload["last_id"] = last_id
        value, _ = client._read_with_capture(path, payload)
        result = value.get("result", {})
        batch = result.get("items") or []
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 1000:
            break
        last_id = result.get("last_id")
        if last_id in (None, ""):
            break
    return items


def main() -> int:
    env = load_env()
    client_id = env.get("OZON_CLIENT_ID", "").strip()
    api_key = env.get("OZON_API_KEY", "").strip()
    if not client_id or not api_key:
        print("OZON_CLIENT_ID / OZON_API_KEY are required in .env")
        return 1
    credentials = OzonCredentials.for_readback_probe(client_id=client_id, api_key=api_key)
    client = OzonSellerClient(credentials=credentials, readback_probe_allowed=True)

    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    print("== probe: /v2/product/list (full catalog) ==")
    try:
        products = paginate_list("/v2/product/list", {"filter": {}}, client)
        _save("products.json", products)
        results.append({"name": "products", "path": "/v2/product/list", "status": "ok", "count": len(products)})
        print(f"  products: {len(products)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "products", "path": "/v2/product/list", "status": "error", "message": str(exc)[:240]})
        print(f"  products error: {str(exc)[:200]}")
        products = []

    offer_ids = sorted({str(p.get("offer_id", "")) for p in products if p.get("offer_id")})
    product_ids = sorted({str(p.get("product_id", "")) for p in products if p.get("product_id")})
    print(f"  offer_ids: {len(offer_ids)} product_ids: {len(product_ids)}")

    print("== probe: /v1/product/info/prices ==")
    try:
        prices = paginate_list(
            "/v1/product/info/prices",
            {"filter": {"product_id": [], "offer_id": [], "visibility": "ALL"}},
            client,
        )
        _save("prices.json", prices)
        results.append({"name": "prices", "path": "/v1/product/info/prices", "status": "ok", "count": len(prices)})
        print(f"  prices: {len(prices)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "prices", "path": "/v1/product/info/prices", "status": "error", "message": str(exc)[:240]})
        print(f"  prices error: {str(exc)[:200]}")

    print("== probe: /v1/product/info/offer-state ==")
    try:
        value, _ = client._read_with_capture(
            "/v1/product/info/offer-state",
            {"offer_id": [], "product_id": [], "sku": []},
        )
        _save("offer_state.json", value)
        items = value.get("result", {}).get("items", [])
        results.append({"name": "offer_state", "path": "/v1/product/info/offer-state", "status": "ok", "count": len(items)})
        print(f"  offer_state: {len(items)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "offer_state", "path": "/v1/product/info/offer-state", "status": "error", "message": str(exc)[:240]})
        print(f"  offer_state error: {str(exc)[:200]}")

    print("== probe: /v3/product/info/list ==")
    try:
        info = paginate_list(
            "/v3/product/info/list",
            {"product_id": [], "offer_id": [], "sku": []},
            client,
        )
        _save("product_info.json", info)
        results.append({"name": "product_info", "path": "/v3/product/info/list", "status": "ok", "count": len(info)})
        print(f"  product_info: {len(info)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "product_info", "path": "/v3/product/info/list", "status": "error", "message": str(exc)[:240]})
        print(f"  product_info error: {str(exc)[:200]}")
        info = []

    print("== probe: /v4/product/info/attributes ==")
    attributes_all: list[dict] = []
    for chunk_start in range(0, len(offer_ids), 100):
        chunk = offer_ids[chunk_start : chunk_start + 100]
        try:
            value, _ = client._read_with_capture(
                "/v4/product/info/attributes",
                {"filter": {"offer_id": chunk, "visibility": "ALL"}, "limit": 1000, "sort_dir": "ASC"},
            )
            attributes_all.extend(value.get("result", {}).get("items", []))
        except Exception as exc:  # noqa: BLE001
            results.append({"name": "attributes", "path": "/v4/product/info/attributes", "status": "error", "message": str(exc)[:240]})
            print(f"  attributes error: {str(exc)[:200]}")
            break
    _save("attributes.json", attributes_all)
    results.append({"name": "attributes", "path": "/v4/product/info/attributes", "status": "ok", "count": len(attributes_all)})
    print(f"  attributes: {len(attributes_all)}")

    print("== probe: /v1/product/info/description ==")
    try:
        value, _ = client._read_with_capture(
            "/v1/product/info/description",
            {"product_id": [], "offer_id": [], "limit": 1000},
        )
        _save("descriptions.json", value)
        items = value.get("result", {}).get("items", [])
        results.append({"name": "descriptions", "path": "/v1/product/info/description", "status": "ok", "count": len(items)})
        print(f"  descriptions: {len(items)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "descriptions", "path": "/v1/product/info/description", "status": "error", "message": str(exc)[:240]})
        print(f"  descriptions error: {str(exc)[:200]}")

    print("== probe: /v1/product/rating-by-sku ==")
    try:
        skus = [int(i.get("id")) for i in info if str(i.get("id", "")).isdigit()][:100]
        value, _ = client._read_with_capture("/v1/product/rating-by-sku", {"skus": skus})
        _save("rating_by_sku.json", value)
        items = value.get("result", {}).get("items", [])
        results.append({"name": "rating_by_sku", "path": "/v1/product/rating-by-sku", "status": "ok", "count": len(items)})
        print(f"  rating_by_sku: {len(items)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "rating_by_sku", "path": "/v1/product/rating-by-sku", "status": "error", "message": str(exc)[:240]})
        print(f"  rating_by_sku error: {str(exc)[:200]}")

    print("== probe: /v1/analytics/price-index ==")
    try:
        value, _ = client._read_with_capture(
            "/v1/analytics/price-index",
            {"items": [{"offer_id": oid} for oid in offer_ids[:100]]},
        )
        _save("price_index.json", value)
        results.append({"name": "price_index", "path": "/v1/analytics/price-index", "status": "ok", "keys": _summary_label(value)})
        print(f"  price_index: {_summary_label(value)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "price_index", "path": "/v1/analytics/price-index", "status": "error", "message": str(exc)[:240]})
        print(f"  price_index error: {str(exc)[:200]}")

    print("== probe: /v1/analytics/data ==")
    try:
        windows = [
            ("2025-08-01", "2026-01-27"),
            ("2026-01-28", "2026-08-01"),
        ]
        analytics_all: list[dict] = []
        for window_from, window_to in windows:
            value, _ = client._read_with_capture(
                "/v1/analytics/data",
                {
                    "date_from": window_from,
                    "date_to": window_to,
                    "metrics": [
                        "ordered_units",
                        "ordered_units_past",
                        "revenue",
                        "revenue_past",
                        "adv_view_pdp_events",
                        "conversion_to_order",
                        "position_category",
                    ],
                    "dimension": ["sku"],
                    "filters": [],
                    "sort": [{"key": "sku", "order": "ASC"}],
                    "limit": 1000,
                    "offset": 0,
                },
            )
            analytics_all.extend(value.get("result", {}).get("data", []))
        _save("analytics_data.json", analytics_all)
        results.append({"name": "analytics_data", "path": "/v1/analytics/data", "status": "ok", "count": len(analytics_all)})
        print(f"  analytics_data: {len(analytics_all)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "analytics_data", "path": "/v1/analytics/data", "status": "error", "message": str(exc)[:240]})
        print(f"  analytics_data error: {str(exc)[:200]}")

    print("== probe: /v1/analytics/stock-on-warehouses ==")
    try:
        value, _ = client._read_with_capture("/v1/analytics/stock-on-warehouses", {"warehouse_id": []})
        _save("stock_on_warehouses.json", value)
        rows = value.get("result", {}).get("rows", [])
        results.append({"name": "stock_on_warehouses", "path": "/v1/analytics/stock-on-warehouses", "status": "ok", "count": len(rows)})
        print(f"  stock_on_warehouses: {len(rows)}")
    except Exception as exc:  # noqa: BLE001
        results.append({"name": "stock_on_warehouses", "path": "/v1/analytics/stock-on-warehouses", "status": "error", "message": str(exc)[:240]})
        print(f"  stock_on_warehouses error: {str(exc)[:200]}")

    print("== probe: /v3/finance/transaction/list (monthly windows) ==")
    finance_count = 0
    cursor = datetime(2025, 8, 1, tzinfo=UTC)
    end = datetime(2026, 8, 1, tzinfo=UTC)
    while cursor < end:
        window_end = min(cursor + timedelta(days=31), end)
        try:
            result = client.finance_transactions(
                date_from=cursor.isoformat(),
                date_to=window_end.isoformat(),
                page=1,
                page_size=1000,
            )
            finance_count += result["operation_count"]
        except Exception as exc:  # noqa: BLE001
            results.append({"name": "finance", "path": "/v3/finance/transaction/list", "status": "error", "message": str(exc)[:240]})
            print(f"  finance error @ {cursor.date()}: {str(exc)[:200]}")
            break
        cursor = window_end
        time.sleep(0.3)
    results.append({"name": "finance", "path": "/v3/finance/transaction/list", "status": "ok", "count": finance_count})
    print(f"  finance operations: {finance_count}")

    client.close()
    _save("probe_summary.json", {"generated_at": datetime.now(UTC).isoformat(), "results": results})
    print("== done ==")
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
