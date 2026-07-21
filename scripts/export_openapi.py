from __future__ import annotations

import json
from pathlib import Path

from apps.control_plane.api import app


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "docs" / "project" / "contracts" / "openapi-v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
