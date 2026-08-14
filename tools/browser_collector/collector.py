"""Local data hub for the KJDS browser extension.

- POST /capture        : store extension page captures under output/browser_capture/
- GET  /data/supply    : 1688 supply stats for a keyword
- GET  /data/match     : match a Russian product title to 1688 supply + margin estimate
- GET  /data/catalog   : our Ozon catalog rows (operational data + landed cost)
- GET  /health         : status

Binds 127.0.0.1 only.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "browser_capture"
RECON = ROOT / "output" / "market_recon"
SUPPLY_FILE = RECON / "supply_1688" / "supply_crawl.json"
CATALOG_FILE = RECON / "per_sku_analysis.json"

RUB_PER_CNY = 12.8
_LOCK = threading.Lock()
_SUPPLY_CACHE: dict | None = None
_SUPPLY_MTIME: float | None = None
_ONDEMAND_DONE: set[str] = set()
_CRAWL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
_PLACEHOLDER_CATS = {"暂无数据", "暂无", "其他", "其它", "其他分类"}

KEYWORD_PATTERNS: list[tuple[str, str]] = [
    ("пылесос", "车载吸尘器"),
    ("триммер", "鼻毛修剪器"),
    ("для носа", "鼻毛修剪器"),
    ("мясорубк", "家用绞肉机"),
    ("измельчител", "家用绞肉机"),
    ("держатель для телефона", "手机吸盘支架"),
    ("присоск", "手机吸盘支架"),
    ("кровать-кресло", "折叠躺椅床"),
    ("раскладушк", "折叠躺椅床"),
    ("шезлонг", "折叠躺椅床"),
    ("накидк", "沙滩罩衫"),
    ("пляжн", "沙滩罩衫"),
    ("сарафан", "沙滩裙"),
    ("платье", "沙滩裙"),
    ("подъемник", "500kg电动葫芦吊"),
    ("таль", "500kg电动葫芦吊"),
    ("лебедк", "PA系列电动葫芦"),
    ("hoist", "500kg电动葫芦吊"),
    ("цепная", "锂电电锯"),
    ("пила", "锂电电锯"),
    ("палатк", "双人帐篷"),
    ("стремянк", "钢制折叠梯"),
    ("лестниц", "钢制折叠梯"),
    ("помад", "变色唇膏"),
    ("губная", "变色唇膏"),
    ("ванна", "婴儿浴盆"),
    ("биткоин", "比特币硬币"),
    ("makita", "牧田DHR182电锤"),
    ("макита", "牧田DHR182电锤"),
    ("смесител", "水龙头"),
    ("лазерн", "激光水平仪"),
    ("уровень", "激光水平仪"),
    ("моторн", "发动机油"),
    ("масло", "发动机油"),
    ("для волос", "发膜"),
    ("маска", "发膜"),
    ("очистител", "清洁剂"),
]

KEYWORD_WEIGHT: dict[str, float] = {
    "车载吸尘器": 0.8,
    "鼻毛修剪器": 0.2,
    "家用绞肉机": 1.2,
    "手机吸盘支架": 0.1,
    "折叠躺椅床": 8.0,
    "沙滩罩衫": 0.2,
    "沙滩裙": 0.25,
    "500kg电动葫芦吊": 10.0,
    "PA系列电动葫芦": 8.0,
    "锂电电锯": 1.8,
    "双人帐篷": 2.0,
    "钢制折叠梯": 4.0,
    "变色唇膏": 0.1,
    "婴儿浴盆": 0.8,
    "牧田DHR182电锤": 3.5,
    "水龙头": 0.6,
    "激光水平仪": 1.0,
    "发动机油": 1.0,
    "发膜": 0.3,
    "清洁剂": 0.3,
}


def _load_supply() -> dict:
    global _SUPPLY_CACHE, _SUPPLY_MTIME
    mtime = SUPPLY_FILE.stat().st_mtime if SUPPLY_FILE.exists() else None
    if _SUPPLY_CACHE is None or mtime != _SUPPLY_MTIME:
        _SUPPLY_CACHE = json.loads(SUPPLY_FILE.read_text(encoding="utf-8")) if SUPPLY_FILE.exists() else {}
        _SUPPLY_MTIME = mtime
    return _SUPPLY_CACHE


def _save_supply(supply: dict) -> None:
    global _SUPPLY_CACHE
    SUPPLY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUPPLY_FILE.write_text(json.dumps(supply, ensure_ascii=False, indent=2), encoding="utf-8")
    _SUPPLY_CACHE = supply


def _keyword_hash(keyword: str) -> str:
    ascii_parts: list[str] = []
    cjk_parts: list[str] = []
    for ch in keyword:
        if ord(ch) < 128:
            ascii_parts.append(ch)
        else:
            cjk_parts.append(ch)
    encoded = ""
    if ascii_parts:
        encoded += "".join(ascii_parts).encode("utf-8").hex().upper()
    if cjk_parts:
        encoded += "".join(cjk_parts).encode("gbk", errors="replace").hex().upper()
    return encoded


def _fetch_1688(url: str) -> str:
    req = urllib.request.Request(url, headers=_CRAWL_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    for enc in ("utf-8", "big5", "gbk"):
        try:
            body = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        body = raw.decode("utf-8", errors="replace")
    if len(body) < 20000:
        raise RuntimeError(f"short page {len(body)}")
    return body


def _parse_1688_cards(html: str) -> list[dict]:
    cards: list[dict] = []
    for m in re.finditer(
        r'<li[^>]*offerId="(\d+)"[^>]*class="([^"]*sm-offerShopwindow[^"]*)"[^>]*>(.*?)</li>',
        html,
        re.S,
    ):
        body = m.group(3)
        rank_m = re.search(r'rank="(\d+)"', m.group(0))
        city_m = re.search(r'<span class="su-city">([^<]+)</span>', body)
        shop_m = re.search(r"alitalk='[^']*\"id\":\"([^\"]+)\"", body)
        img_m = re.search(r'<img[^>]*alt="([^"]+)"', body)
        price_m = re.search(r'<span class="su-price">(?:<[^>]+>[^<]*</[^>]+>)?\s*([0-9][0-9.,]*)', body)
        sales_m = re.search(r"成交\s*([\d.]+)\s*(台|件|套|个|只|箱|批|双|盒)", body)
        cards.append(
            {
                "rank": int(rank_m.group(1)) if rank_m else None,
                "offer_id": m.group(1),
                "title": img_m.group(1).strip() if img_m else "",
                "region": city_m.group(1).strip() if city_m else "",
                "shop": shop_m.group(1).strip() if shop_m else "",
                "price": price_m.group(1).strip() if price_m else "",
                "sales_volume": float(sales_m.group(1)) if sales_m else 0.0,
                "sales_unit": sales_m.group(2) if sales_m else "",
            }
        )
        if len(cards) >= 80:
            break
    return cards


def _crawl_keyword(keyword: str) -> str | None:
    """Fetch 1688 supply data for one keyword and merge it into the cache."""
    if not keyword or keyword in _ONDEMAND_DONE:
        return keyword if keyword in _load_supply() else None
    with _LOCK:
        if keyword in _ONDEMAND_DONE:
            return keyword if keyword in _load_supply() else None
        _ONDEMAND_DONE.add(keyword)
        try:
            h = _keyword_hash(keyword)
            url = f"https://tw.1688.com/item/-{h}.html"
            first = _fetch_1688(url)
            count_m = re.search(r"找到(\d+)[條条]", first)
            count = int(count_m.group(1)) if count_m else 0
            cards = _parse_1688_cards(first)
            for page in (2, 3):
                if len(cards) >= 80:
                    break
                try:
                    cards.extend(_parse_1688_cards(_fetch_1688(url + f"?beginPage={page}")))
                except Exception:  # noqa: BLE001
                    break
                time.sleep(1.0)
            supply = _load_supply()
            supply[keyword] = {
                "keyword": keyword,
                "hash": h,
                "supplier_count": count,
                "price_range": "",
                "supplier_cards": cards[:120],
            }
            _save_supply(supply)
            return keyword
        except Exception:  # noqa: BLE001
            return None
    return None


def _supply_stats(keyword: str) -> dict:
    supply = _load_supply().get(keyword) or {}
    cards = supply.get("supplier_cards") or []
    prices = [float(c["price"]) for c in cards if c.get("price") and float(c["price"]) > 0]
    regions: dict[str, int] = {}
    for c in cards:
        r = c.get("region") or ""
        regions[r] = regions.get(r, 0) + 1
    top_regions = [{"region": r, "cards": n} for r, n in sorted(regions.items(), key=lambda x: -x[1])[:3]]
    sold = sorted(
        ((c.get("title") or "")[:50], float(c.get("sales_volume") or 0), c.get("price") or "") for c in cards
    )
    sold.sort(key=lambda x: -x[1])
    return {
        "keyword": keyword,
        "supplier_count": supply.get("supplier_count") or len(cards),
        "price_min": min(prices) if prices else 0,
        "price_median": sorted(prices)[len(prices) // 2] if prices else 0,
        "price_max": max(prices) if prices else 0,
        "top_regions": top_regions,
        "top_sold": [{"title": t, "volume": v, "price": p} for t, v, p in sold[:3]],
    }


def _margin(keyword: str, price_median_cny: float, price_rub: float) -> dict:
    if price_median_cny <= 0 or price_rub <= 0:
        return {}
    purchase = price_median_cny * RUB_PER_CNY
    weight = KEYWORD_WEIGHT.get(keyword, 0.5)
    rate = 50.0 if weight <= 2 else 32.0 if weight <= 8 else 22.0
    logistics = max(weight, 0.1) * rate * RUB_PER_CNY
    domestic = 5.0 * RUB_PER_CNY
    fees = price_rub * 0.22
    total = purchase + logistics + domestic + fees
    net = price_rub - total
    return {
        "purchase_rub": round(purchase, 0),
        "logistics_rub": round(logistics, 0),
        "fees_rub": round(fees, 0),
        "total_rub": round(total, 0),
        "net_rub": round(net, 0),
        "net_margin_pct": round(net / price_rub * 100, 1) if price_rub else 0,
    }


def _match(query: str, price_rub: float | None) -> dict:
    q = re.sub(r"[^a-zа-я0-9 ]+", " ", (query or "").lower())
    for pattern, keyword in KEYWORD_PATTERNS:
        if pattern in q:
            stats = _supply_stats(keyword)
            margin = _margin(keyword, stats["price_median"], price_rub or 0) if price_rub else {}
            return {"matched": True, "keyword": keyword, "supply": stats, "margin": margin, "weight_kg": KEYWORD_WEIGHT.get(keyword)}
    return {"matched": False, "query": q[:120]}


def _match_cat(cat: str, price_rub: float | None) -> dict:
    catn = re.sub(r"[\s：:，,。·•]+", "", cat or "")
    if len(catn) < 2 or len(catn) > 16 or catn in _PLACEHOLDER_CATS:
        return {"matched": False}
    supply = _load_supply()
    hit = next((kw for kw in supply if len(kw) >= 2 and (kw in catn or catn in kw)), None)
    source = "cache"
    if not hit:
        hit = _crawl_keyword(catn)
        source = "on_demand"
    if not hit:
        return {"matched": False, "cat": catn}
    stats = _supply_stats(hit)
    margin = _margin(hit, stats["price_median"], price_rub or 0) if price_rub else {}
    return {
        "matched": True,
        "keyword": hit,
        "supply": stats,
        "margin": margin,
        "weight_kg": KEYWORD_WEIGHT.get(hit),
        "source": source,
    }


def _catalog() -> list[dict]:
    if CATALOG_FILE.exists():
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    return []


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._reply(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._reply(200, {"ok": True, "files": len(list(OUT.glob("*.json"))) if OUT.exists() else 0, "supply_keywords": len(_load_supply()), "catalog_rows": len(_catalog())})
            return
        if self.path.startswith("/data/supply"):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            keyword = (query.get("q") or [""])[0]
            if not keyword:
                self._reply(400, {"ok": False, "error": "missing q"})
                return
            self._reply(200, _supply_stats(keyword))
            return
        if self.path.startswith("/data/match"):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            q = (query.get("q") or [""])[0]
            cat = (query.get("cat") or [""])[0]
            price_rub = (query.get("price_rub") or [""])[0]
            try:
                price = float(price_rub) if price_rub else None
            except ValueError:
                price = None
            if cat:
                self._reply(200, _match_cat(cat, price))
            else:
                self._reply(200, _match(q, price))
            return
        if self.path.startswith("/data/crawl"):
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            cat = (query.get("cat") or [""])[0]
            if not cat:
                self._reply(400, {"ok": False, "error": "missing cat"})
                return
            self._reply(200, {"ok": True, "keyword": _crawl_keyword(cat), "supply_keywords": len(_load_supply())})
            return
        if self.path.startswith("/data/catalog"):
            self._reply(200, {"rows": _catalog()})
            return
        if self.path.startswith("/files"):
            names = sorted((p.name for p in OUT.glob("*.json")), reverse=True) if OUT.exists() else []
            self._reply(200, {"files": names[:200]})
            return
        self._reply(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/capture":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._reply(400, {"ok": False, "error": f"bad body: {exc}"})
            return
        OUT.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{stamp}_{int(time.time() * 1000) % 100000}.json"
        (OUT / fname).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._reply(200, {"ok": True, "file": fname, "site": payload.get("site", ""), "kind": (payload.get("data") or {}).get("kind", "")})

    def log_message(self, *args) -> None:  # noqa: ARG002
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    print(f"KJDS collector listening on http://127.0.0.1:{port} -> {OUT}")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
