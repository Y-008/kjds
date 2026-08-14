from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.accounts_payable import (
    AccountsPayableAuthorityService,
    SupplierInvoiceLineRow,
    SupplierInvoiceRow,
)
from apps.control_plane.finance import FinanceEntryRow
from apps.control_plane.scoped_accounts_payable import (
    ScopedAccountsPayableWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

AS_OF = "2026-07-30T12:00:00+00:00"
AUTHORITY = "a" * 64
EVIDENCE_SHA = "e" * 64
SCOPE = {
    "tenant_ref": "tenant-cn-1",
    "entity_ref": "entity-cn-1",
    "store_ref": "store-cn-1",
    "scope_grant_authority_sha256": AUTHORITY,
}
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": "entity-cn-1",
    "authority_sha256": AUTHORITY,
}


def principal(
    *,
    stores: frozenset[str] = frozenset({"store-cn-1"}),
) -> Principal:
    return Principal(
        actor_id="ap-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=stores,
    )


def with_hash(payload: dict) -> dict:
    result = copy.deepcopy(payload)
    result["snapshot_sha256"] = ScopedAccountsPayableWorkspace._hash(
        result
    )
    return result


def invoice(number: int = 1) -> dict:
    return {
        "id": f"invoice-{number}",
        "invoice_ref": f"INV-{number:03d}",
        "purchase_order_id": f"order-{number}",
        "supplier_ref": f"supplier-{number}",
        "currency": "CNY",
        "net_amount": "125.000000000000",
        "tax_amount": "0E-12",
        "gross_amount": "125.000000000000",
        "issued_at": f"2026-07-{20 + number:02d}T00:00:00+00:00",
        "due_at": "2026-08-20T00:00:00+00:00",
        "evidence_id": f"invoice-evidence-{number}",
        "payload_sha256": f"{number:x}" * 64,
        "created_by": "invoice-uploader",
        "recorded_at": f"2026-07-{20 + number:02d}T00:01:00+00:00",
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": f"2026-07-{20 + number:02d}T00:00:00+00:00",
    }


def line(number: int = 1) -> dict:
    return {
        "id": f"invoice-line-{number}",
        "invoice_id": f"invoice-{number}",
        "line_number": 1,
        "product_id": "product-1",
        "description": "sample goods",
        "quantity": "10.000000000000",
        "unit_price": "12.500000000000",
        "net_amount": "125.000000000000",
        "tax_amount": "0E-12",
        "gross_amount": "125.000000000000",
        "evidence_id": f"invoice-evidence-{number}",
        "recorded_at": f"2026-07-{20 + number:02d}T00:01:00+00:00",
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": f"2026-07-{20 + number:02d}T00:00:00+00:00",
    }


def ap_source(*numbers: int) -> dict:
    return with_hash(
        {
            "contract_id": "kjds-scoped-accounts-payable-read-source-v1",
            "as_of": AS_OF,
            "scope": SCOPE,
            "invoices": [invoice(item) for item in numbers],
            "lines": [line(item) for item in numbers],
            "truncated": {"invoices": False, "lines": False},
        }
    )


def finance_source() -> dict:
    return with_hash(
        {
            "contract_id": "kjds-scoped-finance-read-source-v1",
            "as_of": AS_OF,
            "scope": SCOPE,
            "facts": [],
            "entries": [],
            "reconciliations": [],
            "truncated": {
                "facts": False,
                "entries": False,
                "reconciliations": False,
            },
        }
    )


def procurement_projection(number: int) -> dict:
    order = {
        "purchase_order_id": f"order-{number}",
        "product": {
            "id": "product-1",
            "sku": "SKU-1",
            "name": "Product 1",
        },
        "supplier_ref": f"supplier-{number}",
        "quantity": 10,
        "currency": "CNY",
        "unit_price": "12.5",
        "order_value": "125",
        "created_at": "2026-07-18T00:00:00+00:00",
        "stage": "golden_sample_approved",
        "latest_effective_at": "2026-07-20T00:00:00+00:00",
        "receipt": {
            "ordered_quantity": 10,
            "received_quantity": 10,
            "damaged_quantity": 0,
            "inspected_quantity": 10,
            "passed_quantity": 10,
            "defect_count": 0,
            "quantity_conserved": True,
        },
        "decision_basis": {
            "approval_id": f"procurement-approval-{number}",
            "approval_status": "approved",
            "independent_approval": True,
            "offer_id": f"offer-{number}",
            "scenario_id": f"scenario-{number}",
            "expected_cm3_cny": "20",
            "cost_evidence_complete": True,
            "authority_evidence_id": f"order-evidence-{number}",
        },
    }
    return with_hash(
        {
            "contract_id": (
                "kjds-native-exact-scope-procurement-receiving-workspace-v1"
            ),
            "status": "ready",
            "as_of": AS_OF,
            "scope": SCOPE,
            "orders": [order],
        }
    )


