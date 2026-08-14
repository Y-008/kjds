from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_ID = "kjds-profit-data-remediation-v1"


class ProfitDataRemediationConflict(ValueError):
    """Raised when one stable input identity carries conflicting content."""


class ProfitDataRemediationInvariantError(ValueError):
    """Raised when source retention or scope invariants do not hold."""


_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "fx_basis_missing": {
        "requirement": "fx_basis_evidence",
        "action": "bind_time_effective_fx_basis",
        "instruction": "Bind source currency, target currency, rate, effective time, and Evidence before profit calculation.",
        "owner_role": "finance-control",
        "deadline_class": "before_any_financial_action",
        "severity": "P0",
        "unblock_impact": 100,
    },
    "mixed_currency_direct_comparison": {
        "requirement": "fx_basis_evidence",
        "action": "invalidate_mixed_currency_comparison",
        "instruction": "Invalidate the direct currency comparison and rebuild it from evidenced MoneyAmount and FxBasis records.",
        "owner_role": "finance-control",
        "deadline_class": "immediate",
        "severity": "P0",
        "unblock_impact": 100,
    },
    "money_currency_missing": {
        "requirement": "money_currency_evidence",
        "action": "capture_original_currency",
        "instruction": "Capture the original currency from source Evidence; do not infer it from marketplace or locale.",
        "owner_role": "finance-control",
        "deadline_class": "before_any_financial_action",
        "severity": "P0",
        "unblock_impact": 98,
    },
    "own_price_currency_missing": {
        "requirement": "money_currency_evidence",
        "action": "capture_original_currency",
        "instruction": "Capture the listing price and its original currency from the same source Evidence.",
        "owner_role": "catalog-operations",
        "deadline_class": "before_repricing_or_listing",
        "severity": "P0",
        "unblock_impact": 96,
    },
    "market_reference_price_missing": {
        "requirement": "market_price_evidence",
        "action": "refresh_market_price_evidence",
        "instruction": "Capture a time-stamped market reference price, currency, variant, and source Evidence.",
        "owner_role": "market-intelligence",
        "deadline_class": "before_repricing_or_pilot",
        "severity": "P1",
        "unblock_impact": 88,
    },
    "variant_identity_unresolved": {
        "requirement": "exact_variant_identity_evidence",
        "action": "resolve_exact_supplier_variant",
        "instruction": "Bind the exact supplier variant to the exact marketplace SKU with reviewable Evidence.",
        "owner_role": "sourcing-operations",
        "deadline_class": "before_purchase_or_pilot",
        "severity": "P1",
        "unblock_impact": 95,
    },
    "product_identity_missing": {
        "requirement": "product_identity_evidence",
        "action": "resolve_product_identity",
        "instruction": "Resolve the platform product and SKU identity without merging ambiguous records.",
        "owner_role": "catalog-operations",
        "deadline_class": "before_catalog_promotion",
        "severity": "P1",
        "unblock_impact": 94,
    },
    "fifteen_component_cost_evidence_incomplete": {
        "requirement": "cost_component_evidence",
        "action": "complete_cost_evidence",
        "instruction": "Capture the required cost components separately with currency, effective time, and Evidence lineage.",
        "owner_role": "profit-operations",
        "deadline_class": "before_purchase_advertising_or_pilot",
        "severity": "P1",
        "unblock_impact": 93,
    },
    "settlement_profit_missing": {
        "requirement": "settlement_lineage_evidence",
        "action": "bind_settlement_to_sku",
        "instruction": "Bind platform settlement lines and adjustments to the exact order and SKU.",
        "owner_role": "finance-control",
        "deadline_class": "before_actual_profit_confirmation",
        "severity": "P1",
        "unblock_impact": 86,
    },
    "three_book_settlement_not_bound_to_sku": {
        "requirement": "settlement_lineage_evidence",
        "action": "bind_settlement_to_sku",
        "instruction": "Reconcile order, settlement, and accounting books to the exact SKU.",
        "owner_role": "finance-control",
        "deadline_class": "before_actual_profit_confirmation",
        "severity": "P1",
        "unblock_impact": 88,
    },
    "cash_profit_missing": {
        "requirement": "bank_cash_lineage_evidence",
        "action": "bind_bank_cash_to_sku",
        "instruction": "Bind cleared bank cash to settlement, order, and SKU before reporting cash profit.",
        "owner_role": "treasury-operations",
        "deadline_class": "before_cash_profit_confirmation",
        "severity": "P1",
        "unblock_impact": 84,
    },
    "bank_cash_profit_not_bound_to_sku": {
        "requirement": "bank_cash_lineage_evidence",
        "action": "bind_bank_cash_to_sku",
        "instruction": "Reconcile cleared bank cash through settlement and order lineage to the exact SKU.",
        "owner_role": "treasury-operations",
        "deadline_class": "before_cash_profit_confirmation",
        "severity": "P1",
        "unblock_impact": 86,
    },
    "reconciled_accrual_profit_missing": {
        "requirement": "accrual_profit_evidence",
        "action": "reconcile_accrual_profit",
        "instruction": "Reconcile evidenced revenue and expense events to the SKU accrual ledger.",
        "owner_role": "finance-control",
        "deadline_class": "before_actual_profit_confirmation",
        "severity": "P1",
        "unblock_impact": 82,
    },
    "independent_scope_binding_pending": {
        "requirement": "scope_binding_evidence",
        "action": "bind_evidence_scope",
        "instruction": "Review and bind the Evidence to exactly one tenant, entity, and store scope.",
        "owner_role": "data-governance",
        "deadline_class": "before_fact_promotion",
        "severity": "P1",
        "unblock_impact": 97,
    },
    "metric_currency_unverified": {
        "requirement": "metric_semantics_evidence",
        "action": "verify_metric_semantics",
        "instruction": "Verify whether the metric is monetary and capture currency and unit semantics from source documentation.",
        "owner_role": "data-governance",
        "deadline_class": "before_metric_financial_use",
        "severity": "P1",
        "unblock_impact": 78,
    },
    "source_evidence_stale": {
        "requirement": "fresh_source_evidence",
        "action": "refresh_source_evidence",
        "instruction": "Capture a new source observation; retain the stale observation and do not rewrite its history.",
        "owner_role": "data-operations",
        "deadline_class": "before_next_decision_snapshot",
        "severity": "P1",
        "unblock_impact": 92,
    },
    "candidate_blocked": {
        "requirement": "blocking_control_resolution",
        "action": "resolve_candidate_blocker",
        "instruction": "Resolve the recorded blocker and rerun the deterministic profit decision; do not bypass the control.",
        "owner_role": "profit-operations",
        "deadline_class": "before_any_candidate_action",
        "severity": "P1",
        "unblock_impact": 90,
    },
}

