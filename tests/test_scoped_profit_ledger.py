from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import ChargeType
from apps.control_plane.finance import FinanceEntryKind
from apps.control_plane.scoped_profit_ledger import (
    COST_ORDER,
    ScopedProfitLedgerAuthority,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ProductRow

AS_OF = "2026-07-29T00:00:00+00:00"
SCOPE = {
    "tenant_ref": "tenant-cn-1",
    "entity_ref": "entity-cn-1",
    "store_ref": "store-cn-1",
    "scope_grant_authority_sha256": "f" * 64,
}
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": SCOPE["entity_ref"],
    "authority_sha256": SCOPE["scope_grant_authority_sha256"],
}


def principal(
    *,
    store_ref: str = SCOPE["store_ref"],
) -> Principal:
    return Principal(
        actor_id="profit-operator",
        roles=frozenset({"operator"}),
        tenant_ref=SCOPE["tenant_ref"],
        store_refs=frozenset({store_ref}),
    )


class MustNotRead:
    calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        raise AssertionError("finance sources must not be read")

    def read_scoped_profit_authorities(self, **_values):
        self.calls += 1
        raise AssertionError("profit authorities must not be read")


class FakeEvidence:
    def __init__(self, hashes: dict[str, str]) -> None:
        self.hashes = hashes
        self.invalid_ids: set[str] = set()

    def verify(self, evidence_id: str):
        if evidence_id not in self.hashes:
            raise KeyError(evidence_id)
        return SimpleNamespace(
            valid=evidence_id not in self.invalid_ids,
            expected_sha256=self.hashes[evidence_id],
        )


class FakeScopedEvidence:
    def __init__(self) -> None:
        self.invalid_ids: set[str] = set()

    def project(self, *, evidence_ids: list[str], **_values):
        return {
            "status": (
                "blocked"
                if set(evidence_ids) & self.invalid_ids
                else "ready"
            ),
            "binding_authority_sha256": "e" * 64,
        }


class FakeFinance:
    def __init__(
        self,
        *,
        source: dict,
        authorities: dict,
    ) -> None:
        self.source = source
        self.authorities = authorities
        self.source_calls = 0
        self.authority_calls = 0

    def read_scoped_sources(self, **_values):
        self.source_calls += 1
        return copy.deepcopy(self.source)

    def read_scoped_profit_authorities(self, **_values):
        self.authority_calls += 1
        return copy.deepcopy(self.authorities)


def engine_with_product():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    at = datetime(2026, 7, 20, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id="product-1",
                sku="SKU-1",
                name="Exact product",
                market="RU",
                channel="OZON",
                status="active",
                created_at=at,
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
                scope_grant_authority_sha256=SCOPE[
                    "scope_grant_authority_sha256"
                ],
                scope_as_of=at,
                created_by="product-reviewer",
            )
        )
    return engine


