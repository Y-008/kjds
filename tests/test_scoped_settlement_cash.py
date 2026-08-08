from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MethodType, SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.evidence_scope import (
    DIRECT_CONTRACT,
    ScopedEvidenceAuthority,
)
from apps.control_plane.finance import (
    FinanceEntryKind,
    FinanceService,
)
from apps.control_plane.scoped_profit_ledger import (
    ScopedProfitOrderSkuReceiptAuthority,
)
from apps.control_plane.scoped_settlement_cash import (
    ScopedSettlementCashWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

AS_OF = "2026-07-29T00:00:00Z"
CURRENT_AS_OF = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
SHA = "a" * 64
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": "entity-cn-1",
    "authority_sha256": "f" * 64,
}


def principal(
    *,
    tenant_ref: str = "tenant-cn-1",
    store_ref: str = "store-cn-1",
) -> Principal:
    return Principal(
        actor_id="finance-operator",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({store_ref}),
    )


class MustNotRead:
    calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        raise AssertionError("finance raw source must not be read")


class MustNotReadProfit:
    native_exact_scope = True
    calls = 0

    def snapshot(self, **_values):
        self.calls += 1
        raise AssertionError("profit source must not be read")


class FakeEvidence:
    def __init__(self, *, invalid_ids: set[str] | None = None) -> None:
        self.invalid_ids = invalid_ids or set()

    def verify(self, evidence_id: str):
        return SimpleNamespace(
            valid=evidence_id not in self.invalid_ids,
            expected_sha256=SHA,
        )


class FakeScopedEvidence:
    def project(self, **_values):
        return {
            "status": "ready",
            "binding_authority_sha256": "e" * 64,
        }


class FakeFinance:
    def __init__(self, source: dict) -> None:
        self.source = source
        self.calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        return copy.deepcopy(self.source)


