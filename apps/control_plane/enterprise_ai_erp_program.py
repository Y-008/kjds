from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


class EnterpriseAiErpProgramError(ValueError):
    """Raised when the static Enterprise AI ERP contract is unsafe or drifts."""


class EnterpriseAiErpProgram:
    """Compile the Enterprise AI ERP operating design into a read-only projection.

    The registry describes roles, squads, work contracts and control policies. It
    is deliberately not an authority for people, work in progress, maturity,
    gates, money, customers or external actions. Construction reads and validates
    the four source registries once; ``project`` only returns a defensive copy.
    """

    CONTRACT_ID = "kjds-enterprise-ai-erp-program-v1"
    SCHEMA_VERSION = "kjds-enterprise-ai-erp-program-v1"
    SUPPORTED_VERSION = "1.0.0"

    TEAM_CONTRACT_ID = "kjds-team-control-tower-v1"
    TEAM_SCHEMA_VERSION = "kjds-team-control-tower-v1"
    TEAM_VERSION = "1.2.0"

    EXPERT_CONTRACT_ID = "kjds-global-portfolio-orchestrator-v1"
    EXPERT_SCHEMA_VERSION = "kjds-global-expert-team-v1"
    EXPERT_VERSION = "1.0"

    ATLAS_CONTRACT_ID = "kjds-cross-border-capability-atlas-v1"
    ATLAS_VERSION = "0.59.0"

    CONTROL_ROLES = (
        "human_business_owner",
        "independent_verifier",
        "independent_approver",
        "risk_authority",
        "executor",
    )
    DOMAIN_ROLES = (
        "enterprise_ontology_mdm_lead",
        "process_intelligence_automation_lead",
        "global_cross_border_market_product_operations_lead",
        "enterprise_finance_accounting_tax_treasury_lead",
        "supply_chain_quality_manufacturing_lead",
        "hcm_organization_change_lead",
        "crm_commercial_customer_value_lead",
        "globalization_country_pack_lead",
        "agent_platform_model_risk_lead",
        "data_product_privacy_sovereignty_lead",
        "integration_partner_ecosystem_lead",
        "customer_implementation_adoption_lead",
        "value_realization_ai_finops_lead",
        "quality_engineering_release_assurance_lead",
    )
    SQUAD_IDS = tuple(f"S{number}" for number in range(1, 9))
    WORK_ITEM_IDS = tuple(f"EAERP-{number:02d}" for number in range(1, 7))
    MATURITY_LEVELS = ("M0", "M1", "M2", "M3", "M4")
    LANE_IDS = tuple("ABCDEFGHIJKLM")
    SQUAD_FUNCTIONS = (
        "domain_product_owner",
        "domain_architect_engineer",
        "data_integration_engineer",
        "ux_business_analyst",
        "independent_qa_verifier",
    )
    SOD_RULES = (
        "writer_vs_verifier",
        "agent_skill_owner_vs_promotion_approver",
        "finance_entry_preparer_vs_payment_approver",
        "regulatory_researcher_vs_legal_signer",
        "migration_author_vs_release_approver",
        "external_action_approver_vs_executor",
    )
    SINGLE_INTEGRATOR_DOMAINS = (
        "registry",
        "runtime",
        "router",
        "openapi",
        "alembic_migration",
        "release",
    )

    ROLE_FIELDS = frozenset(
        {
            "role_ref",
            "title",
            "unique_accountability",
            "alternate_role_ref",
            "outcomes",
            "tool_allowlist",
            "data_allowlist",
            "default_sla_hours",
            "reviewer_role_ref",
            "budget_authority_status",
            "maximum_loss_authority_status",
            "conflict_attestation_required",
            "evidence_requirements",
            "handoff_conditions",
            "stop_conditions",
            "kpis",
        }
    )
    SQUAD_FIELDS = frozenset(
        {
            "squad_ref",
            "title",
            "owner_role_ref",
            "reviewer_role_ref",
            "primary_lane_id",
            "supporting_lane_ids",
            "required_functions",
            "capability_atlas_ids",
            "capability_gap_refs",
            "work_item_refs",
            "first_acceptance_contract",
        }
    )
    WBS_FIELDS = frozenset(
        {
            "work_item_ref",
            "title",
            "goal",
            "exact_scope",
            "jtbd",
            "owner_role_ref",
            "alternate_role_ref",
            "input_authorities",
            "data_classification",
            "dependency_refs",
            "write_set",
            "deliverables",
            "reviewer_role_ref",
            "acceptance_conditions",
            "kpis",
            "budget_policy",
            "maximum_loss_policy",
            "stop_conditions",
            "rollback",
            "sla_hours",
            "observability",
            "evidence_requirements",
            "invalidation_conditions",
            "handoff_conditions",
            "squad_refs",
            "lane_affinity_ids",
        }
    )
    FORBIDDEN_STATIC_TRUTH_FIELDS = frozenset(
        {
            "primary_human_ref",
            "alternate_human_ref",
            "verified_binding_refs",
            "binding_status",
            "current_task",
            "task_status",
            "execution_state",
            "active_writer_ref",
            "observed_active_writers",
            "achieved_maturity",
            "maturity_status",
            "verified_evidence_refs",
            "evidence_refs",
            "gate_passed",
            "owner_thread_id",
            "current_phase",
            "current_level",
            "current_kpi_value",
            "current_gate_result",
            "current_release_result",
            "first_acceptance_result",
            "acceptance_result",
            "achieved_result",
            "pass_result",
            "gate_result",
            "continuation_token",
            "decision_basis_sha256",
        }
    )
    FORBIDDEN_STATIC_TRUTH_KEY_TOKENS = frozenset(
        {"result", "results", "achieved", "pass", "passed"}
    )
    _IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]+")

    def __init__(
        self,
        registry_path: str | Path | None = None,
        organization_registry_path: str | Path | None = None,
        expert_registry_path: str | Path | None = None,
        capability_atlas_path: str | Path | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        configured = registry_path or os.getenv("KJDS_ENTERPRISE_AI_ERP_PROGRAM_PATH")
        self.registry_path = (
            Path(configured)
            if configured
            else root
            / "docs"
            / "project"
            / "registries"
            / "enterprise_ai_erp_program.json"
        )
        self.organization_registry_path = (
            Path(organization_registry_path)
            if organization_registry_path
            else root
            / "docs"
            / "project"
            / "registries"
            / "team_control_tower_registry.json"
        )
        self.expert_registry_path = (
            Path(expert_registry_path)
            if expert_registry_path
            else root
            / "docs"
            / "project"
            / "registries"
            / "global_expert_team_registry.json"
        )
        self.capability_atlas_path = (
            Path(capability_atlas_path)
            if capability_atlas_path
            else root
            / "docs"
            / "project"
            / "registries"
            / "cross_border_capability_atlas.json"
        )

        self._registry = self._read_json(self.registry_path, "program registry")
        self._organization = self._read_json(
            self.organization_registry_path, "team control registry"
        )
        self._experts = self._read_json(
            self.expert_registry_path, "global expert registry"
        )
        self._atlas = self._read_json(
            self.capability_atlas_path, "capability atlas"
        )

        source_context = self._validate_source_contracts()
        self._validate_program_contract(source_context)

        self._source_hashes = {
            "capability_atlas": self._canonical_hash(self._atlas),
            "enterprise_ai_erp_program": self._canonical_hash(self._registry),
            "global_expert_team": self._canonical_hash(self._experts),
            "team_control_tower": self._canonical_hash(self._organization),
        }
        self.registry_sha256 = self._source_hashes["enterprise_ai_erp_program"]
        self.source_bundle_sha256 = self._canonical_hash(self._source_hashes)
        self._projection = self._compile_projection()

    def project(self) -> dict[str, Any]:
        """Return the deterministic static contract projection."""

        return deepcopy(self._projection)

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EnterpriseAiErpProgramError(
                f"Unable to load {label}: {path}"
            ) from exc
        if not isinstance(value, dict):
            raise EnterpriseAiErpProgramError(f"{label} must be an object")
        return value

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def _identifier(cls, value: Any, label: str) -> str:
        if not isinstance(value, str) or not cls._IDENTIFIER.fullmatch(value):
            raise EnterpriseAiErpProgramError(f"Invalid {label}")
        return value

    @staticmethod
    def _text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EnterpriseAiErpProgramError(f"{label} must be non-empty text")
        return value

    @classmethod
    def _unique_identifiers(
        cls, value: Any, label: str, *, allow_empty: bool = False
    ) -> list[str]:
        if not isinstance(value, list) or (not value and not allow_empty):
            raise EnterpriseAiErpProgramError(f"{label} must be a list")
        items = [cls._identifier(item, label) for item in value]
        if len(items) != len(set(items)):
            raise EnterpriseAiErpProgramError(f"{label} must be unique")
        return items

    @classmethod
    def _unique_texts(
        cls, value: Any, label: str, *, allow_empty: bool = False
    ) -> list[str]:
        if not isinstance(value, list) or (not value and not allow_empty):
            raise EnterpriseAiErpProgramError(f"{label} must be a list")
        items = [cls._text(item, label) for item in value]
        if len(items) != len(set(items)):
            raise EnterpriseAiErpProgramError(f"{label} must be unique")
        return items

    def _validate_source_contracts(self) -> dict[str, set[str]]:
        organization = self._organization
        if (
            organization.get("schema_version") != self.TEAM_SCHEMA_VERSION
            or organization.get("contract_id") != self.TEAM_CONTRACT_ID
            or organization.get("version") != self.TEAM_VERSION
            or organization.get("status") != "active_contract"
        ):
            raise EnterpriseAiErpProgramError(
                "Team control registry schema or version drift"
            )
        model = organization.get("organization_model")
        if not isinstance(model, dict):
            raise EnterpriseAiErpProgramError("Team control organization model is required")
        core_roles = model.get("core_roles")
        if not isinstance(core_roles, list) or len(core_roles) != 18:
            raise EnterpriseAiErpProgramError("Exactly eighteen core roles are required")
        core_ids = {
            self._identifier(item.get("role_id"), "core role")
            for item in core_roles
            if isinstance(item, dict)
        }
        if len(core_ids) != 18:
            raise EnterpriseAiErpProgramError("Core role identifiers must be unique")

        experts = self._experts
        if (
            experts.get("schema_version") != self.EXPERT_SCHEMA_VERSION
            or experts.get("contract_id") != self.EXPERT_CONTRACT_ID
            or experts.get("version") != self.EXPERT_VERSION
            or experts.get("status") != "active_contract"
        ):
            raise EnterpriseAiErpProgramError(
                "Global expert registry schema or version drift"
            )
        specialist_roles = experts.get("specialist_roles")
        if not isinstance(specialist_roles, list) or len(specialist_roles) != 12:
            raise EnterpriseAiErpProgramError(
                "Exactly twelve AI specialist roles are required"
            )
        specialist_ids = {
            self._identifier(item.get("role_id"), "AI specialist role")
            for item in specialist_roles
            if isinstance(item, dict)
        }
        if len(specialist_ids) != 12:
            raise EnterpriseAiErpProgramError(
                "AI specialist role identifiers must be unique"
            )
        team_specialists = self._unique_identifiers(
            model.get("ai_specialist_role_refs"), "team AI specialist reference"
        )
        if set(team_specialists) != specialist_ids:
            raise EnterpriseAiErpProgramError(
                "Team and global expert specialist references drift"
            )

        team_controls = self._unique_identifiers(
            model.get("control_role_refs"), "team control role reference"
        )
        expert_controls_raw = experts.get("control_roles")
        if not isinstance(expert_controls_raw, list):
            raise EnterpriseAiErpProgramError("Global expert control roles are required")
        expert_controls = [
            self._identifier(item.get("role_id"), "expert control role")
            for item in expert_controls_raw
            if isinstance(item, dict)
        ]
        if (
            tuple(team_controls) != self.CONTROL_ROLES
            or tuple(expert_controls) != self.CONTROL_ROLES
        ):
            raise EnterpriseAiErpProgramError("Five control role contract drift")

        atlas = self._atlas
        if (
            atlas.get("contract_id") != self.ATLAS_CONTRACT_ID
            or atlas.get("registry_version") != self.ATLAS_VERSION
            or atlas.get("status") != "active"
        ):
            raise EnterpriseAiErpProgramError(
                "Capability atlas contract or version drift"
            )
        domains = atlas.get("domains")
        if not isinstance(domains, list) or not domains:
            raise EnterpriseAiErpProgramError("Capability atlas domains are required")
        capability_ids: set[str] = set()
        for domain in domains:
            if not isinstance(domain, dict) or not isinstance(
                domain.get("capabilities"), list
            ):
                raise EnterpriseAiErpProgramError("Capability atlas domain drift")
            for capability in domain["capabilities"]:
                if not isinstance(capability, dict):
                    raise EnterpriseAiErpProgramError("Capability leaf must be an object")
                capability_id = self._identifier(
                    capability.get("id"), "capability reference"
                )
                if capability_id in capability_ids:
                    raise EnterpriseAiErpProgramError(
                        "Capability identifiers must be unique"
                    )
                capability_ids.add(capability_id)

        return {
            "core_role_ids": core_ids,
            "specialist_role_ids": specialist_ids,
            "control_role_ids": set(self.CONTROL_ROLES),
            "capability_ids": capability_ids,
        }

    def _validate_program_contract(self, context: dict[str, set[str]]) -> None:
        registry = self._registry
        if (
            registry.get("schema_version") != self.SCHEMA_VERSION
            or registry.get("contract_id") != self.CONTRACT_ID
            or registry.get("version") != self.SUPPORTED_VERSION
            or registry.get("status") != "active_contract"
        ):
            raise EnterpriseAiErpProgramError(
                "Enterprise AI ERP program schema or version drift"
            )
        self._reject_static_truth_fields(registry)
        if registry.get("control_role_refs") != list(self.CONTROL_ROLES):
            raise EnterpriseAiErpProgramError("Program control role contract drift")
        self._validate_expert_pool(registry.get("expert_pool_contract"))
        if registry.get("canonical_authorities") != {
            "tasks_and_events": "OperatingTask/Event",
            "lane_and_write_leases": (
                "docs/project/registries/active_workstream_assignments.json"
            ),
            "organization": "docs/project/registries/team_control_tower_registry.json",
            "specialists": "docs/project/registries/global_expert_team_registry.json",
            "capabilities": "docs/project/registries/cross_border_capability_atlas.json",
            "evidence": "Evidence",
            "benchmarks": "StrategicBenchmark",
            "release": "existing_release_and_g1_gates",
        }:
            raise EnterpriseAiErpProgramError("Canonical authority map drift")
        self._validate_source_declarations()

        roles = registry.get("role_contracts")
        if not isinstance(roles, list) or len(roles) != len(self.DOMAIN_ROLES):
            raise EnterpriseAiErpProgramError("Exactly fourteen domain roles are required")
        role_ids = self._item_ids(roles, "role_ref", "domain role")
        if tuple(role_ids) != self.DOMAIN_ROLES:
            raise EnterpriseAiErpProgramError("Fourteen domain role identifiers drift")
        known_roles = (
            set(role_ids)
            | context["core_role_ids"]
            | context["specialist_role_ids"]
            | context["control_role_ids"]
        )
        self._validate_roles(roles, known_roles)

        work_items = registry.get("work_items")
        if not isinstance(work_items, list) or len(work_items) != 6:
            raise EnterpriseAiErpProgramError("Exactly six EAERP work items are required")
        work_item_ids = self._item_ids(
            work_items, "work_item_ref", "EAERP work item"
        )
        if tuple(work_item_ids) != self.WORK_ITEM_IDS:
            raise EnterpriseAiErpProgramError("EAERP-01 through EAERP-06 are required")

        squads = registry.get("squads")
        if not isinstance(squads, list) or len(squads) != 8:
            raise EnterpriseAiErpProgramError("Exactly eight squads are required")
        squad_ids = self._item_ids(squads, "squad_ref", "squad")
        if tuple(squad_ids) != self.SQUAD_IDS:
            raise EnterpriseAiErpProgramError("S1 through S8 are required")

        self._validate_lane_contract(registry.get("lane_contract"))
        self._validate_squads(
            squads,
            known_roles=known_roles,
            work_item_ids=set(work_item_ids),
            capability_ids=context["capability_ids"],
        )
        self._validate_work_items(
            work_items,
            known_roles=known_roles,
            squad_ids=set(squad_ids),
        )
        self._validate_domain_role_coverage(squads, work_items)
        self._validate_squad_work_item_edges(squads, work_items)
        self._topological_order(work_items)
        self._validate_phases(registry.get("phases"))
        self._validate_maturity_model(registry.get("maturity_model"))
        self._validate_sod_rules(registry.get("sod_rules"))
        self._validate_execution_policy(registry.get("execution_policy"))
        self._validate_capability_policy(registry.get("capability_reference_policy"))
        boundary = registry.get("control_boundary")
        required_boundary = {
            "creates_second_task_ledger",
            "creates_second_command_bus",
            "grants_lane_or_repository_lease",
            "grants_external_write",
            "creates_fact",
            "creates_finance_entry",
            "creates_approval",
            "issues_permit",
            "proves_human_binding",
            "proves_active_wip",
            "proves_maturity",
            "proves_gate_pass",
            "proves_top1",
        }
        if (
            not isinstance(boundary, dict)
            or set(boundary) != required_boundary
            or any(value is not False for value in boundary.values())
        ):
            raise EnterpriseAiErpProgramError("Program control boundary must fail closed")

    def _validate_source_declarations(self) -> None:
        expected = {
            "team_control_tower": {
                "contract_id": self.TEAM_CONTRACT_ID,
                "schema_version": self.TEAM_SCHEMA_VERSION,
                "version": self.TEAM_VERSION,
            },
            "global_expert_team": {
                "contract_id": self.EXPERT_CONTRACT_ID,
                "schema_version": self.EXPERT_SCHEMA_VERSION,
                "version": self.EXPERT_VERSION,
            },
            "capability_atlas": {
                "contract_id": self.ATLAS_CONTRACT_ID,
                "registry_version": self.ATLAS_VERSION,
            },
        }
        if self._registry.get("source_contracts") != expected:
            raise EnterpriseAiErpProgramError("Program source contract declarations drift")

    @classmethod
    def _validate_expert_pool(cls, value: Any) -> None:
        if not isinstance(value, dict) or set(value) != {
            "target_minimum",
            "target_maximum",
            "engagement_model",
            "categories",
            "registry_proves_engagement",
        }:
            raise EnterpriseAiErpProgramError("Expert pool contract fields drift")
        if (
            value["target_minimum"] != 30
            or value["target_maximum"] != 60
            or value["engagement_model"] != "task_bounded_professional_pool"
            or value["registry_proves_engagement"] is not False
        ):
            raise EnterpriseAiErpProgramError("Expert pool 30 to 60 boundary drift")
        categories = cls._unique_identifiers(
            value["categories"], "expert pool category"
        )
        if len(categories) != 9:
            raise EnterpriseAiErpProgramError("Nine expert pool categories are required")

    @classmethod
    def _reject_static_truth_fields(cls, value: Any, path: str = "registry") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                key_tokens = set(key.lower().split("_"))
                is_static_denial = key.startswith("proves_") and nested is False
                if (
                    key in cls.FORBIDDEN_STATIC_TRUTH_FIELDS
                    or key_tokens & cls.FORBIDDEN_STATIC_TRUTH_KEY_TOKENS
                ) and not is_static_denial:
                    raise EnterpriseAiErpProgramError(
                        f"Static registry cannot contain dynamic truth field: {path}.{key}"
                    )
                cls._reject_static_truth_fields(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                cls._reject_static_truth_fields(nested, f"{path}[{index}]")

    @classmethod
    def _item_ids(cls, items: list[Any], key: str, label: str) -> list[str]:
        result: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                raise EnterpriseAiErpProgramError(f"{label} must be an object")
            result.append(cls._identifier(item.get(key), label))
        if len(result) != len(set(result)):
            raise EnterpriseAiErpProgramError(f"{label} identifiers must be unique")
        return result

    def _validate_roles(self, roles: list[dict[str, Any]], known_roles: set[str]) -> None:
        for role in roles:
            if set(role) != self.ROLE_FIELDS:
                raise EnterpriseAiErpProgramError("Domain role contract fields drift")
            role_ref = self._identifier(role["role_ref"], "domain role")
            self._text(role["title"], f"{role_ref} title")
            self._text(role["unique_accountability"], f"{role_ref} accountability")
            alternate = self._identifier(role["alternate_role_ref"], "alternate role")
            reviewer = self._identifier(role["reviewer_role_ref"], "reviewer role")
            if alternate not in known_roles or alternate == role_ref:
                raise EnterpriseAiErpProgramError(f"Invalid alternate for {role_ref}")
            if reviewer not in known_roles or reviewer == role_ref:
                raise EnterpriseAiErpProgramError(f"Invalid reviewer for {role_ref}")
            if len({role_ref, alternate, reviewer}) != 3:
                raise EnterpriseAiErpProgramError(
                    f"Primary, alternate and reviewer must differ for {role_ref}"
                )
            outcomes = role["outcomes"]
            if not isinstance(outcomes, dict) or set(outcomes) != {
                "day_30",
                "day_60",
                "day_90",
            }:
                raise EnterpriseAiErpProgramError(f"{role_ref} outcomes drift")
            for day, values in outcomes.items():
                self._unique_identifiers(values, f"{role_ref} {day} outcome")
            for field in (
                "tool_allowlist",
                "data_allowlist",
                "evidence_requirements",
                "handoff_conditions",
                "stop_conditions",
                "kpis",
            ):
                self._unique_identifiers(role[field], f"{role_ref} {field}")
            sla = role["default_sla_hours"]
            if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:
                raise EnterpriseAiErpProgramError(f"{role_ref} SLA must be positive")
            if (
                role["budget_authority_status"] != "UNKNOWN"
                or role["maximum_loss_authority_status"] != "UNKNOWN"
                or role["conflict_attestation_required"] is not True
            ):
                raise EnterpriseAiErpProgramError(
                    f"{role_ref} authority defaults must fail closed"
                )

    def _validate_lane_contract(self, value: Any) -> None:
        expected = {
            "mapping_kind": "affinity_only",
            "mapping_grants_execution_lease": False,
            "valid_lane_ids": list(self.LANE_IDS),
        }
        if value != expected:
            raise EnterpriseAiErpProgramError("Lane affinity contract drift")

    def _validate_squads(
        self,
        squads: list[dict[str, Any]],
        *,
        known_roles: set[str],
        work_item_ids: set[str],
        capability_ids: set[str],
    ) -> None:
        for squad in squads:
            if set(squad) != self.SQUAD_FIELDS:
                raise EnterpriseAiErpProgramError("Squad contract fields drift")
            squad_ref = self._identifier(squad["squad_ref"], "squad")
            self._text(squad["title"], f"{squad_ref} title")
            owner = self._identifier(squad["owner_role_ref"], "squad owner")
            reviewer = self._identifier(squad["reviewer_role_ref"], "squad reviewer")
            if owner not in known_roles or reviewer not in known_roles or owner == reviewer:
                raise EnterpriseAiErpProgramError(f"{squad_ref} role reference drift")
            primary_lane = self._identifier(squad["primary_lane_id"], "primary lane")
            supporting = self._unique_identifiers(
                squad["supporting_lane_ids"], f"{squad_ref} supporting lane"
            )
            if (
                primary_lane not in self.LANE_IDS
                or any(item not in self.LANE_IDS for item in supporting)
                or primary_lane in supporting
            ):
                raise EnterpriseAiErpProgramError(f"{squad_ref} lane reference drift")
            functions = self._unique_identifiers(
                squad["required_functions"], f"{squad_ref} function"
            )
            if tuple(functions) != self.SQUAD_FUNCTIONS:
                raise EnterpriseAiErpProgramError(
                    f"{squad_ref} requires the five canonical functions"
                )
            capabilities = self._unique_identifiers(
                squad["capability_atlas_ids"], f"{squad_ref} capability"
            )
            if not set(capabilities) <= capability_ids:
                raise EnterpriseAiErpProgramError(
                    f"{squad_ref} references an unknown capability"
                )
            self._unique_identifiers(
                squad["capability_gap_refs"], f"{squad_ref} capability gap"
            )
            work_refs = self._unique_identifiers(
                squad["work_item_refs"], f"{squad_ref} work item"
            )
            if not set(work_refs) <= work_item_ids:
                raise EnterpriseAiErpProgramError(
                    f"{squad_ref} references an unknown work item"
                )
            acceptance_contract = self._text(
                squad["first_acceptance_contract"],
                f"{squad_ref} acceptance contract",
            )
            if not acceptance_contract.startswith("验收要求：") or any(
                completed_phrase in acceptance_contract
                for completed_phrase in (
                    "已完成",
                    "已通过",
                    "已取得",
                    "已经完成",
                    "已经通过",
                )
            ):
                raise EnterpriseAiErpProgramError(
                    f"{squad_ref} acceptance contract must be a future requirement"
                )

    def _validate_work_items(
        self,
        work_items: list[dict[str, Any]],
        *,
        known_roles: set[str],
        squad_ids: set[str],
    ) -> None:
        expected_fields = self._registry.get("wbs_contract", {}).get("required_fields")
        if not isinstance(expected_fields, list) or set(expected_fields) != self.WBS_FIELDS:
            raise EnterpriseAiErpProgramError("WBS required-field contract drift")
        item_ids = {item["work_item_ref"] for item in work_items}
        for item in work_items:
            if set(item) != self.WBS_FIELDS:
                raise EnterpriseAiErpProgramError("EAERP work item fields drift")
            item_ref = self._identifier(item["work_item_ref"], "work item")
            for field in ("title", "goal", "exact_scope", "jtbd"):
                self._text(item[field], f"{item_ref} {field}")
            owner = self._identifier(item["owner_role_ref"], "work item owner")
            alternate = self._identifier(item["alternate_role_ref"], "work item alternate")
            reviewer = self._identifier(item["reviewer_role_ref"], "work item reviewer")
            if (
                owner not in known_roles
                or alternate not in known_roles
                or reviewer not in known_roles
                or len({owner, alternate, reviewer}) < 3
            ):
                raise EnterpriseAiErpProgramError(f"{item_ref} role separation drift")
            dependencies = self._unique_identifiers(
                item["dependency_refs"], f"{item_ref} dependency", allow_empty=True
            )
            if item_ref in dependencies or not set(dependencies) <= item_ids:
                raise EnterpriseAiErpProgramError(f"{item_ref} dependency drift")
            squads = self._unique_identifiers(item["squad_refs"], f"{item_ref} squad")
            lanes = self._unique_identifiers(
                item["lane_affinity_ids"], f"{item_ref} lane"
            )
            if not set(squads) <= squad_ids or not set(lanes) <= set(self.LANE_IDS):
                raise EnterpriseAiErpProgramError(f"{item_ref} squad or lane drift")
            for field in (
                "input_authorities",
                "data_classification",
                "write_set",
                "deliverables",
                "acceptance_conditions",
                "kpis",
                "stop_conditions",
                "rollback",
                "observability",
                "evidence_requirements",
                "invalidation_conditions",
                "handoff_conditions",
            ):
                self._unique_identifiers(item[field], f"{item_ref} {field}")
            self._text(item["budget_policy"], f"{item_ref} budget policy")
            self._text(item["maximum_loss_policy"], f"{item_ref} maximum loss")
            sla = item["sla_hours"]
            if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:
                raise EnterpriseAiErpProgramError(f"{item_ref} SLA must be positive")

    def _validate_domain_role_coverage(
        self,
        squads: list[dict[str, Any]],
        work_items: list[dict[str, Any]],
    ) -> None:
        responsibility_refs = {
            role_ref
            for squad in squads
            for role_ref in (squad["owner_role_ref"], squad["reviewer_role_ref"])
        }
        responsibility_refs.update(
            role_ref
            for item in work_items
            for role_ref in (
                item["owner_role_ref"],
                item["alternate_role_ref"],
                item["reviewer_role_ref"],
            )
        )
        missing = set(self.DOMAIN_ROLES) - responsibility_refs
        if missing:
            raise EnterpriseAiErpProgramError(
                "Domain roles require a squad or WBS responsibility mapping: "
                + ", ".join(sorted(missing))
            )

    @staticmethod
    def _validate_squad_work_item_edges(
        squads: list[dict[str, Any]],
        work_items: list[dict[str, Any]],
    ) -> None:
        squad_edges = {
            (squad["squad_ref"], work_item_ref)
            for squad in squads
            for work_item_ref in squad["work_item_refs"]
        }
        work_item_edges = {
            (squad_ref, item["work_item_ref"])
            for item in work_items
            for squad_ref in item["squad_refs"]
        }
        if squad_edges != work_item_edges:
            raise EnterpriseAiErpProgramError(
                "Squad and WBS work item edges must be bidirectional"
            )

    def _topological_order(self, work_items: list[dict[str, Any]]) -> tuple[str, ...]:
        item_ids = {item["work_item_ref"] for item in work_items}
        incoming = {item_ref: 0 for item_ref in item_ids}
        outgoing = {item_ref: set() for item_ref in item_ids}
        for item in work_items:
            current = item["work_item_ref"]
            for dependency in item["dependency_refs"]:
                if dependency not in item_ids or dependency == current:
                    raise EnterpriseAiErpProgramError("Work item dependency drift")
                outgoing[dependency].add(current)
                incoming[current] += 1
        ready = sorted(item for item, count in incoming.items() if count == 0)
        result: list[str] = []
        while ready:
            wave = ready
            ready = []
            for current in wave:
                result.append(current)
                for child in sorted(outgoing[current]):
                    incoming[child] -= 1
                    if incoming[child] == 0:
                        ready.append(child)
            ready.sort()
        if len(result) != len(item_ids):
            raise EnterpriseAiErpProgramError("EAERP work item DAG contains a cycle")
        return tuple(result)

    def _parallel_waves(self, work_items: list[dict[str, Any]]) -> list[list[str]]:
        item_ids = {item["work_item_ref"] for item in work_items}
        incoming = {item_ref: 0 for item_ref in item_ids}
        outgoing = {item_ref: set() for item_ref in item_ids}
        for item in work_items:
            current = item["work_item_ref"]
            for dependency in item["dependency_refs"]:
                outgoing[dependency].add(current)
                incoming[current] += 1
        ready = sorted(item for item, count in incoming.items() if count == 0)
        waves: list[list[str]] = []
        visited = 0
        while ready:
            wave = ready
            waves.append(wave)
            visited += len(wave)
            ready = []
            for current in wave:
                for child in sorted(outgoing[current]):
                    incoming[child] -= 1
                    if incoming[child] == 0:
                        ready.append(child)
            ready.sort()
        if visited != len(item_ids):
            raise EnterpriseAiErpProgramError("EAERP work item DAG contains a cycle")
        return waves

    def _validate_phases(self, phases: Any) -> None:
        expected = (
            ("day_0_30_map_and_contract", 0, 30, "M1"),
            ("day_31_60_foundation_read_only_workspace", 31, 60, "M2"),
            ("day_61_90_real_commerce_loop", 61, 90, "M3"),
            ("day_91_180_enterprise_domain_pilots", 91, 180, "M3"),
            ("day_181_365_scale_and_metric_leadership", 181, 365, "M4"),
        )
        if not isinstance(phases, list) or len(phases) != len(expected):
            raise EnterpriseAiErpProgramError("Five delivery phases are required")
        observed: list[tuple[Any, ...]] = []
        for phase in phases:
            if not isinstance(phase, dict) or set(phase) != {
                "phase_ref",
                "day_from",
                "day_to",
                "target_maturity",
                "acceptance_contract",
            }:
                raise EnterpriseAiErpProgramError("Delivery phase contract drift")
            self._unique_identifiers(
                phase["acceptance_contract"], "phase acceptance contract"
            )
            observed.append(
                (
                    phase["phase_ref"],
                    phase["day_from"],
                    phase["day_to"],
                    phase["target_maturity"],
                )
            )
        if tuple(observed) != expected:
            raise EnterpriseAiErpProgramError("Delivery phase boundaries drift")

    def _validate_maturity_model(self, value: Any) -> None:
        if not isinstance(value, dict) or set(value) != {
            "assessment_unit",
            "levels",
            "promotion_policy",
        }:
            raise EnterpriseAiErpProgramError("Maturity model contract drift")
        if value["assessment_unit"] != "capability_market_scope":
            raise EnterpriseAiErpProgramError("Maturity assessment unit drift")
        levels = value["levels"]
        if not isinstance(levels, list) or len(levels) != 5:
            raise EnterpriseAiErpProgramError("M0 through M4 are required")
        observed: list[str] = []
        for level in levels:
            if not isinstance(level, dict) or set(level) != {
                "level",
                "definition",
                "required_evidence_kinds",
            }:
                raise EnterpriseAiErpProgramError("Maturity level fields drift")
            observed.append(self._identifier(level["level"], "maturity level"))
            self._text(level["definition"], "maturity definition")
            self._unique_identifiers(
                level["required_evidence_kinds"], "maturity evidence kind"
            )
        if tuple(observed) != self.MATURITY_LEVELS:
            raise EnterpriseAiErpProgramError("Maturity levels must be ordered M0 to M4")
        expected_policy = {
            "sequential_only": True,
            "independent_verifier_required": True,
            "registry_declaration_can_promote": False,
            "task_or_calendar_can_promote": False,
            "synthetic_fixture_can_prove_m3_or_m4": False,
            "stale_conflicted_or_missing_evidence_fails_closed": True,
        }
        if value["promotion_policy"] != expected_policy:
            raise EnterpriseAiErpProgramError("Maturity promotion policy drift")

    def _validate_sod_rules(self, rules: Any) -> None:
        if not isinstance(rules, list) or len(rules) != 6:
            raise EnterpriseAiErpProgramError("Six SoD rules are required")
        observed: list[str] = []
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {
                "rule_ref",
                "left_function_ref",
                "right_function_ref",
                "same_role_allowed",
                "same_principal_allowed",
                "identity_authority_required",
            }:
                raise EnterpriseAiErpProgramError("SoD rule fields drift")
            observed.append(self._identifier(rule["rule_ref"], "SoD rule"))
            left = self._identifier(rule["left_function_ref"], "left SoD function")
            right = self._identifier(rule["right_function_ref"], "right SoD function")
            if (
                left == right
                or rule["same_role_allowed"] is not False
                or rule["same_principal_allowed"] is not False
                or rule["identity_authority_required"] is not True
            ):
                raise EnterpriseAiErpProgramError("SoD rules must fail closed")
        if tuple(observed) != self.SOD_RULES:
            raise EnterpriseAiErpProgramError("Canonical SoD rule identifiers drift")

    def _validate_execution_policy(self, value: Any) -> None:
        expected = {
            "control_agent_count": 1,
            "max_parallel_specialist_agents": 3,
            "max_active_writers": 3,
            "max_active_tasks_per_specialist": 1,
            "max_active_tasks_per_writer": 1,
            "max_current_tasks_per_lane": 1,
            "max_weekly_company_outcomes": 3,
            "release_trains_per_week": 2,
            "single_integrator_domains": list(self.SINGLE_INTEGRATOR_DOMAINS),
            "runtime_assignment_authority_connected": False,
            "failed_slice_blocks_independent_slices": False,
            "path_or_hash_drift_action": "STOP_ZERO_WRITE",
            "shared_lease_conflict_action": "STOP_ZERO_WRITE",
        }
        if value != expected:
            raise EnterpriseAiErpProgramError("Parallel execution policy drift")

    @staticmethod
    def _validate_capability_policy(value: Any) -> None:
        if value != {
            "capability_atlas_ids_must_exist": True,
            "capability_gap_refs_are_not_capability_ids": True,
            "gap_declaration_proves_implementation": False,
        }:
            raise EnterpriseAiErpProgramError("Capability reference policy drift")

    def _compile_projection(self) -> dict[str, Any]:
        role_contracts = []
        for role in sorted(self._registry["role_contracts"], key=lambda item: item["role_ref"]):
            role_contracts.append(
                {
                    **deepcopy(role),
                    "binding_status": "UNKNOWN",
                    "reason_codes": ["human_binding_authority_not_connected"],
                }
            )
        squads = []
        for squad in sorted(self._registry["squads"], key=lambda item: item["squad_ref"]):
            squads.append(
                {
                    **deepcopy(squad),
                    "status": "UNKNOWN",
                    "reason_codes": ["role_binding_authority_not_connected"],
                }
            )
        work_by_ref = {
            item["work_item_ref"]: item for item in self._registry["work_items"]
        }
        work_program = []
        for work_ref in self._topological_order(self._registry["work_items"]):
            work_program.append(
                {
                    **deepcopy(work_by_ref[work_ref]),
                    "planned_initial_state": "NOT_STARTED",
                    "execution_status": "UNKNOWN",
                    "achieved_maturity": "UNKNOWN",
                    "resolved_task_promotes_maturity": False,
                    "reason_codes": [
                        "operating_task_authority_not_connected",
                        "maturity_evidence_authority_not_connected",
                    ],
                }
            )
        phases = []
        for phase in self._registry["phases"]:
            phases.append(
                {
                    **deepcopy(phase),
                    "planned_initial_state": "NOT_STARTED",
                    "status": "UNKNOWN",
                    "gate_status": "UNKNOWN",
                    "reason_codes": [
                        "kickoff_evidence_authority_not_connected",
                        "gate_authority_not_connected",
                    ],
                }
            )
        maturity_levels = []
        for level in self._registry["maturity_model"]["levels"]:
            maturity_levels.append(
                {
                    **deepcopy(level),
                    "status": "UNKNOWN",
                    "verified_evidence_refs": None,
                    "reason_codes": [
                        "maturity_evidence_authority_not_connected"
                    ],
                }
            )

        basis = {
            "contract_id": self.CONTRACT_ID,
            "contract_version": self.SUPPORTED_VERSION,
            "status": "UNKNOWN",
            "reason_codes": [
                "human_binding_authority_not_connected",
                "runtime_work_authority_not_connected",
                "maturity_evidence_authority_not_connected",
                "gate_authority_not_connected",
            ],
            "contract_integrity": {
                "status": "VERIFIED",
                "registry_sha256": self.registry_sha256,
                "source_bundle_sha256": self.source_bundle_sha256,
            },
            "source_hashes": [
                {"source_ref": source_ref, "sha256": digest}
                for source_ref, digest in sorted(self._source_hashes.items())
            ],
            "counts": {
                "existing_core_roles": 18,
                "ai_specialists": 12,
                "enterprise_domain_roles": 14,
                "squads": 8,
                "day_0_30_work_items": 6,
                "independent_control_roles": 5,
                "expert_pool_capacity_minimum": 30,
                "expert_pool_capacity_maximum": 60,
                "sod_rules": 6,
                "maturity_levels": 5,
            },
            "organization_readiness": {
                "status": "UNKNOWN",
                "verified_role_bindings": None,
                "verified_alternates": None,
                "verified_qualifications": None,
                "verified_expert_pool_members": None,
                "registry_proves_human_appointment": False,
                "reason_codes": [
                    "human_binding_authority_not_connected",
                    "alternate_binding_authority_not_connected",
                    "qualification_authority_not_connected",
                    "expert_pool_authority_not_connected",
                ],
            },
            "expert_pool_contract": deepcopy(self._registry["expert_pool_contract"]),
            "role_contracts": role_contracts,
            "squad_readiness": {
                "status": "UNKNOWN",
                "items": squads,
                "reason_codes": ["role_binding_authority_not_connected"],
            },
            "work_program": work_program,
            "parallel_waves": self._parallel_waves(self._registry["work_items"]),
            "phases": phases,
            "maturity_model": {
                "status": "UNKNOWN",
                "assessment_unit": self._registry["maturity_model"]["assessment_unit"],
                "levels": maturity_levels,
                "promotion_policy": deepcopy(
                    self._registry["maturity_model"]["promotion_policy"]
                ),
                "execution_state_is_maturity_authority": False,
                "registry_requirement_is_completion_evidence": False,
            },
            "role_conflicts": {
                "status": "UNKNOWN",
                "contract_rules_verified": True,
                "rules": deepcopy(self._registry["sod_rules"]),
                "observed_conflicts": None,
                "reason_codes": [
                    "actor_identity_binding_authority_not_connected"
                ],
            },
            "parallel_execution": {
                "status": "UNKNOWN",
                "policy": deepcopy(self._registry["execution_policy"]),
                "observed_active_writers": None,
                "observed_writer_wip": None,
                "observed_lane_current_tasks": None,
                "reason_codes": ["runtime_work_authority_not_connected"],
            },
            "integration_queue": {
                "status": "UNKNOWN",
                "planned_initial_state": "NOT_STARTED",
                "items": [
                    {
                        "work_item_ref": item["work_item_ref"],
                        "title": item["title"],
                        "dependency_refs": deepcopy(item["dependency_refs"]),
                        "squad_refs": deepcopy(item["squad_refs"]),
                        "lane_affinity_ids": deepcopy(item["lane_affinity_ids"]),
                        "execution_status": "UNKNOWN",
                    }
                    for item in work_program
                ],
                "parallel_waves": self._parallel_waves(
                    self._registry["work_items"]
                ),
                "reason_codes": ["operating_task_authority_not_connected"],
            },
            "capacity_risk": {
                "status": "UNKNOWN",
                "limits": {
                    key: deepcopy(self._registry["execution_policy"][key])
                    for key in (
                        "control_agent_count",
                        "max_parallel_specialist_agents",
                        "max_active_writers",
                        "max_active_tasks_per_specialist",
                        "max_active_tasks_per_writer",
                        "max_current_tasks_per_lane",
                        "max_weekly_company_outcomes",
                    )
                },
                "observed_active_writers": None,
                "observed_specialist_wip": None,
                "observed_lane_wip": None,
                "observed_weekly_company_outcomes": None,
                "capacity_proven_available": False,
                "reason_codes": ["runtime_capacity_authority_not_connected"],
            },
            "next_release_train": {
                "status": "UNKNOWN",
                "release_trains_per_week": self._registry["execution_policy"][
                    "release_trains_per_week"
                ],
                "scheduled_at": None,
                "eligible_work_item_refs": None,
                "gate_status": "UNKNOWN",
                "registry_proves_schedule": False,
                "reason_codes": ["release_authority_not_connected"],
            },
            "control_envelope": {
                "read_only": True,
                "static_registry_is_runtime_authority": False,
                "registry_proves_human_appointment": False,
                "registry_proves_active_wip": False,
                "registry_proves_maturity": False,
                "resolved_task_promotes_maturity": False,
                "operating_task_created": False,
                "fact_created": False,
                "finance_entry_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        return {**basis, "snapshot_sha256": self._canonical_hash(basis)}
