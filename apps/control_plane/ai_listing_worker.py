from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime

from .runtime import runtime
from .security import require_any_role


def run_once(*, store_ref: str, worker_id: str) -> dict | None:
    api_key = os.getenv("KJDS_AI_LISTING_WORKER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("KJDS_AI_LISTING_WORKER_API_KEY is required")
    principal = runtime.authenticator.authenticate(api_key)
    require_any_role(principal, "operator", "admin")
    if not principal.can_access_store(store_ref):
        raise PermissionError("AI Listing worker is not authorized for store_ref")
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=datetime.now(UTC),
    )
    return runtime.ai_listing.process_next(
        worker_id=worker_id,
        principal=principal,
        entity_scope=entity_scope,
        store_ref=store_ref,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process governed AI Listing runs without marketplace writes"
    )
    parser.add_argument("--store-ref", default="ozon-primary")
    parser.add_argument("--worker-id", default="ai-listing-worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds < 0.5 or args.poll_seconds > 60:
        raise ValueError("poll-seconds must be between 0.5 and 60")
    while True:
        result = run_once(store_ref=args.store_ref, worker_id=args.worker_id)
        if result is not None:
            print(
                json.dumps(
                    {
                        "run_id": result["id"],
                        "status": result["status"],
                        "current_stage": result["current_stage"],
                        "external_write_allowed": False,
                    },
                    ensure_ascii=False,
                )
            )
        if args.once:
            return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