class FakeProfit:
    native_exact_scope = True

    def __init__(self, *, order_ref: str) -> None:
        self.order_ref = order_ref
        self.calls = 0

    def snapshot(self, **_values):
        self.calls += 1
        row = {
            "order_ref": self.order_ref,
            "order_count": 1,
            "product_id": "product-1",
            "sku": "SKU-1",
            "status": "reconciled",
            "currency": "CNY",
            "actual_profit": "12.5",
            "actual_cash_cm3": {
                "status": "available",
                "amount": "12.5",
                "currency": "CNY",
            },
            "cash_conservation": {
                "conserved": True,
                "conservation_delta": "0",
            },
            "cost_legs": [
                {"type": "product_cost", "actual": "-20"}
            ],
        }
        order_payload = {
            "external_id": self.order_ref,
            "sku": "SKU-1",
            "quantity": "1",
            "currency": "CNY",
            "gross_revenue": "100",
            "effective_at": "2026-07-20T00:00:00+00:00",
        }
        scope_receipt = {
            "tenant_ref": _values["principal"].tenant_ref,
            "entity_ref": _values["entity_scope"]["entity_ref"],
            "store_ref": _values["store_ref"],
            "scope_grant_authority_sha256": _values["entity_scope"][
                "authority_sha256"
            ],
        }
        order_fact_receipt = {
            "fact_id_sha256": ScopedSettlementCashWorkspace._hash(
                f"fact-{self.order_ref}-order"
            ),
            "payload_sha256": ScopedSettlementCashWorkspace._hash(
                order_payload
            ),
            "order_ref_sha256": ScopedSettlementCashWorkspace._hash(
                self.order_ref
            ),
            "product_sha256": ScopedSettlementCashWorkspace._hash(
                "product-1"
            ),
            "sku_sha256": ScopedSettlementCashWorkspace._hash("SKU-1"),
        }
        receipt = {
            "contract_id": "canonical_order_sku_receipt_v1",
            "issuer_contract_id": (
                "kjds-native-exact-scope-actual-profit-ledger-v1"
            ),
            "scope_sha256": ScopedSettlementCashWorkspace._hash(
                scope_receipt
            ),
            "scope_grant_authority_sha256": scope_receipt[
                "scope_grant_authority_sha256"
            ],
            "order_ref_sha256": order_fact_receipt["order_ref_sha256"],
            "product_sha256": order_fact_receipt["product_sha256"],
            "sku_sha256": order_fact_receipt["sku_sha256"],
            "order_fact_receipt_sha256": (
                ScopedSettlementCashWorkspace._hash(order_fact_receipt)
            ),
            "profit_row_basis_sha256": (
                ScopedSettlementCashWorkspace._hash(row)
            ),
        }
        receipt["receipt_sha256"] = ScopedSettlementCashWorkspace._hash(
            receipt
        )
        row["canonical_order_sku_receipt"] = receipt
        row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(row)
        result = {
            "contract_id": (
                "kjds-native-exact-scope-actual-profit-ledger-v1"
            ),
            "status": "reconciled",
            "as_of": _values["as_of"],
            "scope": {
                "tenant_ref": _values["principal"].tenant_ref,
                "entity_ref": _values["entity_scope"]["entity_ref"],
                "store_ref": _values["store_ref"],
                "scope_grant_authority_sha256": _values["entity_scope"][
                    "authority_sha256"
                ],
            },
            "grain": "order",
            "currency": "CNY",
            "store_ref": _values["store_ref"],
            "filters": {
                "sku": None,
                "order_id": self.order_ref,
                "date_from": None,
                "date_to": None,
                "query": None,
            },
            "counts": {
                "order_candidates": 1,
                "considered": 1,
                "reconciled": 1,
                "excluded": 0,
                "filtered": 1,
                "page": 1,
            },
            "pagination": {"page_size": 100, "next_cursor": None},
            "rows": [row],
            "unallocated": [],
            "excluded": {"count": 0},
            "source_gaps": [],
            "blockers": [],
            "control_envelope": {
                "read_only": True,
                "native_exact_scope": True,
                "scoped_input_read": True,
                "explicit_order_binding_only": True,
                "proportional_allocation_allowed": False,
                "actual_profit_requires_reconciliation": True,
                "external_write_allowed": False,
            },
        }
        result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
            result
        )
        return result

    def verify_order_sku_receipt(self, *, receipt, **values):
        canonical = FakeProfit.snapshot(self, **values)
        rows = canonical["rows"]
        matched = [
            row
            for row in rows
            if row["canonical_order_sku_receipt"] == receipt
        ]
        verified = len(rows) == 1 and len(matched) == 1
        projection = {
            "contract_id": "kjds-profit-order-sku-receipt-authority-v1",
            "status": "verified" if verified else "no_data",
            "as_of": values["as_of"],
            "scope": canonical["scope"],
            "issuer_contract_id": (
                "kjds-native-exact-scope-actual-profit-ledger-v1"
            ),
            "receipt": receipt if verified else None,
            "receipt_sha256": (
                receipt.get("receipt_sha256") if verified else None
            ),
            "source_profit_snapshot_sha256": canonical[
                "snapshot_sha256"
            ],
            "control_envelope": {
                "read_only": True,
                "native_exact_scope": True,
                "external_write_allowed": False,
            },
        }
        projection["snapshot_sha256"] = (
            ScopedSettlementCashWorkspace._hash(projection)
        )
        return projection


