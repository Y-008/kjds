from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.control_plane.api_contracts import SupplierCandidateRfqPackageInput
from apps.control_plane.domain import Product, ProductStatus
from apps.control_plane.routers import procurement_supply
from apps.control_plane.security import Principal
from apps.control_plane.supplier_rfq import candidate_product_snapshot_sha256


def _product() -> Product:
    return Product(
        id="prd-d10-q200",
        sku="KJDS-OZ-RU-RCAP-D10-BLK-Q200-R01",
        name="D10 x 20 black caps, 200 pieces",
        status=ProductStatus.CANDIDATE,
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        scope_grant_authority_sha256="f" * 64,
        scope_as_of="2026-08-14T00:00:00+00:00",
        created_by="operator-a",
    )


def _body(product: Product) -> SupplierCandidateRfqPackageInput:
    return SupplierCandidateRfqPackageInput(
        store_ref="store-a",
        product_id=product.id,
        expected_product_snapshot_sha256=(
            candidate_product_snapshot_sha256(product)
        ),
        source_evidence_ids=["evd-research"],
        idempotency_key="d10-q200-rfq-v1",
        quantity_breaks=[200, 500],
        required_specifications=[
            {"name": "inner_diameter_mm", "required_value": "10"},
            {"name": "length_mm", "required_value": "20"},
        ],
        destination="Yiwu consolidation warehouse",
        response_due_at="2026-08-20T00:00:00+00:00",
        sample_required=True,
        tax_invoice_required=False,
        required_documents=["variant photo"],
        packaging_requirements=["200 pieces per package"],
        confirmed=True,
    )


def _principal() -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def _runtime(product: Product, *, projection: dict, create):
    return SimpleNamespace(
        scope_grants=SimpleNamespace(
            current=lambda **_values: {
                "status": "ready",
                "entity_ref": "entity-a",
            }
        ),
        repo=SimpleNamespace(get_product=lambda _product_id: product),
        scoped_evidence=SimpleNamespace(
            project_targets=lambda **_values: projection
        ),
        supplier_rfq=SimpleNamespace(create_for_candidate_product=create),
    )


def test_candidate_rfq_api_rejects_unbound_source_evidence(monkeypatch) -> None:
    product = _product()

    def must_not_create(**_values):
        raise AssertionError("unbound Evidence must not reach RFQ creation")

    monkeypatch.setattr(
        procurement_supply,
        "runtime",
        _runtime(
            product,
            projection={
                "contract_id": "kjds-scoped-evidence-authority-v1",
                "status": "partial",
                "evidence_ids": ["evd-research"],
                "snapshot_sha256": "a" * 64,
                "binding_authority_sha256": None,
            },
            create=must_not_create,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        procurement_supply.create_supplier_candidate_rfq_package(
            _body(product),
            _principal(),
        )

    assert getattr(exc_info.value, "status_code", None) == 422
    assert "not fully bound" in str(getattr(exc_info.value, "detail", ""))


def test_candidate_rfq_api_freezes_scoped_evidence_authority(monkeypatch) -> None:
    product = _product()
    captured = {}

    @dataclass
    class Evidence:
        id: str

    def create(**values):
        captured.update(values)
        return {
            "evidence": Evidence("evd-rfq"),
            "package": {"authority": {"status": "draft"}},
            "idempotent": False,
        }

    monkeypatch.setattr(
        procurement_supply,
        "runtime",
        _runtime(
            product,
            projection={
                "contract_id": "kjds-scoped-evidence-authority-v1",
                "status": "ready",
                "evidence_ids": ["evd-binding", "evd-research"],
                "snapshot_sha256": "a" * 64,
                "binding_authority_sha256": "b" * 64,
            },
            create=create,
        ),
    )

    result = procurement_supply.create_supplier_candidate_rfq_package(
        _body(product),
        _principal(),
    )

    assert result["evidence"] == {"id": "evd-rfq"}
    assert captured["source_scope_authority"] == {
        "contract_id": "kjds-scoped-evidence-authority-v1",
        "status": "ready",
        "target_evidence_ids": ["evd-research"],
        "projected_evidence_ids": ["evd-binding", "evd-research"],
        "snapshot_sha256": "a" * 64,
        "binding_authority_sha256": "b" * 64,
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "as_of": captured["source_scope_authority"]["as_of"],
    }
    assert captured["source_scope_authority"]["as_of"].endswith("+00:00")
