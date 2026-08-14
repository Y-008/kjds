from pathlib import Path

from apps.control_plane.runtime import build_runtime
from apps.control_plane.scoped_profit_ledger import (
    ScopedProfitLedgerAuthority,
    ScopedProfitOrderSkuReceiptAuthority,
)


def test_runtime_owns_distinct_profit_projection_and_receipt_authorities():
    runtime = build_runtime()
    settlement = runtime.scoped_settlement_cash
    receipt_authority = settlement.profit_receipt_authority

    assert type(settlement.profit_ledger) is ScopedProfitLedgerAuthority
    assert type(receipt_authority) is ScopedProfitOrderSkuReceiptAuthority
    assert receipt_authority is not settlement.profit_ledger
    canonical_profit = (
        receipt_authority._ScopedProfitOrderSkuReceiptAuthority__canonical_profit
    )
    assert type(canonical_profit) is ScopedProfitLedgerAuthority
    assert canonical_profit is not settlement.profit_ledger


def test_settlement_source_never_discovers_verifier_on_profit_adapter():
    source = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "control_plane"
        / "scoped_settlement_cash.py"
    )
    content = source.read_text(encoding="utf-8")

    assert "getattr(\n            self.profit_ledger" not in content
    assert "self.profit_receipt_authority" in content
    assert "source_profit_snapshot_sha256" in content