def source_payload(
    *,
    key: str = "order-1",
    evidence_id: str = "evidence-1",
    include_run: bool = True,
) -> dict:
    order_payload = {
        "external_id": key,
        "sku": "SKU-1",
        "quantity": "1",
        "currency": "CNY",
        "gross_revenue": "100",
        "effective_at": "2026-07-20T00:00:00+00:00",
    }
    accrual_payload = {
        "external_id": key,
        "currency": "CNY",
        "amount": "90",
        "effective_at": "2026-07-21T00:00:00+00:00",
    }
    facts = [
        {
            "id": f"fact-{key}-order",
            "source": "ozon-export",
            "fact_type": "ozon_order",
            "natural_key": key,
            "contract_version": "ozon-v1",
            "payload": order_payload,
            "payload_hash": ScopedSettlementCashWorkspace._hash(
                order_payload
            ),
            "effective_at": "2026-07-20T00:00:00+00:00",
            "recorded_at": "2026-07-20T01:00:00+00:00",
            "evidence_id": evidence_id,
            "product_id": "product-1",
            "resolution_status": "resolved",
            "source_evidence_sha256": SHA,
            "scope_as_of": "2026-07-20T01:00:00+00:00",
        },
        {
            "id": f"fact-{key}-accrual",
            "source": "ozon-export",
            "fact_type": "ozon_accrual",
            "natural_key": key,
            "contract_version": "ozon-v1",
            "payload": accrual_payload,
            "payload_hash": ScopedSettlementCashWorkspace._hash(
                accrual_payload
            ),
            "effective_at": "2026-07-21T00:00:00+00:00",
            "recorded_at": "2026-07-21T01:00:00+00:00",
            "evidence_id": evidence_id,
            "product_id": "product-1",
            "resolution_status": "resolved",
            "source_evidence_sha256": SHA,
            "scope_as_of": "2026-07-21T01:00:00+00:00",
        },
    ]
    entries = [
        {
            "id": f"entry-{key}-settlement",
            "entry_kind": "platform_settlement",
            "source": "ozon",
            "source_ref": f"{key}-settlement",
            "reconciliation_key": key,
            "raw_fee_code": None,
            "amount": "90",
            "currency": "CNY",
            "effective_at": "2026-07-22T00:00:00+00:00",
            "evidence_id": evidence_id,
            "source_fact_id": None,
            "review_required": False,
            "created_by": "finance-operator",
            "recorded_at": "2026-07-22T01:00:00+00:00",
            "source_evidence_sha256": SHA,
            "scope_as_of": "2026-07-22T01:00:00+00:00",
        },
        {
            "id": f"entry-{key}-cash",
            "entry_kind": "bank_receipt",
            "source": "bank",
            "source_ref": f"{key}-cash",
            "reconciliation_key": key,
            "raw_fee_code": None,
            "amount": "90",
            "currency": "CNY",
            "effective_at": "2026-07-23T00:00:00+00:00",
            "evidence_id": evidence_id,
            "source_fact_id": None,
            "review_required": False,
            "created_by": "bank-operator",
            "recorded_at": "2026-07-23T01:00:00+00:00",
            "source_evidence_sha256": SHA,
            "scope_as_of": "2026-07-23T01:00:00+00:00",
        },
    ]
    snapshot = {
        "entry_count": 2,
        "totals": {
            "order_receivable": "0",
            "platform_fee": "0",
            "return_adjustment": "0",
            "platform_settlement": "90",
            "bank_receipt": "90",
            "cash_adjustment": "0",
        },
        "expected_settlement": "90",
        "platform_settlement": "90",
        "bank_receipt": "90",
        "settlement_variance": "0",
        "bank_variance": "0",
        "settlement_variance_ratio": "0",
        "bank_variance_ratio": "0",
        "unknown_fees": [],
        "missing_fx": [],
        "review_required": [],
        "missing_legs": [],
        "evidence_conflicts": [],
        "self_review_dependencies": [],
        "applied_fx": [],
        "applied_fee_mappings": [],
    }
    snapshot["input_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            "reconciliation_key": key,
            "quote_currency": "CNY",
            "fx_source": "bank-of-china",
            "tolerance_ratio": "0.003",
            "entry_ids": [entry["id"] for entry in entries],
            "entry_authorities": [
                entry["source_evidence_sha256"] for entry in entries
            ],
            "snapshot": snapshot,
        }
    )
    reconciliations = (
        [
            {
                "id": f"recon-{key}",
                "reconciliation_key": key,
                "quote_currency": "CNY",
                "fx_source": "bank-of-china",
                "tolerance_ratio": "0.003",
                "status": "matched",
                "snapshot": snapshot,
                "created_by": "independent-reviewer",
                "recorded_at": "2026-07-24T00:00:00+00:00",
                "source_evidence_sha256": (
                    ScopedSettlementCashWorkspace._hash([SHA])
                ),
                "scope_as_of": "2026-07-24T00:00:00+00:00",
            }
        ]
        if include_run
        else []
    )
    source = {
        "contract_id": "kjds-scoped-finance-read-source-v1",
        "as_of": "2026-07-29T00:00:00+00:00",
        "scope": {
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "scope_grant_authority_sha256": "f" * 64,
            "source_evidence_sha256": None,
            "as_of": "2026-07-29T00:00:00+00:00",
            "authority": "native",
        },
        "facts": facts,
        "entries": entries,
        "reconciliations": reconciliations,
        "truncated": {
            "facts": False,
            "entries": False,
            "reconciliations": False,
        },
    }
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        source
    )
    return source


