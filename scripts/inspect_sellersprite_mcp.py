from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.control_plane.marketplace_research_mcp import (  # noqa: E402
    SellerSpriteMcpAdmission,
    SellerSpriteMcpContractError,
)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"{self.prog}: error: invalid_arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _SafeParser(
        description="Inspect SellerSprite MCP inventory without invoking any tool."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the safe inventory hash projection as JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        projection = asyncio.run(SellerSpriteMcpAdmission().inspect()).to_dict()
    except SellerSpriteMcpContractError as exc:
        projection = {
            "contract_id": "kjds-sellersprite-mcp-admission-v1",
            "status": "blocked",
            "reason_codes": [exc.reason_code],
        }
    rendered = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.json:
        print(rendered)
    else:
        print(
            "status={status} tools={count} inventory_sha256={inventory}".format(
                status=projection["status"],
                count=projection.get("tool_count", 0),
                inventory=projection.get("inventory_sha256") or "none",
            )
        )
    return 0 if projection["status"] == "review_required" else 2


if __name__ == "__main__":
    raise SystemExit(main())
