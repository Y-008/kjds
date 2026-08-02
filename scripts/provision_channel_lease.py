"""Provision one authoritative managed lease from a verified official readback.

Explicit ``--provision`` intent is required; ``--preflight`` only verifies the
readback artifacts, re-runs the pure ProviderReadbackVerifier and checks that
no lease already exists.  Credential material is accepted only from the
command-line/env inputs of this provisioning run and is never printed,
persisted outside the managed lease store, or sent to AI prompts.

Usage:
  uv run python scripts/provision_channel_lease.py --preflight \\
      --readback-dir output/readback-20260801 --lease-id lease-ozon-primary-1 \\
      --tenant-ref default --entity-ref kjds --store-ref ozon-primary \\
      --account-ref ozon-seller-account-probe
  uv run python scripts/provision_channel_lease.py --provision ... (same inputs)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine

from apps.control_plane.database import DEFAULT_DATABASE_URL
from apps.control_plane.lease_provisioning import LeaseProvisioningSeam
from apps.control_plane.managed_credential_leases import (
    SqlManagedCredentialLeaseStore,
)
from apps.control_plane.provider_readback_verifier import (
    ProviderReadbackVerifier,
)

PLACEHOLDER = {"", "missing", "replace-me", "replace-with-a-key", "changeme"}


def _required(value: str, name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER:
        raise ValueError(f"{name} is required")
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision one managed channel lease")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--provision", action="store_true")
    parser.add_argument("--readback-dir", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--tenant-ref", required=True)
    parser.add_argument("--entity-ref", required=True)
    parser.add_argument("--store-ref", required=True)
    parser.add_argument("--platform", default="ozon")
    parser.add_argument("--account-ref", required=True)
    parser.add_argument("--adapter-id", default="ozon-seller-api-read")
    parser.add_argument("--adapter-version", default="v1")
    parser.add_argument(
        "--capabilities",
        default=os.getenv("KJDS_CHANNEL_LEASE_CAPABILITIES", "catalog.read"),
    )
    parser.add_argument("--epoch", type=int, default=1)
    parser.add_argument("--secret-reference", required=True)
    parser.add_argument("--lease-ttl-seconds", type=int, default=86_400)
    parser.add_argument(
        "--verifier-actor",
        default=os.getenv("KJDS_CHANNEL_LEASE_VERIFIER_ACTOR", "kjds-readback-verifier"),
    )
    parser.add_argument(
        "--provisioner-actor",
        default=os.getenv("KJDS_CHANNEL_LEASE_PROVISIONER_ACTOR", "kjds-lease-provisioner"),
    )
    parser.add_argument(
        "--created-by",
        default=os.getenv("KJDS_CHANNEL_LEASE_CREATED_BY", "kjds-lease-provisioner"),
    )
    args = parser.parse_args()

    try:
        client_id = _required(
            os.getenv("KJDS_CHANNEL_LEASE_PROVISION_CLIENT_ID", ""),
            "KJDS_CHANNEL_LEASE_PROVISION_CLIENT_ID",
        )
        api_key = _required(
            os.getenv("KJDS_CHANNEL_LEASE_PROVISION_API_KEY", ""),
            "KJDS_CHANNEL_LEASE_PROVISION_API_KEY",
        )
        issuer = _required(
            os.getenv("KJDS_CHANNEL_LEASE_ISSUER", "kjds-managed-store"),
            "KJDS_CHANNEL_LEASE_ISSUER",
        )
        key_id = _required(
            os.getenv("KJDS_CHANNEL_LEASE_KEY_ID", "lease-kid-1"),
            "KJDS_CHANNEL_LEASE_KEY_ID",
        )
        database_url = os.getenv("KJDS_DATABASE_URL", DEFAULT_DATABASE_URL)
        engine = create_engine(database_url)
        store = SqlManagedCredentialLeaseStore(
            engine=engine,
            issuer=issuer,
            key_id=key_id,
        )
        seam = LeaseProvisioningSeam(
            store=store,
            verifier=ProviderReadbackVerifier(),
        )
        common = {
            "readback_dir": Path(args.readback_dir),
            "lease_id": _required(args.lease_id, "--lease-id"),
            "tenant_ref": _required(args.tenant_ref, "--tenant-ref"),
            "entity_ref": _required(args.entity_ref, "--entity-ref"),
            "store_ref": _required(args.store_ref, "--store-ref"),
            "platform": _required(args.platform, "--platform"),
            "account_ref": _required(args.account_ref, "--account-ref"),
            "adapter_id": _required(args.adapter_id, "--adapter-id"),
            "adapter_version": _required(args.adapter_version, "--adapter-version"),
            "capabilities": {
                item.strip()
                for item in str(args.capabilities).split(",")
                if item.strip()
            },
            "authorization_epoch": args.epoch,
            "secret_reference": _required(args.secret_reference, "--secret-reference"),
            "client_id": client_id,
            "api_key": api_key,
            "verifier_actor": _required(args.verifier_actor, "--verifier-actor"),
            "provisioner_actor": _required(args.provisioner_actor, "--provisioner-actor"),
            "as_of": datetime.now(UTC),
        }
        if args.preflight:
            verdict = seam.preflight(**common)
            print(json.dumps(verdict, ensure_ascii=False))
            return
        result = seam.provision(
            **common,
            created_by=_required(args.created_by, "--created-by"),
            lease_ttl_seconds=args.lease_ttl_seconds,
        )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "LEASE_PROVISIONING_FAILED",
                    "error": str(exc),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
