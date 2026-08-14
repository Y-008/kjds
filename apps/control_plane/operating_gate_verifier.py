from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class _Gate:
    id: str
    label: str
    stage_ids: tuple[str, ...]
    support_keys: tuple[str, ...]
    owner: str
    workspace: str
    fallback_action: str


class OperatingStageVerifier:
    """Verify scoped M0→M4 progress without owning business state or I/O."""

    CONTRACT_ID = "kjds-operating-stage-verifier-v1"
    COMMERCE_OS_CONTRACT = "commerce-operating-system/1.0.0"
    STAGE_STATUSES = frozenset(
        {"completed", "ready_for_internal_action", "blocked", "no_data"}
    )
    SUPPORT_KEYS = frozenset(
        {
            "scope_grants",
            "native_imports",
            "native_products",
            "native_facts",
            "content_assets",
            "profit_scenarios",
            "listing_drafts",
            "native_pilots",
            "limited_execution_receipts",
            "orders",
            "finance_entries",
            "reconciliation_runs",
        }
    )
    GATES = (
        _Gate(
            id="m0",
            label="M0 Governance and real candidate",
            stage_ids=("observe", "identity"),
            support_keys=("scope_grants", "native_products"),
            owner="identity-and-product",
            workspace="/goal-todo",
            fallback_action=(
                "establish an owner-approved current entity/store grant and "
                "one real native candidate"
            ),
        ),
        _Gate(
            id="m1",
            label="M1 Intelligence and formal Fact",
            stage_ids=("qualify", "item_draft"),
            support_keys=("native_imports", "native_facts"),
            owner="intelligence-and-finance",
            workspace="/formal-facts",
            fallback_action=(
                "ingest and independently review real scoped source artifacts"
            ),
        ),
        _Gate(
            id="m2",
            label="M2 Content, profit and listing",
            stage_ids=("content", "listing_approval"),
            support_keys=(
                "content_assets",
                "profit_scenarios",
                "listing_drafts",
            ),
            owner="content-commerce-and-finance",
            workspace="/commerce-graph",
            fallback_action=(
                "complete real Passports, offers, actual costs, CM3 and "
                "independent content/listing review"
            ),
        ),
        _Gate(
            id="m3",
            label="M3 Governed Pilot, order and settlement",
            stage_ids=(
                "publish",
                "order",
                "procurement_review",
                "fulfill",
                "settle",
            ),
            support_keys=(
                "native_pilots",
                "limited_execution_receipts",
                "orders",
            ),
            owner="governed-execution-and-operations",
            workspace="/commerce-graph",
            fallback_action=(
                "obtain independent Approval and one-time Permit, then observe "
                "a real governed Pilot through settlement"
            ),
        ),
        _Gate(
            id="m4",
            label="M4 Actual cash and learning",
            stage_ids=("reconcile", "learn"),
            support_keys=("finance_entries", "reconciliation_runs"),
            owner="finance-and-learning",
            workspace="/commerce-graph",
            fallback_action=(
                "reconcile platform settlement, bank cash and actual-cash CM3"
            ),
        ),
    )
    REQUIRED_STAGE_IDS = frozenset(
        stage_id for gate in GATES for stage_id in gate.stage_ids
    )

    def evaluate(
        self,
        *,
        workspace: dict[str, Any],
        support_counts: dict[str, int],
        observation_bucket: str,
    ) -> dict[str, Any]:
        errors, stages, counts = self._validate(
            workspace=workspace,
            support_counts=support_counts,
            observation_bucket=observation_bucket,
        )
        if errors:
            return self._failed(
                errors=errors,
                workspace=workspace,
                support_counts=support_counts,
                observation_bucket=observation_bucket,
            )

        semantic_source = {
            "contract_version": workspace["contract_version"],
            "workspace_status": workspace["status"],
            "scope": {
                "tenant_ref": workspace["scope"].get("tenant_ref"),
                "entity_ref": workspace["scope"].get("entity_ref"),
                "store_ref": workspace["scope"].get("store_ref"),
            },
            "source_snapshots": workspace["source_snapshots"],
            "formal_facts": {
                "status": workspace["formal_facts"].get("status"),
                "formal_fact_count": workspace["formal_facts"].get(
                    "formal_fact_count"
                ),
                "snapshot_sha256": workspace["formal_facts"].get(
                    "snapshot_sha256"
                ),
            },
            "completion_claim": {
                "real_profit_loop_complete": workspace[
                    "completion_claim"
                ].get("real_profit_loop_complete")
            },
            "control_envelope": workspace["control_envelope"],
            "observation_bucket": observation_bucket,
        }
        results: dict[str, dict[str, Any]] = {}
        upstream_passed = True
        for gate in self.GATES:
            selected = [stages[stage_id] for stage_id in gate.stage_ids]
            blockers = self._blockers(
                gate=gate,
                selected=selected,
                counts=counts,
                workspace=workspace,
                upstream_passed=upstream_passed,
            )
            if not blockers:
                state = "passed"
            elif gate.id == "m0" and self._is_empty_m0(
                selected=selected,
                counts=counts,
                workspace=workspace,
            ):
                state = "no_data"
            else:
                state = "blocked"
            next_action = self._next_action(
                gate=gate,
                selected=selected,
                blockers=blockers,
            )
            gate_input = {
                **semantic_source,
                "gate_id": gate.id,
                "source_stages": selected,
                "support_counts": {
                    key: counts[key] for key in gate.support_keys
                },
                "upstream_state": (
                    None
                    if gate.id == "m0"
                    else results[self.GATES[len(results) - 1].id]["state"]
                ),
            }
            results[gate.id] = {
                "state": state,
                "summary": self._summary(
                    gate=gate,
                    state=state,
                    selected=selected,
                    counts=counts,
                    blockers=blockers,
                ),
                "input_sha256": _sha(gate_input),
                "artifact_ref": (
                    f"commerce-os:{workspace['snapshot_sha256']}#{gate.id}"
                ),
                "owner": gate.owner,
                "workspace": gate.workspace,
                "next_action": next_action,
                "source_stage_ids": list(gate.stage_ids),
                "blockers": blockers,
            }
            upstream_passed = upstream_passed and state == "passed"

        overall_state = (
            "passed"
            if all(item["state"] == "passed" for item in results.values())
            else "blocked"
        )
        output = {
            "contract_id": self.CONTRACT_ID,
            "status": overall_state,
            "observation_bucket": observation_bucket,
            "workspace_snapshot_sha256": workspace["snapshot_sha256"],
            "support_counts": counts,
            "gates": results,
            "external_write_allowed": False,
            "model_self_certification_allowed": False,
        }
        output["result_sha256"] = _sha(output)
        return output

    def _validate(
        self,
        *,
        workspace: Any,
        support_counts: Any,
        observation_bucket: Any,
    ) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, int]]:
        errors: list[str] = []
        if not isinstance(workspace, dict):
            return ["workspace_not_object"], {}, {}
        if not isinstance(observation_bucket, str) or not observation_bucket.strip():
            errors.append("observation_bucket_invalid")
        if workspace.get("contract_version") != self.COMMERCE_OS_CONTRACT:
            errors.append("commerce_os_contract_mismatch")
        for key in (
            "scope",
            "source_snapshots",
            "formal_facts",
            "control_envelope",
            "completion_claim",
        ):
            if not isinstance(workspace.get(key), dict):
                errors.append(f"workspace_field_invalid:{key}")
        if not isinstance(workspace.get("snapshot_sha256"), str) or len(
            workspace.get("snapshot_sha256", "")
        ) != 64:
            errors.append("workspace_snapshot_sha256_invalid")
        envelope = workspace.get("control_envelope", {})
        if envelope.get("read_only_projection") is not True:
            errors.append("read_only_projection_not_proven")
        if envelope.get("external_writes") is not False:
            errors.append("external_writes_not_closed")
        for key in (
            "ozon_write",
            "supplier_message",
            "supplier_order",
            "purchase",
            "payment",
            "inventory_write",
            "price_write",
            "advertising_write",
            "agent_self_approval",
            "agent_permit_issuance",
        ):
            if envelope.get(key) is not False:
                errors.append(f"control_not_closed:{key}")

        counts: dict[str, int] = {}
        if not isinstance(support_counts, dict):
            errors.append("support_counts_not_object")
        else:
            missing = self.SUPPORT_KEYS - set(support_counts)
            if missing:
                errors.extend(
                    f"support_count_missing:{key}" for key in sorted(missing)
                )
            for key in sorted(self.SUPPORT_KEYS & set(support_counts)):
                value = support_counts[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    errors.append(f"support_count_invalid:{key}")
                else:
                    counts[key] = value

        stages: dict[str, dict[str, Any]] = {}
        raw_stages = workspace.get("stages")
        if not isinstance(raw_stages, list):
            errors.append("stages_not_list")
        else:
            for item in raw_stages:
                if not isinstance(item, dict):
                    errors.append("stage_not_object")
                    continue
                stage_id = item.get("id")
                if not isinstance(stage_id, str) or not stage_id:
                    errors.append("stage_id_invalid")
                    continue
                if stage_id in stages:
                    errors.append(f"stage_duplicate:{stage_id}")
                    continue
                stages[stage_id] = item
                if item.get("status") not in self.STAGE_STATUSES:
                    errors.append(f"stage_status_invalid:{stage_id}")
                count = item.get("qualified_record_count")
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or count < 0
                ):
                    errors.append(f"stage_count_invalid:{stage_id}")
                if item.get("external_write_allowed") is not False:
                    errors.append(f"stage_external_write_not_closed:{stage_id}")
                if item.get("client_recalculation_allowed") is not False:
                    errors.append(f"stage_client_recalculation_not_closed:{stage_id}")
                for key in ("owner", "next_action", "workspace_href", "why"):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        errors.append(f"stage_field_invalid:{stage_id}:{key}")
            missing_stages = self.REQUIRED_STAGE_IDS - set(stages)
            extra_stages = set(stages) - self.REQUIRED_STAGE_IDS
            errors.extend(
                f"stage_missing:{stage_id}" for stage_id in sorted(missing_stages)
            )
            errors.extend(
                f"stage_unrecognized:{stage_id}" for stage_id in sorted(extra_stages)
            )
        return errors, stages, counts

    @staticmethod
    def _blockers(
        *,
        gate: _Gate,
        selected: list[dict[str, Any]],
        counts: dict[str, int],
        workspace: dict[str, Any],
        upstream_passed: bool,
    ) -> list[str]:
        blockers: list[str] = []
        if not upstream_passed:
            blockers.append("upstream_gate_not_passed")
        if gate.id == "m0":
            if not workspace["scope"].get("entity_ref"):
                blockers.append("current_entity_scope_missing")
            if not workspace["source_snapshots"].get("truth_governance"):
                blockers.append("truth_governance_snapshot_missing")
        for stage in selected:
            if stage["status"] != "completed":
                blockers.append(
                    f"stage_not_completed:{stage['id']}:{stage['status']}"
                )
            if stage["qualified_record_count"] <= 0:
                blockers.append(f"stage_has_no_qualified_record:{stage['id']}")
        for key in gate.support_keys:
            if counts[key] <= 0:
                blockers.append(f"support_count_zero:{key}")
        if gate.id == "m1":
            formal_facts = workspace["formal_facts"]
            if int(formal_facts.get("formal_fact_count") or 0) <= 0:
                blockers.append("formal_fact_count_zero")
            if not formal_facts.get("snapshot_sha256"):
                blockers.append("formal_fact_snapshot_missing")
        if gate.id == "m4" and workspace["completion_claim"].get(
            "real_profit_loop_complete"
        ) is not True:
            blockers.append("real_profit_loop_not_complete")
        return blockers

    @staticmethod
    def _is_empty_m0(
        *,
        selected: list[dict[str, Any]],
        counts: dict[str, int],
        workspace: dict[str, Any],
    ) -> bool:
        return (
            not workspace["scope"].get("entity_ref")
            and all(item["qualified_record_count"] == 0 for item in selected)
            and counts["scope_grants"] == 0
            and counts["native_products"] == 0
        )

    @staticmethod
    def _next_action(
        *,
        gate: _Gate,
        selected: list[dict[str, Any]],
        blockers: list[str],
    ) -> str:
        if not blockers:
            return "continue observing this Gate with the registered verifier"
        for stage in selected:
            if stage["status"] != "completed":
                return stage["next_action"]
        return gate.fallback_action

    @staticmethod
    def _summary(
        *,
        gate: _Gate,
        state: str,
        selected: list[dict[str, Any]],
        counts: dict[str, int],
        blockers: list[str],
    ) -> str:
        stages = ", ".join(
            f"{item['id']}={item['status']}:{item['qualified_record_count']}"
            for item in selected
        )
        support = ", ".join(
            f"{key}={counts[key]}" for key in gate.support_keys
        )
        blocker_text = "none" if not blockers else ",".join(blockers)
        return (
            f"{gate.id.upper()} {state}: Commerce OS [{stages}]; "
            f"database [{support}]; blockers [{blocker_text}]"
        )

    def _failed(
        self,
        *,
        errors: list[str],
        workspace: Any,
        support_counts: Any,
        observation_bucket: Any,
    ) -> dict[str, Any]:
        source_hash = _sha(
            {
                "workspace": workspace,
                "support_counts": support_counts,
                "observation_bucket": observation_bucket,
            }
        )
        gates = {
            gate.id: {
                "state": "failed",
                "summary": (
                    f"{gate.id.upper()} failed closed: verifier input contract "
                    f"errors [{','.join(errors)}]"
                ),
                "input_sha256": _sha([source_hash, gate.id, errors]),
                "artifact_ref": f"verifier-input:{source_hash}#{gate.id}",
                "owner": gate.owner,
                "workspace": gate.workspace,
                "next_action": "repair the scoped verifier input contract and re-observe",
                "source_stage_ids": list(gate.stage_ids),
                "blockers": list(errors),
            }
            for gate in self.GATES
        }
        output = {
            "contract_id": self.CONTRACT_ID,
            "status": "failed",
            "observation_bucket": observation_bucket,
            "workspace_snapshot_sha256": (
                workspace.get("snapshot_sha256")
                if isinstance(workspace, dict)
                else None
            ),
            "support_counts": (
                support_counts if isinstance(support_counts, dict) else {}
            ),
            "gates": gates,
            "external_write_allowed": False,
            "model_self_certification_allowed": False,
        }
        output["result_sha256"] = _sha(output)
        return output
