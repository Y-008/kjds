from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .finance import ACTUAL_PROFIT_COST_TYPES
from .scoped_profit_ledger import (
    CM1_VALUES,
    CM2_VALUES,
    COST_ORDER,
    ScopedProfitLedgerAuthority,
)


class ProfitCostEvidenceConflict(ValueError):
    """Raised when an immutable evidence identity is reused with different content."""


class ProfitCostEvidenceInvariantError(ValueError):
    """Raised when an input cannot be projected without inventing business meaning."""


@dataclass(frozen=True, slots=True)
class CostEvidenceRequirement:
    cost_type: str
    profit_stage: str
    owner: str
    required_document: str
    required_formula_inputs: tuple[str, ...]


_REQUIREMENT_DETAILS = {
    "product_cost": (
        "supply-chain-finance",
        "approved supplier invoice or reconciled supplier payment",
        ("unit_purchase_price", "purchased_quantity"),
    ),
    "domestic_logistics": (
        "logistics-finance",
        "domestic carrier invoice and shipment weight statement",
        ("chargeable_weight_kg", "domestic_rate"),
    ),
    "international_logistics": (
        "logistics-finance",
        "international forwarder invoice and route charge statement",
        ("chargeable_weight_kg", "route_rate"),
    ),
    "packaging": (
        "fulfillment-finance",
        "packaging material issue or supplier invoice",
        ("packaging_unit_cost", "packed_quantity"),
    ),
    "warehousing": (
        "fulfillment-finance",
        "warehouse billing statement",
        ("storage_unit_rate", "storage_quantity", "storage_days"),
    ),
    "customs": (
        "customs-compliance",
        "customs declaration and duty receipt",
        ("customs_value", "duty_rate"),
    ),
    "tax": (
        "tax-control",
        "tax invoice, return, or assessed tax statement",
        ("tax_base", "tax_rate"),
    ),
    "last_mile": (
        "marketplace-finance",
        "platform last-mile charge statement",
        ("chargeable_weight_kg", "last_mile_rate"),
    ),
    "platform_fee": (
        "marketplace-finance",
        "approved platform fee mapping and settlement statement",
        ("gross_sales_amount", "commission_rate"),
    ),
    "advertising": (
        "growth-finance",
        "attributed advertising spend statement",
        ("attributed_ad_spend", "attributed_order_quantity"),
    ),
    "return": (
        "returns-finance",
        "return disposition and processing charge statement",
        ("return_count", "return_processing_cost"),
    ),
    "fx": (
        "treasury-control",
        "bank or payment-provider FX fee statement",
        ("source_amount", "fx_spread_or_fee"),
    ),
    "capital_cost": (
        "finance-control",
        "approved working-capital allocation statement",
        ("occupied_cash_amount", "annualized_rate", "occupied_days"),
    ),
    "customer_compensation": (
        "customer-finance",
        "approved customer compensation record",
        ("compensation_amount",),
    ),
    "damage": (
        "inventory-control",
        "damage report and inventory write-off approval",
        ("damaged_quantity", "loss_per_unit"),
    ),
}


def _profit_stage(cost_type: str) -> str:
    if cost_type in CM1_VALUES:
        return "cm1"
    if cost_type in CM2_VALUES:
        return "cm2"
    return "cm3"


COST_REQUIREMENTS = tuple(
    CostEvidenceRequirement(
        cost_type=item.value,
        profit_stage=_profit_stage(item.value),
        owner=_REQUIREMENT_DETAILS[item.value][0],
        required_document=_REQUIREMENT_DETAILS[item.value][1],
        required_formula_inputs=_REQUIREMENT_DETAILS[item.value][2],
    )
    for item in COST_ORDER
)
_COST_BY_TYPE = {item.cost_type: item for item in COST_REQUIREMENTS}
_COST_INDEX = {item.cost_type: index for index, item in enumerate(COST_REQUIREMENTS)}
_LEVEL_RANK = {"missing": 0, "observed": 1, "reviewed": 2, "actual": 3}
_BOOKS = ("scenario", "accrual", "settlement", "cash")

if len(COST_REQUIREMENTS) != 15:
    raise RuntimeError("Profit cost evidence registry must contain exactly fifteen legs")
if set(_COST_BY_TYPE) != {item.value for item in ACTUAL_PROFIT_COST_TYPES}:
    raise RuntimeError("Profit cost evidence registry drifted from the actual profit ledger")


