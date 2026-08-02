"""Diagnose Ozon endpoint errors: dump full status/body (no secrets)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def main() -> int:
    env = load_env()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        print(f"{var}={env.get(var) or os.environ.get(var) or ''}")
    client_id = env.get("OZON_CLIENT_ID", "").strip()
    api_key = env.get("OZON_API_KEY", "").strip()
    base = "https://api-seller.ozon.ru"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }
    cases = [
        ("/v2/product/list", {"filter": {}, "limit": 10}),
        ("/v1/product/info/prices", {"filter": {"product_id": [], "offer_id": [], "visibility": "ALL"}, "limit": 10}),
        ("/v1/product/info/offer-state", {"offer_id": [], "product_id": [], "sku": []}),
        ("/v3/product/info/list", {"product_id": [], "offer_id": [], "sku": [], "limit": 10}),
        ("/v1/product/info/description", {"product_id": [], "offer_id": [], "limit": 10}),
        ("/v1/product/rating-by-sku", {"skus": []}),
        ("/v1/analytics/stock-on-warehouses", {"warehouse_id": []}),
        ("/v1/analytics/price-index", {"items": []}),
        ("/v3/finance/transaction/list", {
            "filter": {"date": {"from": "2025-09-01T00:00:00Z", "to": "2025-10-01T00:00:00Z"}, "operation_type": [], "posting_number": "", "transaction_type": "all"},
            "page": 1,
            "page_size": 10,
        }),
    ]
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        for path, body in cases:
            try:
                resp = client.post(path, json=body)
                text = resp.text[:600]
                print(f"--- {path} -> {resp.status_code}")
                print(text)
            except Exception as exc:  # noqa: BLE001
                print(f"--- {path} -> EXC {type(exc).__name__}: {str(exc)[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
