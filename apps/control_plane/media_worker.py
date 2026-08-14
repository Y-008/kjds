from __future__ import annotations

import argparse
import socket
import time
from typing import Any


def run_governed_once(
    editing_blueprint: Any,
    *,
    principal: Any,
    store_ref: str,
    job_ref: str,
    worker_id: str,
) -> dict[str, Any]:
    """Process one explicit governed MediaJob without polling a second queue."""

    try:
        outcome = editing_blueprint.process(principal, store_ref, job_ref)
    except Exception as exc:
        return {
            "status": "failed",
            "worker_id": worker_id,
            "job_ref": job_ref,
            "error_code": type(exc).__name__,
            "external_marketplace_write": False,
            "automatic_retry": False,
            "automatic_failover": False,
        }
    return {
        "status": outcome.status.lower(),
        "worker_id": worker_id,
        "job_ref": outcome.job_ref,
        "result_state": outcome.result_state,
        "content_asset_ref": outcome.content_asset_ref,
        "external_marketplace_write": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }


def run_configured_governed_once(
    runtime: Any,
    *,
    actor_id: str,
    store_ref: str,
    job_ref: str,
    worker_id: str,
) -> dict[str, Any]:
    """Resolve a server-configured identity and process one canonical Job."""

    principal = runtime.authenticator.resolve_actor(actor_id)
    return run_governed_once(
        runtime.editing_blueprint,
        principal=principal,
        store_ref=store_ref,
        job_ref=job_ref,
        worker_id=worker_id,
    )


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
    parser.add_argument("--governed-job-ref")
    parser.add_argument("--actor-id")
    parser.add_argument("--store-ref")
    args = parser.parse_args()
    if not 0.2 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.2 and 60")

    from .runtime import runtime

    governed_values = (
        args.governed_job_ref,
        args.actor_id,
        args.store_ref,
    )
    if any(governed_values):
        if not all(governed_values) or not args.once:
            parser.error(
                "governed execution requires --once, --governed-job-ref, "
                "--actor-id, and --store-ref"
            )
        result = run_configured_governed_once(
            runtime,
            actor_id=args.actor_id,
            store_ref=args.store_ref,
            job_ref=args.governed_job_ref,
            worker_id=args.worker_id,
        )
        return 0 if result["status"] != "failed" else 1

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
