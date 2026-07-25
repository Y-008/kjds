from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .action_policies import ActionAuthorizationService, ActionPolicyRegistry
from .domain import ApprovalStatus, new_id
from .pilot_readiness import OZON_PRODUCT_READ_CONTRACT_VERSION
from .pilot_runs import ReadOnlyPilotRunRow
from .read_only_claims import ReadOnlyClaimRow
from .readiness import ExecutionReadinessContext
from .sql_repository import Base

CAUSAL_POLICY_HANDOFF = "causal_policy_handoff"
APPROVED_LISTING_DRAFT = "approved_listing_draft"
MAX_OZON_RESPONSE_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ExecutionSource:
    kind: str
    id: str
    approval_id: str
    snapshot_hash: str
    handoff_id: str | None = None
    policy_id: str | None = None
    release_id: str | None = None


ADAPTERS = {
    "ozon.listing.draft.v1": {
        "action_id": "listing_draft",
        "platform": "Ozon",
        "policy_action": "recommend_listing_change",
        "operation": "listing.update_draft",
        "required_target_keys": ["listing_id"],
        "allowed_patch_keys": ["title", "description", "attributes", "images"],
        "live_execution_supported": False,
        "rollback_required": True,
        "command_delivery_supported": False,
    },
    "ozon.product.import.v3": {
        "action_id": "listing_publish",
        "platform": "Ozon",
        "policy_action": "recommend_listing_change",
        "operation": "product.import.v3",
        "rollback_operation": "product.import.v3",
        "required_target_keys": ["offer_id"],
        "allowed_patch_keys": ["item"],
        "live_execution_supported": True,
        "rollback_required": True,
        "command_delivery_supported": True,
    },
}


