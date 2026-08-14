"""Probe candidate Ozon Seller API paths with and without the local proxy."""

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
    client_id = env.get("OZON_CLIENT_ID", "").strip()
    api_key = env.get("OZON_API_KEY", "").strip()
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }
    cases = [
        ("/v2/product/list", {"filter": {}, "limit": 100}),
        ("/v3/product/list", {"filter": {}, "limit": 100}),
        ("/v1/product/list", {"filter": {}, "limit": 100}),
        ("/v1/product/info/prices", {"filter": {"product_id": [], "offer_id": [], "visibility": "ALL"}, "limit": 100}),
        ("/v1/product/info/offer-state", {"offer_id": ["2105343364UB"], "product_id": [], "sku": []}),
        ("/v3/product/info/list", {"offer_id": ["2105343364UB"], "product_id": [], "sku": [], "limit": 100}),
        ("/v1/analytics/stock_on_warehouses", {"warehouse_id": []}),
        ("/v1/analytics/price-index", {"items": [{"offer_id": "2105343364UB"}]}),
        ("/v2/product/info", {"offer_id": "2105343364UB", "product_id": "", "sku": 0}),
    ]
    for proxy_label, trust_env in (("proxy=on", True), ("proxy=off", False)):
        print(f"##### {proxy_label} #####")
        with httpx.Client(base_url="https://api-seller.ozon.ru", headers=headers, timeout=30, trust_env=trust_env) as client:
            for path, body in cases:
                try:
                    resp = client.post(path, json=body)
                    text = resp.text[:300].replace("\n", " ")
                    print(f"{path} -> {resp.status_code} | {text}")
                except Exception as exc:  # noqa: BLE001
                    print(f"{path} -> EXC {type(exc).__name__}: {str(exc)[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