def workspace(
    source: dict,
    *,
    invalid_ids: set[str] | None = None,
    profit=None,
    receipt_authority=None,
) -> ScopedSettlementCashWorkspace:
    projection_profit = profit or MustNotReadProfit()
    if receipt_authority is None:
        canonical_profit = (
            FakeProfit(order_ref=projection_profit.order_ref)
            if isinstance(projection_profit, FakeProfit)
            else MustNotReadProfit()
        )
        receipt_authority = _receipt_authority(canonical_profit)
    return ScopedSettlementCashWorkspace(
        finance=FakeFinance(source),
        evidence=FakeEvidence(invalid_ids=invalid_ids),
        scoped_evidence=FakeScopedEvidence(),
        profit_ledger=projection_profit,
        profit_receipt_authority=receipt_authority,
    )


def _receipt_authority(canonical_profit):
    authority = object.__new__(ScopedProfitOrderSkuReceiptAuthority)

    def verify(_self, **values):
        return canonical_profit.verify_order_sku_receipt(**values)

    authority.verify_order_sku_receipt = MethodType(verify, authority)
    return authority


def project_values() -> dict:
    return {
        "store_ref": "store-cn-1",
        "principal": principal(),
        "entity_scope": ENTITY_SCOPE,
        "as_of": AS_OF,
    }


def test_missing_or_malformed_entity_never_reads_finance_or_profit():
    finance = MustNotRead()
    profit = MustNotReadProfit()
    service = ScopedSettlementCashWorkspace(
        finance=finance,
        evidence=FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
        profit_ledger=profit,
        profit_receipt_authority=_receipt_authority(profit),
    )

    missing = service.project(
        store_ref="store-cn-1",
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        as_of=AS_OF,
    )
    malformed = service.project(
        store_ref="store-cn-1",
        principal=principal(),
        entity_scope={
            "status": "ready",
            "entity_ref": "entity-cn-1",
            "authority_sha256": "bad",
        },
        as_of=AS_OF,
    )

    assert missing["status"] == "no_data"
    assert malformed["status"] == "blocked"
    assert finance.calls == 0
    assert profit.calls == 0
    assert missing["control_envelope"]["scoped_input_read"] is False


def test_valid_three_book_cycle_is_deterministic_and_suggestion_only():
    source = source_payload()
    profit = FakeProfit(order_ref="order-1")
    service = workspace(source, profit=profit)

    first = service.project(**project_values())
    second = service.project(**project_values())

    assert first == second
    assert first["status"] == "ready"
    assert first["counts"]["reconciled"] == 1
    cycle = first["cycles"][0]
    assert cycle["stage"] == "reconciled"
    assert cycle["books"]["order_accrual"]["gross_revenue"] == "100"
    assert cycle["books"]["platform_settlement"]["amount"] == "90"
    assert cycle["books"]["bank_cash"]["amount"] == "90"
    assert cycle["actual_cash_cm3"]["amount"] == "12.5"
    attribution = cycle["actual_cash_cm3"]["single_sku_attribution"]
    assert attribution["status"] == "verified"
    assert attribution["identity_count"] == 1
    assert "SKU-1" not in str(attribution)
    assert "product-1" not in str(attribution)
    assert profit.calls == 2
    assert first["agent_artifact"]["self_approval_allowed"] is False
    assert first["agent_artifact"]["permit_issue_allowed"] is False
    assert (
        first["agent_artifact"]["finance_record_creation_allowed"]
        is False
    )
    assert first["control_envelope"]["payment_initiated"] is False
    assert first["control_envelope"]["external_write_allowed"] is False


def test_weak_profit_projection_cannot_create_single_sku_cash_truth():
    class WeakProfit:
        native_exact_scope = True

        def snapshot(self, **_values):
            return {
                "status": "reconciled",
                "currency": "CNY",
                "rows": [
                    {
                        "order_ref": "order-1",
                        "status": "reconciled",
                        "actual_profit": "12.5",
                    }
                ],
                "unallocated": [],
                "excluded": {"count": 0},
                "snapshot_sha256": "9" * 64,
            }

    result = workspace(
        source_payload(),
        profit=WeakProfit(),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert actual["status"] == "no_data"
    assert actual["amount"] is None
    assert actual["reason"] == "scoped_profit_authority_contract_invalid"
    assert actual["single_sku_attribution"]["status"] == "no_data"


def test_same_order_payload_bound_to_two_products_fails_closed():
    source = source_payload()
    conflicting = copy.deepcopy(source["facts"][0])
    conflicting["id"] = "fact-order-1-conflicting-product"
    conflicting["product_id"] = "product-2"
    source["facts"].append(conflicting)
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )

    result = workspace(
        source,
        profit=FakeProfit(order_ref="order-1"),
    ).project(**project_values())

    assert result["status"] == "blocked"
    cycle = result["cycles"][0]
    assert cycle["stage"] == "blocked"
    assert "finance_order_fact_current_conflict" in cycle["blockers"]
    assert cycle["actual_cash_cm3"]["status"] == "no_data"


