"""1688 supply-side crawler via tw.1688.com keyword pages (read-only, polite).

Keyword -> URL hash: ASCII segment encoded as UTF-8 hex, CJK segment encoded
as GBK (cp936) hex, concatenated.  Pages:
  https://www.1688.com/chanpin/-<hash>.html      (product overview + count)
  https://tw.1688.com/item/-<hash>.html?beginPage=N  (supplier cards)
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "market_recon" / "supply_1688"
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def keyword_hash(keyword: str) -> str:
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


def parse_supplier_cards(html: str) -> list[dict]:
    cards: list[dict] = []
    for m in re.finditer(
        r'<li[^>]*offerId="(\d+)"[^>]*class="([^"]*sm-offerShopwindow[^"]*)"[^>]*>(.*?)</li>',
        html,
        re.S,
    ):
        offer_id = m.group(1)
        rank_m = re.search(r'rank="(\d+)"', m.group(0))
        body = m.group(3)
        city_m = re.search(r'<span class="su-city">([^<]+)</span>', body)
        shop_m = re.search(r"alitalk='[^']*\"id\":\"([^\"]+)\"", body)
        img_m = re.search(r'<img[^>]*alt="([^"]+)"', body)
        h2_m = re.search(r'<h2[^>]*class="[^"]*sm-offerShopwindow-title[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>', body, re.S)
        title = ""
        if h2_m:
            title = re.sub(r"<[^>]+>", "", h2_m.group(1)).strip()
        if not title and img_m:
            title = img_m.group(1).strip()
        price_m = re.search(r'<span class="su-price">(?:<[^>]+>[^<]*</[^>]+>)?\s*([0-9][0-9.,]*)', body)
        sales_m = re.search(r"成交\s*([\d.]+)\s*(台|件|套|个|只|箱|批|双|盒)", body)
        cards.append(
            {
                "rank": int(rank_m.group(1)) if rank_m else None,
                "offer_id": offer_id,
                "title": title,
                "region": city_m.group(1).strip() if city_m else "",
                "shop": shop_m.group(1).strip() if shop_m else "",
                "price": price_m.group(1).strip() if price_m else "",
                "sales_volume": float(sales_m.group(1)) if sales_m else 0.0,
                "sales_unit": sales_m.group(2) if sales_m else "",
            }
        )
    return cards


def fetch(client: httpx.Client, url: str) -> str:
    for attempt in range(3):
        try:
            resp = client.get(url, timeout=40)
            if resp.status_code == 200 and len(resp.text) > 20000:
                return resp.text
            print(f"  retry {attempt}: {url} status={resp.status_code} len={len(resp.text)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  retry {attempt}: {url} exc={type(exc).__name__} {str(exc)[:100]}")
        time.sleep(4)
    return ""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    keywords = [
        "500kg电动葫芦吊",
        "PA系列电动葫芦",
        "三合一折叠床",
        "折叠躺椅床",
        "锂电电锯",
        "双人帐篷",
        "钢制折叠梯",
        "变色唇膏",
        "手机吸盘支架",
        "婴儿浴盆",
        "比特币硬币",
        "牧田DHR182电锤",
        "车载吸尘器",
        "鼻毛修剪器",
        "家用绞肉机",
        "沙滩罩衫",
        "沙滩裙",
        "水龙头",
        "激光水平仪",
        "发膜",
        "发动机油",
        "清洁剂",
    ]
    all_data: dict[str, dict] = {}
    crawl_file = OUT / "supply_crawl.json"
    if crawl_file.exists():
        try:
            all_data = json.loads(crawl_file.read_text(encoding="utf-8"))
            print(f"existing keywords: {len(all_data)}")
        except Exception:  # noqa: BLE001
            all_data = {}
    todo = [k for k in keywords if k not in all_data]
    categories_file = OUT / "cn_categories.json"
    if categories_file.exists():
        try:
            categories = json.loads(categories_file.read_text(encoding="utf-8"))
            for _group, words in categories.items():
                for w in words:
                    if w not in all_data:
                        todo.append(w)
        except Exception:  # noqa: BLE001
            print("categories load failed")
    todo = list(dict.fromkeys(todo))
    print(f"todo: {todo}")
    with httpx.Client(headers=HEADERS, timeout=40, trust_env=True, follow_redirects=True) as client:
        for keyword in todo:
            h = keyword_hash(keyword)
            list_url = f"https://tw.1688.com/item/-{h}.html"
            print(f"== {keyword} ({h})")
            count = 0
            price_range = ""
            cards: list[dict] = []
            for page in (1, 2, 3):
                page_html = fetch(client, list_url + (f"?beginPage={page}" if page > 1 else ""))
                if page_html:
                    batch = parse_supplier_cards(page_html)
                    if page == 1:
                        count_m = re.search(r"找到(\d+)[條条]", page_html)
                        count = int(count_m.group(1)) if count_m else 0
                    print(f"  page{page}: {len(batch)} cards (count={count})")
                    cards.extend(batch)
                if len(cards) >= 90:
                    break
                time.sleep(1.2)
            all_data[keyword] = {
                "keyword": keyword,
                "hash": h,
                "supplier_count": count,
                "price_range": price_range,
                "supplier_cards": cards[:120],
            }
            sold = sum(c["sales_volume"] for c in cards if c["sales_volume"])
            print(f"  total cards: {len(cards)} total sales_volume: {sold:.0f}")
            (OUT / "supply_crawl.json").write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"saved ({len(all_data)} keywords)", flush=True)
            time.sleep(1.5)
    (OUT / "supply_crawl.json").write_text(json.dumps(all_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved supply_crawl.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
