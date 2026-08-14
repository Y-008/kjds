"""Parse all KJDS browser-extension captures into one structured artifact."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "output" / "browser_capture"
OUT = ROOT / "output" / "market_recon" / "browser_capture_parsed.json"


def main() -> int:
    files = sorted(CAP.glob("*.json"))
    parsed: list[dict] = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        parsed.append({"file": f.name, **d})
    OUT.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"parsed {len(parsed)} captures -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