def test_profit_identity_drift_is_no_data_and_exposes_no_raw_identity():
    class WrongSkuProfit(FakeProfit):
        def snapshot(self, **values):
            result = super().snapshot(**values)
            row = result["rows"][0]
            row.pop("snapshot_sha256")
            row["sku"] = "SKU-OTHER"
            row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(row)
            result.pop("snapshot_sha256")
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

    result = workspace(
        source_payload(),
        profit=WrongSkuProfit(order_ref="order-1"),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert actual["status"] == "no_data"
    assert actual["reason"] == "single_sku_profit_attribution_invalid"
    assert "SKU-OTHER" not in str(actual)


@pytest.mark.parametrize(
    "drift",
    ["actual_profit", "actual_cash", "cost", "conservation"],
)
def test_resealed_profit_projection_cannot_replace_receipt_authority(drift):
    class ReSignedProfit(FakeProfit):
        def snapshot(self, **values):
            result = super().snapshot(**values)
            result.pop("snapshot_sha256")
            row = result["rows"][0]
            row.pop("snapshot_sha256")
            receipt = row.pop("canonical_order_sku_receipt")
            if drift == "actual_profit":
                row["actual_profit"] = "13.5"
                row["actual_cash_cm3"]["amount"] = "13.5"
            elif drift == "actual_cash":
                row["actual_cash_cm3"]["amount"] = "13.5"
                row["actual_profit"] = "13.5"
            elif drift == "cost":
                row["cost_legs"][0]["actual"] = "-21"
            else:
                row["cash_conservation"]["gross_plus_platform_adjustments"] = (
                    "100"
                )
            receipt["profit_row_basis_sha256"] = (
                ScopedSettlementCashWorkspace._hash(row)
            )
            receipt.pop("receipt_sha256")
            receipt["receipt_sha256"] = (
                ScopedSettlementCashWorkspace._hash(receipt)
            )
            row["canonical_order_sku_receipt"] = receipt
            row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(row)
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

    result = workspace(
        source_payload(),
        profit=ReSignedProfit(order_ref="order-1"),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert result["status"] == "partial"
    assert actual["status"] == "no_data"
    assert actual["single_sku_attribution"]["status"] == "no_data"


@pytest.mark.parametrize("authority_mode", ["missing", "error"])
def test_profit_receipt_authority_is_mandatory_and_fails_closed(authority_mode):
    receipt_authority = object()
    if authority_mode == "error":
        receipt_authority = object.__new__(
            ScopedProfitOrderSkuReceiptAuthority
        )

        def fail(_self, **_values):
            raise RuntimeError("authority unavailable")

        receipt_authority.verify_order_sku_receipt = MethodType(
            fail,
            receipt_authority,
        )

    result = workspace(
        source_payload(),
        profit=FakeProfit(order_ref="order-1"),
        receipt_authority=receipt_authority,
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert result["status"] == "partial"
    assert actual["status"] == "no_data"
    assert actual["single_sku_attribution"]["status"] == "no_data"


def test_receipt_authority_snapshot_must_match_consumed_profit_snapshot():
    class TopResealedProfit(FakeProfit):
        def snapshot(self, **values):
            result = super().snapshot(**values)
            result.pop("snapshot_sha256")
            result["adapter_observation_sha256"] = "9" * 64
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

    result = workspace(
        source_payload(),
        profit=TopResealedProfit(order_ref="order-1"),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert result["status"] == "partial"
    assert result["counts"]["actual_cash_cm3_available"] == 0
    assert actual["status"] == "no_data"
    assert actual["single_sku_attribution"]["status"] == "no_data"


def test_malicious_profit_adapter_cannot_supply_its_own_receipt_verifier():
    class JointForgeryProfit(FakeProfit):
        def __init__(self, **values):
            super().__init__(**values)
            self.verifier_calls = 0

        def snapshot(self, **values):
            result = super().snapshot(**values)
            result.pop("snapshot_sha256")
            row = result["rows"][0]
            row.pop("snapshot_sha256")
            receipt = row.pop("canonical_order_sku_receipt")
            row["actual_profit"] = "13.5"
            row["actual_cash_cm3"]["amount"] = "13.5"
            receipt["profit_row_basis_sha256"] = (
                ScopedSettlementCashWorkspace._hash(row)
            )
            receipt.pop("receipt_sha256")
            receipt["receipt_sha256"] = (
                ScopedSettlementCashWorkspace._hash(receipt)
            )
            row["canonical_order_sku_receipt"] = receipt
            row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(row)
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

        def verify_order_sku_receipt(self, **values):
            self.verifier_calls += 1
            result = self.snapshot(**values)
            receipt = result["rows"][0]["canonical_order_sku_receipt"]
            projection = {
                "contract_id": (
                    "kjds-profit-order-sku-receipt-authority-v1"
                ),
                "status": "verified",
                "as_of": values["as_of"],
                "scope": result["scope"],
                "issuer_contract_id": result["contract_id"],
                "receipt": receipt,
                "receipt_sha256": receipt["receipt_sha256"],
                "source_profit_snapshot_sha256": result[
                    "snapshot_sha256"
                ],
                "control_envelope": {
                    "read_only": True,
                    "native_exact_scope": True,
                    "external_write_allowed": False,
                },
            }
            projection["snapshot_sha256"] = (
                ScopedSettlementCashWorkspace._hash(projection)
            )
            return projection

    malicious = JointForgeryProfit(order_ref="order-1")
    result = workspace(
        source_payload(),
        profit=malicious,
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert malicious.verifier_calls == 0
    assert result["status"] == "partial"
    assert result["counts"]["actual_cash_cm3_available"] == 0
    assert actual["status"] == "no_data"
    assert "13.5" not in str(actual)


@pytest.mark.parametrize("drift", ["invalid_as_of", "invalid_conservation"])
def test_malformed_profit_authority_fails_closed_without_raising(drift):
    class MalformedProfit(FakeProfit):
        def snapshot(self, **values):
            result = super().snapshot(**values)
            result.pop("snapshot_sha256")
            if drift == "invalid_as_of":
                result["as_of"] = "not-a-timestamp"
            else:
                row = result["rows"][0]
                row.pop("snapshot_sha256")
                row["cash_conservation"]["conservation_delta"] = "NaN"
                row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    row
                )
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

    result = workspace(
        source_payload(),
        profit=MalformedProfit(order_ref="order-1"),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert actual["status"] == "no_data"
    assert actual["amount"] is None
    assert actual["single_sku_attribution"]["status"] == "no_data"


@pytest.mark.parametrize(
    "drift",
    [
        "none_projection",
        "nan_profit",
        "infinite_profit",
        "wrong_currency",
        "extra_row",
        "wrong_filter",
        "next_cursor",
        "hidden_page",
        "missing_sku",
        "non_reconciled_row",
    ],
)
def test_profit_query_must_be_complete_single_order_authority(drift):
    class DriftingProfit(FakeProfit):
        def snapshot(self, **values):
            if drift == "none_projection":
                return None
            result = super().snapshot(**values)
            result.pop("snapshot_sha256")
            row = result["rows"][0]
            if drift in {"nan_profit", "infinite_profit"}:
                row.pop("snapshot_sha256")
                value = "NaN" if drift == "nan_profit" else "Infinity"
                row["actual_profit"] = value
                row["actual_cash_cm3"]["amount"] = value
                row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    row
                )
            elif drift == "wrong_currency":
                row.pop("snapshot_sha256")
                result["currency"] = "USD"
                row["currency"] = "USD"
                row["actual_cash_cm3"]["currency"] = "USD"
                row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    row
                )
            elif drift == "extra_row":
                other = copy.deepcopy(row)
                other.pop("snapshot_sha256")
                other["order_ref"] = "ORDER-CANARY"
                other["product_id"] = "PRODUCT-CANARY"
                other["sku"] = "SKU-CANARY"
                other["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    other
                )
                result["rows"].append(other)
            elif drift == "wrong_filter":
                result["filters"]["order_id"] = "ORDER-CANARY"
            elif drift == "next_cursor":
                result["pagination"]["next_cursor"] = "opaque-more"
            elif drift == "hidden_page":
                result["counts"]["filtered"] = 2
            elif drift == "missing_sku":
                row.pop("snapshot_sha256")
                row["sku"] = None
                row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    row
                )
            elif drift == "non_reconciled_row":
                row.pop("snapshot_sha256")
                row["status"] = "partial"
                row["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                    row
                )
            result["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
                result
            )
            return result

    result = workspace(
        source_payload(),
        profit=DriftingProfit(order_ref="order-1"),
    ).project(**project_values())
    actual = result["cycles"][0]["actual_cash_cm3"]

    assert result["status"] == "partial"
    assert actual["status"] == "no_data"
    assert actual["amount"] is None
    assert actual["single_sku_attribution"]["status"] == "no_data"
    serialized = str(actual)
    assert "PRODUCT-CANARY" not in serialized
    assert "SKU-CANARY" not in serialized
    assert "ORDER-CANARY" not in serialized


def test_bad_latest_evidence_hides_key_amounts_and_identifiers():
    source = source_payload(evidence_id="bad-evidence")
    service = workspace(source, invalid_ids={"bad-evidence"})

    result = service.project(**project_values())
    rendered = str(result)

    assert result["status"] == "blocked"
    assert result["cycles"] == []
    assert result["excluded"]["business_values_exposed"] is False
    assert "order-1" not in rendered
    assert "'100'" not in rendered
    assert result["excluded"]["count"] > 0


def test_older_bad_reconciliation_does_not_override_latest_valid_run():
    source = source_payload()
    older = copy.deepcopy(source["reconciliations"][0])
    older["id"] = "recon-order-1-older"
    older["recorded_at"] = "2026-07-23T12:00:00+00:00"
    older["snapshot"]["input_sha256"] = "0" * 64
    source["reconciliations"].append(older)
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )

    result = workspace(
        source,
        profit=FakeProfit(order_ref="order-1"),
    ).project(**project_values())

    assert result["status"] == "ready"
    assert result["cycles"][0]["latest_reconciliation"]["id"] == (
        "recon-order-1"
    )


def test_conflicting_settlement_fact_and_entry_fail_closed():
    source = source_payload()
    settlement_payload = {
        "external_id": "order-1",
        "currency": "CNY",
        "amount": "91",
        "effective_at": "2026-07-22T00:00:00+00:00",
    }
    source["facts"].append(
        {
            "id": "fact-order-1-settlement",
            "source": "ozon-export",
            "fact_type": "ozon_settlement",
            "natural_key": "order-1",
            "contract_version": "ozon-v1",
            "payload": settlement_payload,
            "payload_hash": ScopedSettlementCashWorkspace._hash(
                settlement_payload
            ),
            "effective_at": "2026-07-22T00:00:00+00:00",
            "recorded_at": "2026-07-22T01:00:00+00:00",
            "evidence_id": "evidence-1",
            "product_id": "product-1",
            "resolution_status": "resolved",
            "source_evidence_sha256": SHA,
            "scope_as_of": "2026-07-22T01:00:00+00:00",
        }
    )
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )

    result = workspace(source).project(**project_values())

    assert result["status"] == "blocked"
    cycle = result["cycles"][0]
    assert cycle["stage"] == "blocked"
    assert cycle["books"]["platform_settlement"]["amount"] is None
    assert "finance_settlement_source_conflict" in cycle["blockers"]
    assert cycle["actual_cash_cm3"]["amount"] is None


