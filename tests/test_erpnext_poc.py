import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest

from apps.control_plane.erpnext_poc import (
    ALLOWED_DOCTYPES,
    ErpNextPocProjector,
    FxContext,
    MoneyValue,
    reconcile_money,
    validate_projection_batch,
    verify_frappe_webhook,
)

ROOT = Path(__file__).resolve().parents[1]


def test_machine_contract_matches_code_and_keeps_remote_writes_disabled():
    registry = json.loads((ROOT / "docs/project/registries/erpnext_poc_contract.json").read_text(encoding="utf-8"))

    assert registry["mode"] == "poc_dry_run"
    assert registry["remote_write_enabled"] is False
    assert registry["automatic_submit"] is False
    assert set(registry["allowed_doctypes"]) == ALLOWED_DOCTYPES
    assert registry["current_owners"]["canonical_product"] == "kjds"
    assert set(registry["candidate_erpnext_owners"].values()) == {"erpnext"}


def test_item_projection_is_stable_evidence_backed_and_never_submits():
    projector = ErpNextPocProjector()
    first = projector.project_item(
        product_id="prd_001",
        version=2,
        sku="SKU-001",
        name="真实测试商品",
        stock_uom="Nos",
        evidence_ids=["evd_product", "evd_product"],
    )
    second = projector.project_item(
        product_id="prd_001",
        version=2,
        sku="SKU-001",
        name="真实测试商品",
        stock_uom="Nos",
        evidence_ids=["evd_product"],
    )

    assert first == second
    assert first.mode == "poc_dry_run"
    assert first.payload["docstatus"] == 0
    assert first.automatic_submit is False
    assert first.current_owner == "kjds"
    assert first.candidate_owner == "erpnext"
    assert first.evidence_ids == ("evd_product",)
    assert len(first.payload_sha256) == 64


def test_cross_currency_purchase_order_keeps_decimal_fx_time_and_evidence():
    projection = ErpNextPocProjector().project_purchase_order(
        order_id="spo_001",
        version=1,
        supplier_ref="SUPPLIER-001",
        transaction_date="2026-07-20",
        schedule_date="2026-08-10",
        items=[{"item_code": "SKU-001", "quantity": "100", "unit_rate": "12.3400", "currency": "CNY"}],
        company_currency="RUB",
        evidence_ids=["evd_quote", "evd_approval"],
        fx=FxContext(
            transaction_currency="CNY",
            company_currency="RUB",
            rate="11.7500",
            effective_at="2026-07-20T09:00:00+08:00",
            evidence_id="evd_fx",
        ),
    )

    assert projection.payload["currency"] == "CNY"
    assert projection.payload["conversion_rate"] == "11.7500"
    assert projection.payload["items"][0]["rate"] == "12.3400"
    assert projection.payload["custom_kjds_fx_context"]["evidence_id"] == "evd_fx"
    assert projection.evidence_ids == ("evd_quote", "evd_approval", "evd_fx")
    assert json.dumps(projection.to_dict(), ensure_ascii=False)


def test_projection_rejects_missing_fx_floats_evidence_and_submit_mode():
    projector = ErpNextPocProjector()
    common = {
        "order_id": "spo_001",
        "version": 1,
        "supplier_ref": "SUPPLIER-001",
        "transaction_date": "2026-07-20",
        "schedule_date": "2026-08-10",
        "items": [{"item_code": "SKU-001", "quantity": "1", "unit_rate": "10", "currency": "CNY"}],
        "company_currency": "RUB",
        "evidence_ids": ["evd_quote"],
    }
    with pytest.raises(ValueError, match="requires FX evidence"):
        projector.project_purchase_order(**common)
    with pytest.raises(ValueError, match="decimal string"):
        MoneyValue(10.1, "CNY")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="uppercase"):
        MoneyValue("10.1", "cny")
    with pytest.raises(ValueError, match="requires evidence"):
        projector.project_item(
            product_id="prd_001", version=1, sku="SKU-001", name="商品", stock_uom="Nos", evidence_ids=[]
        )
    valid = projector.project_item(
        product_id="prd_001", version=1, sku="SKU-001", name="商品", stock_uom="Nos", evidence_ids=["evd_1"]
    )
    with pytest.raises(ValueError, match="non-submitting dry-run"):
        validate_projection_batch([replace(valid, mode="production_write")])
    with pytest.raises(ValueError, match="non-submitting dry-run"):
        validate_projection_batch([replace(valid, automatic_submit=True)])


def test_batch_allows_exact_retry_but_rejects_same_key_with_different_payload():
    projector = ErpNextPocProjector()
    original = projector.project_item(
        product_id="prd_001", version=1, sku="SKU-001", name="商品", stock_uom="Nos", evidence_ids=["evd_1"]
    )
    assert validate_projection_batch([original, original]) == [original, original]

    conflict = projector.project_item(
        product_id="prd_001", version=1, sku="SKU-001", name="被改名商品", stock_uom="Nos", evidence_ids=["evd_1"]
    )
    assert conflict.idempotency_key == original.idempotency_key
    assert conflict.payload_sha256 != original.payload_sha256
    with pytest.raises(ValueError, match="conflicting payloads"):
        validate_projection_batch([original, conflict])


def test_journal_candidate_must_balance_and_remains_draft():
    projector = ErpNextPocProjector()
    journal = projector.project_journal_candidate(
        source_id="recon_001",
        version=1,
        posting_date="2026-07-20",
        currency="RUB",
        lines=[
            {"account": "OZON-RECEIVABLE", "debit": "9943.02", "credit": "0"},
            {"account": "OZON-CLEARING", "debit": "0", "credit": "9943.02"},
        ],
        evidence_ids=["evd_accrual", "evd_review"],
    )
    assert journal.payload["docstatus"] == 0
    assert journal.payload["accounts"][0]["debit_in_account_currency"] == "9943.02"

    with pytest.raises(ValueError, match="balance exactly"):
        projector.project_journal_candidate(
            source_id="recon_002",
            version=1,
            posting_date="2026-07-20",
            currency="RUB",
            lines=[
                {"account": "A", "debit": "10", "credit": "0"},
                {"account": "B", "debit": "0", "credit": "9"},
            ],
            evidence_ids=["evd_1"],
        )


def test_reconciliation_never_adjusts_and_blocks_currency_mismatch():
    matched = reconcile_money(source=MoneyValue("100.00", "RUB"), target=MoneyValue("100.01", "RUB"), tolerance="0.01")
    difference = reconcile_money(
        source=MoneyValue("100.00", "RUB"), target=MoneyValue("100.02", "RUB"), tolerance="0.01"
    )
    blocked = reconcile_money(source=MoneyValue("100", "RUB"), target=MoneyValue("8", "CNY"))

    assert matched.status == "matched"
    assert difference.status == "difference"
    assert difference.difference == "0.02"
    assert blocked.status == "blocked"
    assert matched.automatic_adjustment is False


def test_frappe_webhook_requires_valid_hmac_sha256():
    body = b'{"doctype":"Purchase Order","name":"PO-0001"}'
    secret = "poc-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_frappe_webhook(body=body, signature=signature, secret=secret) is True
    assert verify_frappe_webhook(body=body + b" ", signature=signature, secret=secret) is False
    assert verify_frappe_webhook(body=body, signature="not-a-signature", secret=secret) is False
    with pytest.raises(ValueError, match="secret is required"):
        verify_frappe_webhook(body=body, signature=signature, secret="")