def review_record(number: int, *, decision: str = "accepted"):
    checks = {
        "authentic_original": True,
        "legal_entity_matches": True,
        "supplier_matches": True,
        "purchase_order_matches": True,
        "receipt_inspection_matches": True,
        "line_quantity_price_matches": True,
        "currency_tax_total_matches": True,
    }
    return SimpleNamespace(
        id=f"review-evidence-{number}",
        source="supplier_invoice_authority_review",
        effective_at=f"2026-07-{22 + number:02d}T00:00:00+00:00",
        recorded_at=f"2026-07-{22 + number:02d}T00:01:00+00:00",
        created_by="invoice-reviewer",
        metadata={
            "contract_id": "kjds-supplier-invoice-authority-review-v1",
            "invoice_id": f"invoice-{number}",
            "invoice_payload_sha256": invoice(number)["payload_sha256"],
            "invoice_evidence_id": f"invoice-evidence-{number}",
            "invoice_evidence_sha256": EVIDENCE_SHA,
            **SCOPE,
            "decision": decision,
            "submitted_by": "invoice-uploader",
            "reviewed_by": "invoice-reviewer",
            "rationale": "verified",
            "checks": checks,
        },
    )


class FakeSource:
    def __init__(self, source: dict) -> None:
        self.source = source
        self.calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        return copy.deepcopy(self.source)


class MustNotRead:
    def __init__(self) -> None:
        self.calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        raise AssertionError("source must not be read")


class FakeProcurement:
    def __init__(self) -> None:
        self.calls = 0

    def project(self, *, query: str, **_values):
        self.calls += 1
        return procurement_projection(int(query.split("-")[-1]))


class FakeEvidence:
    def __init__(
        self,
        *,
        invalid_ids: set[str] | None = None,
        decisions: dict[int, str] | None = None,
    ) -> None:
        self.invalid_ids = invalid_ids or set()
        self.decisions = decisions or {}

    def verify(self, evidence_id: str):
        return SimpleNamespace(
            valid=evidence_id not in self.invalid_ids,
            expected_sha256=EVIDENCE_SHA,
        )

    def target_evidence_ids(self, *, target_id: str, **_values):
        number = int(target_id.split("-")[-1])
        return [f"review-evidence-{number}"]

    def require_current(self, evidence_ids: list[str], **_values):
        if any(item in self.invalid_ids for item in evidence_ids):
            raise ValueError("invalid Evidence")

    def get(self, evidence_id: str):
        number = int(evidence_id.split("-")[-1])
        return review_record(
            number,
            decision=self.decisions.get(number, "accepted"),
        )


class FakeScopedEvidence:
    def project_targets(self, *, evidence_ids: list[str], **_values):
        return {
            "status": "ready",
            "records": [
                {
                    "evidence_id": evidence_id,
                    "scope_binding": {"status": "ready"},
                }
                for evidence_id in evidence_ids
            ],
        }


class FakeRepository:
    def get_approval_at(self, *_args, **_values):
        raise KeyError("no payment approvals")


def workspace(
    *,
    source: dict,
    evidence: FakeEvidence | None = None,
    finance: dict | None = None,
) -> ScopedAccountsPayableWorkspace:
    return ScopedAccountsPayableWorkspace(
        engine=create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        ),
        accounts_payable=FakeSource(source),
        scoped_procurement_receiving=FakeProcurement(),
        finance=FakeSource(finance or finance_source()),
        repository=FakeRepository(),
        evidence=evidence or FakeEvidence(),
        scoped_evidence=FakeScopedEvidence(),
    )