def test_source_truncation_fails_closed_before_business_projection():
    source = source_payload()
    source["truncated"]["entries"] = True
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )

    result = workspace(source).project(**project_values())

    assert result["status"] == "blocked"
    assert result["cycles"] == []
    assert "finance_source_truncated" in result["source_gaps"]
    assert result["control_envelope"]["scoped_input_read"] is True


def test_server_filter_and_opaque_cursor_are_deterministic():
    first_source = source_payload(key="order-a", include_run=False)
    second_source = source_payload(key="order-b", include_run=False)
    source = copy.deepcopy(first_source)
    source["facts"].extend(second_source["facts"])
    source["entries"].extend(second_source["entries"])
    source["snapshot_sha256"] = ScopedSettlementCashWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )
    service = workspace(source)

    first = service.project(**project_values(), page_size=1)
    second = service.project(
        **project_values(),
        page_size=1,
        cursor=first["pagination"]["next_cursor"],
    )
    filtered = service.project(
        **project_values(),
        query="ORDER-A",
        stage="reconcile_pending",
    )

    assert first["counts"]["total_cycles"] == 2
    assert first["pagination"]["next_cursor"]
    assert first["cycles"][0]["reconciliation_key"] != (
        second["cycles"][0]["reconciliation_key"]
    )
    assert filtered["counts"]["filtered"] == 1
    assert filtered["cycles"][0]["reconciliation_key"] == "order-a"


