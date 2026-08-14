from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.control_plane.scoped_sourcing_intelligence import (
    ScopedSourcingIntelligenceWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sourcing import REQUIRED_COST_EVIDENCE_KEYS

AT = datetime(2026, 7, 29, 8, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": "a" * 64,
}
PROJECTED_SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}


def principal(stores=frozenset({"ozon-primary"})):
    return Principal(
        actor_id="operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


class Pim:
    def __init__(self, *, drift=False):
        self.calls = 0
        self.drift = drift

    def project(self, **_kwargs):
        self.calls += 1
        return {
            "contract_id": (
                "wrong"
                if self.drift
                else "kjds-native-exact-scope-pim-workspace-v1"
            ),
            "status": "ready",
            "as_of": AT.isoformat(),
            "scope": PROJECTED_SCOPE,
            "query": {"next_cursor": None},
            "counts": {
                "total_product_groups": 1,
                "page_product_groups": 1,
                "bound_listings": 1,
                "unbound_listings": 0,
                "ready": 1,
                "incomplete": 0,
                "blocked": 0,
            },
            "product_groups": [
                {
                    "product": {
                        "id": "product-1",
                        "sku": "CANON-1",
                        "name": "Canonical one",
                    },
                    "listings": [{"offer_id": "offer-1"}],
                    "passports": [
                        {"kind": "quality", "status": "approved"}
                    ],
                    "readiness": {"status": "ready"},
                    "owner": "pim-governance",
                    "group_snapshot_sha256": "2" * 64,
                }
            ],
            "unbound_listings": [],
            "source_gaps": [],
            "blockers": [],
            "snapshot_sha256": "1" * 64,
        }


def cohort(key="candidate-1"):
    return {
        "candidate_key": key,
        "product_identity": {"category": "test", "model": key},
        "variant_key": {"color": "black"},
        "counts": {
            "observation_rows": 5,
            "own_listing_rows": 1,
            "competitor_listing_rows": 1,
            "unique_competitor_sellers": 1,
            "supplier_option_rows": 3,
            "unique_supplier_identities": 3,
            "checkout_comparable_at_target": 3,
        },
        "own_listing_current_facts": [
            {
                "target_product_id": "product-1",
                "target_offer_id": "offer-1",
                "evidence_id": "market-evidence",
            }
        ],
        "competitor_price_bands": {"median": "100.00"},
        "supplier_price_bands_at_target": {"median": "20.00"},
        "target_purchase_quantity": 3,
        "source_grade_counts": {"B": 5},
        "freshness": {
            "status": "fresh",
            "oldest_observed_at": AT.isoformat(),
            "newest_observed_at": AT.isoformat(),
            "max_age_hours": 168,
        },
        "evidence_ids": ["market-evidence"],
    }


def candidate(key="candidate-1"):
    components = [
        {"name": name, "amount_cny": "1.00", "evidence_id": f"evd-{name}"}
        for name in sorted(REQUIRED_COST_EVIDENCE_KEYS)
    ]
    return {
        "candidate_key": key,
        "canonical_product_id": "product-1",
        "fingerprint": "f" * 64,
        "state": "evaluate",
        "identity_match": {
            "product_identity": {"category": "test", "model": key}
        },
        "economics": {
            "cost_evidence_complete": True,
            "downside": {
                "components": components,
                "cm3_cny": "10.00",
                "conservation_delta_cny": "0.00",
            },
        },
        "strategy": {"classification": "prove"},
        "blockers": ["independent_approval_missing"],
        "next_action": "collect evidence",
        "evidence_ids": ["market-evidence"],
        "invalid_evidence_ids": [],
        "eligible_for_approval": False,
        "pilot_ready": False,
    }


class ScopedBatch:
    def __init__(self, *, cohorts=None, candidates=None):
        self.radar_calls = 0
        self.latest_calls = 0
        self.cohorts = cohorts if cohorts is not None else [cohort()]
        self.candidates = (
            candidates if candidates is not None else [candidate()]
        )

    def market_radar(self, **_kwargs):
        self.radar_calls += 1
        return {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": "ready",
            "as_of": AT.isoformat(),
            "scope": PROJECTED_SCOPE,
            "counts": {
                "unique_exact_identities": len(self.cohorts),
                "competitor_listing_rows": len(self.cohorts),
                "supplier_option_rows": 3 * len(self.cohorts),
                "unique_supplier_identities": 3,
                "checkout_comparable_at_target": 3 * len(self.cohorts),
            },
            "cohorts": self.cohorts,
            "source_gaps": [],
            "blockers": [],
            "snapshot_sha256": "3" * 64,
        }

    def latest(self, **_kwargs):
        self.latest_calls += 1
        return {
            "contract_id": "kjds-scoped-batch-opportunity-v1",
            "status": "ready_with_constraints",
            "as_of": AT.isoformat(),
            "scope": {
                **PROJECTED_SCOPE,
                "scope_evidence_authority_sha256": "4" * 64,
            },
            "counts": {},
            "candidates": self.candidates,
            "source_gaps": [],
            "blockers": [],
            "scoped_snapshot_sha256": "5" * 64,
        }


def evidence(evidence_id, *, metadata=None):
    return SimpleNamespace(
        id=evidence_id,
        sha256=(evidence_id[-1] if evidence_id[-1].isalnum() else "e")
        * 64,
        metadata=metadata or {},
        effective_at=AT.isoformat(),
        effective_until=None,
    )


class Rfq:
    def __init__(self):
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return [
            {
                "evidence": evidence("rfq-1"),
                "package": {
                    "product": {"id": "product-1"},
                    "listing": {"offer_id": "offer-1"},
                    "buyer_requirement": {
                        "quantity_breaks": [3, 10],
                        "response_due_at": AT.isoformat(),
                    },
                    "unanswered_questions": ["price"],
                    "authority": {"status": "draft"},
                    "package_hash": "6" * 64,
                },
            }
        ]


class Dispatch:
    def __init__(self):
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return [
            {
                "evidence": evidence("dispatch-1"),
                "dispatch": {
                    "rfq": {
                        "product_id": "product-1",
                        "evidence_id": "rfq-1",
                    },
                    "supplier": {
                        "supplier_ref": "supplier-1",
                        "platform": "1688",
                    },
                },
                "status": "accepted",
                "delivery_confirmed": False,
            }
        ]


class Quotes:
    def __init__(self):
        self.calls = 0

    def list(self, **_kwargs):
        self.calls += 1
        return [
            {
                "evidence": evidence(
                    f"quote-{index}",
                    metadata={
                        "product_id": "product-1",
                        "supplier_ref": f"supplier-{index}",
                        "document_kind": "supplier_confirmed_quote",
                        "offer_data": {
                            "currency": "CNY",
                            "unit_price": f"{20 + index}.00",
                            "min_order_quantity": 3,
                        },
                    },
                ),
                "status": "accepted",
                "formal_offer_eligible": True,
            }
            for index in range(1, 4)
        ]


class ScopedEvidence:
    def __init__(self, *, status="ready"):
        self.calls = 0
        self.status = status

    def project_targets(self, *, evidence_ids, **_kwargs):
        self.calls += 1
        return {
            "contract_id": "kjds-scoped-evidence-authority-v1",
            "status": self.status,
            "records": [
                {
                    "evidence_id": evidence_id,
                    "scope_binding": {
                        "status": (
                            "ready" if self.status == "ready" else "unbound"
                        )
                    },
                }
                for evidence_id in evidence_ids
            ],
            "invalid_evidence_ids": [],
            "binding_authority_sha256": (
                "7" * 64 if self.status == "ready" else None
            ),
            "source_gaps": (
                [] if self.status == "ready"
                else ["evidence_scope_binding_missing"]
            ),
            "blockers": [],
        }


def workspace(**overrides):
    values = {
        "pim": Pim(),
        "scoped_batch": ScopedBatch(),
        "scoped_evidence": ScopedEvidence(),
        "supplier_rfq": Rfq(),
        "supplier_rfq_dispatch": Dispatch(),
        "supplier_quote_authority": Quotes(),
    }
    values.update(overrides)
    return ScopedSourcingIntelligenceWorkspace(**values), values


def test_missing_entity_performs_zero_upstream_and_raw_reads():
    service, values = workspace()
    result = service.project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "no_data"
    assert result["control_envelope"]["scoped_input_read"] is False
    assert values["pim"].calls == 0
    assert values["scoped_batch"].radar_calls == 0
    assert values["supplier_rfq"].calls == 0
    assert values["scoped_evidence"].calls == 0


def test_projects_research_rfq_three_quotes_and_fifteen_costs():
    service, _ = workspace()
    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "ready"
    assert result["counts"]["canonical_products"] == 1
    assert result["counts"]["exact_research_cohorts"] == 1
    assert result["counts"]["accepted_quotes"] == 3
    assert result["counts"]["products_with_three_accepted_quotes"] == 1
    assert result["counts"]["fifteen_component_downside_ready"] == 1
    item = result["work_items"][0]
    assert item["readiness"] == {
        "status": "ready",
        "market_research_ready": True,
        "canonical_product_bound": True,
        "rfq_draft_ready": True,
        "three_accepted_quotes_ready": True,
        "fifteen_component_downside_ready": True,
    }
    assert len(item["economics"]["downside"]["components"]) == 15
    assert item["economics"]["formal_cm3"] is None
    assert item["economics"]["actual_cash_cm3"] is None
    assert result["control_envelope"]["rfq_dispatched"] is False
    assert result["control_envelope"]["purchase_order_created"] is False
    assert result["agent_artifact"]["self_approval_allowed"] is False
    assert result["agent_artifact"]["permit_issue_allowed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_upstream_contract_drift_blocks_before_batch_or_artifact_read():
    service, values = workspace(pim=Pim(drift=True))
    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "blocked"
    assert result["work_items"] == []
    assert "pim_contract_conflict" in result["source_gaps"]
    assert values["scoped_batch"].radar_calls == 0
    assert values["supplier_rfq"].calls == 0


def test_unbound_quote_or_rfq_evidence_fails_closed_without_payload():
    service, _ = workspace(scoped_evidence=ScopedEvidence(status="partial"))
    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "blocked"
    assert result["work_items"] == []
    assert "sourcing_evidence_not_exact_scope" in result["source_gaps"]
    assert result["counts"]["quote_evidence"] == 0


def test_filter_cursor_and_snapshot_are_deterministic():
    batch = ScopedBatch(
        cohorts=[cohort("candidate-1"), cohort("candidate-2")],
        candidates=[candidate("candidate-1"), candidate("candidate-2")],
    )
    service, _ = workspace(scoped_batch=batch)
    first = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
        readiness="downside",
    )
    replay = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
        readiness="downside",
    )
    assert first["snapshot_sha256"] == replay["snapshot_sha256"]
    assert first["counts"]["total_work_items"] == 2
    assert first["counts"]["page_work_items"] == 1
    assert first["query"]["next_cursor"]
    second = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
        readiness="downside",
        cursor=first["query"]["next_cursor"],
    )
    assert second["work_items"][0]["candidate_key"] == "candidate-2"
    with pytest.raises(ValueError, match="cursor"):
        service.project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=AT,
            cursor="bad",
        )


def test_invalid_ready_entity_and_unauthorized_store_fail_before_reads():
    service, values = workspace()
    invalid = service.project(
        principal=principal(),
        entity_scope={
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": None,
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert invalid["status"] == "blocked"
    assert invalid["scope"]["entity_ref"] is None
    assert values["pim"].calls == 0
    with pytest.raises(PermissionError):
        service.project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="other-store",
            as_of=AT,
        )
