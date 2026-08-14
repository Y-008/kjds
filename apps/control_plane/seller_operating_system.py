from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .ozon_global_rules import ACTION_METADATA

SELLER_OS_CONTRACT_VERSION = "seller-operating-system/1.0.0"
MATURITY_ORDER = (
    "novice",
    "solo",
    "small_team",
    "mid_market",
    "enterprise",
)
OPERATING_MODES = frozenset(
    {
        "controlled_distribution",
        "refined_operation",
        "hero_sku",
        "brand_building",
        "store_cluster",
        "hybrid",
    }
)
STRATEGY_PACK_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "seller_strategy_packs.json"
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


class StrategyPackRegistry:
    """Replayable append-only pack registry with effective-date lookup."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        payload: dict[str, Any] | None = None,
        as_of: date | str | None = None,
    ) -> None:
        self.path = path or STRATEGY_PACK_REGISTRY_PATH
        index = payload or json.loads(
            self.path.read_text(encoding="utf-8")
        )
        if index.get("registry_id") != "seller-strategy-packs-cn-ozon":
            raise RuntimeError("Unknown Seller Strategy Pack registry")
        selected_on = (
            date.fromisoformat(as_of)
            if isinstance(as_of, str)
            else as_of
            if isinstance(as_of, date)
            else date.today()
        )
        if "versions" in index:
            versions = index["versions"]
            if not isinstance(versions, list) or not versions:
                raise RuntimeError(
                    "Seller Strategy Pack version history is empty"
                )
            ordered = sorted(
                versions,
                key=lambda entry: date.fromisoformat(
                    entry["effective_from"]
                ),
            )
            previous_end: date | None = None
            for position, entry in enumerate(ordered):
                start = date.fromisoformat(entry["effective_from"])
                end = (
                    date.fromisoformat(entry["effective_to"])
                    if entry.get("effective_to")
                    else None
                )
                if end is not None and end < start:
                    raise RuntimeError(
                        "Seller Strategy Pack effective interval is invalid"
                    )
                if previous_end is None and position:
                    raise RuntimeError(
                        "Seller Strategy Pack effective intervals overlap: "
                        "an earlier version is open-ended"
                    )
                if previous_end is not None and start <= previous_end:
                    raise RuntimeError(
                        "Seller Strategy Pack effective intervals overlap"
                    )
                previous_end = end
            active = [
                entry
                for entry in ordered
                if date.fromisoformat(entry["effective_from"])
                <= selected_on
                and (
                    not entry.get("effective_to")
                    or selected_on
                    <= date.fromisoformat(entry["effective_to"])
                )
            ]
            if len(active) != 1:
                raise RuntimeError(
                    "No unambiguous Seller Strategy Pack version is "
                    "effective for as_of"
                )
            version_entry = active[0]
            artifact_path = (
                self.path.parent / version_entry["artifact_path"]
            )
            artifact_bytes = artifact_path.read_bytes()
            artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
            if artifact_hash != version_entry["artifact_sha256"]:
                raise RuntimeError(
                    "Seller Strategy Pack artifact hash mismatch"
                )
            raw = json.loads(artifact_bytes.decode("utf-8"))
            if (
                raw.get("version") != version_entry["version"]
                or raw.get("effective_from")
                != version_entry["effective_from"]
                or raw.get("effective_to")
                != version_entry.get("effective_to")
            ):
                raise RuntimeError(
                    "Seller Strategy Pack index and artifact drift"
                )
            self.version_history = ordered
            self.registry_index_hash = _sha256(index)
            self.artifact_path = str(version_entry["artifact_path"])
            self.registry_hash = artifact_hash
        else:
            raw = index
            start = date.fromisoformat(raw["effective_from"])
            end = (
                date.fromisoformat(raw["effective_to"])
                if raw.get("effective_to")
                else None
            )
            if selected_on < start or (end and selected_on > end):
                raise RuntimeError(
                    "Seller Strategy Pack registry is not effective"
                )
            self.version_history = [
                {
                    "version": raw["version"],
                    "effective_from": raw["effective_from"],
                    "effective_to": raw.get("effective_to"),
                    "compatibility": "legacy_embedded_test_payload",
                }
            ]
            self.registry_index_hash = _sha256(raw)
            self.artifact_path = None
            self.registry_hash = _sha256(raw)
        packs = {}
        for maturity in MATURITY_ORDER:
            entry = raw["strategy_packs"].get(maturity)
            if not entry:
                raise RuntimeError(f"Strategy Pack missing: {maturity}")
            commercial = entry["commercial"]
            envelope = entry["policy_envelope"]
            packs[maturity] = {
                "label": entry["label"],
                "commercial_plan": commercial["plan"],
                **{
                    key: value
                    for key, value in commercial.items()
                    if key != "plan"
                },
                **envelope,
            }
        self.raw = raw
        self.selected_as_of = selected_on.isoformat()
        self.strategy_packs = packs
        self.portfolio_policy = raw["portfolio_policy"]
        self.governance_invariants = raw["governance_invariants"]

    def snapshot(self) -> dict[str, Any]:
        return {
            "registry_id": self.raw["registry_id"],
            "version": self.raw["version"],
            "effective_from": self.raw["effective_from"],
            "effective_to": self.raw["effective_to"],
            "observed_at": self.raw["observed_at"],
            "registry_hash": self.registry_hash,
            "registry_index_hash": self.registry_index_hash,
            "selected_as_of": self.selected_as_of,
            "artifact_path": self.artifact_path,
            "version_history": self.version_history,
            "commercial_status": self.raw.get(
                "commercial_status",
                "hypothesis_internal_preview_not_for_sale",
            ),
            "strategy_packs": self.strategy_packs,
            "portfolio_policy": self.portfolio_policy,
            "governance_invariants": self.governance_invariants,
        }


_DEFAULT_STRATEGY_REGISTRY = StrategyPackRegistry()
STRATEGY_PACKS = _DEFAULT_STRATEGY_REGISTRY.strategy_packs
PORTFOLIO_POLICY = _DEFAULT_STRATEGY_REGISTRY.portfolio_policy


class SellerOperatingSystem:
    """Fact classifier and policy envelopes over one shared governance kernel."""

    def __init__(
        self,
        *,
        ozon_rules,
        strategy_registry=None,
        clock=None,
    ) -> None:
        self.ozon_rules = ozon_rules
        self.strategy_registry = (
            strategy_registry or _DEFAULT_STRATEGY_REGISTRY
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def packs(self) -> dict[str, Any]:
        return {
            "contract_version": SELLER_OS_CONTRACT_VERSION,
            "strategy_pack_registry": self.strategy_registry.snapshot(),
            "strategy_packs": self.strategy_registry.strategy_packs,
            "portfolio_policy": self.strategy_registry.portfolio_policy,
            "facts_and_profit_kernel": "identical_for_all_plans",
            "truth_degradation_by_plan": False,
            "usage_charges": {
                "ai_image_video_high_frequency_collection": (
                    "transparent_metered_usage"
                ),
                "managed_operations": (
                    "fixed_service_fee_plus_incremental_profit_reward"
                ),
                "gmv_commission_recommended": False,
            },
            "external_execution_invariant": [
                "independent_approval",
                "one_time_permit",
                "readback",
                "kill_switch",
                "compensation",
            ],
        }

    def classify_maturity(self, facts: dict[str, Any]) -> dict[str, Any]:
        values = facts.get("values")
        provenance = facts.get("provenance")
        if not isinstance(values, dict) or not isinstance(provenance, dict):
            return {
                "status": "no_data",
                "classification": None,
                "confidence": "0",
                "input_completeness": "0",
                "evidence_coverage": "0",
                "classification_confidence": "0",
                "missing_facts": ["values", "provenance"],
                "user_label_promoted_to_fact": False,
            }
        fields = (
            "shops",
            "active_skus",
            "users",
            "warehouses",
            "capital_cny",
            "risk_tolerance",
            "brand_maturity",
            "ops_capability",
        )
        missing = [
            field
            for field in fields
            if values.get(field) in (None, "", "no_data")
        ]
        if missing:
            return {
                "status": "no_data",
                "classification": None,
                "confidence": "0",
                "input_completeness": str(
                    (
                        Decimal(len(fields) - len(missing))
                        / Decimal(len(fields))
                    ).quantize(Decimal("0.01"))
                ),
                "evidence_coverage": "0",
                "classification_confidence": "0",
                "missing_facts": missing,
                "user_label_promoted_to_fact": False,
            }
        numeric_limits = {
            "shops": 10_000,
            "active_skus": 100_000_000,
            "users": 1_000_000,
            "warehouses": 100_000,
        }
        parsed_numbers = {}
        for field, maximum in numeric_limits.items():
            try:
                parsed = int(values[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be an integer") from exc
            if parsed < 0 or parsed > maximum:
                raise ValueError(f"{field} is outside the supported range")
            parsed_numbers[field] = parsed
        capital = _decimal(values["capital_cny"])
        if capital is None or capital < 0 or capital > Decimal("1000000000000"):
            raise ValueError("capital_cny is outside the supported range")
        allowed_scales = {
            "risk_tolerance": {"low", "moderate", "high"},
            "brand_maturity": {
                "unverified",
                "reseller",
                "authorized",
                "owned",
                "portfolio",
            },
            "ops_capability": {
                "guided",
                "manual",
                "standardized",
                "api_scheduled",
                "erp_wms",
            },
        }
        for field, allowed in allowed_scales.items():
            if values[field] not in allowed:
                raise ValueError(
                    f"{field} must be one of: {', '.join(sorted(allowed))}"
                )
        source = provenance.get("source")
        if source not in {
            "user_self_report",
            "system_observed",
            "evidence_verified",
        }:
            raise ValueError("seller fact provenance source is invalid")
        evidence_ids = provenance.get("evidence_ids") or []
        if not isinstance(evidence_ids, list) or not all(
            isinstance(value, str) and value.strip()
            for value in evidence_ids
        ):
            raise ValueError("seller fact evidence_ids must be string ids")
        if source == "evidence_verified" and not evidence_ids:
            raise ValueError(
                "evidence_verified seller facts require evidence_ids"
            )
        try:
            observed_at = datetime.fromisoformat(
                str(provenance.get("observed_at") or "").replace(
                    "Z", "+00:00"
                )
            )
        except ValueError as exc:
            raise ValueError(
                "seller fact observed_at must be ISO-8601"
            ) from exc
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("seller fact observed_at requires timezone")
        age = self.clock() - observed_at.astimezone(UTC)
        if age.total_seconds() < 0:
            raise ValueError("seller fact observed_at cannot be in the future")
        shops = parsed_numbers["shops"]
        skus = parsed_numbers["active_skus"]
        users = parsed_numbers["users"]
        warehouses = parsed_numbers["warehouses"]
        if (
            shops >= 50
            or skus >= 1_000_000
            or users >= 500
            or capital >= Decimal("50000000")
        ):
            classification = "enterprise"
        elif (
            shops >= 10
            or skus >= 100_000
            or users >= 100
            or warehouses >= 10
            or capital >= Decimal("10000000")
        ):
            classification = "mid_market"
        elif (
            shops >= 3
            or skus >= 1000
            or users >= 6
            or warehouses >= 3
            or capital >= Decimal("1000000")
        ):
            classification = "small_team"
        elif (
            shops >= 1
            and (
                skus > 100
                or users > 1
                or capital >= Decimal("100000")
            )
        ):
            classification = "solo"
        else:
            classification = "novice"
        source_confidence = {
            "user_self_report": Decimal("0.55"),
            "system_observed": Decimal("0.85"),
            "evidence_verified": Decimal("1.00"),
        }[source]
        freshness = (
            Decimal("1")
            if age.days <= 30
            else Decimal("0.8")
            if age.days <= 90
            else Decimal("0.5")
        )
        evidence_coverage = {
            "user_self_report": Decimal("0.25"),
            "system_observed": Decimal("0.60"),
            "evidence_verified": Decimal("1.00"),
        }[source]
        confidence = (
            source_confidence
            * freshness
            * (
                Decimal("0.50")
                + Decimal("0.50") * evidence_coverage
            )
        )
        return {
            "status": "classified",
            "classification": classification,
            "classification_semantics": (
                "deprecated_alias_for_scale_segment"
            ),
            "scale_segment": classification,
            "operational_maturity": {
                "guided": "nascent",
                "manual": "manual_repeatable",
                "standardized": "standardized",
                "api_scheduled": "automated",
                "erp_wms": "integrated",
            }[values["ops_capability"]],
            "brand_stage": values["brand_maturity"],
            "risk_posture": values["risk_tolerance"],
            "axis_confidence": {
                "scale_segment": str(
                    confidence.quantize(Decimal("0.01"))
                ),
                "operational_maturity": str(
                    confidence.quantize(Decimal("0.01"))
                ),
                "brand_stage": str(
                    confidence.quantize(Decimal("0.01"))
                ),
                "risk_posture": str(
                    confidence.quantize(Decimal("0.01"))
                ),
            },
            "confidence": str(confidence.quantize(Decimal("0.01"))),
            "input_completeness": "1.00",
            "evidence_coverage": str(
                evidence_coverage.quantize(Decimal("0.01"))
            ),
            "classification_confidence": str(
                confidence.quantize(Decimal("0.01"))
            ),
            "basis": {field: values[field] for field in fields},
            "provenance": {
                "source": source,
                "observed_at": observed_at.astimezone(UTC).isoformat(),
                "evidence_ids": evidence_ids,
                "source_semantics": (
                    "recommendation_input_not_promoted_fact"
                    if source == "user_self_report"
                    else "observed_fact"
                ),
            },
            "missing_facts": [],
            "user_label_promoted_to_fact": False,
        }

    def evaluate(
        self,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self.classify_maturity(
            values.get("seller_facts") or {}
        )
        if profile["status"] == "no_data":
            return {
                "contract_version": SELLER_OS_CONTRACT_VERSION,
                "status": "no_data",
                "seller_profile": profile,
                "strategy": None,
                "policy_envelope": None,
                "portfolio": None,
                "advantage": None,
                "external_write_performed": False,
            }
        scale_segment = profile["scale_segment"]
        pack = self.strategy_registry.strategy_packs[scale_segment]
        strategy = self._strategy(
            values.get("operating_facts") or {},
            profile=profile,
        )
        envelope = self._envelope(
            pack,
            values.get("policy_overrides") or {},
        )
        portfolio = self._portfolio(
            values.get("portfolio_items") or []
        )
        advantage = self._advantage(
            values.get("advantage_facts") or {},
            envelope=envelope,
        )
        blockers = sorted(
            set(
                strategy["blockers"]
                + envelope["blockers"]
                + portfolio["blockers"]
                + advantage["blockers"]
            )
        )
        action_readiness = self._action_readiness(
            strategy=strategy,
            envelope=envelope,
            portfolio=portfolio,
            advantage=advantage,
            values=values,
        )
        basis = {
            "seller_profile": profile,
            "strategy": strategy,
            "policy_envelope": envelope,
            "portfolio": portfolio,
            "advantage": advantage,
            "ozon_rule_registry_hash": self.ozon_rules.registry_hash,
            "strategy_pack_registry_hash": (
                self.strategy_registry.registry_hash
            ),
        }
        return {
            "contract_version": SELLER_OS_CONTRACT_VERSION,
            "status": (
                "ready"
                if action_readiness["external_publish"]["status"] == "ready"
                else "ready_with_constraints"
            ),
            **basis,
            "strategy_pack": {
                **pack,
                "recommendation_basis": (
                    "scale_capacity_fit_with_separate_operational_brand_"
                    "and_risk_strategy_axes"
                ),
                "commercial_entitlement_created": False,
                "facts_and_profit_kernel": "shared",
                "truth_degraded": False,
            },
            "decision_fingerprint": _sha256(basis),
            "blockers": blockers,
            "action_readiness": action_readiness,
            "confidence": min(
                profile["confidence"],
                strategy["confidence"],
            ),
            "external_execution": {
                "approval_required": True,
                "one_time_permit_required": True,
                "readback_required": True,
                "kill_switch_required": True,
                "compensation_required": True,
                "permit_created": False,
                "external_write_performed": False,
            },
        }

    @staticmethod
    def _action_readiness(
        *,
        strategy: dict[str, Any],
        envelope: dict[str, Any],
        portfolio: dict[str, Any],
        advantage: dict[str, Any],
        values: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        def action(
            blockers: list[str],
            *,
            not_applicable: bool = False,
        ) -> dict[str, Any]:
            return {
                "status": (
                    "not_applicable_prelaunch"
                    if not_applicable
                    else "blocked"
                    if blockers
                    else "ready"
                ),
                "blockers": sorted(set(blockers)),
                "why": (
                    "action_scoped_requirements_satisfied"
                    if not blockers
                    else "action_scoped_requirements_missing"
                ),
            }

        scoring = strategy["blockers"]
        pilot = scoring + envelope["blockers"]
        external = pilot + [
            "independent_approval_missing",
            "one_time_permit_missing",
            "readback_plan_missing",
            "kill_switch_check_missing",
            "compensation_plan_missing",
        ]
        portfolio_items = values.get("portfolio_items") or []
        has_actual_cash = any(
            item.get("actual_cash_cm3_cny") not in (None, "", "no_data")
            for item in portfolio_items
        )
        scale = external + (
            []
            if has_actual_cash
            else ["scale_reconciled_cash_cm3_missing"]
        )
        reconcile = (
            []
            if portfolio_items
            else ["settlement_order_or_statement_missing"]
        )
        result = {
            "observe_research": action([]),
            "candidate_score": action(scoring),
            "content_draft": action([]),
            "pilot_approve": action(pilot),
            "external_publish": action(external),
            "scale": action(scale + advantage["blockers"]),
            "settlement_reconcile": action(
                reconcile + portfolio["blockers"],
                not_applicable=not portfolio_items,
            ),
        }
        for name, row in result.items():
            row.update(ACTION_METADATA[name])
            row["missing_evidence"] = [
                blocker
                for blocker in row["blockers"]
                if any(
                    token in blocker
                    for token in (
                        "evidence",
                        "approval",
                        "permit",
                        "readback",
                        "statement",
                        "reconciled",
                    )
                )
            ]
        return result

    def candidate_matrix(
        self,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        economics = candidate["economics"]
        downside = economics["downside"]
        actual_cash = economics.get("actual_profit")
        rule_state = candidate["ozon_global_cn"]["state"]
        rows = []
        for maturity in MATURITY_ORDER:
            pack = self.strategy_registry.strategy_packs[maturity]
            budget = Decimal(pack["single_sku_budget_cny"])
            cash = _decimal(downside.get("inventory_cash_cny"))
            within_budget = cash is not None and cash <= budget
            blockers = []
            if not within_budget:
                blockers.append("profile_single_sku_budget_exceeded")
            if rule_state != "ready":
                blockers.append("ozon_global_cn_rules_not_ready")
            if candidate["pilot_ready"] is not True:
                blockers.append("candidate_pilot_gates_not_ready")
            rows.append(
                {
                    "maturity": maturity,
                    "label": pack["label"],
                    "scenario_semantics": (
                        "policy_scenario_not_actual_seller_profile"
                    ),
                    "scan_batch_max": pack["scan_batch_max"],
                    "approval_layers": pack["approval_layers"],
                    "single_sku_budget_cny": (
                        pack["single_sku_budget_cny"]
                    ),
                    "initial_pilot_units_max": 3,
                    "scaled_inventory_cap": pack[
                        "scaled_inventory_cap"
                    ],
                    "inventory_stage_semantics": (
                        "scale cap applies only after 24h/72h/7d "
                        "readback, settlement and independent approval"
                    ),
                    "advertising_daily_cap_cny": (
                        pack["advertising_daily_cap_cny"]
                    ),
                    "permit_ttl_minutes": pack["permit_ttl_minutes"],
                    "decision": (
                        "eligible_for_independent_approval"
                        if not blockers
                        else "blocked"
                    ),
                    "blockers": blockers,
                    "actual_cash_profit_used": actual_cash is not None,
                    "external_write_performed": False,
                }
            )
        return {
            "same_candidate_facts": True,
            "candidate_fingerprint": candidate["fingerprint"],
            "rows": rows,
            "success_metric": (
                "reconciled_cm3_cash_cycle_and_controlled_learning"
            ),
            "automatic_listing_count_is_success_metric": False,
        }

    @staticmethod
    def _strategy(
        facts: dict[str, Any],
        *,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        downside = _decimal(facts.get("downside_cm3_cny"))
        settlements = int(facts.get("settlement_cycles") or 0)
        confidence = _decimal(facts.get("data_confidence"))
        if downside is None:
            blockers.append("strategy_downside_cm3_no_data")
        if confidence is None:
            blockers.append("strategy_confidence_no_data")
            confidence = Decimal("0")
        if downside is not None and downside <= 0:
            mode = "controlled_distribution"
            blockers.append("strategy_downside_cm3_not_positive")
        elif (
            profile["scale_segment"] == "enterprise"
            and profile["operational_maturity"] == "integrated"
            and settlements >= 2
            and facts.get("multi_entity_ready") is True
        ):
            mode = "store_cluster"
        elif (
            profile["brand_stage"] in {"owned", "portfolio"}
            and facts.get("brand_authorized") is True
            and settlements >= 2
        ):
            mode = "brand_building"
        elif settlements >= 2 and confidence >= Decimal("0.9"):
            mode = "hero_sku"
        elif (
            settlements >= 1
            and confidence >= Decimal("0.75")
            and profile["operational_maturity"]
            in {"standardized", "automated", "integrated"}
        ):
            mode = "refined_operation"
        elif (
            profile["risk_posture"] == "high"
            and profile["operational_maturity"]
            in {"standardized", "automated", "integrated"}
        ):
            mode = "hybrid"
        else:
            mode = "controlled_distribution"
        return {
            "status": "blocked" if blockers else "recommended",
            "operating_mode": mode,
            "confidence": str(confidence),
            "blockers": blockers,
            "user_label_promoted_to_fact": False,
            "allowed_modes": sorted(OPERATING_MODES),
            "axis_basis": {
                "scale_segment": profile["scale_segment"],
                "operational_maturity": profile[
                    "operational_maturity"
                ],
                "brand_stage": profile["brand_stage"],
                "risk_posture": profile["risk_posture"],
            },
        }

    @staticmethod
    def _envelope(
        pack: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        envelope = {
            "external_write_default": pack["external_write_default"],
            "scan_batch_max": pack["scan_batch_max"],
            "single_sku_budget_cny": pack["single_sku_budget_cny"],
            "initial_pilot_units_max": 3,
            "scaled_inventory_cap": pack["scaled_inventory_cap"],
            "advertising_daily_cap_cny": (
                pack["advertising_daily_cap_cny"]
            ),
            "approval_layers": pack["approval_layers"],
            "permit_ttl_minutes": pack["permit_ttl_minutes"],
            "price_stop_loss": "downside_cm3_cny <= 0",
            "inventory_stop_loss": "cash_cycle_or_sell_through_breach",
            "kill_switch_required": True,
        }
        allowed = {
            "scan_batch_max",
            "single_sku_budget_cny",
            "scaled_inventory_cap",
            "advertising_daily_cap_cny",
        }
        for key, value in overrides.items():
            if key not in allowed:
                blockers.append(f"policy_override_{key}_not_allowed")
                continue
            default = _decimal(envelope[key])
            requested = _decimal(value)
            if default is None or requested is None or requested > default:
                blockers.append(f"policy_override_{key}_expands_default")
                continue
            envelope[key] = str(requested)
        return {
            "status": "blocked" if blockers else "ready",
            **envelope,
            "blockers": blockers,
            "configurable_only_within_governance": True,
        }

    @staticmethod
    def _portfolio(items: list[dict[str, Any]]) -> dict[str, Any]:
        buckets = {key: [] for key in PORTFOLIO_POLICY if key != "semantics"}
        blockers = []
        if not items:
            return {
                "status": "no_data",
                "snapshot_established": False,
                "allocation_policy": PORTFOLIO_POLICY,
                "buckets": buckets,
                "counts": {key: 0 for key in buckets},
                "candidate_pool_is_portfolio": False,
                "unclassified": [],
                "blockers": ["portfolio_snapshot_missing"],
                "automatic_migration_basis": [
                    "actual_cash_cm3",
                    "cash_cycle",
                    "returns",
                    "fulfillment",
                    "data_confidence",
                ],
            }
        for item in items:
            sku_ref = str(item.get("sku_ref") or "")
            if not sku_ref:
                blockers.append("portfolio_sku_ref_missing")
                continue
            cash_cm3 = _decimal(item.get("actual_cash_cm3_cny"))
            confidence = _decimal(item.get("confidence"))
            returns = _decimal(item.get("return_rate"))
            fulfillment_status = item.get("fulfillment_status")
            fulfilled = fulfillment_status == "verified"
            cycles = int(item.get("settlement_cycles") or 0)
            if (
                cash_cm3 is None
                or confidence is None
                or returns is None
                or fulfillment_status not in {"verified", "failed"}
                or cycles < 1
            ):
                continue
            if cash_cm3 is not None and cash_cm3 <= 0:
                bucket = "exit"
            elif (
                cash_cm3 is not None
                and confidence is not None
                and confidence >= Decimal("0.9")
                and fulfilled
                and cycles >= 2
                and returns is not None
                and returns <= Decimal("0.1")
            ):
                bucket = "proven"
            elif cash_cm3 is not None and cycles >= 1 and fulfilled:
                bucket = "growth"
            else:
                bucket = "experiment"
            buckets[bucket].append(sku_ref)
        classified = sum(len(values) for values in buckets.values())
        classified_skus = {
            sku_ref for values in buckets.values() for sku_ref in values
        }
        unclassified = [
            str(item.get("sku_ref") or "missing_sku_ref")
            for item in items
            if str(item.get("sku_ref") or "missing_sku_ref")
            not in classified_skus
        ]
        if unclassified:
            blockers.append("portfolio_minimum_fact_contract_incomplete")
        return {
            "status": (
                "no_data"
                if classified == 0
                else "partial"
                if blockers
                else "ready"
            ),
            "snapshot_established": classified > 0,
            "classified_snapshot_established": classified > 0,
            "allocation_policy": PORTFOLIO_POLICY,
            "buckets": buckets,
            "counts": {key: len(value) for key, value in buckets.items()},
            "unclassified": unclassified,
            "unclassified_count": len(unclassified),
            "unclassified_receives_allocation": False,
            "blockers": blockers,
            "automatic_migration_basis": [
                "actual_cash_cm3",
                "cash_cycle",
                "returns",
                "fulfillment",
                "data_confidence",
            ],
        }

    def _advantage(
        self,
        facts: dict[str, Any],
        *,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        rule_impact = self.ozon_rules.impact(
            previous_registry=facts.get("previous_registry"),
            previous_registry_hash=facts.get(
                "previous_registry_hash"
            ),
            sku_bindings=facts.get("sku_rule_bindings") or [],
            as_of=facts.get("as_of"),
        )
        required = (
            "price_index_frontier",
            "cluster_inventory",
            "content_quality_score",
            "russian_semantic_matrix",
            "qa_insights",
            "advertising_marginal_profit",
            "cash_constrained_replenishment",
            "verified_parent_variant",
        )
        missing = [
            field
            for field in required
            if facts.get(field) in (None, "", "no_data")
        ]
        return {
            "status": (
                "no_data"
                if missing or rule_impact["state"] == "no_data"
                else "ready"
            ),
            "rule_registry_hash": self.ozon_rules.registry_hash,
            "rule_change_simulation": rule_impact,
            "capabilities": {
                "price_index_profit_frontier": (
                    facts.get("price_index_frontier")
                ),
                "region_cluster_inventory": facts.get("cluster_inventory"),
                "content_quality_score": facts.get("content_quality_score"),
                "russian_semantic_compatibility": (
                    facts.get("russian_semantic_matrix")
                ),
                "review_qa_insights": facts.get("qa_insights"),
                "advertising_marginal_profit": (
                    facts.get("advertising_marginal_profit")
                ),
                "cash_constrained_replenishment": (
                    facts.get("cash_constrained_replenishment")
                ),
                "parent_winner_variant_expansion": (
                    facts.get("verified_parent_variant")
                ),
            },
            "policy_envelope_applied": envelope["status"] == "ready",
            "rule_bypass_allowed": False,
            "blockers": [
                f"advantage_{field}_no_data" for field in missing
            ]
            + (
                ["advantage_rule_diff_no_data"]
                if rule_impact["state"] == "no_data"
                else []
            ),
        }
