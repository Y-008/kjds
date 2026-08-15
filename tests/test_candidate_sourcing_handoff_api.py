from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.control_plane.api_contracts import CandidateSourcingHandoffInput
from apps.control_plane.routers import product_content
from apps.control_plane.security import Principal


def _principal() -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def _body() -> CandidateSourcingHandoffInput:
    return CandidateSourcingHandoffInput(
        candidate_ref="candidate://d10-q200",
        candidate_name="D10 x 20 black caps, 200 pieces",
        market="RU",
        category="bolt_end_caps",
        as_of="2026-08-14T00:00:00+00:00",
        demand_report_evidence_id="evd-demand-report",
        sku="KJDS-OZ-RU-RCAP-D10-BLK-Q200-R01",
        store_ref="store-a",
        confirmed=True,
    )


def test_candidate_handoff_api_requires_current_entity_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        product_content,
        "runtime",
        SimpleNamespace(
            scope_grants=SimpleNamespace(
                current=lambda **_values: {
                    "status": "no_data",
                    "entity_ref": None,
                    "reason": "entity_scope_authority_missing",
                }
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        product_content.handoff_candidate_to_sourcing(
            _body(),
            _principal(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "entity_scope_authority_missing"


def test_candidate_handoff_api_passes_stable_scope_authority(monkeypatch) -> None:
    captured = {}
    links = []

    def handoff(**values):
        captured.update(values)
        return {
            "product": SimpleNamespace(id="prd-d10-q200"),
            "created": True,
            "candidate_ref": values["candidate_ref"],
            "demand_report_evidence_id": values[
                "demand_report_evidence_id"
            ],
            "evidence_ids": ["evd-demand", "evd-supplier"],
            "operating_scope": {
                key: values[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "scope_grant_authority_sha256",
                    "scope_as_of",
                )
            },
            "next_gate": "prelisting_supplier_rfq",
            "next_api_path": "/v1/sourcing/candidate-rfq-packages",
            "automatic_procurement": False,
            "automatic_listing": False,
        }

    monkeypatch.setattr(
        product_content,
        "runtime",
        SimpleNamespace(
            scope_grants=SimpleNamespace(
                current=lambda **_values: {
                    "status": "ready",
                    "entity_ref": "entity-a",
                    "authority_sha256": "a" * 64,
                    "grant_effective_at": "2026-08-01T00:00:00+00:00",
                }
            ),
            market=SimpleNamespace(
                handoff_candidate_to_sourcing=handoff
            ),
            evidence=SimpleNamespace(
                link=lambda **values: links.append(values)
            ),
        ),
    )

    result = product_content.handoff_candidate_to_sourcing(
        _body(),
        _principal(),
    )

    assert result["created"] is True
    assert captured["tenant_ref"] == "tenant-a"
    assert captured["entity_ref"] == "entity-a"
    assert captured["store_ref"] == "store-a"
    assert captured["scope_grant_authority_sha256"] == "a" * 64
    assert captured["scope_as_of"] == "2026-08-01T00:00:00+00:00"
    assert captured["confirmed_by"] == "operator-a"
    assert len(links) == 3
    assert {item["relationship"] for item in links} == {
        "candidate_basis",
        "demand_report_basis",
    }
