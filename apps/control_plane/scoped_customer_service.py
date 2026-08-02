from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .customer_service import CustomerServiceAuthorityService
from .domain import ApprovalStatus
from .execution_plans import ExecutionPlanRow
from .limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
)
from .security import Principal
from .sql_repository import ProductRow


class _DisabledCustomerMessageReadbackAuthority:
    """Production-safe null port until an authorized message adapter exists."""

    CONTRACT_ID = "kjds-customer-message-readback-authority-v1"

    def attest(self, **_kwargs) -> dict[str, Any]:
        return {
            "contract_id": self.CONTRACT_ID,
            "status": "no_data",
            "reason": "customer_message_adapter_authority_unbound",
            "external_write_allowed": False,
            "private_erp_interface_allowed": False,
        }


class ScopedCustomerServiceWorkspace:
    """Project service-case truth and independently verified send authority."""

    CONTRACT_ID = "kjds-native-exact-scope-customer-service-v1"
    ARTIFACT_CONTRACT_ID = "kjds-customer-service-agent-artifact-v1"
    SOURCE_CONTRACT_ID = "kjds-customer-service-read-source-v1"
    RETURNS_CONTRACT_ID = "kjds-native-exact-scope-returns-aftersales-v1"
    MESSAGE_READBACK_AUTHORITY_CONTRACT_ID = (
        "kjds-customer-message-readback-authority-v1"
    )
    MESSAGE_READBACK_EVIDENCE_CONTRACT_ID = (
        "kjds-customer-message-readback-evidence-v1"
    )
    MESSAGE_READBACK_SOURCES = frozenset(
        {
            "customer_message_adapter_readback",
            "official_customer_message_readback",
            "authorized_customer_message_readback",
        }
    )
    STAGES = frozenset(
        {
            "opened",
            "triaged",
            "reply_drafted",
            "reply_approval_pending",
            "reply_permit_pending",
            "reply_readback_pending",
            "awaiting_customer",
            "return_in_progress",
            "dispute_in_progress",
            "resolved",
            "closed",
            "blocked",
        }
    )
    EVENT_STATE = {
        "case_opened": "opened",
        "triaged": "triaged",
        "message_received": "triaged",
        "reply_drafted": "reply_drafted",
        "reply_approval_pending": "reply_approval_pending",
        "reply_permit_pending": "reply_permit_pending",
        "reply_readback_pending": "reply_readback_pending",
        "message_sent_readback": "awaiting_customer",
        "return_opened": "return_in_progress",
        "rma_opened": "return_in_progress",
        "dispute_opened": "dispute_in_progress",
        "dispute_resolved": "resolved",
        "rma_resolved": "resolved",
        "resolved": "resolved",
        "closed": "closed",
    }
    TRANSITIONS = {
        None: {"opened"},
        "opened": {
            "triaged",
            "return_in_progress",
            "dispute_in_progress",
            "resolved",
            "closed",
        },
        "triaged": {
            "triaged",
            "reply_drafted",
            "return_in_progress",
            "dispute_in_progress",
            "resolved",
            "closed",
        },
        "reply_drafted": {
            "reply_drafted",
            "reply_approval_pending",
            "triaged",
            "return_in_progress",
            "dispute_in_progress",
            "resolved",
        },
        "reply_approval_pending": {
            "reply_drafted",
            "reply_permit_pending",
            "triaged",
            "resolved",
        },
        "reply_permit_pending": {
            "reply_drafted",
            "reply_readback_pending",
            "triaged",
            "resolved",
        },
        "reply_readback_pending": {
            "awaiting_customer",
            "triaged",
            "resolved",
        },
        "awaiting_customer": {
            "triaged",
            "reply_drafted",
            "return_in_progress",
            "dispute_in_progress",
            "resolved",
            "closed",
        },
        "return_in_progress": {
            "triaged",
            "reply_drafted",
            "dispute_in_progress",
            "resolved",
            "closed",
        },
        "dispute_in_progress": {
            "triaged",
            "reply_drafted",
            "return_in_progress",
            "resolved",
            "closed",
        },
        "resolved": {"triaged", "closed"},
        "closed": set(),
    }

    def __init__(
        self,
        *,
        engine,
        source,
        evidence,
        scoped_evidence,
        returns,
        repository,
        action_policies=None,
        message_readback_authority=None,
    ) -> None:
        self.engine = engine
        self.source = source
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence
        self.returns = returns
        self.repository = repository
        self.action_policies = action_policies
        self.message_readback_authority = (
            message_readback_authority
            or _DisabledCustomerMessageReadbackAuthority()
        )

    def project(
        self,
        *,
        store_ref: str = "ozon-primary",
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
        query: str | None = None,
        stage: str | None = None,
        channel: str | None = None,
        priority: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        filters = {
            "query": self._query(query) or None,
            "stage": self._stage(stage),
            "channel": self._filter_choice(
                channel,
                "channel",
                CustomerServiceAuthorityService.CHANNELS,
            ),
            "priority": self._filter_choice(
                priority,
                "priority",
                CustomerServiceAuthorityService.PRIORITIES,
            ),
        }
        page_size = self._page_size(page_size)
        normalized_cursor = str(cursor or "").strip() or None
        if context["status"] != "ready":
            return self._empty(
                context=context,
                filters=filters,
                page_size=page_size,
                status=context["status"],
                reason=context["reason"],
            )

        source = self.source.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        source_issues = self._source_issues(source, context=context)
        if source_issues:
            return self._empty(
                context=context,
                filters=filters,
                page_size=page_size,
                status="blocked",
                reason=source_issues[0],
                extra_gaps=source_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=source.get("snapshot_sha256"),
            )
        cases = source["cases"]
        if not cases:
            return self._empty(
                context=context,
                filters=filters,
                page_size=page_size,
                status="no_data",
                reason="customer_service_case_missing",
                scoped_input_read=True,
                source_snapshot_sha256=source.get("snapshot_sha256"),
            )

        events_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in source["events"]:
            events_by_case[str(event.get("case_id") or "")].append(event)

        rows: list[dict[str, Any]] = []
        exclusions: Counter[str] = Counter()
        returns_hashes: dict[str, str] = {}
        evidence_cache: dict[str, tuple[Any | None, list[str]]] = {}
        for case in cases:
            item, issues, returns_hash = self._case_item(
                case=case,
                events=events_by_case.get(str(case.get("id") or ""), []),
                context=context,
                principal=principal,
                entity_scope=entity_scope or {},
                evidence_cache=evidence_cache,
            )
            if returns_hash:
                returns_hashes[str(case.get("id") or "")] = returns_hash
            if issues:
                exclusions.update(issues)
            elif item is not None:
                rows.append(item)

        rows.sort(key=self._cursor_key, reverse=True)
        counts = self._counts(rows)
        filtered = [
            item for item in rows if self._matches(item, filters=filters)
        ]
        start = 0
        if normalized_cursor:
            key = self._decode_cursor(normalized_cursor)
            positions = {
                self._cursor_key(item): index
                for index, item in enumerate(filtered)
            }
            if key not in positions:
                raise ValueError(
                    "cursor does not belong to the current customer-service result"
                )
            start = positions[key] + 1
        page = filtered[start : start + page_size]
        next_cursor = (
            self._encode_cursor(self._cursor_key(page[-1]))
            if page and start + page_size < len(filtered)
            else None
        )
        gaps = sorted(exclusions)
        status = (
            "blocked"
            if exclusions
            else "ready"
            if rows
            else "no_data"
        )
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=page_size,
            total_filtered=len(filtered),
            next_cursor=next_cursor,
            cases=page,
            counts=counts,
            excluded={
                "count": sum(exclusions.values()),
                "reason_counts": dict(sorted(exclusions.items())),
                "business_values_exposed": False,
            },
            source_gaps=gaps,
            source_snapshot_sha256=source.get("snapshot_sha256"),
            returns_snapshot_sha256_by_case=returns_hashes,
        )

    def _case_item(
        self,
        *,
        case: dict[str, Any],
        events: list[dict[str, Any]],
        context: dict[str, Any],
        principal: Principal | None,
        entity_scope: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        issues = self._case_issues(
            case,
            context=context,
            evidence_cache=evidence_cache,
        )
        case_id = str(case.get("id") or "")
        ordered_events = sorted(
            events,
            key=lambda item: (
                self._integer(item.get("sequence")),
                str(item.get("id") or ""),
            ),
        )
        state: str | None = None
        dispute_status = "not_observed"
        rma_status = "not_observed"
        execution_authority = {
            "status": "not_observed",
            "approval_id": None,
            "command_id": None,
            "receipt_id": None,
            "readback_evidence_ids": [],
        }
        previous_time: datetime | None = None
        source_refs: set[str] = set()
        for position, event in enumerate(ordered_events, start=1):
            event_issues = self._event_issues(
                event,
                case=case,
                position=position,
                previous_time=previous_time,
                context=context,
                evidence_cache=evidence_cache,
                source_refs=source_refs,
            )
            issues.extend(event_issues)
            event_type = str(event.get("event_type") or "")
            next_state = self.EVENT_STATE.get(event_type)
            if next_state is None:
                issues.append("customer_service_event_type_invalid")
            elif next_state not in self.TRANSITIONS.get(state, set()):
                issues.append("customer_service_transition_invalid")
            else:
                state = next_state
            with suppress(ValueError):
                previous_time = self._timestamp(
                    event.get("effective_at"),
                    "effective_at",
                )
            if event_type == "dispute_opened":
                dispute_status = "open"
            elif event_type == "dispute_resolved":
                dispute_status = "resolved"
            elif event_type == "rma_opened":
                rma_status = "open"
            elif event_type == "rma_resolved":
                rma_status = "resolved"
            if event_type == "message_sent_readback":
                binding_issues, execution_authority = (
                    self._execution_authority_issues(
                        event=event,
                        case=case,
                        context=context,
                        evidence_cache=evidence_cache,
                    )
                )
                issues.extend(binding_issues)

        if not ordered_events:
            issues.append("customer_service_event_missing")
        if events and state is None:
            issues.append("customer_service_state_missing")
        if issues:
            return None, sorted(set(issues)), None

        returns = self.returns.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"].isoformat(),
            query=str(case.get("order_external_id") or ""),
            page_size=100,
        )
        returns_hash = str(returns.get("snapshot_sha256") or "") or None
        returns_issues = self._returns_issues(returns, context=context)
        matching_returns = [
            item
            for item in returns.get("returns", [])
            if item.get("order_external_id")
            == case.get("order_external_id")
        ]
        if len(matching_returns) > 1:
            returns_issues.append("customer_service_return_ambiguous")
        requires_return = bool(
            case.get("classification") in {"return", "refund", "rma"}
            or rma_status != "not_observed"
            or state == "return_in_progress"
        )
        if requires_return and not matching_returns:
            returns_issues.append("customer_service_return_authority_missing")
        if returns_issues:
            return None, sorted(set(returns_issues)), returns_hash

        latest = ordered_events[-1]
        return_item = matching_returns[0] if matching_returns else None
        return {
            "case_id": case_id,
            "external_case_ref": case["external_case_ref"],
            "channel": case["channel"],
            "order_external_id": case["order_external_id"],
            "product": {
                "id": case["product_id"],
                "sku": case["sku"],
            },
            "locale": case["locale"],
            "classification": case["classification"],
            "priority": case["priority"],
            "stage": state,
            "opened_at": case["opened_at"],
            "latest_effective_at": latest["effective_at"],
            "timeline": ordered_events,
            "event_count": len(ordered_events),
            "return_authority": {
                "status": "ready" if return_item else "not_observed",
                "return": return_item,
            },
            "dispute": {"status": dispute_status},
            "rma": {"status": rma_status},
            "execution_authority": execution_authority,
            "evidence_ids": [
                case["evidence_id"],
                *[event["evidence_id"] for event in ordered_events],
            ],
            "owner": self._owner(state),
            "sla": self._sla(state, case["priority"]),
            "next": self._next(state),
            "next_workspace": self._next_workspace(state),
        }, [], returns_hash

    def _case_issues(
        self,
        case: dict[str, Any],
        *,
        context: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
    ) -> list[str]:
        issues = []
        required = (
            "id",
            "external_case_ref",
            "channel",
            "order_external_id",
            "product_id",
            "sku",
            "locale",
            "classification",
            "priority",
            "evidence_id",
            "payload_sha256",
            "opened_at",
            "recorded_at",
            "created_by",
            "source_evidence_sha256",
            "scope_as_of",
        )
        if any(not str(case.get(field) or "").strip() for field in required):
            issues.append("customer_service_case_contract_invalid")
            return issues
        if case.get("channel") not in CustomerServiceAuthorityService.CHANNELS:
            issues.append("customer_service_case_channel_invalid")
        if (
            case.get("classification")
            not in CustomerServiceAuthorityService.CLASSIFICATIONS
        ):
            issues.append("customer_service_case_classification_invalid")
        if case.get("priority") not in CustomerServiceAuthorityService.PRIORITIES:
            issues.append("customer_service_case_priority_invalid")
        issues.extend(
            self._temporal_issues(
                case,
                fields=("opened_at", "recorded_at", "scope_as_of"),
                context=context,
                prefix="customer_service_case",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=case.get("evidence_id"),
                source_sha256=case.get("source_evidence_sha256"),
                context=context,
                prefix="customer_service_case",
                evidence_cache=evidence_cache,
            )
        )
        if not self._sha256(str(case.get("payload_sha256") or "")):
            issues.append("customer_service_case_payload_hash_invalid")
        expected = {
            "contract_id": CustomerServiceAuthorityService.CASE_CONTRACT_ID,
            "external_case_ref": case.get("external_case_ref"),
            "channel": case.get("channel"),
            "order_external_id": case.get("order_external_id"),
            "product_id": case.get("product_id"),
            "sku": case.get("sku"),
            "locale": case.get("locale"),
            "classification": case.get("classification"),
            "priority": case.get("priority"),
            "evidence_id": case.get("evidence_id"),
            "evidence_sha256": case.get("source_evidence_sha256"),
            "opened_at": case.get("opened_at"),
            "scope": context["scope"],
        }
        if case.get("payload_sha256") != self._hash(expected):
            issues.append("customer_service_case_payload_hash_drift")
        with Session(self.engine) as session:
            product = session.get(ProductRow, str(case.get("product_id") or ""))
        if (
            product is None
            or product.sku != case.get("sku")
            or product.tenant_ref != context["scope"]["tenant_ref"]
            or product.entity_ref != context["scope"]["entity_ref"]
            or product.store_ref != context["scope"]["store_ref"]
            or product.scope_grant_authority_sha256
            != context["scope"]["scope_grant_authority_sha256"]
            or product.scope_as_of is None
            or self._aware(product.scope_as_of) > context["cutoff"]
            or self._aware(product.created_at) > context["cutoff"]
        ):
            issues.append("customer_service_product_authority_invalid")
        return sorted(set(issues))

    def _event_issues(
        self,
        event: dict[str, Any],
        *,
        case: dict[str, Any],
        position: int,
        previous_time: datetime | None,
        context: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
        source_refs: set[str],
    ) -> list[str]:
        issues = []
        required = (
            "id",
            "case_id",
            "source_event_ref",
            "sequence",
            "event_type",
            "direction",
            "locale",
            "summary",
            "evidence_id",
            "payload_sha256",
            "effective_at",
            "recorded_at",
            "created_by",
            "source_evidence_sha256",
            "scope_as_of",
        )
        if any(
            event.get(field) is None or str(event.get(field)).strip() == ""
            for field in required
        ):
            issues.append("customer_service_event_contract_invalid")
            return issues
        if event.get("case_id") != case.get("id"):
            issues.append("customer_service_event_case_conflict")
        if self._integer(event.get("sequence")) != position:
            issues.append("customer_service_event_sequence_invalid")
        source_ref = str(event.get("source_event_ref") or "")
        if source_ref in source_refs:
            issues.append("customer_service_event_source_duplicate")
        source_refs.add(source_ref)
        if (
            event.get("event_type")
            not in CustomerServiceAuthorityService.EVENT_TYPES
        ):
            issues.append("customer_service_event_type_invalid")
        if (
            event.get("direction")
            not in CustomerServiceAuthorityService.DIRECTIONS
        ):
            issues.append("customer_service_event_direction_invalid")
        try:
            CustomerServiceAuthorityService._safe_summary(
                str(event.get("summary") or "")
            )
        except ValueError:
            issues.append("customer_service_event_pii_leak")
        event_type = str(event.get("event_type") or "")
        body_sha256 = str(event.get("body_sha256") or "")
        if (
            (
                event_type
                in CustomerServiceAuthorityService.BODY_REQUIRED_EVENTS
                or bool(body_sha256)
            )
            and not self._sha256(body_sha256)
        ):
            issues.append("customer_service_event_body_hash_invalid")
        issues.extend(
            self._temporal_issues(
                event,
                fields=("effective_at", "recorded_at", "scope_as_of"),
                context=context,
                prefix="customer_service_event",
            )
        )
        try:
            effective = self._timestamp(
                event.get("effective_at"), "effective_at"
            )
            if effective < self._timestamp(case.get("opened_at"), "opened_at"):
                issues.append("customer_service_event_predates_case")
            if previous_time is not None and effective < previous_time:
                issues.append("customer_service_event_time_regression")
        except ValueError:
            pass
        issues.extend(
            self._evidence_issues(
                evidence_id=event.get("evidence_id"),
                source_sha256=event.get("source_evidence_sha256"),
                context=context,
                prefix="customer_service_event",
                evidence_cache=evidence_cache,
            )
        )
        execution = (
            event.get("approval_id"),
            event.get("command_id"),
            event.get("receipt_id"),
        )
        if event_type == "message_sent_readback":
            if any(not str(value or "").strip() for value in execution):
                issues.append("customer_service_send_authority_incomplete")
            if event.get("direction") != "outbound":
                issues.append("customer_service_send_direction_invalid")
        elif any(str(value or "").strip() for value in execution):
            issues.append("customer_service_execution_binding_unexpected")
        expected = {
            "contract_id": CustomerServiceAuthorityService.EVENT_CONTRACT_ID,
            "case_id": event.get("case_id"),
            "source_event_ref": event.get("source_event_ref"),
            "sequence": event.get("sequence"),
            "event_type": event.get("event_type"),
            "direction": event.get("direction"),
            "locale": event.get("locale"),
            "summary": event.get("summary"),
            "body_sha256": event.get("body_sha256"),
            "evidence_id": event.get("evidence_id"),
            "evidence_sha256": event.get("source_evidence_sha256"),
            "effective_at": event.get("effective_at"),
            "approval_id": event.get("approval_id"),
            "command_id": event.get("command_id"),
            "receipt_id": event.get("receipt_id"),
            "scope": context["scope"],
        }
        if event.get("payload_sha256") != self._hash(expected):
            issues.append("customer_service_event_payload_hash_drift")
        return sorted(set(issues))

    def _execution_authority_issues(
        self,
        *,
        event: dict[str, Any],
        case: dict[str, Any],
        context: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
    ) -> tuple[list[str], dict[str, Any]]:
        issues = []
        approval_id = str(event.get("approval_id") or "")
        command_id = str(event.get("command_id") or "")
        receipt_id = str(event.get("receipt_id") or "")
        authority = {
            "status": "verified",
            "approval_id": approval_id or None,
            "command_id": command_id or None,
            "receipt_id": receipt_id or None,
            "readback_evidence_ids": [],
        }
        try:
            policy = self.action_policies.get(
                "customer_service_reply_send"
            )
            policy_version = self.action_policies.snapshot()[
                "policy_version"
            ]
            if (
                policy.get("risk_tier") != "L3"
                or policy.get("external_business_side_effect") is not True
                or policy.get("execution_permit_required") is not True
                or policy.get("idempotency_required") is not True
                or policy.get("readback_required") is not True
                or policy.get("allowed_executor") != "limited_executor"
                or policy.get("fail_closed") is not True
            ):
                issues.append("customer_service_reply_policy_invalid")
        except (AttributeError, KeyError, RuntimeError, ValueError):
            policy_version = None
            issues.append("customer_service_reply_policy_missing")
        try:
            approval = self.repository.get_approval_at(
                approval_id,
                as_of=context["cutoff"],
            )
            if (
                approval.status is not ApprovalStatus.APPROVED
                or approval.action != "customer_service.send_reply"
                or approval.resource_type != "customer_service_case"
                or approval.resource_id != case.get("id")
                or not approval.decided_by
                or approval.requested_by == approval.decided_by
            ):
                issues.append("customer_service_reply_approval_invalid")
            expected_payload = {
                "case_id": case.get("id"),
                "body_sha256": event.get("body_sha256"),
                "tenant_ref": context["scope"]["tenant_ref"],
                "entity_ref": context["scope"]["entity_ref"],
                "store_ref": context["scope"]["store_ref"],
            }
            if any(
                approval.payload.get(key) != value
                for key, value in expected_payload.items()
            ):
                issues.append("customer_service_reply_approval_payload_conflict")
        except (KeyError, RuntimeError, ValueError):
            issues.append("customer_service_reply_approval_missing")

        with Session(self.engine) as session:
            command = session.get(LimitedExecutionCommandRow, command_id)
            receipt = session.get(LimitedExecutionReceiptRow, receipt_id)
            plan = (
                session.get(ExecutionPlanRow, command.plan_id)
                if command is not None
                else None
            )
        if command is None or plan is None:
            issues.append("customer_service_reply_permit_missing")
            authority["status"] = "blocked"
            return sorted(set(issues)), authority
        target = command.target_json or {}
        if (
            plan.source_kind != "approved_customer_service_reply"
            or plan.source_id != case.get("id")
            or plan.source_snapshot_hash != event.get("body_sha256")
            or plan.action_id != "customer_service_reply_send"
            or plan.action_policy_version != policy_version
            or not plan.adapter_id
            or plan.adapter_id != command.adapter_id
            or plan.target_json.get("case_id") != case.get("id")
            or plan.target_json.get("body_sha256")
            != event.get("body_sha256")
            or self._aware(plan.created_at) > context["cutoff"]
            or
            command.command_kind != "execute"
            or command.action_id != "customer_service_reply_send"
            or command.action_policy_version != policy_version
            or command.operation != "customer_service.send_reply"
            or command.status != "succeeded"
            or target.get("case_id") != case.get("id")
            or target.get("body_sha256") != event.get("body_sha256")
            or target.get("tenant_ref") != context["scope"]["tenant_ref"]
            or target.get("entity_ref") != context["scope"]["entity_ref"]
            or target.get("store_ref") != context["scope"]["store_ref"]
            or approval_id not in {plan.source_approval_id, plan.approval_id}
            or self._aware(command.created_at) > context["cutoff"]
            or not self._sha256(command.decision_hash)
            or not self._sha256(command.authorization_hash)
        ):
            issues.append("customer_service_reply_permit_invalid")
        if (
            receipt is None
            or receipt.command_id != command_id
            or receipt.outcome != "succeeded"
            or not receipt.mutation_applied
            or not self._sha256(receipt.request_hash)
            or not self._sha256(receipt.resulting_state_hash)
            or not receipt.remote_operation_id
            or self._aware(receipt.recorded_at) > context["cutoff"]
            or self._aware(receipt.recorded_at)
            > self._aware(command.permit_expires_at)
        ):
            issues.append("customer_service_reply_readback_invalid")
            authority["status"] = "blocked"
            return sorted(set(issues)), authority
        evidence_ids = [
            str(item) for item in receipt.evidence_json if str(item).strip()
        ]
        for evidence_id in evidence_ids:
            issues.extend(
                self._evidence_issues(
                    evidence_id=evidence_id,
                    source_sha256=None,
                    context=context,
                    prefix="customer_service_reply_readback",
                    evidence_cache=evidence_cache,
                    accept_record_hash=True,
                )
            )
        attestation_issues, attestation = (
            self._message_readback_authority_issues(
                plan=plan,
                command=command,
                receipt=receipt,
                event=event,
                case=case,
                evidence_ids=evidence_ids,
                context=context,
                evidence_cache=evidence_cache,
            )
        )
        issues.extend(attestation_issues)
        authority["readback_evidence_ids"] = evidence_ids
        authority["adapter_id"] = attestation.get("authority", {}).get(
            "adapter_id"
        )
        authority["remote_operation_id"] = attestation.get(
            "success", {}
        ).get("remote_operation_id")
        authority["authority_contract_id"] = attestation.get("contract_id")
        if issues:
            authority["status"] = "blocked"
        return sorted(set(issues)), authority

    def _message_readback_authority_issues(
        self,
        *,
        plan,
        command,
        receipt,
        event: dict[str, Any],
        case: dict[str, Any],
        evidence_ids: list[str],
        context: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
    ) -> tuple[list[str], dict[str, Any]]:
        try:
            attestation = self.message_readback_authority.attest(
                principal=context["principal"],
                entity_scope=context["entity_scope"],
                store_ref=context["scope"]["store_ref"],
                as_of=context["cutoff"],
                case_id=case.get("id"),
                event_id=event.get("id"),
                body_sha256=event.get("body_sha256"),
                plan_id=plan.id,
                command_id=command.id,
                receipt_id=receipt.id,
            )
        except (AttributeError, KeyError, RuntimeError, ValueError):
            return ["customer_service_message_readback_authority_error"], {}
        issues: list[str] = []
        if (
            attestation.get("contract_id")
            != self.MESSAGE_READBACK_AUTHORITY_CONTRACT_ID
            or attestation.get("status") != "verified"
            or attestation.get("as_of") != context["cutoff"].isoformat()
        ):
            return [
                "customer_service_message_readback_authority_unbound"
            ], attestation
        snapshot = str(attestation.get("snapshot_sha256") or "")
        expected_snapshot = self._hash(
            {
                key: value
                for key, value in attestation.items()
                if key != "snapshot_sha256"
            }
        )
        if snapshot != expected_snapshot:
            issues.append(
                "customer_service_message_readback_authority_hash_drift"
            )
        authority = attestation.get("authority") or {}
        binding = attestation.get("binding") or {}
        success = attestation.get("success") or {}
        kill_switch = attestation.get("kill_switch") or {}
        compensation = attestation.get("compensation") or {}
        if (
            authority.get("source_kind")
            not in {
                "official_public_api",
                "authorized_export",
                "written_authorized_adapter",
            }
            or authority.get("immutable") is not True
            or authority.get("revoked") is not False
            or not str(authority.get("adapter_version") or "").strip()
            or authority.get("adapter_id") != plan.adapter_id
            or authority.get("adapter_id") != command.adapter_id
        ):
            issues.append(
                "customer_service_message_adapter_authority_invalid"
            )
        expected_binding = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "case_id": case.get("id"),
            "event_id": event.get("id"),
            "body_sha256": event.get("body_sha256"),
            "action_id": "customer_service_reply_send",
            "operation": "customer_service.send_reply",
            "command_id": command.id,
            "receipt_id": receipt.id,
            "remote_operation_id": receipt.remote_operation_id,
            "worker_id": command.claimed_by,
        }
        if any(
            binding.get(key) != value
            for key, value in expected_binding.items()
        ):
            issues.append(
                "customer_service_message_readback_binding_drift"
            )
        if (
            success.get("outcome") != "succeeded"
            or success.get("mutation_applied") is not True
            or success.get("platform_acknowledged") is not True
            or success.get("resulting_state_hash")
            != receipt.resulting_state_hash
            or success.get("remote_operation_id")
            != receipt.remote_operation_id
            or self._timestamp_or_none(success.get("observed_at")) is None
            or self._timestamp_or_none(success.get("observed_at"))
            > context["cutoff"]
        ):
            issues.append(
                "customer_service_message_readback_success_invalid"
            )
        if (
            kill_switch.get("status") != "released"
            or self._timestamp_or_none(kill_switch.get("observed_at"))
            is None
            or self._timestamp_or_none(kill_switch.get("observed_at"))
            > context["cutoff"]
        ):
            issues.append("customer_service_message_kill_switch_invalid")
        if (
            compensation.get("strategy") != "manual_case_follow_up"
            or compensation.get("status") != "ready"
            or not str(compensation.get("owner") or "").strip()
        ):
            issues.append(
                "customer_service_message_compensation_invalid"
            )
        evidence_specs = (
            (
                authority.get("authorization_evidence_id"),
                authority.get("authorization_evidence_sha256"),
                "customer_message_adapter_authorization",
                {
                    "adapter_id": authority.get("adapter_id"),
                    "adapter_version": authority.get("adapter_version"),
                    "action_id": "customer_service_reply_send",
                    "authorization_status": "active",
                    "revoked": False,
                },
            ),
            (
                success.get("readback_evidence_id"),
                success.get("readback_evidence_sha256"),
                "customer_message_adapter_readback",
                {
                    **expected_binding,
                    "evidence_contract_id": (
                        self.MESSAGE_READBACK_EVIDENCE_CONTRACT_ID
                    ),
                    "outcome": "succeeded",
                    "mutation_applied": True,
                    "platform_acknowledged": True,
                },
            ),
            (
                kill_switch.get("evidence_id"),
                kill_switch.get("evidence_sha256"),
                "kill_switch_release",
                {
                    "adapter_id": authority.get("adapter_id"),
                    "action_id": "customer_service_reply_send",
                    "status": "released",
                },
            ),
            (
                compensation.get("evidence_id"),
                compensation.get("evidence_sha256"),
                "customer_message_compensation_plan",
                {
                    "case_id": case.get("id"),
                    "strategy": "manual_case_follow_up",
                    "status": "ready",
                },
            ),
        )
        readback_evidence_id = str(
            success.get("readback_evidence_id") or ""
        )
        if (
            not readback_evidence_id
            or readback_evidence_id == event.get("evidence_id")
            or readback_evidence_id not in evidence_ids
        ):
            issues.append(
                "customer_service_message_readback_evidence_not_independent"
            )
        if (
            str(authority.get("authorization_evidence_id") or "")
            not in {str(item) for item in plan.evidence_json}
        ):
            issues.append(
                "customer_service_message_adapter_authorization_unbound"
            )
        for evidence_id, evidence_sha256, source, metadata in evidence_specs:
            issues.extend(
                self._message_authority_evidence_issues(
                    evidence_id=evidence_id,
                    evidence_sha256=evidence_sha256,
                    source=source,
                    metadata=metadata,
                    context=context,
                    evidence_cache=evidence_cache,
                )
            )
        return sorted(set(issues)), attestation

    def _message_authority_evidence_issues(
        self,
        *,
        evidence_id: Any,
        evidence_sha256: Any,
        source: str,
        metadata: dict[str, Any],
        context: dict[str, Any],
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
    ) -> list[str]:
        prefix = "customer_service_message_authority"
        issues = self._evidence_issues(
            evidence_id=evidence_id,
            source_sha256=None,
            context=context,
            prefix=prefix,
            evidence_cache=evidence_cache,
            accept_record_hash=True,
        )
        normalized = str(evidence_id or "")
        record = evidence_cache.get(normalized, (None, []))[0]
        if record is None:
            return issues
        actual_sha256 = str(
            getattr(record, "sha256", None)
            or getattr(record, "record_sha256", None)
            or ""
        )
        if (
            source not in self.MESSAGE_READBACK_SOURCES
            and source
            not in {
                "customer_message_adapter_authorization",
                "kill_switch_release",
                "customer_message_compensation_plan",
            }
        ):
            issues.append(f"{prefix}_source_invalid")
        if str(getattr(record, "source", "")) != source:
            issues.append(f"{prefix}_source_invalid")
        if evidence_sha256 != actual_sha256:
            issues.append(f"{prefix}_hash_drift")
        record_metadata = getattr(record, "metadata", None) or {}
        if any(
            record_metadata.get(key) != value
            for key, value in metadata.items()
        ):
            issues.append(f"{prefix}_metadata_binding_drift")
        return issues

    def _evidence_issues(
        self,
        *,
        evidence_id: Any,
        source_sha256: Any,
        context: dict[str, Any],
        prefix: str,
        evidence_cache: dict[str, tuple[Any | None, list[str]]],
        accept_record_hash: bool = False,
    ) -> list[str]:
        normalized = str(evidence_id or "").strip()
        if not normalized:
            return [f"{prefix}_evidence_missing"]
        if normalized not in evidence_cache:
            record = None
            issues: list[str] = []
            try:
                self.evidence.require_current(
                    [normalized],
                    as_of=context["cutoff"],
                )
                record = self.evidence.get(normalized)
                projection = self.scoped_evidence.project_targets(
                    evidence_ids=[normalized],
                    principal=context["principal"],
                    entity_scope=context["entity_scope"],
                    store_ref=context["scope"]["store_ref"],
                    as_of=context["cutoff"],
                )
                target = next(
                    (
                        item
                        for item in projection.get("records", [])
                        if item.get("evidence_id", item.get("id"))
                        == normalized
                    ),
                    None,
                )
                if (
                    projection.get("status") != "ready"
                    or target is None
                    or (
                        target.get("status")
                        or (target.get("scope_binding") or {}).get("status")
                    )
                    != "ready"
                ):
                    issues.append("evidence_scope_invalid")
            except (KeyError, RuntimeError, ValueError):
                issues.append("evidence_invalid")
            evidence_cache[normalized] = (record, issues)
        record, cached = evidence_cache[normalized]
        issues = [f"{prefix}_{item}" for item in cached]
        claimed = str(source_sha256 or "")
        if claimed and (
            record is None
            or claimed
            not in {
                str(record.sha256),
                str(getattr(record, "record_sha256", "")),
            }
        ):
            issues.append(f"{prefix}_evidence_hash_conflict")
        if (
            not claimed
            and not accept_record_hash
            and record is not None
        ):
            issues.append(f"{prefix}_source_hash_missing")
        return sorted(set(issues))

    @classmethod
    def _source_issues(
        cls,
        value: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues = []
        if value.get("contract_id") != cls.SOURCE_CONTRACT_ID:
            issues.append("customer_service_source_contract_conflict")
        if value.get("as_of") != context["cutoff"].isoformat():
            issues.append("customer_service_source_as_of_conflict")
        if value.get("scope") != context["scope"]:
            issues.append("customer_service_source_scope_conflict")
        if not isinstance(value.get("cases"), list) or not isinstance(
            value.get("events"), list
        ):
            issues.append("customer_service_source_payload_invalid")
        if any((value.get("truncated") or {}).values()):
            issues.append("customer_service_source_truncated")
        if not cls._valid_snapshot(value):
            issues.append("customer_service_source_snapshot_hash_drift")
        return sorted(set(issues))

    @classmethod
    def _returns_issues(
        cls,
        value: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues = []
        if value.get("contract_id") != cls.RETURNS_CONTRACT_ID:
            issues.append("customer_service_returns_contract_conflict")
        if value.get("as_of") != context["cutoff"].isoformat():
            issues.append("customer_service_returns_as_of_conflict")
        if value.get("scope") != context["scope"]:
            issues.append("customer_service_returns_scope_conflict")
        if not isinstance(value.get("returns"), list):
            issues.append("customer_service_returns_payload_invalid")
        if value.get("pagination", {}).get("next_cursor"):
            issues.append("customer_service_returns_truncated")
        if value.get("status") == "blocked":
            issues.append("customer_service_returns_blocked")
        if not cls._valid_snapshot(value):
            issues.append("customer_service_returns_snapshot_hash_drift")
        return sorted(set(issues))

    def _payload(
        self,
        *,
        context: dict[str, Any],
        status: str,
        filters: dict[str, Any],
        page_size: int,
        total_filtered: int,
        next_cursor: str | None,
        cases: list[dict[str, Any]],
        counts: dict[str, int],
        excluded: dict[str, Any],
        source_gaps: list[str],
        source_snapshot_sha256: str | None,
        returns_snapshot_sha256_by_case: dict[str, str],
        scoped_input_read: bool = True,
    ) -> dict[str, Any]:
        gaps = sorted(set(source_gaps))
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "filters": filters,
            "counts": {
                **counts,
                "filtered": total_filtered,
                "page": len(cases),
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "cases": cases,
            "excluded": excluded,
            "source_gaps": gaps,
            "blockers": self._blockers(gaps),
            "owner": "customer-operations",
            "sla": "before the platform response or dispute deadline",
            "next": (
                "Capture authorized non-sensitive Case/Event authority and "
                "keep raw customer data inside governed Evidence."
            ),
            "next_workspace": "/customer-service",
            "upstream": {
                "customer_service_source_snapshot_sha256": (
                    source_snapshot_sha256
                ),
                "returns_snapshot_sha256_by_case": dict(
                    sorted(returns_snapshot_sha256_by_case.items())
                ),
            },
            "privacy_envelope": {
                "raw_message_body_exposed": False,
                "customer_name_exposed": False,
                "customer_address_exposed": False,
                "customer_phone_exposed": False,
                "customer_email_exposed": False,
                "platform_handle_exposed": False,
                "pii_allowed_in_artifact": False,
                "pii_allowed_in_cursor": False,
            },
            "control_envelope": {
                "read_only_projection": True,
                "scoped_input_read": scoped_input_read,
                "client_recalculation_allowed": False,
                "case_created": False,
                "event_created": False,
                "message_marked_sent": False,
                "refund_created": False,
                "dispute_created": False,
                "rma_created": False,
                "approval_created": False,
                "permit_created": False,
                "message_adapter_enabled": False,
                "external_write_allowed": False,
                "private_erp_interface_allowed": False,
            },
        }
        input_hash = self._hash(core)
        suggestions = [
            {
                "type": "reply_draft_suggestion",
                "case_id": item["case_id"],
                "locale": item["locale"],
                "classification": item["classification"],
                "template_key": (
                    f"customer_service.{item['classification']}."
                    f"{item['locale']}"
                ),
                "draft_status": "suggested_not_created",
                "raw_customer_data_used": False,
                "body_sha256": None,
                "owner": item["owner"],
                "next_workspace": item["next_workspace"],
            }
            for item in cases
            if item["stage"]
            in {
                "opened",
                "triaged",
                "reply_drafted",
                "awaiting_customer",
            }
        ]
        suggestions.extend(
            {
                "type": "internal_task_suggestion",
                "code": gap,
                "owner": "customer-operations",
                "next_workspace": "/customer-service",
            }
            for gap in gaps
        )
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "version": "1",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "input_snapshot_sha256": input_hash,
            "suggestions": suggestions,
            "authority": (
                "redacted_reply_draft_and_internal_task_suggestion_only"
            ),
            "owner": "customer-operations",
            "raw_pii_read_allowed": False,
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "mark_sent_allowed": False,
            "refund_allowed": False,
            "dispute_allowed": False,
            "customer_contact_allowed": False,
            "external_write_allowed": False,
        }
        core["agent_artifact"] = {
            **artifact,
            "artifact_sha256": self._hash(artifact),
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _empty(
        self,
        *,
        context: dict[str, Any],
        filters: dict[str, Any],
        page_size: int,
        status: str,
        reason: str,
        extra_gaps: list[str] | None = None,
        scoped_input_read: bool = False,
        source_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=page_size,
            total_filtered=0,
            next_cursor=None,
            cases=[],
            counts=self._counts([]),
            excluded={
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            source_gaps=[reason, *(extra_gaps or [])],
            source_snapshot_sha256=source_snapshot_sha256,
            returns_snapshot_sha256_by_case={},
            scoped_input_read=scoped_input_read,
        )

    @classmethod
    def _context(
        cls,
        *,
        store_ref: str,
        principal: Principal | None,
        entity_scope: dict[str, Any] | None,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = str(store_ref or "").strip()
        if not store or len(store) > 160:
            raise ValueError("store_ref must be 1 to 160 characters")
        cutoff = cls._timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        if principal is not None and not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        scope = entity_scope or {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        }
        authority = str(scope.get("authority_sha256") or "").strip().lower()
        ready = bool(
            principal is not None
            and scope.get("status") == "ready"
            and str(scope.get("entity_ref") or "").strip()
            and cls._sha256(authority)
        )
        malformed = bool(scope.get("status") == "ready" and not ready)
        return {
            "status": "ready" if ready else "blocked" if malformed else "no_data",
            "reason": (
                "customer_service_scope_authority_invalid"
                if malformed
                else str(
                    scope.get("reason")
                    or (
                        "customer_service_scope_principal_missing"
                        if principal is None
                        else "entity_scope_authority_missing"
                    )
                )
            ),
            "cutoff": cutoff,
            "principal": principal,
            "entity_scope": scope,
            "scope": {
                "tenant_ref": (
                    principal.tenant_ref if principal is not None else None
                ),
                "entity_ref": (
                    str(scope.get("entity_ref"))
                    if scope.get("entity_ref")
                    else None
                ),
                "store_ref": store,
                "scope_grant_authority_sha256": authority if ready else None,
            },
        }

    @classmethod
    def _counts(cls, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "total_cases": len(rows),
            "total_events": sum(item["event_count"] for item in rows),
            "open_disputes": sum(
                item["dispute"]["status"] == "open" for item in rows
            ),
            "open_rmas": sum(item["rma"]["status"] == "open" for item in rows),
            "verified_sends": sum(
                item["execution_authority"]["status"] == "verified"
                for item in rows
            ),
            **{stage: 0 for stage in sorted(cls.STAGES)},
        }
        for item in rows:
            counts[item["stage"]] += 1
        return counts

    @staticmethod
    def _matches(
        item: dict[str, Any],
        *,
        filters: dict[str, Any],
    ) -> bool:
        query = filters["query"]
        return bool(
            (
                not query
                or query in item["external_case_ref"].lower()
                or query in item["order_external_id"].lower()
                or query in item["product"]["sku"].lower()
            )
            and (
                filters["stage"] is None
                or item["stage"] == filters["stage"]
            )
            and (
                filters["channel"] is None
                or item["channel"] == filters["channel"]
            )
            and (
                filters["priority"] is None
                or item["priority"] == filters["priority"]
            )
        )

    @staticmethod
    def _cursor_key(item: dict[str, Any]) -> str:
        return json.dumps(
            [
                item["latest_effective_at"],
                item["opened_at"],
                item["case_id"],
                item["external_case_ref"],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _encode_cursor(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> str:
        try:
            padding = "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(value + padding).decode()
            parsed = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("cursor is invalid") from exc
        if (
            not isinstance(parsed, list)
            or len(parsed) != 4
            or not all(isinstance(item, str) for item in parsed)
        ):
            raise ValueError("cursor is invalid")
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _temporal_issues(
        cls,
        value: dict[str, Any],
        *,
        fields: tuple[str, ...],
        context: dict[str, Any],
        prefix: str,
    ) -> list[str]:
        issues = []
        for field in fields:
            try:
                parsed = cls._timestamp(value.get(field), field)
                if parsed > context["cutoff"]:
                    issues.append(f"{prefix}_{field}_future")
            except ValueError:
                issues.append(f"{prefix}_{field}_invalid")
        return issues

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = str(value.get("snapshot_sha256") or "")
        return bool(
            cls._sha256(claimed)
            and claimed
            == cls._hash(
                {
                    key: item
                    for key, item in value.items()
                    if key != "snapshot_sha256"
                }
            )
        )

    @staticmethod
    def _query(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) > 160:
            raise ValueError("query must be at most 160 characters")
        return normalized

    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized not in cls.STAGES:
            raise ValueError("stage is unsupported")
        return normalized

    @staticmethod
    def _filter_choice(
        value: str | None,
        field: str,
        allowed: frozenset[str],
    ) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized not in allowed:
            raise ValueError(f"{field} is unsupported")
        return normalized

    @staticmethod
    def _page_size(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page_size must be an integer")
        if not 1 <= value <= 100:
            raise ValueError("page_size must be between 1 and 100")
        return value

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return -1
        return parsed if not isinstance(value, bool) else -1

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @classmethod
    def _timestamp_or_none(cls, value: Any) -> datetime | None:
        try:
            return cls._timestamp(value, "authority timestamp")
        except ValueError:
            return None

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value.lower()
        )

    @staticmethod
    def _blockers(gaps: list[str]) -> list[dict[str, str]]:
        return [
            {
                "code": gap,
                "severity": "P0",
                "owner": "customer-operations",
                "next_action": (
                    "Repair exact Case/Event/Evidence or independent "
                    "Approval/Permit/Readback authority."
                ),
                "workspace": "/customer-service",
            }
            for gap in sorted(set(gaps))
        ]

    @staticmethod
    def _owner(stage: str) -> str:
        return (
            "compliance-operations"
            if stage == "dispute_in_progress"
            else "returns-control"
            if stage == "return_in_progress"
            else "customer-operations"
        )

    @staticmethod
    def _sla(stage: str, priority: str) -> str:
        if priority == "urgent":
            return "within 30 minutes"
        return {
            "opened": "within 4 hours",
            "triaged": "before the platform response deadline",
            "reply_drafted": "within 2 hours",
            "reply_approval_pending": "before the platform response deadline",
            "reply_permit_pending": "within approved Permit window",
            "reply_readback_pending": "before Permit expiry",
            "awaiting_customer": "monitor until customer or platform deadline",
            "return_in_progress": "within return SLA",
            "dispute_in_progress": "before dispute deadline",
            "resolved": "monitor for 24 hours",
            "closed": "retention review only",
        }[stage]

    @staticmethod
    def _next(stage: str) -> str:
        return {
            "opened": "Triage using only authorized redacted context.",
            "triaged": "Prepare a versioned redacted reply draft.",
            "reply_drafted": "Request an independent reply Approval.",
            "reply_approval_pending": "Observe an independent Approval decision.",
            "reply_permit_pending": "Observe a one-time bounded Permit.",
            "reply_readback_pending": "Require immutable successful Readback.",
            "awaiting_customer": "Observe a new authorized customer event.",
            "return_in_progress": "Reconcile Return and finance authority.",
            "dispute_in_progress": "Preserve evidence and observe dispute outcome.",
            "resolved": "Close only after the resolution is stable.",
            "closed": "Retain the immutable audit trail.",
        }[stage]

    @staticmethod
    def _next_workspace(stage: str) -> str:
        return (
            "/returns"
            if stage == "return_in_progress"
            else "/evidenceops"
            if stage == "dispute_in_progress"
            else "/customer-service"
        )

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