def build_sources(
    *,
    key: str = "order-1",
    missing_cost_type: ChargeType | None = None,
    include_old_order: bool = False,
) -> tuple[dict, dict, dict[str, str]]:
    order_at = datetime(2026, 7, 20, tzinfo=UTC)
    payload = {
        "external_id": key,
        "sku": "SKU-1",
        "quantity": "1",
        "currency": "CNY",
        "gross_revenue": "100",
        "effective_at": order_at.isoformat(),
    }
    hashes = {
        "evidence-order": "1" * 64,
        "evidence-platform": "2" * 64,
        "evidence-bank": "3" * 64,
    }
    fact = {
        "id": f"fact-{key}",
        "source": "ozon-export",
        "fact_type": "ozon_order",
        "natural_key": key,
        "contract_version": "ozon-v1",
        "payload": payload,
        "payload_hash": ScopedProfitLedgerAuthority._hash(payload),
        "effective_at": order_at.isoformat(),
        "recorded_at": (order_at + timedelta(minutes=1)).isoformat(),
        "evidence_id": "evidence-order",
        "product_id": "product-1",
        "resolution_status": "resolved",
        "source_evidence_sha256": hashes["evidence-order"],
        "scope_as_of": (order_at + timedelta(minutes=1)).isoformat(),
    }
    facts = [fact]
    if include_old_order:
        old_payload = {**payload, "gross_revenue": "95"}
        facts.insert(
            0,
            {
                **fact,
                "id": f"fact-{key}-old",
                "payload": old_payload,
                "payload_hash": ScopedProfitLedgerAuthority._hash(
                    old_payload
                ),
                "effective_at": (
                    order_at - timedelta(days=1)
                ).isoformat(),
                "recorded_at": (
                    order_at - timedelta(days=1, minutes=-1)
                ).isoformat(),
            },
        )

    common = {
        "reconciliation_key": key,
        "raw_fee_code": None,
        "currency": "CNY",
        "source_fact_id": None,
        "review_required": False,
        "scope_as_of": (order_at + timedelta(hours=1)).isoformat(),
    }
    entries = [
        {
            **common,
            "id": f"entry-{key}-receivable",
            "entry_kind": FinanceEntryKind.ORDER_RECEIVABLE.value,
            "source": "reviewed-order",
            "source_ref": f"{key}-receivable",
            "profit_cost_type": None,
            "amount": "100",
            "effective_at": order_at.isoformat(),
            "evidence_id": "evidence-platform",
            "source_fact_id": fact["id"],
            "created_by": "entry-reviewer",
            "recorded_at": (
                order_at + timedelta(minutes=2)
            ).isoformat(),
            "source_evidence_sha256": hashes["evidence-platform"],
        },
        {
            **common,
            "id": f"entry-{key}-settlement",
            "entry_kind": FinanceEntryKind.PLATFORM_SETTLEMENT.value,
            "source": "ozon-settlement",
            "source_ref": f"{key}-settlement",
            "profit_cost_type": None,
            "amount": "100",
            "effective_at": (
                order_at + timedelta(minutes=3)
            ).isoformat(),
            "evidence_id": "evidence-platform",
            "created_by": "settlement-reviewer",
            "recorded_at": (
                order_at + timedelta(minutes=4)
            ).isoformat(),
            "source_evidence_sha256": hashes["evidence-platform"],
        },
        {
            **common,
            "id": f"entry-{key}-receipt",
            "entry_kind": FinanceEntryKind.BANK_RECEIPT.value,
            "source": "bank-statement",
            "source_ref": f"{key}-receipt",
            "profit_cost_type": None,
            "amount": "100",
            "effective_at": (
                order_at + timedelta(minutes=5)
            ).isoformat(),
            "evidence_id": "evidence-bank",
            "created_by": "bank-reviewer",
            "recorded_at": (
                order_at + timedelta(minutes=6)
            ).isoformat(),
            "source_evidence_sha256": hashes["evidence-bank"],
        },
    ]
    for index, cost_type in enumerate(COST_ORDER):
        if cost_type is missing_cost_type:
            continue
        evidence_id = f"evidence-cost-{cost_type.value}"
        hashes[evidence_id] = f"{index + 4:064x}"
        if cost_type is ChargeType.PLATFORM_FEE:
            entries.append(
                {
                    **common,
                    "id": f"entry-{key}-cost-{cost_type.value}",
                    "entry_kind": FinanceEntryKind.PLATFORM_FEE.value,
                    "source": "ozon-platform-fee",
                    "source_ref": f"{key}-cost-{cost_type.value}",
                    "raw_fee_code": "platform_fee_total",
                    "profit_cost_type": None,
                    "amount": "0",
                    "effective_at": (
                        order_at + timedelta(minutes=10 + index)
                    ).isoformat(),
                    "evidence_id": evidence_id,
                    "created_by": f"cost-reviewer-{index}",
                    "recorded_at": (
                        order_at + timedelta(minutes=30 + index)
                    ).isoformat(),
                    "source_evidence_sha256": hashes[evidence_id],
                }
            )
            continue
        entries.append(
            {
                **common,
                "id": f"entry-{key}-cost-{cost_type.value}",
                "entry_kind": FinanceEntryKind.BANK_PAYMENT.value,
                "source": "bank-cost-allocation",
                "source_ref": f"{key}-cost-{cost_type.value}",
                "profit_cost_type": cost_type.value,
                "amount": (
                    "-20"
                    if cost_type is ChargeType.PRODUCT_COST
                    else "0"
                ),
                "effective_at": (
                    order_at + timedelta(minutes=10 + index)
                ).isoformat(),
                "evidence_id": evidence_id,
                "created_by": f"cost-reviewer-{index}",
                "recorded_at": (
                    order_at + timedelta(minutes=30 + index)
                ).isoformat(),
                "source_evidence_sha256": hashes[evidence_id],
            }
        )
    entries.sort(
        key=lambda item: (
            item["effective_at"],
            item["id"],
        )
    )
    totals = {kind.value: Decimal("0") for kind in FinanceEntryKind}
    for entry in entries:
        totals[entry["entry_kind"]] += Decimal(entry["amount"])
    snapshot = {
        "entry_count": len(entries),
        "totals": {
            name: str(value) for name, value in totals.items()
        },
        "expected_settlement": "100",
        "platform_settlement": "100",
        "bank_receipt": "100",
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
        "applied_fee_mappings": (
            []
            if missing_cost_type is ChargeType.PLATFORM_FEE
            else [
                {
                    "entry_id": f"entry-{key}-cost-platform_fee",
                    "mapping_id": "mapping-platform-fee",
                    "canonical_type": ChargeType.PLATFORM_FEE.value,
                }
            ]
        ),
    }
    snapshot["input_sha256"] = ScopedProfitLedgerAuthority._hash(
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
    run_at = order_at + timedelta(hours=2)
    run = {
        "id": f"recon-{key}",
        "reconciliation_key": key,
        "quote_currency": "CNY",
        "fx_source": "bank-of-china",
        "tolerance_ratio": "0.003",
        "status": "matched",
        "snapshot": snapshot,
        "created_by": "independent-controller",
        "recorded_at": run_at.isoformat(),
        "source_evidence_sha256": ScopedProfitLedgerAuthority._hash(
            sorted(
                {
                    entry["source_evidence_sha256"]
                    for entry in entries
                }
            )
        ),
        "scope_as_of": run_at.isoformat(),
    }
    source = {
        "contract_id": "kjds-scoped-finance-read-source-v1",
        "as_of": AS_OF,
        "scope": {
            **SCOPE,
            "source_evidence_sha256": None,
            "as_of": AS_OF,
            "authority": "native",
        },
        "facts": facts,
        "entries": entries,
        "reconciliations": [run],
        "truncated": {
            "facts": False,
            "entries": False,
            "reconciliations": False,
        },
    }
    source["snapshot_sha256"] = ScopedProfitLedgerAuthority._hash(source)
    hashes["evidence-map-platform"] = "d" * 64
    authorities = {
        "contract_id": "kjds-scoped-profit-authority-source-v1",
        "as_of": AS_OF,
        "scope": source["scope"],
        "fee_mappings": [
            {
                "id": "mapping-platform-fee",
                "provider": "ozon",
                "raw_code": "platform_fee_total",
                "canonical_type": ChargeType.PLATFORM_FEE.value,
                "sign_rule": "absolute_outflow",
                "version": 1,
                "effective_from": (
                    order_at - timedelta(days=1)
                ).isoformat(),
                "effective_until": None,
                "evidence_id": "evidence-map-platform",
                "approved_by": "mapping-reviewer",
                "recorded_at": (
                    order_at - timedelta(hours=1)
                ).isoformat(),
                "source_evidence_sha256": hashes[
                    "evidence-map-platform"
                ],
                "scope_as_of": (
                    order_at - timedelta(hours=1)
                ).isoformat(),
            }
        ],
        "fx_rates": [],
        "truncated": {
            "fee_mappings": False,
            "fx_rates": False,
        },
    }
    authorities["snapshot_sha256"] = (
        ScopedProfitLedgerAuthority._hash(authorities)
    )
    return source, authorities, hashes


def authority_for(
    *,
    source: dict,
    authorities: dict,
    hashes: dict[str, str],
):
    finance = FakeFinance(source=source, authorities=authorities)
    evidence = FakeEvidence(hashes)
    scoped_evidence = FakeScopedEvidence()
    authority = ScopedProfitLedgerAuthority(
        engine=engine_with_product(),
        finance=finance,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    return authority, finance, evidence, scoped_evidence


def test_missing_entity_scope_returns_no_data_without_any_raw_read():
    finance = MustNotRead()
    result = ScopedProfitLedgerAuthority(
        engine=None,
        finance=finance,
        evidence=FakeEvidence({}),
        scoped_evidence=FakeScopedEvidence(),
    ).snapshot(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["rows"] == []
    assert result["control_envelope"]["scoped_input_read"] is False
    assert finance.calls == 0


def test_native_exact_scope_profit_is_deterministic_and_conserves():
    source, authorities, hashes = build_sources()
    authority, finance, _, _ = authority_for(
        source=source,
        authorities=authorities,
        hashes=hashes,
    )

    first = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )
    second = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )
    erosion = authority.erosion(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )

    assert first == second
    assert first["status"] == "reconciled"
    assert first["control_envelope"]["native_exact_scope"] is True
    assert first["control_envelope"]["legacy_order_charge_read"] is False
    assert first["rows"][0]["actual_profit"] == "80"
    assert first["rows"][0]["cm3"] == "80"
    assert len(first["rows"][0]["cost_legs"]) == 15
    assert first["rows"][0]["cost_coverage"]["unknown"] == 0
    assert first["rows"][0]["cash_conservation"]["conserved"] is True
    assert erosion["conserved"] is True
    assert erosion["baseline"] == "100"
    assert erosion["result"] == "80"
    assert finance.source_calls == 3
    assert finance.authority_calls == 3


def test_missing_fifteenth_cost_leg_fails_closed_without_business_values():
    source, authorities, hashes = build_sources(
        missing_cost_type=ChargeType.ADVERTISING,
    )
    authority, _, _, _ = authority_for(
        source=source,
        authorities=authorities,
        hashes=hashes,
    )

    result = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )
    serialized = str(result)

    assert result["status"] == "blocked"
    assert result["rows"] == []
    assert result["excluded"]["business_values_exposed"] is False
    assert (
        result["excluded"]["reason_counts"][
            "profit_cost_leg_unknown:advertising"
        ]
        == 1
    )
    assert "order-1" not in serialized
    assert "evidence-cost-product_cost" not in serialized
    assert "'80'" not in serialized