def test_direct_call_rejects_unauthorized_store():
    with pytest.raises(PermissionError, match="not authorized"):
        workspace(source_payload()).project(
            store_ref="other-store",
            principal=principal(),
            entity_scope=ENTITY_SCOPE,
            as_of=AS_OF,
        )


def sqlite_services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return (
        FinanceService(engine),
        evidence,
        ScopedEvidenceAuthority(evidence=evidence),
    )


def capture_scoped_evidence(
    evidence: EvidenceService,
    *,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
    content: bytes,
):
    digest = hashlib.sha256(content).hexdigest()
    return evidence.capture(
        content=content,
        filename=f"{entity_ref}.csv",
        content_type="text/csv",
        source="official-export",
        source_ref=f"official://{entity_ref}/{digest}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by=f"source-{entity_ref}",
        metadata={
            "evidence_scope_contract_id": DIRECT_CONTRACT,
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "reviewed_by": f"reviewer-{entity_ref}",
        },
    )


def scope_for(record, *, tenant_ref: str, entity_ref: str, store_ref: str):
    return {
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
        "scope_grant_authority_sha256": "f" * 64,
        "source_evidence_sha256": record.sha256,
        "scope_as_of": CURRENT_AS_OF,
    }


def test_finance_sql_source_isolates_native_scope_and_legacy_rows():
    finance, evidence, _scoped = sqlite_services()
    source_a = capture_scoped_evidence(
        evidence,
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        content=b"entity-a",
    )
    source_b = capture_scoped_evidence(
        evidence,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        content=b"entity-b",
    )
    common = {
        "entry_kind": FinanceEntryKind.BANK_RECEIPT,
        "source": "bank",
        "source_ref": "same-reference",
        "reconciliation_key": "order-1",
        "amount": Decimal("90"),
        "currency": "CNY",
        "effective_at": "2026-07-20T00:00:00Z",
        "created_by": "finance-operator",
    }
    finance.record_entry(evidence_id=source_a.id, **common)
    finance.record_entry(
        evidence_id=source_a.id,
        scope_authority=scope_for(
            source_a,
            tenant_ref="tenant-a",
            entity_ref="entity-a",
            store_ref="store-a",
        ),
        **common,
    )
    finance.record_entry(
        evidence_id=source_b.id,
        scope_authority=scope_for(
            source_b,
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        ),
        **common,
    )

    result = finance.read_scoped_sources(
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        scope_grant_authority_sha256="f" * 64,
        as_of=CURRENT_AS_OF,
    )

    assert len(result["entries"]) == 1
    assert result["entries"][0]["source_evidence_sha256"] == (
        source_a.sha256
    )
    assert result["scope"]["tenant_ref"] == "tenant-a"
    assert result["truncated"] == {
        "facts": False,
        "entries": False,
        "reconciliations": False,
    }


def test_scoped_finance_write_rejects_evidence_authority_drift():
    finance, evidence, _scoped = sqlite_services()
    source = capture_scoped_evidence(
        evidence,
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        content=b"entity-a",
    )
    scope = scope_for(
        source,
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
    )
    scope["source_evidence_sha256"] = "0" * 64

    with pytest.raises(
        ValueError,
        match="source Evidence authority changed",
    ):
        finance.record_entry(
            entry_kind=FinanceEntryKind.BANK_RECEIPT,
            source="bank",
            source_ref="line-1",
            reconciliation_key="order-1",
            amount=Decimal("90"),
            currency="CNY",
            effective_at="2026-07-20T00:00:00Z",
            evidence_id=source.id,
            created_by="finance-operator",
            scope_authority=scope,
        )
