from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRAFT = ROOT / "docs/project/registries/ozon_bolt_cap_d10_q200_draft.json"
DEFAULT_MEDIA = ROOT / "output/market_recon/listing_readiness/d10_q200_media_readiness.json"
DEFAULT_CHECKOUT = (
    ROOT / "output/market_recon/supply_1688/d10_q200/supplier_checkout_collection_plan.json"
)
DEFAULT_FACT_REQUEST = (
    ROOT / "output/market_recon/supply_1688/d10_q200/supplier_fact_request_pack.json"
)
DEFAULT_OUTPUT = ROOT / "output/market_recon/listing_readiness/d10_q200_launch_preflight.json"
CONTRACT_ID = "kjds-d10-launch-preflight-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load_sealed(path: Path, field: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    claimed = str(value.get(field) or "").lower()
    unsealed = {key: item for key, item in value.items() if key != field}
    if claimed != _hash(unsealed):
        raise ValueError(f"{path.name} integrity check failed")
    return value


def build_preflight(
    *,
    draft: dict[str, Any],
    media: dict[str, Any],
    checkout: dict[str, Any],
    fact_request: dict[str, Any],
    sources: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if draft.get("offer_id") != fact_request.get("target_offer_id"):
        raise ValueError("D10 fact request offer binding mismatch")
    if checkout.get("plan_sha256") != fact_request.get("sources", {}).get(
        "checkout_plan", {}
    ).get("plan_sha256"):
        raise ValueError("D10 fact request checkout plan binding mismatch")
    if draft.get("draft_sha256") != fact_request.get("sources", {}).get("draft", {}).get(
        "draft_sha256"
    ):
        raise ValueError("D10 fact request draft binding mismatch")
    media_result = media.get("readiness")
    if not isinstance(media_result, dict) or media_result.get("offer_id") != draft.get(
        "offer_id"
    ):
        raise ValueError("D10 media readiness offer binding mismatch")
    research = draft["supplier_research"]
    canonical_product_id = draft["erp_defaults"]["canonical_product_id"]
    supplier_responses = sum(
        entry.get("response_status") != "awaiting_manual_supplier_response"
        for entry in fact_request["entries"]
    )
    blockers = set(draft.get("release_blockers") or [])
    blockers.update(media_result.get("blockers") or [])
    if canonical_product_id is None:
        blockers.add("canonical_product_not_created")
    if supplier_responses < fact_request["minimum_independent_responses"]:
        blockers.add("three_supplier_fact_responses_missing")
    if research["exact_purchase_candidates"] < 3:
        blockers.add("three_verified_checkout_snapshots_missing")
    if research["formal_supplier_offers"] < 3:
        blockers.add("three_canonical_supplier_offers_missing")
    if draft["screening_price"]["max_purchase_price_cny"] is None:
        blockers.update(
            {
                "formal_price_evidence_missing",
                "twelve_non_checkout_cost_evidence_missing",
                "purchase_ceiling_missing",
                "profit_scenario_missing",
            }
        )
    blockers.update(
        {
            "listing_approval_plan_missing",
            "canonical_listing_draft_missing",
            "erp_review_package_missing",
        }
    )
    chain = [
        {
            "stage": "supplier_facts",
            "state": "blocked",
            "evidence": {
                "requested": fact_request["entry_count"],
                "responses_received": supplier_responses,
                "minimum_required": fact_request["minimum_independent_responses"],
            },
        },
        {
            "stage": "canonical_product",
            "state": "ready" if canonical_product_id else "blocked",
            "canonical_product_id": canonical_product_id,
        },
        {
            "stage": "supplier_offers",
            "state": "blocked",
            "verified_checkout_snapshots": research["exact_purchase_candidates"],
            "canonical_supplier_offers": research["formal_supplier_offers"],
        },
        {
            "stage": "profit_scenario",
            "state": "blocked",
            "max_purchase_price_cny": draft["screening_price"]["max_purchase_price_cny"],
        },
        {
            "stage": "content_assets",
            "state": media_result["status"],
            "blocker_count": len(media_result.get("blockers") or []),
        },
        {"stage": "listing_approval_plan", "state": "blocked"},
        {"stage": "canonical_listing_draft", "state": "blocked"},
        {"stage": "erp_review_package", "state": "blocked"},
        {"stage": "erp_draft_sync", "state": "blocked"},
        {"stage": "ozon_listing_write", "state": "not_authorized"},
    ]
    result = {
        "contract_id": CONTRACT_ID,
        "status": "blocked_pre_canonical",
        "offer_id": draft["offer_id"],
        "sources": sources,
        "current_facts": {
            "observed_supplier_offers": research["observed_offers"],
            "exact_dimension_and_color_candidates": research[
                "exact_dimension_and_color_candidates"
            ],
            "shortlisted_distinct_suppliers": research["shortlisted_distinct_suppliers"],
            "supplier_fact_requests": fact_request["entry_count"],
            "supplier_fact_responses": supplier_responses,
            "media_status": media_result["status"],
            "canonical_product_id": canonical_product_id,
            "max_purchase_price_cny": draft["screening_price"]["max_purchase_price_cny"],
        },
        "chain": chain,
        "blockers": sorted(blockers),
        "next_actions": [
            "manually_send_supplier_fact_requests_and_capture_at_least_three_current_responses",
            "create_canonical_product_after_database_runtime_is_current",
            "promote_three_verified_checkout_snapshots_then_capture_three_canonical_supplier_offers",
            "bind_formal_price_and_twelve_non_checkout_cost_legs_then_calculate_profit_scenario",
            "replace_family_images_with_exact_variant_material_and_packaging_evidence",
            "create_listing_approval_plan_and_canonical_listing_draft_before_erp_review",
        ],
        "semantic_limits": {
            "external_supplier_contact_performed": False,
            "erp_write_performed": False,
            "ozon_write_performed": False,
            "purchase_order_created": False,
            "payment_created": False,
        },
    }
    result["preflight_sha256"] = _hash(result)
    return result


def _source(path: Path, seal_field: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(ROOT).as_posix(),
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        seal_field: payload[seal_field],
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Project a sealed D10 launch/ERP preflight.")
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--media", type=Path, default=DEFAULT_MEDIA)
    parser.add_argument("--checkout", type=Path, default=DEFAULT_CHECKOUT)
    parser.add_argument("--fact-request", type=Path, default=DEFAULT_FACT_REQUEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = {
        "draft": args.draft.resolve(),
        "media": args.media.resolve(),
        "checkout": args.checkout.resolve(),
        "fact_request": args.fact_request.resolve(),
    }
    values = {
        "draft": _load_sealed(paths["draft"], "draft_sha256"),
        "media": _load_sealed(paths["media"], "projection_sha256"),
        "checkout": _load_sealed(paths["checkout"], "plan_sha256"),
        "fact_request": _load_sealed(paths["fact_request"], "pack_sha256"),
    }
    sources = {
        key: _source(paths[key], field, values[key])
        for key, field in {
            "draft": "draft_sha256",
            "media": "projection_sha256",
            "checkout": "plan_sha256",
            "fact_request": "pack_sha256",
        }.items()
    }
    result = build_preflight(
        draft=values["draft"],
        media=values["media"],
        checkout=values["checkout"],
        fact_request=values["fact_request"],
        sources=sources,
    )
    output = args.output.resolve()
    _atomic_json(output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "blockers": len(result["blockers"]),
                "supplier_fact_requests": result["current_facts"]["supplier_fact_requests"],
                "supplier_fact_responses": result["current_facts"]["supplier_fact_responses"],
                "canonical_product_id": result["current_facts"]["canonical_product_id"],
                "output": str(output),
                "preflight_sha256": result["preflight_sha256"],
                "external_write_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