class ProfitCostEvidenceWorkspace:
    """Project evidence coverage without calculating profit or writing formal facts.

    The single interface accepts already-retained, exact-scope SKU evidence. It only
    classifies evidence readiness. The existing scoped profit ledger remains the
    sole authority that can certify an ``actual`` cost leg.
    """

    CONTRACT_ID = "kjds-profit-cost-evidence-readiness-v1"
    REGISTRY_VERSION = "profit-cost-evidence/1.0.0"
    ACTUAL_AUTHORITY_CONTRACT_ID = ScopedProfitLedgerAuthority.CONTRACT_ID

    def project(
        self,
        *,
        scope: dict[str, Any],
        sku_inputs: list[dict[str, Any]],
        as_of: datetime | str,
    ) -> dict[str, Any]:
        normalized_scope = self._scope(scope)
        cutoff = self._timestamp(as_of, "as_of")
        normalized_inputs, duplicate_count = self._deduplicate_skus(
            sku_inputs,
            scope=normalized_scope,
        )
        sku_results = [
            self._project_sku(item, scope=normalized_scope, as_of=cutoff)
            for item in normalized_inputs
        ]
        sku_results.sort(key=lambda item: item["sku"])

        request_queue = sorted(
            (
                request
                for item in sku_results
                for request in item["evidence_requests"]
            ),
            key=lambda item: (
                item["priority_rank"],
                item["sku"],
                item["cost_order"],
                item["request_id"],
            ),
        )
        status_counts = Counter(
            leg["status"]
            for item in sku_results
            for leg in item["cost_coverage"]["legs"]
        )
        input_payload = {
            "scope": normalized_scope,
            "as_of": cutoff.isoformat(),
            "sku_inputs": normalized_inputs,
        }
        input_sha256 = self._hash(input_payload)
        blocked_skus = sum(
            item["pilot_gate"]["status"] == "blocked" for item in sku_results
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "registry_version": self.REGISTRY_VERSION,
            "status": (
                "no_data"
                if not sku_results
                else "blocked"
                if blocked_skus
                else "ready_for_profit_validation"
            ),
            "scope": normalized_scope,
            "as_of": cutoff.isoformat(),
            "cost_registry": [self._requirement_payload(item) for item in COST_REQUIREMENTS],
            "summary": {
                "sku_count": len(sku_results),
                "required_cost_legs_per_sku": len(COST_REQUIREMENTS),
                "evaluated_cost_legs": len(sku_results) * len(COST_REQUIREMENTS),
                "coverage_status_counts": {
                    level: status_counts[level] for level in _LEVEL_RANK
                },
                "pilot_blocked_skus": blocked_skus,
                "evidence_request_count": len(request_queue),
                "duplicate_sku_inputs": duplicate_count,
            },
            "skus": sku_results,
            "evidence_request_queue": request_queue,
            "input_sha256": input_sha256,
            "control_envelope": {
                "read_only_projection": True,
                "database_writes_performed": False,
                "formal_facts_promoted": False,
                "profit_calculation_performed": False,
                "missing_costs_imputed": False,
                "cross_currency_aggregation_performed": False,
                "actual_authority_contract_id": self.ACTUAL_AUTHORITY_CONTRACT_ID,
                "profit_books_strictly_separated": True,
            },
        }
        payload["workspace_id"] = f"pcew_{input_sha256[:24]}"
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _project_sku(
        self,
        item: dict[str, Any],
        *,
        scope: dict[str, str],
        as_of: datetime,
    ) -> dict[str, Any]:
        sku = self._required(item.get("sku"), "sku", 240)
        quote_currency = self._currency(item.get("quote_currency"), "quote_currency")
        variant = self._variant_state(item.get("variant_identity"), scope=scope)
        quantity = self._quantity_state(item.get("quantity"), scope=scope)

        raw_cost_records = self._records(
            item.get("cost_evidence"),
            "cost_evidence",
            scope=scope,
        )
        raw_fx_records = self._records(
            item.get("fx_bases"),
            "fx_bases",
            scope=scope,
        )
        raw_book_records = self._records(
            item.get("book_evidence"),
            "book_evidence",
            scope=scope,
        )
        cost_records, duplicate_cost_records = self._deduplicate_records(
            raw_cost_records,
            identity_name="cost evidence",
            identity=lambda record: (
                self._required(record.get("cost_type"), "cost_type", 80),
                self._required(record.get("evidence_id"), "evidence_id", 240),
            ),
        )
        fx_records, duplicate_fx_records = self._deduplicate_records(
            raw_fx_records,
            identity_name="FX basis",
            identity=lambda record: self._required(
                record.get("fx_basis_id") or record.get("evidence_id"),
                "fx_basis_id",
                240,
            ),
        )
        book_records, duplicate_book_records = self._deduplicate_records(
            raw_book_records,
            identity_name="book evidence",
            identity=lambda record: (
                self._required(record.get("book"), "book", 40),
                self._required(record.get("evidence_id"), "evidence_id", 240),
            ),
        )

        source_currencies = {
            self._currency(value, "source_currencies")
            for value in self._list(item.get("source_currencies"), "source_currencies")
        }
        source_currencies.add(quote_currency)
        unclassified: list[dict[str, Any]] = []
        by_cost: dict[str, list[dict[str, Any]]] = {
            cost_type: [] for cost_type in _COST_BY_TYPE
        }
        for record in cost_records:
            cost_type = str(record.get("cost_type") or "").strip()
            if cost_type not in by_cost:
                unclassified.append(
                    {
                        "evidence_id": str(record.get("evidence_id") or "").strip() or None,
                        "declared_cost_type": cost_type or None,
                        "reason_code": "cost_type_outside_actual_profit_registry",
                        "record_sha256": self._hash(record),
                    }
                )
                continue
            by_cost[cost_type].append(record)
            currency = self._currency_or_none(record.get("currency"))
            if currency:
                source_currencies.add(currency)

        fx_state = self._fx_state(
            currencies=source_currencies,
            quote_currency=quote_currency,
            records=fx_records,
            as_of=as_of,
        )
        legs = [
            self._cost_leg(
                requirement,
                records=by_cost[requirement.cost_type],
                quote_currency=quote_currency,
                fx_state=fx_state,
                variant=variant,
                quantity=quantity,
                as_of=as_of,
            )
            for requirement in COST_REQUIREMENTS
        ]
        counts = Counter(item["status"] for item in legs)
        scenario_blockers = sorted(
            {
                blocker
                for leg in legs
                if _LEVEL_RANK[leg["status"]] < _LEVEL_RANK["reviewed"]
                for blocker in leg["pilot_blocker_codes"]
            }
            | set(fx_state["blocker_codes"])
            | set(variant["blocker_codes"])
            | set(quantity["blocker_codes"])
        )
        books = self._book_readiness(
            book_records,
            scope=scope,
            scenario_blockers=scenario_blockers,
            as_of=as_of,
        )
        requests = self._requests(
            sku=sku,
            scope=scope,
            legs=legs,
            fx_state=fx_state,
            variant=variant,
            quantity=quantity,
            books=books,
        )
        cost_gate_passed = not scenario_blockers
        payload = {
            "sku": sku,
            "quote_currency": quote_currency,
            "variant_identity": variant,
            "quantity": quantity,
            "fx_readiness": fx_state,
            "cost_coverage": {
                "required": len(COST_REQUIREMENTS),
                "missing": counts["missing"],
                "observed": counts["observed"],
                "reviewed": counts["reviewed"],
                "actual": counts["actual"],
                "reviewed_or_actual": counts["reviewed"] + counts["actual"],
                "actual_only": counts["actual"],
                "scenario_coverage_ratio": self._ratio(
                    counts["reviewed"] + counts["actual"],
                    len(COST_REQUIREMENTS),
                ),
                "actual_coverage_ratio": self._ratio(
                    counts["actual"],
                    len(COST_REQUIREMENTS),
                ),
                "legs": legs,
            },
            "profit_book_readiness": books,
            "pilot_gate": {
                "status": "ready_for_profit_validation" if cost_gate_passed else "blocked",
                "decision_class": "hold" if cost_gate_passed else "needs_data",
                "cost_evidence_gate_passed": cost_gate_passed,
                "pilot_proposal_allowed": False,
                "automatic_execution_allowed": False,
                "blocker_codes": scenario_blockers,
                "next_gate": (
                    "deterministic_downside_cm3_validation"
                    if cost_gate_passed
                    else "complete_cost_fx_variant_and_quantity_evidence"
                ),
                "reason": (
                    "positive_downside_cm3_is_not_calculated_by_this_readiness_module"
                    if cost_gate_passed
                    else "profit_inputs_are_not_safe_for_pilot_evaluation"
                ),
            },
            "unclassified_evidence": sorted(
                unclassified,
                key=lambda record: (
                    str(record["declared_cost_type"] or ""),
                    str(record["evidence_id"] or ""),
                    record["record_sha256"],
                ),
            ),
            "evidence_requests": requests,
            "duplicate_inputs": {
                "cost_evidence": duplicate_cost_records,
                "fx_bases": duplicate_fx_records,
                "book_evidence": duplicate_book_records,
            },
        }
        payload["input_sha256"] = self._hash(item)
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _cost_leg(
        self,
        requirement: CostEvidenceRequirement,
        *,
        records: list[dict[str, Any]],
        quote_currency: str,
        fx_state: dict[str, Any],
        variant: dict[str, Any],
        quantity: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        evaluated = [
            self._evaluate_cost_record(
                record,
                requirement=requirement,
                quote_currency=quote_currency,
                fx_state=fx_state,
                variant=variant,
                quantity=quantity,
                as_of=as_of,
            )
            for record in records
        ]
        evaluated.sort(
            key=lambda record: (
                _LEVEL_RANK[record["effective_level"]],
                record["effective_at"] or "",
                record["evidence_id"],
            ),
            reverse=True,
        )
        status = evaluated[0]["effective_level"] if evaluated else "missing"
        if status == "actual":
            blockers: list[str] = []
        elif status == "reviewed":
            blockers = [f"actual_cost_evidence_missing:{requirement.cost_type}"]
        elif status == "observed":
            blockers = sorted(
                {
                    f"reviewed_cost_evidence_missing:{requirement.cost_type}",
                    *(
                        issue
                        for record in evaluated
                        for issue in record["quality_issues"]
                    ),
                }
            )
        else:
            blockers = [f"cost_evidence_missing:{requirement.cost_type}"]
        pilot_blockers = [] if _LEVEL_RANK[status] >= 2 else blockers
        return {
            **self._requirement_payload(requirement),
            "status": status,
            "evidence_ids": sorted(
                {record["evidence_id"] for record in evaluated if record["evidence_id"]}
            ),
            "retained_record_count": len(evaluated),
            "selected_record": evaluated[0] if evaluated else None,
            "blocker_codes": blockers,
            "pilot_blocker_codes": pilot_blockers,
            "missing_value_guessed": False,
        }

    def _evaluate_cost_record(
        self,
        record: dict[str, Any],
        *,
        requirement: CostEvidenceRequirement,
        quote_currency: str,
        fx_state: dict[str, Any],
        variant: dict[str, Any],
        quantity: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        evidence_id = str(record.get("evidence_id") or "").strip()
        declared_level = str(record.get("evidence_level") or "observed").strip().lower()
        issues: list[str] = []
        if declared_level not in {"observed", "reviewed", "actual"}:
            issues.append(f"cost_evidence_level_invalid:{requirement.cost_type}")
            declared_level = "observed"
        if not evidence_id:
            issues.append(f"cost_evidence_id_missing:{requirement.cost_type}")
        effective_at, freshness_issues = self._freshness(
            record,
            as_of=as_of,
            prefix=f"cost_evidence:{requirement.cost_type}",
        )
        issues.extend(freshness_issues)
        currency = self._currency_or_none(record.get("currency"))
        if currency is None:
            issues.append(f"cost_currency_missing:{requirement.cost_type}")
        elif currency != quote_currency and not self._fx_pair_ready(
            fx_state,
            source_currency=currency,
            quote_currency=quote_currency,
        ):
            issues.append(
                f"cost_fx_basis_missing:{requirement.cost_type}:{currency}/{quote_currency}"
            )
        amount = self._decimal_or_none(record.get("amount"))
        if amount is None or amount < 0:
            issues.append(f"cost_amount_invalid:{requirement.cost_type}")
        if not variant["exact"]:
            issues.append(f"exact_variant_identity_missing:{requirement.cost_type}")
        elif str(record.get("variant_ref") or "").strip() != variant["variant_ref"]:
            issues.append(f"cost_variant_binding_conflict:{requirement.cost_type}")
        if not quantity["exact"]:
            issues.append(f"exact_quantity_missing:{requirement.cost_type}")
        record_quantity = self._decimal_or_none(record.get("quantity"))
        if record_quantity is None or record_quantity <= 0:
            issues.append(f"cost_quantity_invalid:{requirement.cost_type}")
        elif str(record.get("quantity_basis") or "").strip().lower() != "exact":
            issues.append(f"cost_quantity_basis_not_exact:{requirement.cost_type}")
        elif quantity["exact"] and record_quantity != Decimal(str(quantity["value"])):
            issues.append(f"cost_quantity_binding_conflict:{requirement.cost_type}")

        formula = record.get("formula_inputs")
        formula = formula if isinstance(formula, dict) else {}
        missing_formula = [
            name
            for name in requirement.required_formula_inputs
            if not self._present(formula.get(name))
        ]
        actual_authority = (
            record.get("authority_contract_id") == self.ACTUAL_AUTHORITY_CONTRACT_ID
            and record.get("authority_status") == "reconciled"
        )
        common_ready = not issues
        if declared_level == "actual" and actual_authority and common_ready:
            effective_level = "actual"
        elif (
            _LEVEL_RANK[declared_level] >= _LEVEL_RANK["reviewed"]
            and common_ready
            and not missing_formula
        ):
            effective_level = "reviewed"
        else:
            effective_level = "observed"
        if effective_level == "observed" and missing_formula:
            issues.extend(
                f"cost_formula_input_missing:{requirement.cost_type}:{name}"
                for name in missing_formula
            )
        if declared_level == "actual" and not actual_authority:
            issues.append(f"actual_cost_authority_missing:{requirement.cost_type}")
        return {
            "evidence_id": evidence_id or None,
            "declared_level": declared_level,
            "effective_level": effective_level,
            "effective_at": effective_at.isoformat() if effective_at else None,
            "currency": currency,
            "variant_ref": str(record.get("variant_ref") or "").strip() or None,
            "quantity_basis": str(record.get("quantity_basis") or "").strip() or None,
            "actual_authority_verified": actual_authority,
            "formula_inputs_complete": not missing_formula,
            "quality_issues": sorted(set(issues)),
            "record_sha256": self._hash(record),
        }

    def _fx_state(
        self,
        *,
        currencies: set[str],
        quote_currency: str,
        records: list[dict[str, Any]],
        as_of: datetime,
    ) -> dict[str, Any]:
        pairs = []
        blockers: list[str] = []
        for source in sorted(currencies - {quote_currency}):
            evaluated = []
            for record in records:
                if self._currency_or_none(record.get("source_currency")) != source:
                    continue
                if self._currency_or_none(record.get("quote_currency")) != quote_currency:
                    continue
                issues: list[str] = []
                rate = self._decimal_or_none(record.get("rate"))
                if rate is None or rate <= 0:
                    issues.append(f"fx_rate_invalid:{source}/{quote_currency}")
                evidence_id = str(record.get("evidence_id") or "").strip()
                if not evidence_id:
                    issues.append(f"fx_evidence_id_missing:{source}/{quote_currency}")
                effective_at, freshness_issues = self._freshness(
                    record,
                    as_of=as_of,
                    prefix=f"fx_basis:{source}/{quote_currency}",
                )
                issues.extend(freshness_issues)
                level = str(record.get("evidence_level") or "observed").strip().lower()
                if level not in {"reviewed", "actual"}:
                    issues.append(f"fx_basis_not_reviewed:{source}/{quote_currency}")
                purposes = {
                    str(item).strip()
                    for item in self._list(record.get("purposes"), "fx_basis.purposes")
                    if str(item).strip()
                }
                if "scenario_profit" not in purposes:
                    issues.append(
                        f"fx_purpose_not_authorized:{source}/{quote_currency}:scenario_profit"
                    )
                evaluated.append(
                    {
                        "evidence_id": evidence_id or None,
                        "effective_at": effective_at.isoformat() if effective_at else None,
                        "rate": self._decimal_text(rate) if rate is not None else None,
                        "ready": not issues,
                        "quality_issues": sorted(set(issues)),
                        "record_sha256": self._hash(record),
                    }
                )
            ready = [item for item in evaluated if item["ready"]]
            ready.sort(
                key=lambda item: (item["effective_at"] or "", item["evidence_id"] or ""),
                reverse=True,
            )
            pair_blockers: list[str] = []
            selected = ready[0] if ready else None
            if ready:
                latest_effective_at = ready[0]["effective_at"]
                latest_rates = {
                    item["rate"]
                    for item in ready
                    if item["effective_at"] == latest_effective_at
                }
                if len(latest_rates) > 1:
                    selected = None
                    pair_blockers.append(f"fx_basis_conflict:{source}/{quote_currency}")
            if selected is None and not pair_blockers:
                pair_blockers.append(f"fx_basis_missing:{source}/{quote_currency}")
                pair_blockers.extend(
                    issue for item in evaluated for issue in item["quality_issues"]
                )
            blockers.extend(pair_blockers)
            pairs.append(
                {
                    "source_currency": source,
                    "quote_currency": quote_currency,
                    "status": "ready" if selected else "blocked",
                    "selected_evidence_id": selected["evidence_id"] if selected else None,
                    "retained_record_count": len(evaluated),
                    "blocker_codes": sorted(set(pair_blockers)),
                }
            )
        return {
            "status": "not_required" if not pairs else "ready" if not blockers else "blocked",
            "quote_currency": quote_currency,
            "required_pairs": pairs,
            "blocker_codes": sorted(set(blockers)),
            "inverse_or_implicit_rates_used": False,
        }

    def _book_readiness(
        self,
        records: list[dict[str, Any]],
        *,
        scope: dict[str, str],
        scenario_blockers: list[str],
        as_of: datetime,
    ) -> dict[str, Any]:
        del scope  # Scope was fail-closed when the records entered the module.
        result: dict[str, Any] = {
            "scenario": {
                "status": "ready" if not scenario_blockers else "needs_data",
                "source": "reviewed_or_actual_fifteen_cost_coverage",
                "amount": None,
                "currency": None,
                "blocker_codes": scenario_blockers,
                "calculation_performed": False,
            }
        }
        for book in _BOOKS[1:]:
            candidates = []
            for record in records:
                if str(record.get("book") or "").strip().lower() != book:
                    continue
                issues: list[str] = []
                evidence_id = str(record.get("evidence_id") or "").strip()
                if not evidence_id:
                    issues.append(f"{book}_evidence_id_missing")
                _effective_at, freshness_issues = self._freshness(
                    record,
                    as_of=as_of,
                    prefix=f"{book}_evidence",
                )
                issues.extend(freshness_issues)
                expected_authority = (
                    self.ACTUAL_AUTHORITY_CONTRACT_ID
                    if book in {"settlement", "cash"}
                    else {"kjds-profit-ledger-v1", self.ACTUAL_AUTHORITY_CONTRACT_ID}
                )
                authority = str(record.get("authority_contract_id") or "").strip()
                authority_ready = (
                    authority in expected_authority
                    if isinstance(expected_authority, set)
                    else authority == expected_authority
                )
                if not authority_ready or record.get("authority_status") not in {
                    "reconciled",
                    "available",
                }:
                    issues.append(f"{book}_authority_missing")
                candidates.append(
                    {
                        "evidence_id": evidence_id or None,
                        "ready": not issues,
                        "quality_issues": sorted(set(issues)),
                        "record_sha256": self._hash(record),
                    }
                )
            ready = sorted(
                (item for item in candidates if item["ready"]),
                key=lambda item: (item["evidence_id"] or "", item["record_sha256"]),
            )
            blocker_codes = [] if ready else [f"{book}_profit_evidence_missing"]
            if not ready:
                blocker_codes.extend(
                    issue for item in candidates for issue in item["quality_issues"]
                )
            result[book] = {
                "status": "available" if ready else "no_data",
                "source": "explicit_book_authority_only",
                "amount": None,
                "currency": None,
                "evidence_ids": [item["evidence_id"] for item in ready],
                "blocker_codes": sorted(set(blocker_codes)),
                "calculation_performed": False,
            }
        result["strictly_separated"] = True
        return result

    def _requests(
        self,
        *,
        sku: str,
        scope: dict[str, str],
        legs: list[dict[str, Any]],
        fx_state: dict[str, Any],
        variant: dict[str, Any],
        quantity: dict[str, Any],
        books: dict[str, Any],
    ) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        if not variant["exact"]:
            requests.append(
                self._request(
                    sku=sku,
                    scope=scope,
                    request_type="variant_identity",
                    target="exact",
                    owner="catalog-control",
                    document="platform variant attributes, barcode, and supplier variant binding",
                    formula_inputs=("platform_sku", "supplier_variant_ref"),
                    blocker_codes=variant["blocker_codes"],
                    priority_rank=2,
                )
            )
        if not quantity["exact"]:
            requests.append(
                self._request(
                    sku=sku,
                    scope=scope,
                    request_type="quantity_basis",
                    target="exact",
                    owner="inventory-control",
                    document="exact order, purchase, or shipment quantity statement",
                    formula_inputs=("quantity", "quantity_unit"),
                    blocker_codes=quantity["blocker_codes"],
                    priority_rank=3,
                )
            )
        for pair in fx_state["required_pairs"]:
            if pair["status"] == "ready":
                continue
            requests.append(
                self._request(
                    sku=sku,
                    scope=scope,
                    request_type="fx_basis",
                    target=f"{pair['source_currency']}/{pair['quote_currency']}",
                    owner="treasury-control",
                    document="reviewed point-in-time FX rate with source evidence and validity window",
                    formula_inputs=("source_currency", "quote_currency", "rate", "effective_at"),
                    blocker_codes=pair["blocker_codes"],
                    priority_rank=1,
                )
            )
        for leg in legs:
            if leg["status"] == "actual":
                continue
            requirement = _COST_BY_TYPE[leg["cost_type"]]
            target = "actual" if leg["status"] == "reviewed" else "reviewed"
            rank = (
                70 + _COST_INDEX[leg["cost_type"]]
                if target == "actual"
                else 10 + _COST_INDEX[leg["cost_type"]]
                if leg["status"] == "missing"
                else 30 + _COST_INDEX[leg["cost_type"]]
            )
            requests.append(
                self._request(
                    sku=sku,
                    scope=scope,
                    request_type="cost_leg",
                    target=f"{leg['cost_type']}:{target}",
                    owner=requirement.owner,
                    document=requirement.required_document,
                    formula_inputs=requirement.required_formula_inputs,
                    blocker_codes=leg["blocker_codes"],
                    priority_rank=rank,
                    cost_type=leg["cost_type"],
                )
            )
        for index, book in enumerate(_BOOKS[1:]):
            state = books[book]
            if state["status"] == "available":
                continue
            requests.append(
                self._request(
                    sku=sku,
                    scope=scope,
                    request_type="profit_book",
                    target=book,
                    owner="finance-control",
                    document=f"explicit {book} profit authority evidence",
                    formula_inputs=("reconciliation_key", "authority_contract_id"),
                    blocker_codes=state["blocker_codes"],
                    priority_rank=90 + index,
                )
            )
        return sorted(
            requests,
            key=lambda item: (
                item["priority_rank"],
                item["cost_order"],
                item["request_id"],
            ),
        )

    def _request(
        self,
        *,
        sku: str,
        scope: dict[str, str],
        request_type: str,
        target: str,
        owner: str,
        document: str,
        formula_inputs: tuple[str, ...],
        blocker_codes: list[str],
        priority_rank: int,
        cost_type: str | None = None,
    ) -> dict[str, Any]:
        identity = {
            "scope": scope,
            "sku": sku,
            "request_type": request_type,
            "target": target,
        }
        return {
            "request_id": f"pcer_{self._hash(identity)[:24]}",
            "sku": sku,
            "request_type": request_type,
            "cost_type": cost_type,
            "target_level_or_basis": target,
            "owner": owner,
            "required_document": document,
            "required_formula_inputs": list(formula_inputs),
            "priority": "p0" if priority_rank <= 10 else "p1" if priority_rank <= 40 else "p2",
            "priority_rank": priority_rank,
            "cost_order": _COST_INDEX.get(cost_type, -1),
            "blocker_codes": sorted(set(blocker_codes)),
            "automatic_execution_allowed": False,
            "missing_value_guessed": False,
        }

    def _variant_state(
        self,
        value: Any,
        *,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        record = value if isinstance(value, dict) else {}
        if record:
            self._assert_scope(record, scope=scope, label="variant_identity")
        status = str(record.get("status") or "").strip().lower()
        variant_ref = str(record.get("variant_ref") or "").strip()
        evidence_id = str(record.get("evidence_id") or "").strip()
        blockers = []
        if status != "exact":
            blockers.append("exact_variant_identity_missing")
        if not variant_ref:
            blockers.append("variant_ref_missing")
        if not evidence_id:
            blockers.append("variant_identity_evidence_missing")
        exact = not blockers
        return {
            "status": "exact" if exact else "unresolved",
            "exact": exact,
            "variant_ref": variant_ref or None,
            "evidence_id": evidence_id or None,
            "blocker_codes": sorted(blockers),
        }

    def _quantity_state(
        self,
        value: Any,
        *,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        record = value if isinstance(value, dict) else {}
        if record:
            self._assert_scope(record, scope=scope, label="quantity")
        quantity = self._decimal_or_none(record.get("value"))
        basis = str(record.get("basis") or "").strip().lower()
        evidence_id = str(record.get("evidence_id") or "").strip()
        blockers = []
        if quantity is None or quantity <= 0:
            blockers.append("quantity_invalid")
        if basis != "exact":
            blockers.append("quantity_basis_not_exact")
        if not evidence_id:
            blockers.append("quantity_evidence_missing")
        exact = not blockers
        return {
            "status": "exact" if exact else "unresolved",
            "exact": exact,
            "value": self._decimal_text(quantity) if quantity is not None else None,
            "basis": basis or None,
            "evidence_id": evidence_id or None,
            "blocker_codes": sorted(blockers),
        }

    @staticmethod
    def _fx_pair_ready(
        fx_state: dict[str, Any],
        *,
        source_currency: str,
        quote_currency: str,
    ) -> bool:
        return any(
            item["source_currency"] == source_currency
            and item["quote_currency"] == quote_currency
            and item["status"] == "ready"
            for item in fx_state["required_pairs"]
        )

    def _freshness(
        self,
        record: dict[str, Any],
        *,
        as_of: datetime,
        prefix: str,
    ) -> tuple[datetime | None, list[str]]:
        issues: list[str] = []
        try:
            effective_at = self._timestamp(record.get("effective_at"), f"{prefix}.effective_at")
        except ValueError:
            effective_at = None
            issues.append(f"{prefix}:effective_at_invalid")
        if effective_at and effective_at > as_of:
            issues.append(f"{prefix}:not_yet_effective")
        if record.get("effective_until") is None:
            issues.append(f"{prefix}:freshness_unproven")
        else:
            try:
                effective_until = self._timestamp(
                    record.get("effective_until"),
                    f"{prefix}.effective_until",
                )
            except ValueError:
                issues.append(f"{prefix}:effective_until_invalid")
            else:
                if effective_at and effective_until < effective_at:
                    issues.append(f"{prefix}:validity_window_invalid")
                if effective_until < as_of:
                    issues.append(f"{prefix}:stale")
        return effective_at, issues

    def _deduplicate_skus(
        self,
        values: Any,
        *,
        scope: dict[str, str],
    ) -> tuple[list[dict[str, Any]], int]:
        if not isinstance(values, list):
            raise ProfitCostEvidenceInvariantError("sku_inputs must be a list")
        by_sku: dict[str, dict[str, Any]] = {}
        duplicates = 0
        for raw in values:
            if not isinstance(raw, dict):
                raise ProfitCostEvidenceInvariantError("Every sku input must be an object")
            self._assert_scope(raw, scope=scope, label="sku input")
            sku = self._required(raw.get("sku"), "sku", 240)
            normalized = self._normalize_collection_order(raw)
            current = by_sku.get(sku)
            if current is None:
                by_sku[sku] = normalized
            elif self._hash(current) == self._hash(normalized):
                duplicates += 1
            else:
                raise ProfitCostEvidenceConflict(
                    f"SKU {sku!r} was supplied with conflicting immutable content"
                )
        return [by_sku[key] for key in sorted(by_sku)], duplicates

    def _deduplicate_records(
        self,
        records: list[dict[str, Any]],
        *,
        identity_name: str,
        identity,
    ) -> tuple[list[dict[str, Any]], int]:
        result: dict[Any, dict[str, Any]] = {}
        duplicates = 0
        for record in records:
            key = identity(record)
            current = result.get(key)
            if current is None:
                result[key] = record
            elif self._hash(current) == self._hash(record):
                duplicates += 1
            else:
                raise ProfitCostEvidenceConflict(
                    f"{identity_name} identity {key!r} has conflicting immutable content"
                )
        return sorted(result.values(), key=self._hash), duplicates

    def _records(
        self,
        value: Any,
        label: str,
        *,
        scope: dict[str, str],
    ) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ProfitCostEvidenceInvariantError(f"{label} must be a list")
        result = []
        for record in value:
            if not isinstance(record, dict):
                raise ProfitCostEvidenceInvariantError(f"Every {label} record must be an object")
            self._assert_scope(record, scope=scope, label=label)
            result.append(record)
        return result

    @staticmethod
    def _normalize_collection_order(value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        for key in ("source_currencies", "cost_evidence", "fx_bases", "book_evidence"):
            collection = normalized.get(key)
            if isinstance(collection, list):
                normalized[key] = sorted(
                    collection,
                    key=lambda item: json.dumps(
                        ProfitCostEvidenceWorkspace._canonical(item),
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                )
        return normalized

    @staticmethod
    def _requirement_payload(requirement: CostEvidenceRequirement) -> dict[str, Any]:
        return {
            "cost_type": requirement.cost_type,
            "profit_stage": requirement.profit_stage,
            "owner": requirement.owner,
            "required_document": requirement.required_document,
            "required_formula_inputs": list(requirement.required_formula_inputs),
        }

    @classmethod
    def _scope(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ProfitCostEvidenceInvariantError("scope must be an object")
        return {
            key: cls._required(value.get(key), f"scope.{key}", 160)
            for key in ("tenant_ref", "entity_ref", "store_ref")
        }

    @classmethod
    def _assert_scope(
        cls,
        record: dict[str, Any],
        *,
        scope: dict[str, str],
        label: str,
    ) -> None:
        record_scope = record.get("scope")
        if not isinstance(record_scope, dict):
            raise PermissionError(f"{label} is outside the authorized profit evidence scope")
        try:
            normalized = cls._scope(record_scope)
        except ProfitCostEvidenceInvariantError as exc:
            raise PermissionError(
                f"{label} is outside the authorized profit evidence scope"
            ) from exc
        if normalized != scope:
            raise PermissionError(f"{label} is outside the authorized profit evidence scope")

    @staticmethod
    def _required(value: Any, label: str, max_length: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > max_length:
            raise ProfitCostEvidenceInvariantError(
                f"{label} must be 1 to {max_length} characters"
            )
        return normalized

    @staticmethod
    def _currency(value: Any, label: str) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise ProfitCostEvidenceInvariantError(
                f"{label} must be a three-letter currency code"
            )
        return normalized

    @classmethod
    def _currency_or_none(cls, value: Any) -> str | None:
        try:
            return cls._currency(value, "currency")
        except ProfitCostEvidenceInvariantError:
            return None

    @staticmethod
    def _timestamp(value: Any, label: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            normalized = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
        else:
            raise ValueError(f"{label} must be an ISO-8601 timestamp")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"

    @staticmethod
    def _present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    @staticmethod
    def _list(value: Any, label: str) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ProfitCostEvidenceInvariantError(f"{label} must be a list")
        return value

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> str:
        return ProfitCostEvidenceWorkspace._decimal_text(
            Decimal(numerator) / Decimal(denominator)
        )

    @classmethod
    def _hash(cls, value: Any) -> str:
        encoded = json.dumps(
            cls._canonical(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _canonical(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._canonical(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._canonical(item) for item in value]
        if isinstance(value, set | frozenset):
            return sorted(cls._canonical(item) for item in value)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ProfitCostEvidenceInvariantError(
                    "Naive datetimes cannot enter profit evidence hashes"
                )
            return value.astimezone(UTC).isoformat()
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ProfitCostEvidenceInvariantError(
                    "Non-finite decimals cannot enter profit evidence hashes"
                )
            return cls._decimal_text(value)
        if isinstance(value, float):
            parsed = Decimal(str(value))
            if not parsed.is_finite():
                raise ProfitCostEvidenceInvariantError(
                    "Non-finite floats cannot enter profit evidence hashes"
                )
            return cls._decimal_text(parsed)
        return value
