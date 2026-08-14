from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .evidence_scope import ScopedEvidenceAuthority
from .governance_scope import GovernanceScopeAuthority
from .security import Principal


class TruthGovernanceService:
    """Compose existing truth and execution authorities into one read-only view."""

    CONTRACT_ID = "kjds-truth-governance-v1"
    CONTRIBUTION_AUTHORITIES = {
        "scenario_contribution": "approved_profit_scenario",
        "accrual_contribution": "formal_order_and_cost_evidence",
        "settlement_contribution": "platform_settlement_ledger",
        "cash_contribution": "bank_receipt_and_reconciliation_ledger",
    }

    def __init__(
        self,
        *,
        evidence,
        rules,
        profit_ledger,
        governance,
        execution_plans,
        limited_executor,
        post_execution,
        kill_switch,
        scope_grants=None,
        scoped_evidence=None,
        scoped_governance=None,
    ) -> None:
        self.evidence = evidence
        self.rules = rules
        self.profit_ledger = profit_ledger
        self.governance = governance
        self.execution_plans = execution_plans
        self.limited_executor = limited_executor
        self.post_execution = post_execution
        self.kill_switch = kill_switch
        self.scope_grants = scope_grants
        self.scoped_evidence = scoped_evidence or ScopedEvidenceAuthority(
            evidence=evidence
        )
        self.scoped_governance = (
            scoped_governance
            or GovernanceScopeAuthority(
                governance=governance,
                execution_plans=execution_plans,
                limited_executor=limited_executor,
                post_execution=post_execution,
                scoped_evidence=self.scoped_evidence,
            )
        )

    def snapshot(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: str | None = None,
        evidence_ids: list[str] | None = None,
        sku: str | None = None,
        order_id: str | None = None,
        currency: str = "CNY",
    ) -> dict[str, Any]:
        scope = store_ref.strip()
        if not scope:
            raise ValueError("store_ref is required")
        if not principal.can_access_store(scope):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = self._as_of(as_of)
        cutoff_iso = cutoff.isoformat()
        blockers: list[dict[str, Any]] = []

        scope_projection = self._scope(
            principal=principal,
            store_ref=scope,
            as_of=cutoff,
        )
        blockers.extend(scope_projection["blockers"])

        evidence_projection = self.scoped_evidence.project(
            evidence_ids=evidence_ids or [],
            principal=principal,
            entity_scope=scope_projection["entity_scope"],
            store_ref=scope,
            as_of=cutoff,
        )
        blockers.extend(evidence_projection["blockers"])

        rule_projection = self._rules(as_of=cutoff)
        blockers.extend(rule_projection["blockers"])

        ledger = self.profit_ledger.snapshot(
            store_ref=scope,
            sku=sku,
            order_id=order_id,
            date_to=cutoff.date().isoformat(),
            grain="order",
            currency=currency,
            as_of=cutoff_iso,
            principal=principal,
            entity_scope=scope_projection["entity_scope"],
        )
        contribution_views = self._contribution_views(ledger)
        blockers.extend(contribution_views["blockers"])

        execution = self._execution(
            principal=principal,
            entity_scope=scope_projection["entity_scope"],
            store_ref=scope,
            as_of=cutoff,
        )
        blockers.extend(execution["blockers"])

        blocker_codes = sorted({item["code"] for item in blockers})
        action_readiness = self._action_readiness(
            scope=scope_projection,
            evidence=evidence_projection,
            rules=rule_projection,
            contributions=contribution_views,
            execution=execution,
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "contract_version": "1.0.0",
            "as_of": cutoff_iso,
            "status": (
                "blocked"
                if evidence_projection["status"] == "blocked"
                else "ready_with_constraints"
                if blocker_codes
                else "ready"
            ),
            "scope": scope_projection,
            "authority_hashes": {
                "identity_sha256": self._hash(
                    {
                        "actor_id": principal.actor_id,
                        "roles": sorted(principal.roles),
                        "tenant_ref": principal.tenant_ref,
                        "store_refs": sorted(principal.store_refs),
                    }
                ),
                "scope_grant_sha256": scope_projection["entity_scope"].get(
                    "authority_sha256"
                ),
                "evidence_sha256": evidence_projection["snapshot_sha256"],
                "evidence_scope_sha256": evidence_projection[
                    "binding_authority_sha256"
                ],
                "governance_scope_sha256": execution[
                    "governance_scope_sha256"
                ],
                "rule_registry_sha256": rule_projection["registry_sha256"],
                "rule_compiled_policy_sha256": rule_projection[
                    "compiled_policy_sha256"
                ],
                "profit_ledger_sha256": ledger["snapshot_sha256"],
            },
            "contribution_views": contribution_views["views"],
            "governance": {
                **execution["governance"],
                "scope_authority": execution["governance_scope"],
            },
            "control_envelope": {
                "read_only": True,
                "external_writes": False,
                "ozon_write": False,
                "supplier_write": False,
                "purchase_write": False,
                "payment_write": False,
                "ads_write": False,
                "independent_approval_required": True,
                "one_time_permit_required": True,
                "readback_required": True,
                "kill_switch_required": True,
                "compensation_required": True,
            },
            "source_gaps": sorted(
                set(
                    evidence_projection["source_gaps"]
                    + rule_projection["source_gaps"]
                    + contribution_views["source_gaps"]
                    + execution["source_gaps"]
                )
            ),
            "blockers": sorted(
                blockers,
                key=lambda item: (
                    item["severity"],
                    item["code"],
                    item["owner"],
                ),
            ),
            "blocker_codes": blocker_codes,
            "action_readiness": action_readiness,
            "owner": "operating-governance",
            "sla": "P0 before any external approval; P1 within 1 business day",
            "next": (
                "Resolve the highest-severity blocker in its linked workspace; "
                "read-only research remains available where action_readiness permits."
            ),
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _scope(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        entity_scope = (
            self.scope_grants.current(
                principal=principal,
                store_ref=store_ref,
                as_of=as_of,
            )
            if self.scope_grants is not None
            else {
                "status": "no_data",
                "entity_ref": None,
                "authority": None,
                "authority_sha256": None,
                "reason": "entity_scope_authority_missing",
            }
        )
        blockers: list[dict[str, Any]] = []
        if entity_scope["status"] != "ready":
            reason = entity_scope.get("reason", "entity_scope_authority_missing")
            blockers.append(
                self._blocker(
                    reason,
                    severity="P0",
                    owner="identity-governance",
                    sla="before external approval",
                    next_action=(
                        "Create or repair a formal tenant/entity/store grant "
                        "with immutable grade A Evidence."
                    ),
                    workspace="/team-rbac",
                )
            )
        return {
            "tenant_scope": {
                "status": "ready",
                "tenant_ref": principal.tenant_ref,
                "authority": "authenticated_principal",
            },
            "entity_scope": entity_scope,
            "store_scope": {
                "status": "ready",
                "store_ref": store_ref,
                "authorized_store_refs": sorted(principal.store_refs),
                "authority": "authenticated_principal",
            },
            "actor_scope": {
                "status": "ready",
                "actor_id": principal.actor_id,
                "roles": sorted(principal.roles),
                "authority": "authenticated_principal",
            },
            "blockers": blockers,
        }

    def _rules(self, *, as_of: datetime) -> dict[str, Any]:
        snapshot = self.rules.snapshot(as_of=as_of.date().isoformat())
        gaps = list(snapshot.get("source_evidence_gaps", []))
        missing = list(snapshot.get("missing_domains", []))
        blockers: list[dict[str, Any]] = []
        if snapshot.get("state") == "no_data" or missing:
            blockers.append(
                self._blocker(
                    "effective_rule_domains_missing",
                    severity="P0",
                    owner="policy-owner",
                    sla="before candidate scoring",
                    next_action="Bind an effective Global CN rule version for every required domain.",
                    workspace="/rule-advantage",
                )
            )
        if gaps:
            blockers.append(
                self._blocker(
                    "rule_source_evidence_binding_missing",
                    severity="P0",
                    owner="policy-owner",
                    sla="before pilot approval",
                    next_action="Attach official source content hash, Evidence ID, and observed_at.",
                    workspace="/rule-advantage",
                )
            )
        return {
            "status": snapshot.get("state", "no_data"),
            "registry_sha256": snapshot.get("registry_hash"),
            "compiled_policy_sha256": snapshot.get("compiled_policy_hash"),
            "effective_rule_count": snapshot.get("effective_rule_count", 0),
            "missing_domains": missing,
            "source_evidence_gaps": gaps,
            "source_gaps": [
                *[f"missing_rule_domain:{item}" for item in missing],
                *[f"rule_source_evidence_gap:{item}" for item in gaps],
            ],
            "blockers": blockers,
        }

    def _contribution_views(self, ledger: dict[str, Any]) -> dict[str, Any]:
        rows = ledger.get("rows", [])
        views: dict[str, dict[str, Any]] = {}
        gaps: list[str] = []
        blockers: list[dict[str, Any]] = []
        for field, authority in self.CONTRIBUTION_AUTHORITIES.items():
            available_rows = [row for row in rows if row.get(field) is not None]
            if not rows:
                status = "no_data"
            elif available_rows:
                status = (
                    "ready"
                    if field != "cash_contribution"
                    or all(row.get("status") == "reconciled" for row in available_rows)
                    else "partial"
                )
            else:
                status = "no_data"
            if status != "ready":
                gaps.append(f"{field}:{status}")
            views[field] = {
                "status": status,
                "authority": authority,
                "available_rows": len(available_rows),
                "total_rows": len(rows),
                "currency": ledger.get("currency"),
                "ledger_status": ledger.get("status", "no_data"),
                "actual_profit_claim_allowed": (
                    field == "cash_contribution"
                    and status == "ready"
                    and ledger.get("status") == "reconciled"
                ),
            }
        if not rows:
            blockers.append(
                self._blocker(
                    "profit_ledger_no_data",
                    severity="P1",
                    owner="finance-owner",
                    sla="before scale or settlement reconciliation",
                    next_action="Bind order, cost, settlement, and bank facts by explicit natural keys.",
                    workspace="/profit-ledger",
                )
            )
        return {
            "views": views,
            "source_gaps": gaps,
            "blockers": blockers,
        }

    def _execution(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scoped = self.scoped_governance.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        source_gaps = list(scoped["source_gaps"])
        blockers = list(scoped["blockers"])
        reviews = scoped["reviews"]
        plans = scoped["plans"]
        commands = scoped["commands"]
        windows = scoped["windows"]

        approved_plans = [
            item
            for item in plans
            if item.get("approval_status") == "approved"
            and item.get("source_approval_status") == "approved"
        ]
        live_permits = [
            item
            for item in commands
            if item.get("command_kind") == "execute"
            and item.get("status") in {"queued", "claimed", "write_started"}
            and self._timestamp(item.get("permit_expires_at")) > as_of
        ]
        receipts = [
            item["receipt"]
            for item in commands
            if item.get("command_kind") == "execute" and item.get("receipt")
        ]
        rollbacks = [
            item for item in commands if item.get("command_kind") == "rollback"
        ]
        readback_ready = any(
            receipt.get("outcome") == "succeeded"
            and receipt.get("resulting_state_hash")
            and receipt.get("evidence_ids")
            for receipt in receipts
        )
        kill = self.kill_switch.current(as_of=as_of)

        governance = {
            "approval": {
                "status": "ready" if approved_plans else "no_data",
                "independent": any(
                    item.get("approval_decided_by")
                    and item.get("approval_decided_by") != item.get("created_by")
                    for item in approved_plans
                ),
                "approved_plan_count": len(approved_plans),
                "gate_review_count": len(reviews),
                "authority": "governed_execution_plan",
            },
            "permit": {
                "status": "ready" if live_permits else "no_data",
                "live_one_time_permit_count": len(live_permits),
                "authority": "limited_execution_command",
            },
            "readback": {
                "status": (
                    "ready"
                    if readback_ready
                    else "not_applicable_prelaunch"
                    if not receipts
                    else "blocked"
                ),
                "receipt_count": len(receipts),
                "authority": "immutable_execution_receipt",
            },
            "kill_switch": {
                "status": "engaged" if kill.engaged else "released",
                "engaged": kill.engaged,
                "reason": kill.reason,
                "changed_at": kill.changed_at,
                "authority": "kill_switch_event_log",
            },
            "compensation": {
                "status": (
                    "ready"
                    if rollbacks
                    else "not_applicable_prelaunch"
                    if not receipts
                    else "no_data"
                ),
                "rollback_command_count": len(rollbacks),
                "observation_window_count": len(windows),
                "authority": "limited_executor_and_post_execution",
            },
        }
        if not approved_plans:
            source_gaps.append("independent_approval_not_bound")
        if not live_permits:
            source_gaps.append("one_time_permit_not_bound")
        if receipts and not readback_ready:
            blockers.append(
                self._blocker(
                    "execution_readback_incomplete",
                    severity="P0",
                    owner="execution-owner",
                    sla="immediate after any external write attempt",
                    next_action="Record immutable before/after hashes and platform receipt Evidence.",
                    workspace="/growth-command",
                )
            )
        if receipts and not rollbacks:
            source_gaps.append("compensation_command_not_bound")
        return {
            "governance": governance,
            "governance_scope": {
                "contract_id": scoped["contract_id"],
                "status": scoped["status"],
                "counts": scoped["counts"],
                "excluded_counts": scoped["excluded_counts"],
            },
            "governance_scope_sha256": scoped["authority_sha256"],
            "source_gaps": source_gaps,
            "blockers": blockers,
        }

    @staticmethod
    def _action_readiness(
        *,
        scope: dict[str, Any],
        evidence: dict[str, Any],
        rules: dict[str, Any],
        contributions: dict[str, Any],
        execution: dict[str, Any],
    ) -> dict[str, Any]:
        research_ready = (
            scope["tenant_scope"]["status"] == "ready"
            and scope["store_scope"]["status"] == "ready"
        )
        rule_ready = rules["status"] == "ready"
        evidence_ready = evidence["status"] == "ready"
        ledger_has_data = any(
            item["status"] != "no_data"
            for item in contributions["views"].values()
        )
        approval_ready = execution["governance"]["approval"]["status"] == "ready"
        permit_ready = execution["governance"]["permit"]["status"] == "ready"
        return {
            "observe_research": {
                "status": "ready" if research_ready else "blocked",
                "why": "Authenticated tenant and store scope are sufficient for read-only research.",
                "owner": "market-owner",
                "sla": "now",
                "next_workspace": "/growth-command",
            },
            "candidate_score": {
                "status": (
                    "ready"
                    if evidence_ready and rule_ready
                    else "research_only"
                ),
                "why": "Scoring requires current Evidence and a fully bound compiled rule snapshot.",
                "owner": "category-owner",
                "sla": "before candidate scoring",
                "next_workspace": "/rule-advantage",
            },
            "content_draft": {
                "status": "ready_with_constraints" if research_ready else "blocked",
                "why": "Drafting may continue, but facts, rights, and rule gaps remain visible.",
                "owner": "content-owner",
                "sla": "before content approval",
                "next_workspace": "/media/workbench",
            },
            "pilot_approve": {
                "status": (
                    "ready"
                    if evidence_ready
                    and rule_ready
                    and ledger_has_data
                    and scope["entity_scope"]["status"] == "ready"
                    else "blocked"
                ),
                "why": "Pilot approval additionally requires entity authority and evidence-bound economics.",
                "owner": "independent-approver",
                "sla": "before pilot approval",
                "next_workspace": "/growth-command",
            },
            "external_publish": {
                "status": "blocked",
                "why": (
                    "M0 is read-only; independent approval and a live one-time Permit "
                    f"are observed as approval={approval_ready}, permit={permit_ready}."
                ),
                "owner": "execution-owner",
                "sla": "closed until Pilot Gate",
                "next_workspace": "/growth-command",
            },
            "scale": {
                "status": "blocked",
                "why": "Scale requires actual settlement/cash contribution and later Release/Pilot gates.",
                "owner": "portfolio-owner",
                "sla": "after 24h/72h/7d and settlement readback",
                "next_workspace": "/portfolio-cockpit",
            },
            "settlement_reconcile": {
                "status": (
                    "ready"
                    if contributions["views"]["accrual_contribution"]["status"]
                    != "no_data"
                    else "no_data"
                ),
                "why": "Reconciliation starts from actual accrual and ends with settlement and bank Evidence.",
                "owner": "finance-owner",
                "sla": "within the settlement dispute window",
                "next_workspace": "/profit-ledger",
            },
        }

    @staticmethod
    def _as_of(value: str | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("as_of must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _blocker(
        code: str,
        *,
        severity: str,
        owner: str,
        sla: str,
        next_action: str,
        workspace: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "owner": owner,
            "sla": sla,
            "next": next_action,
            "next_workspace": workspace,
        }

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