_DEFAULT_REQUIREMENT = {
    "requirement": "source_validation_evidence",
    "action": "review_source_issue",
    "instruction": "Review the source issue, attach corrective Evidence, and rerun normalization without inventing missing values.",
    "owner_role": "data-governance",
    "deadline_class": "before_fact_promotion",
    "severity": "P2",
    "unblock_impact": 50,
}

_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_STATUS_ORDER = {"open": 0, "stale": 1, "blocked": 2}


class ProfitDataRemediationWorkspace:
    """Compile retained data defects into a deterministic remediation queue.

    The module is deliberately pure: callers provide bundle, source-item, and
    candidate projections. It neither queries authorities nor promotes facts.
    """

    CONTRACT_ID = CONTRACT_ID

    def project(
        self,
        *,
        scope: Mapping[str, Any],
        bundle: Mapping[str, Any] | Any,
        source_items: Iterable[Mapping[str, Any] | Any],
        candidates: Mapping[str, Any] | Iterable[Mapping[str, Any] | Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized_as_of = self._as_of(as_of)
        normalized_scope = self._scope(scope)
        normalized_bundle = self._bundle(bundle)
        self._assert_scope(normalized_scope, normalized_bundle.get("scope"), "bundle")

        candidate_envelope, candidate_records = self._candidate_input(candidates)
        self._assert_scope(
            normalized_scope,
            candidate_envelope.get("scope"),
            "profit candidate workspace",
        )

        sources, duplicate_source_count = self._normalize_sources(
            source_items,
            expected_scope=normalized_scope,
            as_of=normalized_as_of,
        )
        normalized_candidates, duplicate_candidate_count = self._normalize_candidates(
            candidate_records,
            expected_scope=normalized_scope,
            as_of=normalized_as_of,
        )
        reconciliation = self._reconcile(normalized_bundle, sources, duplicate_source_count)

        candidate_signals = {
            candidate["sku"]: candidate["priority_signals"]
            for candidate in normalized_candidates
            if candidate["sku"]
        }
        issues = self._source_issues(
            sources,
            scope=normalized_scope,
            candidate_signals=candidate_signals,
        )
        issues.extend(self._candidate_issues(normalized_candidates, scope=normalized_scope))
        issues.sort(key=self._priority_key)
        for rank, issue in enumerate(issues, start=1):
            issue["priority_rank"] = rank

        input_payload = {
            "scope": normalized_scope,
            "as_of": normalized_as_of.isoformat(),
            "bundle": normalized_bundle,
            "source_items": sources,
            "candidates": normalized_candidates,
        }
        input_sha256 = self._hash(input_payload)
        workspace_id = f"pdrw_{input_sha256[:24]}"
        status = self._workspace_status(issues, reconciliation)
        groups = {
            "by_sku": self._group(issues, "sku", missing_key="unbound"),
            "by_source": self._group(issues, "source_ref", missing_key="profit_command"),
            "by_error_code": self._group(issues, "error_code", missing_key="unknown"),
            "by_evidence_requirement": self._group(
                issues,
                "evidence_requirement",
                missing_key="source_validation_evidence",
            ),
        }
        return {
            "contract_id": self.CONTRACT_ID,
            "workspace_id": workspace_id,
            "input_sha256": input_sha256,
            "scope": normalized_scope,
            "as_of": normalized_as_of.isoformat(),
            "status": status,
            "reconciliation": reconciliation,
            "summary": {
                "source_items": len(sources),
                "candidates": len(normalized_candidates),
                "remediation_items": len(issues),
                "open": sum(issue["status"] == "open" for issue in issues),
                "stale": sum(issue["status"] == "stale" for issue in issues),
                "blocked": sum(issue["status"] == "blocked" for issue in issues),
                "duplicate_source_inputs": duplicate_source_count,
                "duplicate_candidate_inputs": duplicate_candidate_count,
            },
            "source_inventory": sources,
            "candidate_inventory": normalized_candidates,
            "remediation_queue": issues,
            "groups": groups,
            "control_envelope": {
                "missing_values_guessed": False,
                "formal_fact_promoted": False,
                "automatic_action_allowed": False,
                "external_write_allowed": False,
                "cross_currency_aggregation_performed": False,
                "cross_currency_value_comparison_performed": False,
                "source_history_rewritten": False,
            },
        }

    @classmethod
    def _bundle(cls, value: Mapping[str, Any] | Any) -> dict[str, Any]:
        counts = cls._value(value, "counts", default={}) or {}
        source_total = cls._integer(
            cls._value(counts, "source_total", default=cls._value(value, "source_total")),
            "bundle source_total",
        )
        accepted = cls._integer(
            cls._value(counts, "accepted", default=cls._value(value, "accepted_count")),
            "bundle accepted",
        )
        quarantined = cls._integer(
            cls._value(
                counts,
                "quarantined",
                default=cls._value(value, "quarantined_count"),
            ),
            "bundle quarantined",
        )
        if min(source_total, accepted, quarantined) < 0:
            raise ProfitDataRemediationInvariantError("Bundle counts cannot be negative")
        if accepted + quarantined != source_total:
            raise ProfitDataRemediationInvariantError(
                "Bundle violates accepted + quarantined = source_total"
            )
        return {
            "bundle_id": cls._text(cls._value(value, "bundle_id", "id")) or None,
            "bundle_sha256": cls._text(cls._value(value, "bundle_sha256")) or None,
            "archive_evidence_id": cls._text(
                cls._value(value, "archive_evidence_id")
            )
            or None,
            "status": cls._text(cls._value(value, "status")) or "unknown",
            "scope": cls._optional_scope(cls._value(value, "scope", default=value)),
            "counts": {
                "source_total": source_total,
                "accepted": accepted,
                "quarantined": quarantined,
            },
            "quality": cls._json_safe(cls._value(value, "quality", "quality_json", default={}) or {}),
        }

    @classmethod
    def _normalize_sources(
        cls,
        values: Iterable[Mapping[str, Any] | Any],
        *,
        expected_scope: dict[str, str],
        as_of: datetime,
    ) -> tuple[list[dict[str, Any]], int]:
        unique: dict[str, tuple[str, dict[str, Any]]] = {}
        duplicate_count = 0
        for position, value in enumerate(values):
            item_scope = cls._optional_scope(cls._value(value, "scope", default=value))
            cls._assert_scope(expected_scope, item_scope, f"source item at position {position}")
            artifact_path = cls._text(cls._value(value, "artifact_path"))
            artifact_kind = cls._text(cls._value(value, "artifact_kind")) or "unknown"
            record_index = cls._integer(
                cls._value(value, "record_index", default=position),
                "record_index",
            )
            bundle_id = cls._text(cls._value(value, "bundle_id")) or None
            source_identity = cls._text(cls._value(value, "source_item_id", "id"))
            if not source_identity:
                source_identity = "src_" + cls._hash(
                    {
                        "scope": expected_scope,
                        "bundle_id": bundle_id,
                        "artifact_path": artifact_path,
                        "record_index": record_index,
                    }
                )[:24]
            disposition = cls._text(cls._value(value, "disposition"))
            if disposition not in {"accepted", "quarantined"}:
                raise ProfitDataRemediationInvariantError(
                    f"Source item {source_identity} must be accepted or quarantined"
                )
            payload = cls._json_safe(cls._value(value, "payload", "payload_json", default={}) or {})
            reason_codes = cls._codes(
                cls._value(value, "reason_codes", "reason_codes_json", default=[])
            )
            evidence_ids = cls._evidence_ids(value)
            source_sha256 = cls._text(cls._value(value, "source_sha256")) or cls._hash(payload)
            stale = cls._is_stale(value, as_of=as_of)
            normalized = {
                "source_item_id": source_identity,
                "bundle_id": bundle_id,
                "scope": expected_scope,
                "artifact_path": artifact_path,
                "artifact_kind": artifact_kind,
                "source_ref": f"{artifact_kind}:{artifact_path or 'unknown'}",
                "record_index": record_index,
                "record_key": cls._text(cls._value(value, "record_key")) or None,
                "sku": cls._source_sku(value, payload),
                "source_sha256": source_sha256,
                "disposition": disposition,
                "highest_stage": cls._text(cls._value(value, "highest_stage")) or "raw_evidence",
                "reason_codes": reason_codes,
                "evidence_ids": evidence_ids,
                "stale": stale,
                "payload": payload,
                "lineage": {
                    "bundle_id": bundle_id,
                    "source_item_id": source_identity,
                    "source_sha256": source_sha256,
                    "evidence_ids": evidence_ids,
                    "highest_stage": cls._text(cls._value(value, "highest_stage"))
                    or "raw_evidence",
                },
            }
            fingerprint = cls._hash(normalized)
            previous = unique.get(source_identity)
            if previous:
                if previous[0] != fingerprint:
                    raise ProfitDataRemediationConflict(
                        f"Source item {source_identity} has conflicting immutable content"
                    )
                duplicate_count += 1
                continue
            unique[source_identity] = (fingerprint, normalized)
        return (
            sorted((value[1] for value in unique.values()), key=lambda item: item["source_item_id"]),
            duplicate_count,
        )

    @classmethod
    def _normalize_candidates(
        cls,
        values: Iterable[Mapping[str, Any] | Any],
        *,
        expected_scope: dict[str, str],
        as_of: datetime,
    ) -> tuple[list[dict[str, Any]], int]:
        unique: dict[str, tuple[str, dict[str, Any]]] = {}
        duplicate_count = 0
        for position, value in enumerate(values):
            candidate_scope = cls._optional_scope(cls._value(value, "scope", default={}))
            cls._assert_scope(expected_scope, candidate_scope, f"candidate at position {position}")
            candidate_id = cls._text(cls._value(value, "candidate_id"))
            sku = cls._text(cls._value(value, "sku", "offer_id")) or None
            if not candidate_id:
                if not sku:
                    raise ProfitDataRemediationInvariantError(
                        f"Candidate at position {position} has no stable identity"
                    )
                candidate_id = f"candidate:{sku}"
            reason_codes = cls._candidate_reason_codes(value)
            stale = cls._is_stale(value, as_of=as_of)
            candidate_status = cls._text(cls._value(value, "status"))
            decision_class = cls._text(cls._value(value, "decision_class"))
            blocked = bool(cls._value(value, "blocked", default=False)) or candidate_status == "blocked" or decision_class == "blocked"
            if blocked and "candidate_blocked" not in reason_codes:
                reason_codes.append("candidate_blocked")
                reason_codes.sort()
            signals = cls._priority_signals(value)
            evidence_ids = cls._evidence_ids(value)
            normalized = {
                "candidate_id": candidate_id,
                "scope": expected_scope,
                "sku": sku,
                "decision_class": decision_class or None,
                "status": candidate_status or None,
                "reason_codes": reason_codes,
                "evidence_ids": evidence_ids,
                "input_sha256": cls._text(cls._value(value, "input_sha256")) or None,
                "stale": stale,
                "blocked": blocked,
                "priority_signals": signals,
                "lineage": {
                    "candidate_id": candidate_id,
                    "input_sha256": cls._text(cls._value(value, "input_sha256")) or None,
                    "evidence_ids": evidence_ids,
                },
            }
            fingerprint = cls._hash(normalized)
            previous = unique.get(candidate_id)
            if previous:
                if previous[0] != fingerprint:
                    raise ProfitDataRemediationConflict(
                        f"Candidate {candidate_id} has conflicting immutable content"
                    )
                duplicate_count += 1
                continue
            unique[candidate_id] = (fingerprint, normalized)
        return (
            sorted((value[1] for value in unique.values()), key=lambda item: item["candidate_id"]),
            duplicate_count,
        )

    @classmethod
    def _source_issues(
        cls,
        sources: list[dict[str, Any]],
        *,
        scope: dict[str, str],
        candidate_signals: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for source in sources:
            codes = list(source["reason_codes"])
            if source["disposition"] == "quarantined" and not codes:
                codes.append("quarantined_without_reason")
            if source["stale"] and "source_evidence_stale" not in codes:
                codes.append("source_evidence_stale")
            for code in sorted(set(codes)):
                issues.append(
                    cls._issue(
                        scope=scope,
                        origin_type="source_item",
                        origin_id=source["source_item_id"],
                        source_item_id=source["source_item_id"],
                        candidate_id=None,
                        sku=source["sku"],
                        source_ref=source["source_ref"],
                        code=code,
                        status="stale" if source["stale"] else "open",
                        evidence_ids=source["evidence_ids"],
                        lineage=source["lineage"],
                        priority_signals=candidate_signals.get(
                            source["sku"], cls._empty_priority_signals()
                        ),
                    )
                )
        return issues

    @classmethod
    def _candidate_issues(
        cls,
        candidates: list[dict[str, Any]],
        *,
        scope: dict[str, str],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for candidate in candidates:
            status = "stale" if candidate["stale"] else "blocked" if candidate["blocked"] else "open"
            codes = list(candidate["reason_codes"])
            if candidate["stale"] and "source_evidence_stale" not in codes:
                codes.append("source_evidence_stale")
            for code in sorted(set(codes)):
                issues.append(
                    cls._issue(
                        scope=scope,
                        origin_type="profit_candidate",
                        origin_id=candidate["candidate_id"],
                        source_item_id=None,
                        candidate_id=candidate["candidate_id"],
                        sku=candidate["sku"],
                        source_ref="profit_command",
                        code=code,
                        status=status,
                        evidence_ids=candidate["evidence_ids"],
                        lineage=candidate["lineage"],
                        priority_signals=candidate["priority_signals"],
                    )
                )
        return issues

    @classmethod
    def _issue(
        cls,
        *,
        scope: dict[str, str],
        origin_type: str,
        origin_id: str,
        source_item_id: str | None,
        candidate_id: str | None,
        sku: str | None,
        source_ref: str,
        code: str,
        status: str,
        evidence_ids: list[str],
        lineage: dict[str, Any],
        priority_signals: dict[str, Any],
    ) -> dict[str, Any]:
        policy = dict(_REQUIREMENTS.get(code, _DEFAULT_REQUIREMENT))
        identity = {
            "scope": scope,
            "origin_type": origin_type,
            "origin_id": origin_id,
            "error_code": code,
            "evidence_requirement": policy["requirement"],
        }
        issue_sha256 = cls._hash(identity)
        return {
            "remediation_item_id": f"pdri_{issue_sha256[:24]}",
            "issue_sha256": issue_sha256,
            "scope": scope,
            "status": status,
            "origin_type": origin_type,
            "origin_id": origin_id,
            "source_item_id": source_item_id,
            "candidate_id": candidate_id,
            "sku": sku,
            "source_ref": source_ref,
            "error_code": code,
            "evidence_requirement": policy["requirement"],
            "severity": policy["severity"],
            "unblock_impact_score": policy["unblock_impact"],
            "estimated_loss_exposure": priority_signals["estimated_loss_exposure"],
            "value_at_risk": priority_signals["value_at_risk"],
            "action": {
                "action_code": policy["action"],
                "instruction": policy["instruction"],
                "owner_role": policy["owner_role"],
                "deadline_class": policy["deadline_class"],
                "automatic_execution_allowed": False,
            },
            "evidence_ids": evidence_ids,
            "lineage": lineage,
            "missing_value_guessed": False,
            "priority_rank": None,
        }

    @classmethod
    def _candidate_reason_codes(cls, value: Mapping[str, Any] | Any) -> list[str]:
        codes = set(cls._codes(cls._value(value, "reason_codes", default=[])))
        profit = cls._value(value, "profit", default={}) or {}
        if isinstance(profit, Mapping):
            for projection in profit.values():
                if not isinstance(projection, Mapping):
                    continue
                if projection.get("status") in {"no_data", "blocked", "stale"}:
                    reason = cls._text(projection.get("reason"))
                    if reason:
                        codes.add(reason)
        cost_coverage = cls._value(value, "cost_coverage", default={}) or {}
        if isinstance(cost_coverage, Mapping):
            required = cls._optional_integer(cost_coverage.get("required"))
            evidenced = cls._optional_integer(cost_coverage.get("evidenced"))
            if required is not None and evidenced is not None and evidenced < required:
                codes.add("fifteen_component_cost_evidence_incomplete")
        raw_money = cls._value(value, "raw_money", default={}) or {}
        if isinstance(raw_money, Mapping):
            own = raw_money.get("own_price")
            market = raw_money.get("market_reference_price")
            if isinstance(own, Mapping) and isinstance(market, Mapping):
                own_currency = cls._currency(own.get("currency"))
                market_currency = cls._currency(market.get("currency"))
                if own_currency and market_currency and own_currency != market_currency and not raw_money.get("fx_basis"):
                    codes.add("fx_basis_missing")
        return sorted(codes)

    @classmethod
    def _priority_signals(cls, candidate: Mapping[str, Any] | Any) -> dict[str, Any]:
        evidence_ids = cls._evidence_ids(candidate)
        candidate_currency = cls._currency(
            cls._value(candidate, "display_currency", default=None)
        )
        raw_money = cls._value(candidate, "raw_money", default={}) or {}
        if isinstance(raw_money, Mapping):
            candidate_currency = cls._currency(raw_money.get("display_currency")) or candidate_currency

        explicit_loss = cls._money_signal(
            cls._value(candidate, "estimated_loss_exposure", default=None),
            fallback_currency=candidate_currency,
            basis="reported_estimated_loss_exposure",
            fallback_evidence_ids=evidence_ids,
        )
        explicit_var = cls._money_signal(
            cls._value(candidate, "value_at_risk", default=None),
            fallback_currency=candidate_currency,
            basis="reported_value_at_risk",
            fallback_evidence_ids=evidence_ids,
        )
        profit = cls._value(candidate, "profit", default={}) or {}
        if not explicit_var and isinstance(profit, Mapping):
            risk = profit.get("risk_adjusted_profit") or {}
            scenario = profit.get("scenario_profit") or {}
            if isinstance(risk, Mapping):
                explicit_var = cls._negative_profit_signal(
                    risk,
                    fields=("cvar_cm3", "downside_cm3", "amount"),
                    basis_prefix="negative_risk_adjusted",
                    fallback_currency=candidate_currency,
                    fallback_evidence_ids=evidence_ids,
                )
            if not explicit_var and isinstance(scenario, Mapping):
                explicit_var = cls._negative_profit_signal(
                    scenario,
                    fields=("cvar_cm3", "downside_cm3"),
                    basis_prefix="negative_scenario",
                    fallback_currency=candidate_currency,
                    fallback_evidence_ids=evidence_ids,
                )
        if not explicit_loss and isinstance(profit, Mapping):
            for basis in ("cash_profit", "settlement_profit", "accrual_profit"):
                projection = profit.get(basis) or {}
                if isinstance(projection, Mapping):
                    explicit_loss = cls._negative_profit_signal(
                        projection,
                        fields=("amount",),
                        basis_prefix=f"negative_{basis}",
                        fallback_currency=candidate_currency,
                        fallback_evidence_ids=evidence_ids,
                    )
                if explicit_loss:
                    break
        return {
            "estimated_loss_exposure": explicit_loss or cls._no_data_signal(),
            "value_at_risk": explicit_var or cls._no_data_signal(),
        }

    @classmethod
    def _money_signal(
        cls,
        value: Any,
        *,
        fallback_currency: str | None,
        basis: str,
        fallback_evidence_ids: list[str],
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            amount = cls._decimal(value.get("amount"))
            currency = cls._currency(value.get("currency")) or fallback_currency
            evidence_ids = sorted(
                {
                    *fallback_evidence_ids,
                    *cls._codes(value.get("evidence_ids") or []),
                    *(
                        [cls._text(value.get("evidence_id"))]
                        if cls._text(value.get("evidence_id"))
                        else []
                    ),
                }
            )
            signal_basis = cls._text(value.get("basis")) or basis
        else:
            amount = cls._decimal(value)
            currency = fallback_currency
            evidence_ids = fallback_evidence_ids
            signal_basis = basis
        if amount is None or amount < 0 or not currency:
            return None
        return {
            "status": "reported" if evidence_ids else "reported_unverified",
            "amount": cls._decimal_text(amount),
            "currency": currency,
            "basis": signal_basis,
            "evidence_ids": evidence_ids,
        }

    @classmethod
    def _negative_profit_signal(
        cls,
        projection: Mapping[str, Any],
        *,
        fields: tuple[str, ...],
        basis_prefix: str,
        fallback_currency: str | None,
        fallback_evidence_ids: list[str],
    ) -> dict[str, Any] | None:
        currency = cls._currency(projection.get("currency")) or fallback_currency
        evidence_ids = sorted(
            {
                *fallback_evidence_ids,
                *cls._codes(projection.get("evidence_ids") or []),
                *(
                    [cls._text(projection.get("evidence_id"))]
                    if cls._text(projection.get("evidence_id"))
                    else []
                ),
            }
        )
        for field in fields:
            amount = cls._decimal(projection.get(field))
            if amount is not None and amount < 0 and currency:
                return {
                    "status": "derived_from_reported_negative_profit",
                    "amount": cls._decimal_text(abs(amount)),
                    "currency": currency,
                    "basis": f"{basis_prefix}_{field}",
                    "evidence_ids": evidence_ids,
                }
        return None

    @classmethod
    def _reconcile(
        cls,
        bundle: dict[str, Any],
        sources: list[dict[str, Any]],
        duplicate_source_count: int,
    ) -> dict[str, Any]:
        observed = {
            "source_total": len(sources),
            "accepted": sum(item["disposition"] == "accepted" for item in sources),
            "quarantined": sum(item["disposition"] == "quarantined" for item in sources),
        }
        declared = bundle["counts"]
        if observed != declared:
            raise ProfitDataRemediationInvariantError(
                "Observed source inventory does not reconcile to bundle counts"
            )
        return {
            **observed,
            "accepted_plus_quarantined": observed["accepted"] + observed["quarantined"],
            "conservation_passed": observed["accepted"] + observed["quarantined"] == observed["source_total"],
            "declared_counts_match": observed == declared,
            "all_source_items_retained": True,
            "duplicate_input_occurrences": duplicate_source_count,
        }

    @classmethod
    def _group(
        cls,
        issues: list[dict[str, Any]],
        field: str,
        *,
        missing_key: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for issue in issues:
            key = cls._text(issue.get(field)) or missing_key
            grouped.setdefault(key, []).append(issue)
        result: list[dict[str, Any]] = []
        for key, members in grouped.items():
            members.sort(key=cls._priority_key)
            signals: dict[str, Decimal] = {}
            for member in members:
                for signal_name in ("value_at_risk", "estimated_loss_exposure"):
                    signal = member[signal_name]
                    amount = cls._decimal(signal.get("amount"))
                    currency = cls._currency(signal.get("currency"))
                    if amount is not None and currency:
                        signals[currency] = max(amount, signals.get(currency, Decimal("0")))
            result.append(
                {
                    "key": key,
                    "issue_count": len(members),
                    "source_item_count": len(
                        {item["source_item_id"] for item in members if item["source_item_id"]}
                    ),
                    "candidate_count": len(
                        {item["candidate_id"] for item in members if item["candidate_id"]}
                    ),
                    "remediation_item_ids": [item["remediation_item_id"] for item in members],
                    "status_counts": {
                        status: sum(item["status"] == status for item in members)
                        for status in ("open", "stale", "blocked")
                    },
                    "max_priority_signal_by_currency": [
                        {"currency": currency, "amount": cls._decimal_text(amount)}
                        for currency, amount in sorted(signals.items())
                    ],
                    "evidence_ids": sorted(
                        {
                            evidence_id
                            for item in members
                            for evidence_id in item["evidence_ids"]
                        }
                    ),
                }
            )
        return sorted(
            result,
            key=lambda group: (
                cls._priority_key(
                    next(
                        item
                        for item in issues
                        if item["remediation_item_id"] == group["remediation_item_ids"][0]
                    )
                ),
                group["key"],
            ),
        )

    @classmethod
    def _priority_key(cls, issue: dict[str, Any]) -> tuple[Any, ...]:
        signal = issue.get("value_at_risk") or {}
        if signal.get("status") == "no_data":
            signal = issue.get("estimated_loss_exposure") or {}
        amount = cls._decimal(signal.get("amount"))
        currency = cls._currency(signal.get("currency")) or "ZZZ"
        return (
            _STATUS_ORDER.get(issue.get("status"), 9),
            _SEVERITY_ORDER.get(issue.get("severity"), 9),
            -int(issue.get("unblock_impact_score") or 0),
            1 if amount is None else 0,
            currency,
            -(amount or Decimal("0")),
            issue.get("remediation_item_id") or "",
        )

    @classmethod
    def _candidate_input(
        cls,
        value: Mapping[str, Any] | Iterable[Mapping[str, Any] | Any],
    ) -> tuple[dict[str, Any], Iterable[Mapping[str, Any] | Any]]:
        if isinstance(value, Mapping):
            records = value.get("candidates")
            if records is None:
                records = value.get("items")
            if records is None:
                raise ProfitDataRemediationInvariantError(
                    "Candidate workspace must contain candidates"
                )
            if not isinstance(records, Iterable) or isinstance(records, (str, bytes, Mapping)):
                raise ProfitDataRemediationInvariantError("candidates must be an iterable of records")
            return dict(value), records
        if isinstance(value, (str, bytes)):
            raise ProfitDataRemediationInvariantError("candidates must be an iterable of records")
        return {}, value

    @staticmethod
    def _workspace_status(
        issues: list[dict[str, Any]],
        reconciliation: dict[str, Any],
    ) -> str:
        if not reconciliation["conservation_passed"]:
            return "blocked"
        if any(issue["status"] == "blocked" for issue in issues):
            return "blocked"
        if issues:
            return "ready_with_constraints"
        return "complete"

    @classmethod
    def _source_sku(cls, value: Mapping[str, Any] | Any, payload: Any) -> str | None:
        direct = cls._text(cls._value(value, "sku", "offer_id"))
        if direct:
            return direct
        if isinstance(payload, Mapping):
            return cls._text(payload.get("sku") or payload.get("offer_id")) or None
        return None

    @classmethod
    def _evidence_ids(cls, value: Mapping[str, Any] | Any) -> list[str]:
        ids = set(
            cls._codes(
                cls._value(value, "evidence_ids", "evidence_refs", default=[])
            )
        )
        for field in ("artifact_evidence_id", "evidence_id", "request_evidence_id"):
            evidence_id = cls._text(cls._value(value, field))
            if evidence_id:
                ids.add(evidence_id)
        return sorted(ids)

    @classmethod
    def _is_stale(cls, value: Mapping[str, Any] | Any, *, as_of: datetime) -> bool:
        if bool(cls._value(value, "stale", "is_stale", default=False)):
            return True
        expires_at = cls._value(value, "expires_at", "effective_until", default=None)
        if not expires_at:
            return False
        parsed = cls._datetime(expires_at)
        if parsed is None:
            raise ProfitDataRemediationInvariantError("Staleness timestamp must be timezone-aware ISO-8601")
        return parsed <= as_of

    @classmethod
    def _scope(cls, value: Mapping[str, Any]) -> dict[str, str]:
        normalized = cls._optional_scope(value)
        if normalized is None:
            raise ProfitDataRemediationInvariantError(
                "scope requires tenant_ref, entity_ref, and store_ref"
            )
        return normalized

    @classmethod
    def _optional_scope(cls, value: Any) -> dict[str, str] | None:
        if value is None:
            return None
        tenant_ref = cls._text(cls._value(value, "tenant_ref"))
        entity_ref = cls._text(cls._value(value, "entity_ref"))
        store_ref = cls._text(cls._value(value, "store_ref"))
        present = [bool(tenant_ref), bool(entity_ref), bool(store_ref)]
        if not any(present):
            return None
        if not all(present):
            raise ProfitDataRemediationInvariantError(
                "Scope must include tenant_ref, entity_ref, and store_ref together"
            )
        scope = {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
        }
        authority = cls._text(
            cls._value(value, "scope_grant_authority_sha256", "authority_sha256")
        )
        if authority:
            if len(authority) != 64:
                raise ProfitDataRemediationInvariantError(
                    "Scope authority hash must contain 64 characters"
                )
            scope["scope_grant_authority_sha256"] = authority
        return scope

    @classmethod
    def _assert_scope(
        cls,
        expected: dict[str, str],
        actual: dict[str, str] | None,
        label: str,
    ) -> None:
        if actual is None:
            return
        for field in ("tenant_ref", "entity_ref", "store_ref"):
            if actual[field] != expected[field]:
                raise PermissionError(f"{label} is outside the authorized remediation scope")
        expected_authority = expected.get("scope_grant_authority_sha256")
        actual_authority = actual.get("scope_grant_authority_sha256")
        if expected_authority and actual_authority and expected_authority != actual_authority:
            raise PermissionError(f"{label} uses a different scope grant authority")

    @staticmethod
    def _as_of(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _value(value: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(value, Mapping) and name in value:
                return value[name]
            if not isinstance(value, Mapping) and hasattr(value, name):
                return getattr(value, name)
        return default

    @staticmethod
    def _text(value: Any) -> str:
        return str(value).strip() if value not in (None, "") else ""

    @classmethod
    def _codes(cls, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, Iterable) or isinstance(value, Mapping):
            raise ProfitDataRemediationInvariantError("Code and Evidence collections must be iterable")
        return sorted({cls._text(item) for item in value if cls._text(item)})

    @staticmethod
    def _integer(value: Any, field: str) -> int:
        if isinstance(value, bool):
            raise ProfitDataRemediationInvariantError(f"{field} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ProfitDataRemediationInvariantError(f"{field} must be an integer") from exc
        if str(parsed) != str(value).strip() and not isinstance(value, int):
            raise ProfitDataRemediationInvariantError(f"{field} must be an integer")
        return parsed

    @staticmethod
    def _optional_integer(value: Any) -> int | None:
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _currency(value: Any) -> str | None:
        text = str(value).strip() if value not in (None, "") else ""
        if len(text) == 3 and text.isascii() and text.isalpha() and text.isupper():
            return text
        return None

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value in (None, "") or isinstance(value, (bool, float)):
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"

    @classmethod
    def _datetime(cls, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

    @classmethod
    def _hash(cls, value: Any) -> str:
        canonical = json.dumps(
            cls._json_safe(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): cls._json_safe(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted((cls._json_safe(item) for item in value), key=str)
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ProfitDataRemediationInvariantError(
                    "Input datetime values must include a timezone"
                )
            return value.astimezone(UTC).isoformat()
        if isinstance(value, Decimal):
            return cls._decimal_text(value)
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ProfitDataRemediationInvariantError(
                    "Non-finite floating point values are not accepted in remediation inputs"
                )
            # Source JSON may already contain finite floats. Preserve their decimal
            # text for lineage without admitting binary floats into money logic.
            return cls._decimal_text(Decimal(str(value)))
        return str(value)

    @staticmethod
    def _no_data_signal() -> dict[str, Any]:
        return {
            "status": "no_data",
            "amount": None,
            "currency": None,
            "basis": None,
            "evidence_ids": [],
        }

    @classmethod
    def _empty_priority_signals(cls) -> dict[str, Any]:
        return {
            "estimated_loss_exposure": cls._no_data_signal(),
            "value_at_risk": cls._no_data_signal(),
        }


def build_profit_data_remediation_workspace(
    *,
    scope: Mapping[str, Any],
    bundle: Mapping[str, Any] | Any,
    source_items: Iterable[Mapping[str, Any] | Any],
    candidates: Mapping[str, Any] | Iterable[Mapping[str, Any] | Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Functional entry point for callers that do not need a service object."""

    return ProfitDataRemediationWorkspace().project(
        scope=scope,
        bundle=bundle,
        source_items=source_items,
        candidates=candidates,
        as_of=as_of,
    )
