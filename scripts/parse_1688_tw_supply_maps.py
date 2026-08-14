"""Parse tw.1688.com supply-map pages into structured supplier counts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "market_recon" / "supply_1688"
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

PAGES = {
    "500kg_hoist": "https://tw.1688.com/item/-3530306B67B5E7B6AFBAF9C2ABB5F5.html?beginPage=2",
    "pa_series_hoist": "https://tw.1688.com/item/-7061CFB5C1D0B5E7B6AFBAF9C2AB.html",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def extract_region_counts(text: str) -> list[dict]:
    found: list[dict] = []
    # Common patterns: "河北 保定 123" style lists in supply maps.
    lines = re.split(r"[\n\r]+", text)
    for line in lines:
        line = line.strip()
        if not line or len(line) > 120:
            continue
        m = re.match(r"^([\u4e00-\u9fff]{2,8})\s+([\u4e00-\u9fff]{2,8})?\s*(\d+)\s*$", line)
        if m:
            province = m.group(1)
            city = m.group(2) or ""
            count = int(m.group(3))
            found.append({"province": province, "city": city, "supplier_count": count})
    return found


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, dict] = {}
    with httpx.Client(headers=HEADERS, timeout=40, trust_env=True, follow_redirects=True) as client:
        for key, url in PAGES.items():
            resp = client.get(url)
            text = resp.text
            title_match = re.search(r"<title>(.*?)</title>", text, re.S)
            title = title_match.group(1).strip() if title_match else ""
            counts = extract_region_counts(text)
            # fallback: look for region names in script JSON
            if not counts:
                for pat in (r'"name"\s*:\s*"([\u4e00-\u9fff]{2,8})"', r"([\u4e00-\u9fff]{2,8})地[区域]"):
                    for m in re.finditer(pat, text):
                        counts.append({"province": m.group(1), "city": "", "supplier_count": 0})
            all_results[key] = {
                "url": url,
                "title": title,
                "html_len": len(text),
                "region_rows": counts[:200],
            }
            print(f"{key}: title={title[:60]} len={len(text)} rows={len(counts)}")
            for row in counts[:25]:
                print(f"   {row}")
            (OUT / f"{key}.html").write_text(text, encoding="utf-8")
    (OUT / "supply_map_summary.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