class ExecutionPlanRow(Base):
    __tablename__ = "governed_execution_plans"
    __table_args__ = (
        UniqueConstraint("handoff_id", "idempotency_key", name="uq_execution_plan_key"),
        UniqueConstraint(
            "source_kind", "source_id", "idempotency_key", name="uq_execution_plan_source_key"
        ),
        CheckConstraint(
            "length(source_kind) > 0 "
            "AND length(source_id) > 0 "
            "AND length(source_approval_id) > 0 "
            "AND length(source_snapshot_hash) = 64",
            name="ck_execution_plan_source_fields",
        ),
        CheckConstraint(
            "(source_kind = 'causal_policy_handoff' "
            "AND source_id = handoff_id "
            "AND handoff_id IS NOT NULL "
            "AND policy_id IS NOT NULL "
            "AND release_id IS NOT NULL) "
            "OR (source_kind = 'approved_listing_draft' "
            "AND handoff_id IS NULL "
            "AND policy_id IS NULL "
            "AND release_id IS NULL)",
            name="ck_execution_plan_source_variant",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    source_approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_id: Mapped[str | None] = mapped_column(
        ForeignKey("causal_policy_activation_handoffs.id"), nullable=True
    )
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("causal_policies.id"), nullable=True)
    release_id: Mapped[str | None] = mapped_column(
        ForeignKey("causal_policy_releases.id"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    action_id: Mapped[str] = mapped_column(String, nullable=False)
    action_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    precondition_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intended_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rollback_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    permit_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approval_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionDryRunRow(Base):
    __tablename__ = "governed_execution_dry_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("governed_execution_plans.id"), unique=True, nullable=False
    )
    current_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    performed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionPlanService:
    def __init__(
        self,
        *,
        engine,
        policy_shadow,
        policies,
        evidence,
        commerce,
        action_policies: ActionPolicyRegistry | None = None,
        action_authorization: ActionAuthorizationService | None = None,
        readiness_provider: Callable[[ExecutionReadinessContext], dict[str, Any]] | None = None,
        sourcing=None,
        repository=None,
    ) -> None:
        self.engine = engine
        self.policy_shadow = policy_shadow
        self.policies = policies
        self.evidence = evidence
        self.commerce = commerce
        self.sourcing = sourcing
        self.repository = repository
        if action_authorization is not None:
            self.action_authorization = action_authorization
            self.action_policies = action_authorization.registry
        else:
            self.action_policies = action_policies or ActionPolicyRegistry()
            self.action_authorization = ActionAuthorizationService(self.action_policies)
        self.readiness_provider = readiness_provider

    @staticmethod
    def adapters() -> list[dict[str, Any]]:
        return [{"id": key, **value} for key, value in ADAPTERS.items()]

    def create(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
        adapter_id: str,
        target: dict[str, Any],
        precondition_state_hash: str,
        intended_patch: dict[str, Any],
        rollback_patch: dict[str, Any],
        evidence_ids: list[str],
        created_by: str,
        risk_limits: dict[str, Any] | None = None,
        risk_values: dict[str, Any] | None = None,
        risk_currency: str | None = None,
    ) -> dict[str, Any]:
        handoff = self.policy_shadow.get_handoff(handoff_id)
        if not handoff["activation_eligible"]:
            raise ValueError("Execution planning requires an active approved policy handoff")
        policy = self.policies.get(handoff["policy_id"])
        adapter = self._adapter(adapter_id)
        if adapter["platform"] != policy["applicability"]["platform"]:
            raise ValueError("Execution adapter platform is outside policy applicability")
        if adapter["policy_action"] != policy["action"]["type"]:
            raise ValueError("Execution adapter does not support the policy action")
        source = ExecutionSource(
            kind=CAUSAL_POLICY_HANDOFF,
            id=handoff_id,
            approval_id=handoff["approval_id"],
            snapshot_hash=handoff["policy_snapshot_hash"],
            handoff_id=handoff_id,
            policy_id=policy["id"],
            release_id=handoff["release_id"],
        )
        return self._create_from_source(
            source,
            idempotency_key=idempotency_key,
            adapter_id=adapter_id,
            target=target,
            precondition_state_hash=precondition_state_hash,
            intended_patch=intended_patch,
            rollback_patch=rollback_patch,
            evidence_ids=evidence_ids,
            created_by=created_by,
            risk_limits=risk_limits,
            risk_values=risk_values,
            risk_currency=risk_currency,
        )

    def create_from_approved_listing(
        self,
        draft_id: str,
        *,
        idempotency_key: str,
        precondition_state_hash: str,
        evidence_ids: list[str],
        created_by: str,
        risk_limits: dict[str, Any] | None = None,
        risk_values: dict[str, Any] | None = None,
        risk_currency: str | None = None,
    ) -> dict[str, Any]:
        if self.sourcing is None or self.repository is None:
            raise RuntimeError("Approved Listing execution source is not configured")
        draft = self.sourcing.store.get_listing_draft(draft_id)
        if not draft.approval_id:
            raise ValueError("Listing execution requires a Listing approval")
        source_approval = self.commerce.repo.get_approval(draft.approval_id)
        if (
            source_approval.action != "listing.publish"
            or source_approval.resource_type != "listing_draft"
            or source_approval.resource_id != draft.id
        ):
            raise ValueError("Listing execution source approval does not match the draft")
        if source_approval.status != ApprovalStatus.APPROVED or not source_approval.decided_by:
            raise ValueError("Listing execution requires an approved Listing snapshot")
        if source_approval.decided_by == source_approval.requested_by:
            raise ValueError("Listing execution requires an independent Listing reviewer")
        draft = self.sourcing.verify_listing_approval(
            draft_id=draft.id,
            approval_id=source_approval.id,
            approval_payload=source_approval.payload,
        )
        if draft.target_platform.strip().upper() != "OZON":
            raise ValueError("Approved Listing execution currently supports Ozon only")
        product = self.repository.get_product(draft.product_id)
        if product.channel.strip().upper() != "OZON":
            raise ValueError("Listing product is not bound to the Ozon channel")
        offer_id = self._required(product.sku, "Ozon offer ID")
        target = {"offer_id": offer_id}
        precondition_state_hash = self._state_hash(precondition_state_hash)
        before_state, rollback_item, before_evidence_id = self._approved_listing_before_state(
            evidence_ids,
            offer_id=offer_id,
        )
        if self._hash(before_state) != precondition_state_hash:
            raise ValueError("Approved before-state Evidence does not match the precondition hash")
        intended_item = self._listing_import_item(draft.listing_data, offer_id=offer_id)
        source = ExecutionSource(
            kind=APPROVED_LISTING_DRAFT,
            id=draft.id,
            approval_id=source_approval.id,
            snapshot_hash=self._state_hash(source_approval.payload["listing_snapshot_sha256"]),
        )
        return self._create_from_source(
            source,
            idempotency_key=idempotency_key,
            adapter_id="ozon.product.import.v3",
            target=target,
            precondition_state_hash=precondition_state_hash,
            intended_patch={"item": intended_item},
            rollback_patch={"item": rollback_item},
            evidence_ids=[*evidence_ids, before_evidence_id],
            created_by=created_by,
            risk_limits=risk_limits,
            risk_values=risk_values,
            risk_currency=risk_currency,
            before_state_evidence_id=before_evidence_id,
        )

    def _create_from_source(
        self,
        source: ExecutionSource,
        *,
        idempotency_key: str,
        adapter_id: str,
        target: dict[str, Any],
        precondition_state_hash: str,
        intended_patch: dict[str, Any],
        rollback_patch: dict[str, Any],
        evidence_ids: list[str],
        created_by: str,
        risk_limits: dict[str, Any] | None,
        risk_values: dict[str, Any] | None,
        risk_currency: str | None,
        before_state_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        adapter = self._adapter(adapter_id)
        action_policy = self.action_policies.get(adapter["action_id"])
        if adapter["live_execution_supported"] and action_policy["decision_scope"] != "real_execution":
            raise ValueError("Live execution adapter must use a real-execution action policy")
        idempotency_key = self._required(idempotency_key, "Execution idempotency key")
        created_by = self._required(created_by, "Execution plan creator")
        target = self._target(target, adapter)
        precondition_state_hash = self._state_hash(precondition_state_hash)
        intended_patch = self._patch(intended_patch, adapter, "Intended patch")
        rollback_patch = self._patch(rollback_patch, adapter, "Rollback patch")
        if adapter["operation"] == "product.import.v3":
            if intended_patch["item"].get("offer_id") != target["offer_id"]:
                raise ValueError("Intended Ozon import item must match target offer_id")
            if rollback_patch["item"].get("offer_id") != target["offer_id"]:
                raise ValueError("Rollback Ozon import item must match target offer_id")
        if intended_patch == rollback_patch:
            raise ValueError("Rollback patch must restore a different prior state")
        evidence_ids = self._evidence(evidence_ids)
        readiness_context = self._readiness_context(
            action_id=adapter["action_id"],
            target=target,
            source=source,
            precondition_state_hash=precondition_state_hash,
            evidence_ids=evidence_ids,
            before_state_evidence_id=before_state_evidence_id,
        )
        readiness_snapshot = self.action_readiness_snapshot(readiness_context)
        evidence_ids = self._evidence(
            [*evidence_ids, *self._readiness_evidence_ids(readiness_snapshot)]
        )
        authorization = self.action_authorization.authorize_action(
            action=adapter["action_id"],
            subject_id=self._subject_ref(adapter_id, target),
            actor_id=created_by,
            occurred_at=datetime.now(UTC),
            phase="request",
            limits=risk_limits,
            values=risk_values,
            currency=risk_currency,
            readiness=self._readiness_flags(readiness_snapshot),
            source_kind=source.kind,
        )
        self.action_authorization.require_allowed(authorization)
        risk = authorization["risk"]
        canonical = {
            "source_kind": source.kind,
            "source_id": source.id,
            "source_approval_id": source.approval_id,
            "source_snapshot_hash": source.snapshot_hash,
            "idempotency_key": idempotency_key,
            "adapter_id": adapter_id,
            "action_id": adapter["action_id"],
            "action_policy_version": self.action_policies.policy_version,
            "target": target,
            "precondition_state_hash": precondition_state_hash,
            "intended_patch": intended_patch,
            "rollback_patch": rollback_patch,
            "risk_limits": risk["limits"],
            "risk_values": risk["values"],
            "risk_currency": risk["currency"],
            "permit_ttl_seconds": risk["permit_ttl_seconds"],
            "evidence_ids": evidence_ids,
            "readiness_snapshot": readiness_snapshot,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session:
            exact = session.scalar(
                select(ExecutionPlanRow).where(ExecutionPlanRow.request_hash == request_hash)
            )
            if exact is not None:
                return self.get(exact.id)
            previous = session.scalar(
                select(ExecutionPlanRow).where(
                    ExecutionPlanRow.source_kind == source.kind,
                    ExecutionPlanRow.source_id == source.id,
                    ExecutionPlanRow.idempotency_key == idempotency_key,
                )
            )
            if previous is not None:
                raise ValueError("Execution idempotency key already has immutable content")
        approval = self.commerce.request_approval(
            action="platform_execution.execute_plan",
            resource_type="governed_execution_plan",
            resource_id=request_hash,
            requested_by=created_by,
            payload={
                "source_kind": source.kind,
                "source_id": source.id,
                "source_approval_id": source.approval_id,
                "source_snapshot_hash": source.snapshot_hash,
                "handoff_id": source.handoff_id,
                "policy_id": source.policy_id,
                "release_id": source.release_id,
                "adapter_id": adapter_id,
                "action_id": adapter["action_id"],
                "action_policy_version": self.action_policies.policy_version,
                "risk_tier": action_policy["risk_tier"],
                "operation": adapter["operation"],
                "target": target,
                "precondition_state_hash": precondition_state_hash,
                "intended_patch": intended_patch,
                "rollback_patch": rollback_patch,
                "risk_limits": risk["limits"],
                "risk_values": risk["values"],
                "risk_currency": risk["currency"],
                "permit_ttl_seconds": risk["permit_ttl_seconds"],
                "readiness_snapshot": readiness_snapshot,
                "live_execution_supported": adapter["live_execution_supported"],
            },
        )
        try:
            with Session(self.engine) as session, session.begin():
                row = ExecutionPlanRow(
                    id=new_id("gxp"),
                    request_hash=request_hash,
                    source_kind=source.kind,
                    source_id=source.id,
                    source_approval_id=source.approval_id,
                    source_snapshot_hash=source.snapshot_hash,
                    handoff_id=source.handoff_id,
                    policy_id=source.policy_id,
                    release_id=source.release_id,
                    idempotency_key=idempotency_key,
                    adapter_id=adapter_id,
                    action_id=adapter["action_id"],
                    action_policy_version=self.action_policies.policy_version,
                    target_json=target,
                    precondition_state_hash=precondition_state_hash,
                    intended_patch_json=intended_patch,
                    rollback_patch_json=rollback_patch,
                    risk_limits_json=risk["limits"],
                    risk_values_json=risk["values"],
                    risk_currency=risk["currency"],
                    permit_ttl_seconds=risk["permit_ttl_seconds"],
                    evidence_json=evidence_ids,
                    approval_id=approval.id,
                    created_by=created_by,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                plan_id = row.id
        except IntegrityError:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(ExecutionPlanRow).where(
                        ExecutionPlanRow.source_kind == source.kind,
                        ExecutionPlanRow.source_id == source.id,
                        ExecutionPlanRow.idempotency_key == idempotency_key,
                    )
                )
            if winner is None or winner.request_hash != request_hash:
                raise ValueError("Execution idempotency key already has immutable content") from None
            return self.get(winner.id)
        self._link(evidence_ids, "governed_execution_plan", plan_id, created_by)
        return self.get(plan_id)

    def _approved_listing_before_state(
        self,
        evidence_ids: list[str],
        *,
        offer_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        candidates: list[tuple[ReadOnlyClaimRow, ReadOnlyPilotRunRow]] = []
        with Session(self.engine) as session:
            claims = list(
                session.scalars(
                    select(ReadOnlyClaimRow).where(
                        ReadOnlyClaimRow.evidence_id.in_(evidence_ids),
                        ReadOnlyClaimRow.status == "accepted",
                    )
                )
            )
            for claim in claims:
                run = session.get(ReadOnlyPilotRunRow, claim.run_id)
                if run is not None:
                    candidates.append((claim, run))
        target_hash = hashlib.sha256(offer_id.encode()).hexdigest()
        matching = [
            (claim, run)
            for claim, run in candidates
            if run.operation == "ozon.product.read"
            and run.status == "completed"
            and run.outcome == "succeeded"
            and run.target_hash == target_hash
            and (run.summary_json or {}).get("contract_version")
            == OZON_PRODUCT_READ_CONTRACT_VERSION
            and (run.summary_json or {}).get("state_sha256") == claim.source_state_sha256
        ]
        if len(matching) != 1:
            raise ValueError(
                "Listing execution requires one accepted Ozon product Claim for the server-derived offer"
            )
        claim, run = matching[0]
        raw_ids = self.evidence.target_evidence_ids(
            target_type="read_only_pilot_run",
            target_id=run.id,
            relationship="raw_response",
        )
        if len(raw_ids) != 1:
            raise ValueError("Listing execution requires one raw before-state Evidence record")
        self.evidence.require_current([raw_ids[0]])
        content, record = self.evidence.content(raw_ids[0])
        verification = self.evidence.verify(raw_ids[0])
        if (
            not verification.valid
            or record.source != "ozon-isolated-read-worker"
            or record.source_ref != run.id
            or record.content_type != "application/json"
            or record.grade.value != "A"
            or record.metadata.get("raw_response_stored") is not True
            or record.metadata.get("response_sha256") != run.response_sha256
            or record.sha256 != run.response_sha256
            or record.byte_size != run.response_byte_size
        ):
            raise ValueError("Raw Ozon before-state Evidence failed integrity verification")
        state = self._ozon_state_from_bundle(content, offer_id=offer_id)
        if self._hash(state) != claim.source_state_sha256:
            raise ValueError("Accepted Ozon Claim does not match raw before-state Evidence")
        rollback_item = self._rollback_item_from_state(state, offer_id=offer_id)
        return state, rollback_item, record.id

    @classmethod
    def _ozon_state_from_bundle(cls, content: bytes, *, offer_id: str) -> dict[str, Any]:
        try:
            bundle = json.loads(content)
            if (
                bundle.get("schema_version") != "ozon-response-bundle-v2"
                or bundle.get("contract_version") != OZON_PRODUCT_READ_CONTRACT_VERSION
            ):
                raise ValueError
            responses = bundle["responses"]
            if not isinstance(responses, list) or not 1 <= len(responses) <= 3:
                raise ValueError
            decoded: dict[str, Any] = {}
            for item in responses:
                if not isinstance(item, dict) or item.get("status_code") != 200:
                    raise ValueError
                path = item["path"]
                if not isinstance(path, str) or path in decoded:
                    raise ValueError
                body = base64.b64decode(item["body_base64"], validate=True)
                if len(body) > MAX_OZON_RESPONSE_BODY_BYTES:
                    raise ValueError
                body_sha256 = item["body_sha256"]
                if not isinstance(body_sha256, str) or not hmac.compare_digest(
                    body_sha256, hashlib.sha256(body).hexdigest()
                ):
                    raise ValueError
                decoded[path] = json.loads(body)
            info = decoded["/v3/product/info/list"]
            attribute_paths = {
                "/v4/product/info/attributes",
                "/v3/products/info/attributes",
            }.intersection(decoded)
            if len(attribute_paths) != 1 or len(decoded) != 2:
                raise ValueError
            attributes = decoded[attribute_paths.pop()]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Raw Ozon before-state Evidence has an unsupported contract") from exc
        info_items = info.get("items") if isinstance(info, dict) else None
        result = attributes.get("result") if isinstance(attributes, dict) else None
        attribute_items = result.get("items") if isinstance(result, dict) else result
        if not isinstance(info_items, list) or not isinstance(attribute_items, list):
            raise ValueError("Raw Ozon before-state Evidence is missing product records")
        for items in (info_items, attribute_items):
            if (
                len(items) != 1
                or not isinstance(items[0], dict)
                or str(items[0].get("offer_id", "")).strip() != offer_id
            ):
                raise ValueError("Raw Ozon before-state Evidence does not prove one target offer")
        return {
            "contract_version": OZON_PRODUCT_READ_CONTRACT_VERSION,
            "offer_id": offer_id,
            "info": info,
            "attributes": attributes,
        }

    @staticmethod
    def _rollback_item_from_state(state: dict[str, Any], *, offer_id: str) -> dict[str, Any]:
        result = state["attributes"]["result"]
        attribute_item = result["items"][0] if isinstance(result, dict) else result[0]
        rollback_item = dict(attribute_item)
        rollback_item["offer_id"] = offer_id
        required = {"name", "description", "description_category_id", "attributes", "images"}
        if not required.issubset(rollback_item):
            raise ValueError(
                "Raw Ozon before-state cannot reconstruct a complete rollback import item"
            )
        return rollback_item

    @staticmethod
    def _listing_import_item(listing_data: dict[str, Any], *, offer_id: str) -> dict[str, Any]:
        attributes = listing_data.get("attributes")
        images = listing_data.get("images")
        if not isinstance(attributes, list) or not attributes:
            raise ValueError("Approved Listing attributes must be a complete Ozon attribute list")
        if not isinstance(images, list) or not images:
            raise ValueError("Approved Listing images must be a non-empty list")
        item = {
            "offer_id": offer_id,
            "name": ExecutionPlanService._required(
                str(listing_data.get("title", "")), "Approved Listing title"
            ),
            "description": ExecutionPlanService._required(
                str(listing_data.get("description", "")), "Approved Listing description"
            ),
            "description_category_id": int(listing_data["category_id"]),
            "attributes": attributes,
            "images": images,
        }
        return item

    def dry_run(
        self,
        plan_id: str,
        *,
        current_state_hash: str,
        evidence_ids: list[str],
        performed_by: str,
    ) -> dict[str, Any]:
        plan = self.get(plan_id)
        performed_by = self._required(performed_by, "Dry-run operator")
        current_state_hash = self._state_hash(current_state_hash)
        evidence_ids = self._evidence(evidence_ids)
        checks = [
            {
                "name": (
                    "policy_handoff_active"
                    if plan["source_kind"] == CAUSAL_POLICY_HANDOFF
                    else "approved_listing_source_active"
                ),
                "passed": plan["source_validity_status"] == "active",
            },
            {
                "name": "precondition_snapshot_matches",
                "passed": current_state_hash == plan["precondition_state_hash"],
            },
            {"name": "rollback_contract_present", "passed": bool(plan["rollback_patch"])},
            {"name": "adapter_live_writes_disabled", "passed": True},
        ]
        passed = all(item["passed"] for item in checks)
        canonical = {
            "plan_id": plan_id,
            "current_state_hash": current_state_hash,
            "checks": checks,
            "evidence_ids": evidence_ids,
            "performed_by": performed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.request_hash == request_hash)
            )
            if exact is not None:
                return self._dry_run(exact)
            previous = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.plan_id == plan_id)
            )
            if previous is not None:
                raise ValueError("Execution plan already has an immutable dry-run receipt")
            row = ExecutionDryRunRow(
                id=new_id("gxd"),
                request_hash=request_hash,
                plan_id=plan_id,
                current_state_hash=current_state_hash,
                checks_json=checks,
                passed=passed,
                evidence_json=evidence_ids,
                performed_by=performed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._dry_run(row)
        self._link(evidence_ids, "governed_execution_dry_run", result["id"], performed_by)
        return result

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(session.scalars(select(ExecutionPlanRow.id).order_by(ExecutionPlanRow.created_at)))
        return [self.get(item_id) for item_id in ids]

    def get(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ExecutionPlanRow, plan_id)
            if row is None:
                raise KeyError(f"Governed execution plan not found: {plan_id}")
            result = self._plan(row)
            dry_run = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.plan_id == plan_id)
            )
        source_context = self._source_context(result)
        approval = self.commerce.repo.get_approval(result["approval_id"])
        dry_run_passed = bool(dry_run and dry_run.passed)
        current_readiness_snapshot = self.action_readiness_snapshot(
            self._plan_readiness_context(result)
        )
        authorization = self.action_authorization.authorize_action(
            action=result["action_id"],
            subject_id=self._subject_ref(result["adapter_id"], result["target"]),
            actor_id=result["created_by"],
            occurred_at=datetime.now(UTC),
            phase="permit",
            limits=result["risk_limits"],
            values=result["risk_values"],
            currency=result["risk_currency"],
            policy_version=result["action_policy_version"],
            readiness=self._readiness_flags(current_readiness_snapshot),
            source_kind=result["source_kind"],
            approval_actor_ids=(
                [approval.decided_by]
                if approval.status.value == "approved" and approval.decided_by
                else []
            ),
        )
        authorization_blocking_reasons = list(authorization["blocking_reasons"])
        if source_context["validity_status"] != "active":
            authorization_blocking_reasons.append("EXECUTION_SOURCE_INVALID")
        frozen_readiness_snapshot = (
            approval.payload.get("readiness_snapshot", {})
            if isinstance(approval.payload, dict)
            else {}
        )
        try:
            self.evidence.require_current(result["evidence_ids"])
        except (KeyError, RuntimeError, ValueError):
            authorization_blocking_reasons.append("PLAN_EVIDENCE_INVALID")
        frozen_readiness_evidence_ids = self._readiness_evidence_ids(
            frozen_readiness_snapshot
        )
        if frozen_readiness_evidence_ids:
            try:
                self.evidence.require_current(frozen_readiness_evidence_ids)
            except (KeyError, RuntimeError, ValueError):
                authorization_blocking_reasons.append("READINESS_EVIDENCE_INVALID")
        authorization_blocking_reasons = sorted(set(authorization_blocking_reasons))
        ready_for_executor = (
            source_context["validity_status"] == "active"
            and approval.status.value == "approved"
            and dry_run_passed
            and not authorization_blocking_reasons
        )
        decision_packet = self._decision_packet(
            result=result,
            source_context=source_context,
            approval=approval,
            dry_run=self._dry_run(dry_run) if dry_run else None,
            frozen_readiness_snapshot=frozen_readiness_snapshot,
        )
        return {
            **result,
            "source_approval_status": source_context["approval_status"],
            "source_approval_decided_by": source_context["approval_decided_by"],
            "source_validity_status": source_context["validity_status"],
            "approval_status": approval.status.value,
            "approval_decided_by": approval.decided_by,
            "handoff_validity_status": source_context.get("handoff_validity_status"),
            "dry_run": self._dry_run(dry_run) if dry_run else None,
            "ready_for_executor": ready_for_executor,
            "authorization_blocking_reasons": authorization_blocking_reasons,
            "current_readiness_snapshot": current_readiness_snapshot,
            "decision_packet": decision_packet,
            "execution_eligible": False,
            "adapter": {"id": result["adapter_id"], **self._adapter(result["adapter_id"])},
            "action_policy": authorization["action_policy"],
            "live_execution_supported": self._adapter(result["adapter_id"])[
                "live_execution_supported"
            ],
            "automatic_execution": False,
        }

    def _source_context(self, result: dict[str, Any]) -> dict[str, Any]:
        if result["source_kind"] == CAUSAL_POLICY_HANDOFF:
            handoff = self.policy_shadow.get_handoff(result["source_id"])
            snapshot_matches = handoff["policy_snapshot_hash"] == result["source_snapshot_hash"]
            source_matches = handoff["approval_id"] == result["source_approval_id"]
            validity_status = (
                handoff["validity_status"]
                if snapshot_matches and source_matches
                else "source_snapshot_changed"
            )
            return {
                "approval_status": handoff["approval_status"],
                "approval_decided_by": handoff["approval_decided_by"],
                "validity_status": validity_status,
                "handoff_validity_status": validity_status,
            }
        if self.sourcing is None:
            return {
                "approval_status": "unknown",
                "approval_decided_by": None,
                "validity_status": "source_resolver_unavailable",
            }
        approval = self.commerce.repo.get_approval(result["source_approval_id"])
        try:
            self.sourcing.verify_listing_approval(
                draft_id=result["source_id"],
                approval_id=approval.id,
                approval_payload=approval.payload,
            )
        except (KeyError, ValueError):
            validity_status = "source_snapshot_changed"
        else:
            validity_status = (
                "active"
                if approval.status == ApprovalStatus.APPROVED
                and approval.decided_by
                and approval.decided_by != approval.requested_by
                and approval.payload.get("listing_snapshot_sha256")
                == result["source_snapshot_hash"]
                else "source_approval_invalid"
            )
        return {
            "approval_status": approval.status.value,
            "approval_decided_by": approval.decided_by,
            "validity_status": validity_status,
        }

    def action_readiness(
        self,
        plan: dict[str, Any],
        *,
        executor_identity_ref: str | None = None,
    ) -> dict[str, bool]:
        return self._readiness_flags(
            self.action_readiness_snapshot(
                self._plan_readiness_context(
                    plan,
                    executor_identity_ref=executor_identity_ref,
                )
            )
        )

    def action_readiness_snapshot(
        self, context: ExecutionReadinessContext
    ) -> dict[str, dict[str, Any]]:
        if self.readiness_provider is None:
            return {}
        readiness = self.readiness_provider(context)
        if not isinstance(readiness, dict):
            raise ValueError("Action readiness provider must return a mapping")
        result: dict[str, dict[str, Any]] = {}
        for key, value in readiness.items():
            requirement_id = self._required(str(key), "Readiness requirement")
            if isinstance(value, bool):
                snapshot = {
                    "ready": value,
                    "evidence_ids": [],
                    "blocking_reasons": [],
                }
            elif isinstance(value, dict):
                snapshot = {
                    "ready": value.get("ready") is True,
                    "evidence_ids": self._string_list(
                        value.get("evidence_ids", []),
                        "Readiness evidence IDs",
                    ),
                    "blocking_reasons": self._string_list(
                        value.get("blocking_reasons", []),
                        "Readiness blocking reasons",
                    ),
                }
            else:
                raise ValueError("Action readiness values must be booleans or mappings")
            result[requirement_id] = {
                **snapshot,
                "snapshot_hash": self._hash(snapshot),
            }
        return dict(sorted(result.items()))

    @staticmethod
    def _readiness_context(
        *,
        action_id: str,
        target: dict[str, Any],
        source: ExecutionSource,
        precondition_state_hash: str,
        evidence_ids: list[str],
        before_state_evidence_id: str | None,
    ) -> ExecutionReadinessContext:
        return ExecutionReadinessContext(
            action_id=action_id,
            target=target,
            source_kind=source.kind,
            source_id=source.id,
            source_approval_id=source.approval_id,
            source_snapshot_hash=source.snapshot_hash,
            precondition_state_hash=precondition_state_hash,
            evidence_ids=tuple(evidence_ids),
            before_state_verified=before_state_evidence_id is not None,
            before_state_evidence_id=before_state_evidence_id,
        )

    def _plan_readiness_context(
        self,
        plan: dict[str, Any],
        *,
        executor_identity_ref: str | None = None,
    ) -> ExecutionReadinessContext:
        before_state_verified = False
        before_state_evidence_id = None
        if plan.get("source_kind") == APPROVED_LISTING_DRAFT:
            try:
                before_state, _, before_state_evidence_id = self._approved_listing_before_state(
                    plan.get("evidence_ids", []),
                    offer_id=plan["target"]["offer_id"],
                )
                before_state_verified = hmac.compare_digest(
                    self._hash(before_state),
                    plan["precondition_state_hash"],
                )
            except (KeyError, RuntimeError, TypeError, ValueError):
                before_state_verified = False
                before_state_evidence_id = None
        return ExecutionReadinessContext(
            action_id=plan["action_id"],
            target=plan["target"],
            source_kind=plan.get("source_kind"),
            source_id=plan.get("source_id"),
            source_approval_id=plan.get("source_approval_id"),
            source_snapshot_hash=plan.get("source_snapshot_hash"),
            precondition_state_hash=plan.get("precondition_state_hash"),
            evidence_ids=tuple(plan.get("evidence_ids", [])),
            before_state_verified=before_state_verified,
            before_state_evidence_id=before_state_evidence_id,
            executor_identity_ref=executor_identity_ref,
        )

    @staticmethod
    def _readiness_flags(snapshot: dict[str, dict[str, Any]]) -> dict[str, bool]:
        return {
            requirement_id: requirement.get("ready") is True
            for requirement_id, requirement in snapshot.items()
        }

    @staticmethod
    def _readiness_evidence_ids(snapshot: dict[str, dict[str, Any]]) -> list[str]:
        return sorted(
            {
                evidence_id
                for requirement in snapshot.values()
                if isinstance(requirement, dict)
                for evidence_id in requirement.get("evidence_ids", [])
                if isinstance(evidence_id, str) and evidence_id.strip()
            }
        )

    @classmethod
    def _string_list(cls, value: Any, name: str) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        if len(value) > 100:
            raise ValueError(f"{name} exceeds the 100 item limit")
        normalized: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{name} entries must be strings")
            normalized.add(cls._required(item, name))
        return sorted(normalized)

    @staticmethod
    def _adapter(adapter_id: str) -> dict[str, Any]:
        try:
            return ADAPTERS[adapter_id]
        except KeyError as exc:
            raise ValueError(f"Unsupported governed execution adapter: {adapter_id}") from exc

    @classmethod
    def _target(cls, value: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("Execution target must be structured")
        missing = set(adapter["required_target_keys"]) - set(value)
        if missing:
            raise ValueError(f"Execution target is missing: {', '.join(sorted(missing))}")
        if set(value) - set(adapter["required_target_keys"]):
            raise ValueError("Execution target contains unsupported identifiers")
        return {key: cls._required(str(item), f"Target {key}") for key, item in value.items()}

    @staticmethod
    def _patch(value: dict[str, Any], adapter: dict[str, Any], name: str) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{name} must be a non-empty structured object")
        unsupported = set(value) - set(adapter["allowed_patch_keys"])
        if unsupported:
            raise ValueError(f"{name} contains unsupported fields: {', '.join(sorted(unsupported))}")
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 131072:
            raise ValueError(f"{name} exceeds the 128 KiB limit")
        if adapter["operation"] == "product.import.v3":
            item = value.get("item")
            if not isinstance(item, dict) or not item:
                raise ValueError(f"{name} requires a complete Ozon import item")
        return value

    @staticmethod
    def _state_hash(value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("State hash must be a SHA-256 hexadecimal digest")
        return normalized

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Evidence is required")
        self.evidence.require_current(normalized)
        return normalized

    def _link(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports",
                created_by=actor,
            )

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def _subject_ref(cls, adapter_id: str, target: dict[str, Any]) -> str:
        return cls._hash({"adapter_id": adapter_id, "target": target})

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _plan(cls, row: ExecutionPlanRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_kind": row.source_kind,
            "source_id": row.source_id,
            "source_approval_id": row.source_approval_id,
            "source_snapshot_hash": row.source_snapshot_hash,
            "handoff_id": row.handoff_id,
            "policy_id": row.policy_id,
            "release_id": row.release_id,
            "idempotency_key": row.idempotency_key,
            "adapter_id": row.adapter_id,
            "action_id": row.action_id,
            "action_policy_version": row.action_policy_version,
            "target": row.target_json,
            "precondition_state_hash": row.precondition_state_hash,
            "intended_patch": row.intended_patch_json,
            "rollback_patch": row.rollback_patch_json,
            "risk_limits": row.risk_limits_json,
            "risk_values": row.risk_values_json,
            "risk_currency": row.risk_currency,
            "permit_ttl_seconds": row.permit_ttl_seconds,
            "evidence_ids": row.evidence_json,
            "approval_id": row.approval_id,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _decision_packet(
        cls,
        *,
        result: dict[str, Any],
        source_context: dict[str, Any],
        approval,
        dry_run: dict[str, Any] | None,
        frozen_readiness_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        packet = {
            "schema_version": "decision-packet-v1",
            "action": result["action_id"],
            "subject": result["target"],
            "requested_by": result["created_by"],
            "policy_version": result["action_policy_version"],
            "source": {
                "kind": result["source_kind"],
                "id": result["source_id"],
                "approval_id": result["source_approval_id"],
                "snapshot_hash": result["source_snapshot_hash"],
                "approval_status": source_context["approval_status"],
                "validity_status": source_context["validity_status"],
            },
            "causal_policy_id": result["policy_id"],
            "causal_policy_release_id": result["release_id"],
            "causal_policy_snapshot_hash": (
                result["source_snapshot_hash"]
                if result["source_kind"] == CAUSAL_POLICY_HANDOFF
                else None
            ),
            "evidence_ids": result["evidence_ids"],
            "readiness_snapshot": frozen_readiness_snapshot,
            "adapter_id": result["adapter_id"],
            "risk_limits": result["risk_limits"],
            "risk_values": result["risk_values"],
            "risk_currency": result["risk_currency"],
            "approval": {
                "id": result["approval_id"],
                "status": approval.status.value,
                "decided_by": approval.decided_by,
                "reason": approval.decision_reason,
            },
            "dry_run_hash": cls._hash(dry_run) if dry_run else None,
            "expiry_conditions": [
                "action_policy_version_changes",
                "source_snapshot_changes",
                "source_approval_is_not_approved",
                "approval_is_not_approved",
                "evidence_becomes_invalid",
                "readiness_evidence_becomes_invalid",
                "permit_expires",
            ],
        }
        return {**packet, "decision_hash": cls._hash(packet), "immutable_projection": True}

    @classmethod
    def _dry_run(cls, row: ExecutionDryRunRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "current_state_hash": row.current_state_hash,
            "checks": row.checks_json,
            "passed": row.passed,
            "evidence_ids": row.evidence_json,
            "performed_by": row.performed_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
            "platform_write_performed": False,
        }