def test_missing_entity_scope_reads_no_raw_sources():
    accounts_payable = MustNotRead()
    finance = MustNotRead()
    result = ScopedAccountsPayableWorkspace(
        engine=None,
        accounts_payable=accounts_payable,
        scoped_procurement_receiving=object(),
        finance=finance,
        repository=object(),
        evidence=object(),
        scoped_evidence=object(),
    ).project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["control_envelope"]["scoped_input_read"] is False
    assert accounts_payable.calls == 0
    assert finance.calls == 0


def test_verified_invoice_projects_server_three_way_match():
    result = workspace(source=ap_source(1)).project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "ready"
    assert result["counts"]["total"] == 1
    row = result["invoices"][0]
    assert row["stage"] == "payment_approval_pending"
    assert row["three_way_match"]["matched"] is True
    assert row["amounts"]["open"] == "125"
    assert row["payment_control"]["adapter_enabled"] is False
    assert result["control_envelope"]["external_write_allowed"] is False
    assert result["agent_artifact"]["self_approval_allowed"] is False
    assert result["agent_artifact"]["permit_issue_allowed"] is False


def test_bad_latest_review_evidence_fails_closed():
    result = workspace(
        source=ap_source(1),
        evidence=FakeEvidence(invalid_ids={"review-evidence-1"}),
    ).project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["invoices"] == []
    assert result["excluded"]["business_values_exposed"] is False
    assert (
        "supplier_invoice_latest_review_evidence_invalid"
        in result["excluded"]["reason_counts"]
    )


def test_rejected_latest_review_is_explicit_not_paid():
    result = workspace(
        source=ap_source(1),
        evidence=FakeEvidence(decisions={1: "rejected"}),
    ).project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "ready"
    assert result["invoices"][0]["stage"] == "rejected"
    assert result["invoices"][0]["amounts"]["paid"] == "0"


def test_three_way_quantity_mismatch_remains_pending():
    source = ap_source(1)
    source["lines"][0]["quantity"] = "9.000000000000"
    source["lines"][0]["net_amount"] = "125.000000000000"
    source["snapshot_sha256"] = ScopedAccountsPayableWorkspace._hash(
        {
            key: value
            for key, value in source.items()
            if key != "snapshot_sha256"
        }
    )
    result = workspace(source=source).project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "ready"
    row = result["invoices"][0]
    assert row["stage"] == "three_way_match_pending"
    assert row["three_way_match"]["checks"]["quantity_matches"] is False


def test_cross_store_is_forbidden_before_source_reads():
    accounts_payable = MustNotRead()
    with pytest.raises(PermissionError):
        ScopedAccountsPayableWorkspace(
            engine=None,
            accounts_payable=accounts_payable,
            scoped_procurement_receiving=object(),
            finance=object(),
            repository=object(),
            evidence=object(),
            scoped_evidence=object(),
        ).project(
            principal=principal(stores=frozenset({"other-store"})),
            entity_scope=ENTITY_SCOPE,
            store_ref="store-cn-1",
            as_of=AS_OF,
        )
    assert accounts_payable.calls == 0


def test_stable_filter_and_cursor_are_server_authoritative():
    service = workspace(source=ap_source(1, 2))
    first = service.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
        page_size=1,
    )
    repeated = service.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
        page_size=1,
    )
    second = service.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
        page_size=1,
        cursor=first["pagination"]["next_cursor"],
    )
    filtered = service.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
        query="inv-001",
    )

    assert first["snapshot_sha256"] == repeated["snapshot_sha256"]
    assert first["invoices"][0]["invoice_id"] == "invoice-2"
    assert second["invoices"][0]["invoice_id"] == "invoice-1"
    assert filtered["counts"]["filtered"] == 1


