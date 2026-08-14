from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any


class EnterprisePositioningError(ValueError):
    """Raised when an enterprise profile or positioning contract drifts."""


class EnterprisePositioningAdvisor:
    """Compile enterprise positioning and capability templates from one profile.

    ``position(profile)`` is the Module's only Interface. The implementation is
    deterministic and side-effect free: it cannot create identities, appoint a
    human, start work, grant authority, promote facts, or write externally.
    """

    CONTRACT_ID = "kjds-enterprise-positioning-advisor-v2"
    SCHEMA_VERSION = "kjds-enterprise-positioning-profiles-v2"
    VERSION = "2.0.0"
    PROFILE_FIELDS = frozenset(
        {
            "enterprise_ref",
            "business_model",
            "stage",
            "headcount_band",
            "markets",
            "platforms",
            "risk_class",
            "primary_objective",
        }
    )
    RECOMMENDATION_STATUSES = frozenset(
        {"required_now", "supporting_ai", "on_demand", "standby"}
    )
    SOD_RULES = (
        ("writer_vs_verifier", "artifact_writer", "artifact_verifier"),
        (
            "agent_skill_owner_vs_promotion_approver",
            "agent_or_skill_owner",
            "promotion_approver",
        ),
        (
            "finance_entry_preparer_vs_payment_approver",
            "finance_entry_preparer",
            "payment_approver",
        ),
        (
            "regulatory_researcher_vs_legal_signer",
            "regulatory_researcher",
            "formal_legal_opinion_signer",
        ),
        (
            "migration_author_vs_release_approver",
            "migration_author",
            "final_release_approver",
        ),
        (
            "external_action_approver_vs_executor",
            "external_action_approver",
            "external_action_executor",
        ),
    )
    _IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]+")

    def __init__(
        self,
        registry_path: str | Path | None = None,
        team_registry_path: str | Path | None = None,
        expert_registry_path: str | Path | None = None,
        enterprise_program_path: str | Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        registries = root / "docs" / "project" / "registries"
        configured = registry_path or os.getenv("KJDS_ENTERPRISE_POSITIONING_PATH")
        self.registry_path = Path(configured) if configured else (
            registries / "enterprise_positioning_profiles.json"
        )
        self.team_registry_path = Path(
            team_registry_path or registries / "team_control_tower_registry.json"
        )
        self.expert_registry_path = Path(
            expert_registry_path or registries / "global_expert_team_registry.json"
        )
        self.enterprise_program_path = Path(
            enterprise_program_path or registries / "enterprise_ai_erp_program.json"
        )

        self._registry = self._read_json(self.registry_path, "positioning registry")
        self._team = self._read_json(self.team_registry_path, "team registry")
        self._experts = self._read_json(self.expert_registry_path, "expert registry")
        self._enterprise_program = self._read_json(
            self.enterprise_program_path, "enterprise program registry"
        )
        self._catalog, self._catalog_has_duplicates = self._build_catalog()
        self._validate_registry()
        self._source_hashes = {
            "enterprise_ai_erp_program": self._hash(self._enterprise_program),
            "enterprise_positioning_profiles": self._hash(self._registry),
            "global_expert_team": self._hash(self._experts),
            "team_control_tower": self._hash(self._team),
        }
        self.source_bundle_sha256 = self._hash(self._source_hashes)

    def position(self, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return one defensive, deterministic capability and seat projection."""

        normalized = self._profile(
            self._registry["current_profile"] if profile is None else profile
        )
        stage = self._registry["stage_policies"][normalized["stage"]]
        business = self._registry["business_model_policies"][
            normalized["business_model"]
        ]
        risk = self._registry["risk_policies"][normalized["risk_class"]]
        objective = self._registry["objective_policies"][
            normalized["primary_objective"]
        ]

        statuses = dict.fromkeys(self._catalog, "standby")
        reasons: dict[str, list[str]] = {role_ref: [] for role_ref in self._catalog}
        self._apply_role_list(
            statuses,
            reasons,
            stage["required_now_role_refs"],
            "required_now",
            f"stage:{normalized['stage']}",
        )
        self._apply_role_list(
            statuses,
            reasons,
            stage["supporting_ai_role_refs"],
            "supporting_ai",
            f"stage:{normalized['stage']}",
        )
        self._apply_role_list(
            statuses,
            reasons,
            stage["on_demand_role_refs"],
            "on_demand",
            f"stage:{normalized['stage']}",
        )
        for role_ref, status in business["role_statuses"].items():
            self._promote(
                statuses,
                reasons,
                role_ref,
                status,
                f"business_model:{normalized['business_model']}",
            )
        for rule in self._registry["conditional_roles"]:
            if rule.get("market") and rule["market"] not in normalized["markets"]:
                continue
            if rule.get("platform") and rule["platform"] not in normalized["platforms"]:
                continue
            self._promote(
                statuses,
                reasons,
                rule["role_ref"],
                rule["recommendation_status"],
                rule["reason_code"],
            )
        self._apply_role_list(
            statuses,
            reasons,
            risk["required_control_role_refs"],
            "required_now",
            f"risk_class:{normalized['risk_class']}",
        )
        self._apply_role_list(
            statuses,
            reasons,
            risk["on_demand_control_role_refs"],
            "on_demand",
            f"risk_class:{normalized['risk_class']}",
        )

        priority = {
            role_ref: index + 1
            for index, role_ref in enumerate(objective["priority_role_refs"])
        }
        roster = [
            self._role_projection(
                role_ref,
                self._catalog[role_ref],
                statuses[role_ref],
                reasons[role_ref],
                priority.get(role_ref),
            )
            for role_ref in sorted(self._catalog)
        ]
        gaps = self._role_gaps(normalized)
        capacity = self._capacity_plan(normalized)
        seat_plan = self._seat_plan(statuses)
        next_activation = self._next_activation(objective, statuses)
        result = {
            "contract_id": self.CONTRACT_ID,
            "version": self.VERSION,
            "status": "RECOMMENDATION_ONLY",
            "enterprise_profile": normalized,
            "profile_scope": {
                "enterprise_ref": normalized["enterprise_ref"],
                "scope_ref": (
                    f"enterprise-profile://{normalized['enterprise_ref']}"
                ),
                "grants_authority": False,
            },
            "enterprise_positioning": {
                "archetype_ref": stage["archetype_ref"],
                "current_positioning": stage["positioning"],
                "value_wedge": stage["value_wedge"],
                "business_model_emphasis": business["emphasis"],
                "target_positioning": self._registry["target_positioning"],
                "promotion_gate_status": "BLOCKED_EVIDENCE",
                "required_gates": deepcopy(
                    self._registry["target_promotion_gates"]
                ),
                "automation_ceiling": risk["automation_ceiling"],
                "boundaries": deepcopy(
                    self._registry["positioning_boundaries"]
                ),
            },
            "role_roster": roster,
            "role_summary": {
                "catalog_total": len(roster),
                "required_now": self._count(roster, "required_now"),
                "supporting_ai": self._count(roster, "supporting_ai"),
                "on_demand": self._count(roster, "on_demand"),
                "standby": self._count(roster, "standby"),
                "unsupported_gap": len(gaps),
                "core": sum(item["role_kind"] == "core" for item in roster),
                "ai_specialist": sum(
                    item["role_kind"] == "ai_specialist" for item in roster
                ),
                "independent_control": sum(
                    item["role_kind"] == "independent_control" for item in roster
                ),
            },
            "seat_plan": seat_plan,
            "minimum_human_accountability": [
                {
                    "seat_ref": item["seat_ref"],
                    "binding_status": "UNKNOWN",
                    "appointment_evidence_present": False,
                    "role_template_is_appointment_evidence": False,
                }
                for item in seat_plan
            ],
            "separation_of_duties": deepcopy(
                self._enterprise_program["sod_rules"]
            ),
            "role_gaps": gaps,
            "next_role_activation": next_activation,
            "capacity_plan": capacity,
            "system_actions": {
                "identities_created": False,
                "agents_created": False,
                "humans_appointed": False,
                "appointments_created": False,
                "roles_bound": False,
                "tasks_started": False,
                "budgets_created": False,
                "approvals_created": False,
                "permits_issued": False,
                "production_authority_granted": False,
                "facts_promoted": False,
                "external_write_performed": False,
            },
            "source_hashes": deepcopy(self._source_hashes),
            "source_bundle_sha256": self.source_bundle_sha256,
        }
        result["snapshot_sha256"] = self._hash(result)
        return deepcopy(result)

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EnterprisePositioningError(f"Unable to load {label}: {path}") from exc
        if not isinstance(value, dict):
            raise EnterprisePositioningError(f"{label} must be an object")
        return value

    @staticmethod
    def _hash(value: Any) -> str:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _build_catalog(self) -> tuple[dict[str, dict[str, str]], bool]:
        entries: list[tuple[str, dict[str, str]]] = []
        for item in self._team["organization_model"]["core_roles"]:
            entries.append(
                (
                    item["role_id"],
                    {
                        "title": item["title"],
                        "mission": item["mission"],
                        "role_kind": "core",
                    },
                )
            )
        for item in self._experts["specialist_roles"]:
            entries.append(
                (
                    item["role_id"],
                    {
                        "title": item["title"],
                        "mission": item["mission"],
                        "role_kind": "ai_specialist",
                    },
                )
            )
        for item in self._registry["control_role_templates"]:
            entries.append(
                (
                    item["role_ref"],
                    {
                        "title": item["title"],
                        "mission": item["mission"],
                        "role_kind": "independent_control",
                    },
                )
            )
        catalog = dict(entries)
        return catalog, len(catalog) != len(entries)

    def _validate_registry(self) -> None:
        if (
            self._registry.get("schema_version") != self.SCHEMA_VERSION
            or self._registry.get("contract_id") != self.CONTRACT_ID
            or self._registry.get("version") != self.VERSION
        ):
            raise EnterprisePositioningError("Positioning contract identity drifted")
        if self._catalog_has_duplicates or len(self._catalog) != 35:
            raise EnterprisePositioningError(
                "Enterprise role catalog must contain 35 unique templates"
            )
        if self._registry.get("status_precedence") != [
            "standby",
            "on_demand",
            "supporting_ai",
            "required_now",
        ]:
            raise EnterprisePositioningError("Role status precedence drifted")
        allowed = self._registry["allowed_values"]
        policy_names = {
            "stage": "stage_policies",
            "business_model": "business_model_policies",
            "headcount_band": "headcount_policies",
            "risk_class": "risk_policies",
            "primary_objective": "objective_policies",
        }
        for field, policy_name in policy_names.items():
            if set(allowed[field]) != set(self._registry[policy_name]):
                raise EnterprisePositioningError(f"{field} policy coverage drifted")
        for stage_ref, policy in self._registry["stage_policies"].items():
            self._validate_role_refs(
                policy["required_now_role_refs"], f"stage:{stage_ref}:required"
            )
            self._validate_role_refs(
                policy["supporting_ai_role_refs"], f"stage:{stage_ref}:ai"
            )
            if any(
                self._catalog[role_ref]["role_kind"] != "ai_specialist"
                for role_ref in policy["supporting_ai_role_refs"]
            ):
                raise EnterprisePositioningError(
                    f"Supporting AI policy contains human role: {stage_ref}"
                )
            self._validate_role_refs(
                policy["on_demand_role_refs"], f"stage:{stage_ref}:on_demand"
            )
        for model_ref, policy in self._registry["business_model_policies"].items():
            self._validate_status_map(policy["role_statuses"], f"business:{model_ref}")
            self._validate_role_refs(
                policy["priority_role_refs"], f"business:{model_ref}:priority"
            )
        for risk_ref, policy in self._registry["risk_policies"].items():
            refs = (
                policy["required_control_role_refs"]
                + policy["on_demand_control_role_refs"]
            )
            self._validate_role_refs(refs, f"risk:{risk_ref}")
            if any(
                self._catalog[role_ref]["role_kind"] != "independent_control"
                for role_ref in refs
            ):
                raise EnterprisePositioningError(
                    f"Risk policy contains non-control role: {risk_ref}"
                )
        for objective_ref, policy in self._registry["objective_policies"].items():
            self._validate_role_refs(
                policy["priority_role_refs"], f"objective:{objective_ref}"
            )
            if not set(policy["activation_gate_by_role"]) <= set(
                policy["priority_role_refs"]
            ):
                raise EnterprisePositioningError(
                    f"Objective activation gates drifted: {objective_ref}"
                )
        for rule in self._registry["conditional_roles"]:
            self._validate_role_refs([rule["role_ref"]], "conditional")
            if rule["recommendation_status"] not in self.RECOMMENDATION_STATUSES:
                raise EnterprisePositioningError("Conditional status drifted")
        self._validate_conditional_role_maps()
        self._validate_seats()
        sod = self._enterprise_program.get("sod_rules", [])
        self._validate_sod_rules(sod)
        boundaries = self._registry["positioning_boundaries"]
        forbidden = {
            "is_business_truth_authority",
            "system_may_appoint_humans",
            "system_may_grant_production_authority",
            "role_templates_may_external_write",
            "profile_scope_grants_authority",
        }
        if any(boundaries.get(key) is not False for key in forbidden):
            raise EnterprisePositioningError("Positioning authority boundary drifted")
        self._profile(self._registry["current_profile"])

    def _validate_conditional_role_maps(self) -> None:
        market_map = self._registry.get("supported_market_role_map")
        platform_map = self._registry.get("supported_platform_role_map")
        if not isinstance(market_map, dict) or not isinstance(platform_map, dict):
            raise EnterprisePositioningError("Supported role maps drifted")
        self._validate_role_refs(list(market_map.values()), "supported markets")
        self._validate_role_refs(list(platform_map.values()), "supported platforms")
        observed: dict[tuple[str, str], str] = {}
        for rule in self._registry["conditional_roles"]:
            dimensions = [key for key in ("market", "platform") if rule.get(key)]
            if len(dimensions) != 1:
                raise EnterprisePositioningError("Conditional role dimension drifted")
            dimension = dimensions[0]
            key = (dimension, rule[dimension])
            if key in observed:
                raise EnterprisePositioningError("Conditional role mapping duplicated")
            observed[key] = rule["role_ref"]
        expected = {
            **{("market", key): value for key, value in market_map.items()},
            **{("platform", key): value for key, value in platform_map.items()},
        }
        if observed != expected:
            raise EnterprisePositioningError("Conditional role maps are not bijective")

    def _validate_sod_rules(self, rules: Any) -> None:
        if not isinstance(rules, list) or len(rules) != len(self.SOD_RULES):
            raise EnterprisePositioningError("Six SoD rules are required")
        observed: list[tuple[str, str, str]] = []
        required_fields = {
            "rule_ref",
            "left_function_ref",
            "right_function_ref",
            "same_role_allowed",
            "same_principal_allowed",
            "identity_authority_required",
        }
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != required_fields:
                raise EnterprisePositioningError("SoD rule fields drifted")
            observed.append(
                (
                    rule["rule_ref"],
                    rule["left_function_ref"],
                    rule["right_function_ref"],
                )
            )
            if (
                not self._IDENTIFIER.fullmatch(rule["rule_ref"])
                or not self._IDENTIFIER.fullmatch(rule["left_function_ref"])
                or not self._IDENTIFIER.fullmatch(rule["right_function_ref"])
                or rule["left_function_ref"] == rule["right_function_ref"]
                or rule["same_role_allowed"] is not False
                or rule["same_principal_allowed"] is not False
                or rule["identity_authority_required"] is not True
            ):
                raise EnterprisePositioningError("SoD rules must fail closed")
        if tuple(observed) != self.SOD_RULES:
            raise EnterprisePositioningError("Canonical SoD rules drifted")

    def _validate_seats(self) -> None:
        seats = self._registry["seat_templates"]
        if not 2 <= len(seats) <= 4:
            raise EnterprisePositioningError("Human seat plan must contain 2-4 seats")
        seat_refs = [item["seat_ref"] for item in seats]
        if len(seat_refs) != len(set(seat_refs)):
            raise EnterprisePositioningError("Human seat refs must be unique")
        bundled: list[str] = []
        for seat in seats:
            refs = seat["role_bundle_refs"]
            self._validate_role_refs(refs, f"seat:{seat['seat_ref']}")
            if any(
                self._catalog[role_ref]["role_kind"] == "ai_specialist"
                for role_ref in refs
            ):
                raise EnterprisePositioningError("AI templates cannot fill human seats")
            bundled.extend(refs)
        human_roles = {
            role_ref
            for role_ref, role in self._catalog.items()
            if role["role_kind"] != "ai_specialist"
        }
        if len(bundled) != len(set(bundled)) or set(bundled) != human_roles:
            raise EnterprisePositioningError("Human seat role coverage drifted")

    def _validate_role_refs(self, refs: Any, label: str) -> None:
        if (
            not isinstance(refs, list)
            or len(refs) != len(set(refs))
            or not set(refs) <= set(self._catalog)
        ):
            raise EnterprisePositioningError(f"Role refs drifted: {label}")

    def _validate_status_map(self, status_map: Any, label: str) -> None:
        if not isinstance(status_map, dict) or not set(status_map) <= set(self._catalog):
            raise EnterprisePositioningError(f"Role status map drifted: {label}")
        if not set(status_map.values()) <= self.RECOMMENDATION_STATUSES:
            raise EnterprisePositioningError(f"Role status values drifted: {label}")

    def _profile(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(profile, Mapping) or set(profile) != self.PROFILE_FIELDS:
            raise EnterprisePositioningError("Enterprise profile fields drifted")
        value = dict(profile)
        enterprise_ref = value["enterprise_ref"]
        if (
            not isinstance(enterprise_ref, str)
            or not self._IDENTIFIER.fullmatch(enterprise_ref)
        ):
            raise EnterprisePositioningError("Invalid enterprise_ref")
        allowed = self._registry["allowed_values"]
        for field in (
            "business_model",
            "stage",
            "headcount_band",
            "risk_class",
            "primary_objective",
        ):
            if value[field] not in allowed[field]:
                raise EnterprisePositioningError(
                    f"Unsupported enterprise profile {field}"
                )
        value["markets"] = self._identifiers(
            value["markets"], "markets", upper=True
        )
        value["platforms"] = self._identifiers(
            value["platforms"], "platforms", upper=False
        )
        return value

    def _identifiers(self, raw: Any, label: str, *, upper: bool) -> list[str]:
        if not isinstance(raw, (list, tuple)) or not raw:
            raise EnterprisePositioningError(f"{label} must be a non-empty list")
        values = []
        for item in raw:
            if not isinstance(item, str):
                raise EnterprisePositioningError(f"Invalid {label}")
            normalized = item.upper() if upper else item.lower()
            if not self._IDENTIFIER.fullmatch(normalized):
                raise EnterprisePositioningError(f"Invalid {label}")
            values.append(normalized)
        if len(values) != len(set(values)):
            raise EnterprisePositioningError(f"{label} must be unique")
        return sorted(values)

    def _apply_role_list(
        self,
        statuses: dict[str, str],
        reasons: dict[str, list[str]],
        role_refs: list[str],
        status: str,
        reason: str,
    ) -> None:
        for role_ref in role_refs:
            self._promote(statuses, reasons, role_ref, status, reason)

    def _promote(
        self,
        statuses: dict[str, str],
        reasons: dict[str, list[str]],
        role_ref: str,
        status: str,
        reason: str,
    ) -> None:
        precedence = self._registry["status_precedence"]
        if precedence.index(status) > precedence.index(statuses[role_ref]):
            statuses[role_ref] = status
        if reason not in reasons[role_ref]:
            reasons[role_ref].append(reason)

    @staticmethod
    def _template_ref(role_ref: str) -> str:
        return f"role-template://kjds/enterprise-positioning/v2/{role_ref}"

    def _role_projection(
        self,
        role_ref: str,
        role: Mapping[str, str],
        status: str,
        reason_codes: list[str],
        objective_priority: int | None,
    ) -> dict[str, Any]:
        return {
            "role_ref": role_ref,
            "role_template_ref": self._template_ref(role_ref),
            "title": role["title"],
            "mission": role["mission"],
            "role_kind": role["role_kind"],
            "recommendation_status": status,
            "reason_codes": sorted(reason_codes) or ["not_required_by_current_profile"],
            "objective_priority": objective_priority,
            "runtime_mode": "capability_template_only",
            "human_binding_status": "UNKNOWN",
            "human_seat_eligible": role["role_kind"] != "ai_specialist",
            "production_authority_granted": False,
            "external_write_allowed": False,
            "formal_fact_promotion_allowed": False,
        }

    @staticmethod
    def _count(roster: list[dict[str, Any]], status: str) -> int:
        return sum(item["recommendation_status"] == status for item in roster)

    def _seat_plan(self, statuses: Mapping[str, str]) -> list[dict[str, Any]]:
        seats = []
        for template in self._registry["seat_templates"]:
            active_refs = [
                role_ref
                for role_ref in template["role_bundle_refs"]
                if statuses[role_ref] == "required_now"
            ]
            seats.append(
                {
                    "seat_ref": template["seat_ref"],
                    "title": template["title"],
                    "mission": template["mission"],
                    "binding_status": "UNKNOWN",
                    "role_bundle_refs": active_refs,
                    "ai_templates_excluded": True,
                    "appointment_evidence_present": False,
                    "sod_conflict_refs": [],
                }
            )
        return seats

    def _capacity_plan(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        policy = self._registry["headcount_policies"][profile["headcount_band"]]
        return {
            "headcount_band": profile["headcount_band"],
            "max_human_seats": policy["max_human_seats"],
            "planned_human_seats": len(self._registry["seat_templates"]),
            "max_parallel_workstreams": policy["max_parallel_workstreams"],
            "max_active_work_per_human": policy["max_active_work_per_human"],
            "role_bundle_mode": policy["role_bundle_mode"],
            "ai_templates_count_as_humans": False,
        }

    def _next_activation(
        self, objective: Mapping[str, Any], statuses: Mapping[str, str]
    ) -> dict[str, Any]:
        for role_ref in objective["priority_role_refs"]:
            if statuses[role_ref] != "required_now":
                return {
                    "role_ref": role_ref,
                    "role_template_ref": self._template_ref(role_ref),
                    "current_status": statuses[role_ref],
                    "target_status": "required_now",
                    "reason_code": "primary_objective_next_capability",
                    "required_gate": objective["activation_gate_by_role"].get(
                        role_ref, "human_business_owner_activation_decision"
                    ),
                }
        return {
            "role_ref": None,
            "role_template_ref": None,
            "current_status": None,
            "target_status": "required_now",
            "reason_code": "objective_capabilities_already_required",
            "required_gate": "none",
        }

    def _role_gaps(self, profile: Mapping[str, Any]) -> list[dict[str, str]]:
        gaps = []
        market_map = self._registry["supported_market_role_map"]
        platform_map = self._registry["supported_platform_role_map"]
        for market in profile["markets"]:
            if market not in market_map:
                gaps.append(
                    {
                        "gap_ref": f"country_general_manager:{market}",
                        "recommendation_status": "unsupported_gap",
                        "reason_code": "market_specific_role_contract_missing",
                        "authority_status": "UNKNOWN",
                    }
                )
        for platform in profile["platforms"]:
            if platform not in platform_map:
                gaps.append(
                    {
                        "gap_ref": f"channel_operations_lead:{platform}",
                        "recommendation_status": "unsupported_gap",
                        "reason_code": "platform_specific_role_contract_missing",
                        "authority_status": "UNKNOWN",
                    }
                )
        return gaps
