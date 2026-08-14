"""One-shot bounded official Ozon readback probe (BAS-160 step 4 input).

Explicit ``--execute`` intent is required.  The probe performs exactly one
bounded read-only finance query against the official Seller API and persists a
content-addressed response bundle plus a non-secret identity summary.  It never
prints or stores Client-Id/Api-Key material, never constructs a provider client
through the managed worker factory, and never performs any write.

Usage:
  uv run python scripts/capture_ozon_readback.py --preflight
  uv run python scripts/capture_ozon_readback.py --execute \
      --account-ref ozon-seller-account-probe --output-dir output/readback
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from apps.control_plane.ozon_worker import (
    OzonCredentials,
    OzonSellerClient,
    validate_execution_environment,
)
from apps.control_plane.provider_readback_verifier import (
    PROVIDER_READBACK_VERIFIER_VERSION,
    READBACK_SUMMARY_CONTRACT_ID,
)

SUMMARY_SCHEMA_VERSION = "1"
PLATFORM = "ozon"
ADAPTER_ID = "ozon-seller-api-read"
ADAPTER_VERSION = "v1"
DEFAULT_DATE_FROM = "2025-10-01T00:00:00+00:00"
DEFAULT_DATE_TO = "2025-10-31T00:00:00+00:00"
PRODUCT_READ_OPERATION = "ozon.product.read"
FINANCE_READ_OPERATION = "ozon.finance.read"
PRODUCT_CONTRACT_VERSION = "ozon-product-read-v1"
FINANCE_CONTRACT_VERSION = "ozon-finance-transactions-v1"
PRODUCT_REQUIRED_CAPABILITY = "catalog.read"
FINANCE_REQUIRED_CAPABILITY = "finance.read"
PLACEHOLDER = {
    "",
    "missing",
    "replace-me",
    "replace-with-a-key",
    "changeme",
}


def _required(value: str, name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER:
        raise ValueError(f"{name} is required")
    return cleaned


def _report(environment: dict[str, str]) -> dict:
    client_id = _required(environment.get("OZON_CLIENT_ID", ""), "OZON_CLIENT_ID")
    api_key = _required(environment.get("OZON_API_KEY", ""), "OZON_API_KEY")
    return {
        "status": "ready_for_explicit_execution",
        "mode": "offline_preflight",
        "network_calls_performed": False,
        "operations": [PRODUCT_READ_OPERATION, FINANCE_READ_OPERATION],
        "official_origin": "https://api-seller.ozon.ru",
        "endpoints": ["/v3/product/info/list", "/v4/product/info/attributes", "/v3/finance/transaction/list"],
        "read_only": True,
        "credentials_present": True,
        "client_id_len": len(client_id),
        "api_key_len": len(api_key),
        "client_id_sha256": hashlib.sha256(client_id.encode()).hexdigest(),
        "explicit_execution_required": True,
    }


def _capture(
    *,
    environment: dict[str, str],
    date_from: str,
    date_to: str,
    account_ref: str,
    captured_by: str,
    operation: str,
    offer_id: str,
    output_dir: Path,
    tenant_ref: str | None,
    entity_ref: str | None,
    store_ref: str | None,
    secret_reference: str | None,
) -> dict:
    client_id = _required(environment.get("OZON_CLIENT_ID", ""), "OZON_CLIENT_ID")
    api_key = _required(environment.get("OZON_API_KEY", ""), "OZON_API_KEY")
    account_ref = _required(account_ref, "--account-ref")
    captured_by = _required(captured_by, "--captured-by")
    validate_execution_environment(environment)
    credentials = OzonCredentials.for_readback_probe(
        client_id=client_id,
        api_key=api_key,
    )
    client = OzonSellerClient(
        credentials=credentials,
        readback_probe_allowed=True,
    )
    try:
        if operation == FINANCE_READ_OPERATION:
            result = client.finance_transactions(
                date_from=date_from,
                date_to=date_to,
                page=1,
                page_size=100,
            )
            contract_version = FINANCE_CONTRACT_VERSION
            required_capability = FINANCE_REQUIRED_CAPABILITY
            query_window_sha256 = result["query_window_sha256"]
            operation_count = result["operation_count"]
            page, page_size, page_count = (
                result["page"],
                result["page_size"],
                result["page_count"],
            )
        else:
            offer_id = _required(offer_id, "--offer-id")
            result = client.offer_state(offer_id)
            contract_version = PRODUCT_CONTRACT_VERSION
            required_capability = PRODUCT_REQUIRED_CAPABILITY
            query_window_sha256 = hashlib.sha256(offer_id.encode()).hexdigest()
            operation_count = 2
            page, page_size, page_count = 1, 1, 1
    finally:
        client.close()
    bundle = result["response_evidence_bytes"]
    observed_at = datetime.now(UTC)
    fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id=client_id,
        api_key=api_key,
        platform=PLATFORM,
        account_ref=account_ref,
    )
    summary = {
        "contract_id": READBACK_SUMMARY_CONTRACT_ID,
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "verifier_version": PROVIDER_READBACK_VERIFIER_VERSION,
        "platform": PLATFORM,
        "account_ref": account_ref,
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
        "required_capability": required_capability,
        "scope": {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
        },
        "client_id_sha256": hashlib.sha256(client_id.encode()).hexdigest(),
        "credential_fingerprint_sha256": fingerprint,
        "secret_reference_sha256": hashlib.sha256(
            (secret_reference or "kjds-readback-probe-v1").encode()
        ).hexdigest(),
        "observed_at": observed_at.isoformat(),
        "operation": operation,
        "query_window_sha256": query_window_sha256,
        "response_bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "response_byte_size": len(bundle),
        "operation_count": operation_count,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "captured_by": captured_by,
        "official_origin_verified": True,
        "contract_version": contract_version,
        "credential_material_returned": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "readback-bundle.json"
    summary_path = output_dir / "readback-summary.json"
    bundle_path.write_bytes(bundle)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "status": "captured",
        "bundle_path": str(bundle_path),
        "summary_path": str(summary_path),
        "bundle_sha256": summary["response_bundle_sha256"],
        "operation_count": summary["operation_count"],
        "credential_material_returned": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded official Ozon readback probe")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--date-from", default=os.getenv("KJDS_READBACK_DATE_FROM", DEFAULT_DATE_FROM))
    parser.add_argument("--date-to", default=os.getenv("KJDS_READBACK_DATE_TO", DEFAULT_DATE_TO))
    parser.add_argument(
        "--operation",
        choices=(PRODUCT_READ_OPERATION, FINANCE_READ_OPERATION),
        default=os.getenv("KJDS_READBACK_OPERATION", PRODUCT_READ_OPERATION),
    )
    parser.add_argument("--offer-id", default=os.getenv("KJDS_READBACK_OFFER_ID", ""))
    parser.add_argument("--account-ref", default=os.getenv("KJDS_READBACK_ACCOUNT_REF", ""))
    parser.add_argument("--captured-by", default=os.getenv("KJDS_READBACK_CAPTURED_BY", ""))
    parser.add_argument(
        "--tenant-ref",
        default=os.getenv("KJDS_READBACK_TENANT_REF", ""),
        help="Canonical tenant binding for the readback scope (empty = unbound probe)",
    )
    parser.add_argument(
        "--entity-ref",
        default=os.getenv("KJDS_READBACK_ENTITY_REF", ""),
        help="Canonical entity binding for the readback scope (empty = unbound probe)",
    )
    parser.add_argument(
        "--store-ref",
        default=os.getenv("KJDS_READBACK_STORE_REF", ""),
        help="Canonical store binding for the readback scope (empty = unbound probe)",
    )
    parser.add_argument(
        "--secret-reference",
        default=os.getenv("KJDS_READBACK_SECRET_REFERENCE", ""),
        help="Non-secret managed-store secret reference hashed into the summary",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("KJDS_READBACK_OUTPUT_DIR", "output/readback"),
    )
    args = parser.parse_args()
    environment = dict(os.environ)
    if args.preflight:
        print(json.dumps(_report(environment), ensure_ascii=False))
        return
    try:
        result = _capture(
            environment=environment,
            date_from=args.date_from,
            date_to=args.date_to,
            account_ref=args.account_ref,
            captured_by=args.captured_by,
            operation=args.operation,
            offer_id=args.offer_id,
            output_dir=Path(args.output_dir),
            tenant_ref=(
                args.tenant_ref.strip()
                if args.tenant_ref and args.tenant_ref.strip()
                else None
            ),
            entity_ref=(
                args.entity_ref.strip()
                if args.entity_ref and args.entity_ref.strip()
                else None
            ),
            store_ref=(
                args.store_ref.strip()
                if args.store_ref and args.store_ref.strip()
                else None
            ),
            secret_reference=(
                args.secret_reference.strip()
                if args.secret_reference and args.secret_reference.strip()
                else None
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "failed", "error_code": "READBACK_FAILED", "error": str(exc)}))
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
