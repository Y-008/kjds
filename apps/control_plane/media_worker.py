from __future__ import annotations

import argparse
import socket
import time
from typing import Any


def run_once(media_workbench: Any, *, worker_id: str) -> dict[str, Any]:
    claimed = media_workbench.claim_video(worker_id=worker_id)
    if claimed is None:
        return {
            "status": "idle",
            "worker_id": worker_id,
            "execution_id": None,
            "external_marketplace_write": False,
        }
    execution_id = claimed["id"]
    try:
        result = media_workbench.execute_video(
            execution_id,
            worker_id=worker_id,
        )
        return {
            "status": "completed",
            "worker_id": worker_id,
            "execution_id": execution_id,
            "result": result,
            "external_marketplace_write": False,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "worker_id": worker_id,
            "execution_id": execution_id,
            "error_code": type(exc).__name__,
            "external_marketplace_write": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KJDS PostgreSQL-lease media worker"
    )
    parser.add_argument(
        "--worker-id",
        default=f"media-worker-{socket.gethostname()}",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 0.2 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.2 and 60")

    from .runtime import runtime

    while True:
        result = run_once(
            runtime.media_workbench,
            worker_id=args.worker_id,
        )
        if args.once:
            return 0 if result["status"] != "failed" else 1
        if result["status"] == "idle":
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