def test_bad_latest_order_evidence_does_not_fall_back_to_old_fact():
    source, authorities, hashes = build_sources(include_old_order=True)
    authority, _, evidence, _ = authority_for(
        source=source,
        authorities=authorities,
        hashes=hashes,
    )
    evidence.invalid_ids.add("evidence-order")

    result = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["rows"] == []
    assert result["excluded"]["reason_counts"]["profit_order_invalid"] == 1


def test_store_outside_principal_scope_is_forbidden_before_read():
    source, authorities, hashes = build_sources()
    authority, finance, _, _ = authority_for(
        source=source,
        authorities=authorities,
        hashes=hashes,
    )

    with pytest.raises(PermissionError):
        authority.snapshot(
            principal=principal(store_ref="other-store"),
            entity_scope=ENTITY_SCOPE,
            store_ref=SCOPE["store_ref"],
            as_of=AS_OF,
        )

    assert finance.source_calls == 0
    assert finance.authority_calls == 0


def test_cursor_is_stable_and_bound_to_current_result():
    source_a, authorities, hashes = build_sources(key="order-a")
    source_b, _, hashes_b = build_sources(key="order-b")
    source_a["facts"].extend(source_b["facts"])
    source_a["entries"].extend(source_b["entries"])
    source_a["reconciliations"].extend(source_b["reconciliations"])
    source_a["snapshot_sha256"] = ScopedProfitLedgerAuthority._hash(
        {
            key: value
            for key, value in source_a.items()
            if key != "snapshot_sha256"
        }
    )
    authority, _, _, _ = authority_for(
        source=source_a,
        authorities=authorities,
        hashes={**hashes, **hashes_b},
    )

    first = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
        page_size=1,
    )
    second = authority.snapshot(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref=SCOPE["store_ref"],
        as_of=AS_OF,
        page_size=1,
        cursor=first["pagination"]["next_cursor"],
    )

    assert len(first["rows"]) == 1
    assert len(second["rows"]) == 1
    assert first["rows"][0]["order_ref"] != second["rows"][0]["order_ref"]