def test_database_rejects_invalid_invoice_scope_and_partial_payment_binding():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            SupplierInvoiceRow(
                id="invoice-invalid",
                invoice_ref="INV-X",
                purchase_order_id="missing-order",
                supplier_ref="supplier-1",
                currency="CNY",
                net_amount=125,
                tax_amount=0,
                gross_amount=125,
                issued_at=now,
                due_at=now,
                evidence_id="missing-evidence",
                payload_sha256="1" * 64,
                created_by="operator",
                recorded_at=now,
                tenant_ref="tenant-cn-1",
                entity_ref="entity-cn-1",
                store_ref="store-cn-1",
                scope_grant_authority_sha256="short",
                source_evidence_sha256=EVIDENCE_SHA,
                scope_as_of=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(
            FinanceEntryRow(
                id="fin-invalid",
                entry_kind="bank_payment",
                source="bank",
                source_ref="payment-1",
                reconciliation_key="invoice-1",
                raw_fee_code=None,
                profit_cost_type="product_cost",
                amount=-10,
                currency="CNY",
                effective_at=now,
                evidence_id="missing-evidence",
                source_fact_id=None,
                supplier_invoice_id="invoice-1",
                supplier_ref=None,
                payment_approval_id=None,
                payment_command_id=None,
                review_required=False,
                created_by="operator",
                recorded_at=now,
                tenant_ref="tenant-cn-1",
                entity_ref="entity-cn-1",
                store_ref="store-cn-1",
                scope_grant_authority_sha256=AUTHORITY,
                source_evidence_sha256=EVIDENCE_SHA,
                scope_as_of=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_line_table_requires_positive_quantity():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            SupplierInvoiceLineRow(
                id="line-invalid",
                invoice_id="missing-invoice",
                line_number=1,
                product_id="missing-product",
                description="invalid",
                quantity=0,
                unit_price=1,
                net_amount=0,
                tax_amount=0,
                gross_amount=0,
                evidence_id="missing-evidence",
                recorded_at=now,
                tenant_ref="tenant-cn-1",
                entity_ref="entity-cn-1",
                store_ref="store-cn-1",
                scope_grant_authority_sha256=AUTHORITY,
                source_evidence_sha256=EVIDENCE_SHA,
                scope_as_of=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_accounts_payable_source_read_is_exact_and_deterministic():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 29, tzinfo=UTC)
    with Session(engine) as session:
        for suffix, store_ref, authority in (
            ("a", "store-cn-1", AUTHORITY),
            ("b", "other-store", "b" * 64),
        ):
            invoice_row = SupplierInvoiceRow(
                id=f"invoice-{suffix}",
                invoice_ref="INV-SHARED",
                purchase_order_id=f"order-{suffix}",
                supplier_ref="supplier-shared",
                currency="CNY",
                net_amount=125,
                tax_amount=0,
                gross_amount=125,
                issued_at=now,
                due_at=datetime(2026, 8, 29, tzinfo=UTC),
                evidence_id=f"evidence-{suffix}",
                payload_sha256=suffix * 64,
                created_by="operator",
                recorded_at=now,
                tenant_ref="tenant-cn-1",
                entity_ref="entity-cn-1",
                store_ref=store_ref,
                scope_grant_authority_sha256=authority,
                source_evidence_sha256=EVIDENCE_SHA,
                scope_as_of=now,
            )
            session.add(invoice_row)
            session.add(
                SupplierInvoiceLineRow(
                    id=f"line-{suffix}",
                    invoice_id=invoice_row.id,
                    line_number=1,
                    product_id=f"product-{suffix}",
                    description="sample",
                    quantity=10,
                    unit_price=12.5,
                    net_amount=125,
                    tax_amount=0,
                    gross_amount=125,
                    evidence_id=f"evidence-{suffix}",
                    recorded_at=now,
                    tenant_ref="tenant-cn-1",
                    entity_ref="entity-cn-1",
                    store_ref=store_ref,
                    scope_grant_authority_sha256=authority,
                    source_evidence_sha256=EVIDENCE_SHA,
                    scope_as_of=now,
                )
            )
        session.commit()

    service = AccountsPayableAuthorityService(
        engine=engine,
        evidence=object(),
        scoped_evidence=object(),
    )
    values = {
        "tenant_ref": "tenant-cn-1",
        "entity_ref": "entity-cn-1",
        "store_ref": "store-cn-1",
        "scope_grant_authority_sha256": AUTHORITY,
        "as_of": AS_OF,
    }
    first = service.read_scoped_sources(**values)
    repeated = service.read_scoped_sources(**values)

    assert [item["id"] for item in first["invoices"]] == ["invoice-a"]
    assert [item["id"] for item in first["lines"]] == ["line-a"]
    assert first["scope"] == SCOPE
    assert first["snapshot_sha256"] == repeated["snapshot_sha256"]
