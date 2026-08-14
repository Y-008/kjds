"""Governed commercial discovery contract kernel (COM-001 prep-only slice).

Freezes the first-ICP customer qualification, the read-only profit-truth
diagnostic deliverable, the C0 contract/DPA/SLA checklist, the pricing
hypothesis and the governed sales-copy rules from the dual-engine
commercialization & Russia GTM contract. This kernel is a read-only classifier
and contract fixture: it admits no customer write, invoice, payment,
receivable, Fact, FinanceEntry, Approval, Permit, Pilot or Outbox authority, and
every pricing figure stays `not_for_sale`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DISCOVERY_CONTRACT = "kjds-commercial-discovery-v1"
QUALIFICATION_CONTRACT = "kjds-customer-qualification-v1"
DIAGNOSTIC_CONTRACT = "kjds-profit-diagnostic-deliverable-v1"
CHECKLIST_CONTRACT = "kjds-contract-dpa-sla-checklist-v1"
SALES_COPY_CONTRACT = "kjds-sales-copy-v1"

ICP_COUNTRY = "cn"
ICP_OZON_STORES = (1, 3)
ICP_ACTIVE_SKUS = (50, 500)
ICP_TEAM_SIZE = (3, 20)

ICP_NUMERIC_FIELDS: dict[str, tuple[int, int]] = {
    "ozon_stores": ICP_OZON_STORES,
    "active_skus": ICP_ACTIVE_SKUS,
    "team_size": ICP_TEAM_SIZE,
}

REJECT_CONDITIONS = frozenset(
    {
        "no_real_account",
        "refuses_evidence",
        "sells_prohibited_or_infringing",
        "requests_blackhat",
        "requests_unapproved_direct_write",
        "demands_profit_guarantee",
    }
)

DEFER_CONDITIONS = frozenset(
    {
        "novice_insufficient_data_or_payment",
        "large_enterprise_requirements",
    }
)

_REJECT_TRIGGERS: dict[str, tuple[str, bool]] = {
    "no_real_account": ("has_real_account", False),
    "refuses_evidence": ("provides_evidence", False),
    "sells_prohibited_or_infringing": ("sells_prohibited_or_infringing", True),
    "requests_blackhat": ("requests_blackhat", True),
    "requests_unapproved_direct_write": ("requests_unapproved_direct_write", True),
    "demands_profit_guarantee": ("demands_profit_guarantee", True),
}

_DEFER_TRIGGERS: dict[str, tuple[str, bool]] = {
    "novice_insufficient_data_or_payment": ("is_novice_insufficient_data_or_payment", True),
    "large_enterprise_requirements": ("has_large_enterprise_requirements", True),
}

QUALIFICATION_STATUSES = frozenset({"rejected", "deferred", "needs_evidence", "qualified"})

DIAGNOSTIC_SCOPE = ("single_store", "read_only")
DIAGNOSTIC_OUTPUTS = ("data_quality_report", "sku_profit_gap")
DIAGNOSTIC_DELIVERY_FORMAT = "one_delivery_meeting"
DIAGNOSTIC_SUCCESS_CONDITION = "customer_accepted_problem_and_next_action_within_5_working_days"

PRICING_HYPOTHESIS = (
    {
        "product": "profit_truth_diagnostic",
        "scope": "single_store_read_only",
        "price_cny": 4800,
        "unit": "per_run",
        "not_for_sale": True,
        "note": "one_delivery_meeting",
    },
    {
        "product": "design_partner_pilot",
        "scope": "single_customer_isolated_single_store",
        "price_cny": 19800,
        "unit": "per_store",
        "not_for_sale": True,
        "note": "90_day_managed_validation",
    },
    {
        "product": "team_edition",
        "scope": "multi_role_workspace_reconciliation_tasks",
        "price_cny": 39900,
        "unit": "per_store_per_year",
        "not_for_sale": True,
        "note": "implementation_and_connectors_billed_separately",
    },
    {
        "product": "enterprise",
        "scope": None,
        "price_cny": None,
        "unit": None,
        "not_for_sale": True,
        "note": "post_g7_quote",
    },
)

CONTRACT_CHECKLIST_ITEMS = (
    "contract",
    "dpa",
    "privacy",
    "data_processing",
    "data_retention_deletion",
    "security_disclosure",
    "incident_notification",
    "support_sla",
)

ALLOWED_SALES_FRAMINGS = frozenset(
    {
        "traceable_sku_cash_profit",
        "controlled_actions",
        "evidence_first",
        "loss_and_gap_discovery",
    }
)

PROHIBITED_SALES_CLAIMS = frozenset(
    {
        "guaranteed_profit",
        "fully_automated_store_takeover",
        "ai_guaranteed_growth",
        "market_leader",
    }
)

STATUSES = frozenset({"ADMITTED", "NOT_ADMITTED", "STALE", "INVALIDATED"})

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
        "invoice",
        "payment",
        "receivable",
    }
)


class CommercialDiscoveryError(ValueError):
    """Stable, non-sensitive contract failure for commercial discovery."""


@dataclass(frozen=True)
class QualificationResult:
    status: str
    contract_id: str
    qualified: bool
    reject_reasons: tuple[str, ...]
    defer_reasons: tuple[str, ...]
    unknowns: tuple[str, ...]
    icp_checks: tuple[dict[str, Any], ...]
    external_action_allowed: bool
    result_sha256: str


@dataclass(frozen=True)
class DiagnosticDeliverable:
    status: str
    contract_id: str
    scope: tuple[str, ...]
    outputs: tuple[str, ...]
    delivery_format: str
    success_condition: str
    not_for_sale: bool
    external_write_allowed: bool
    unknowns: tuple[str, ...]
    deliverable_sha256: str


@dataclass(frozen=True)
class PricingItem:
    product: str
    scope: str | None
    price_cny: int | None
    unit: str | None
    not_for_sale: bool
    note: str | None
    item_sha256: str


@dataclass(frozen=True)
class ChecklistResult:
    contract_id: str
    items: tuple[dict[str, str], ...]
    all_unknown: bool
    checklist_sha256: str


@dataclass(frozen=True)
class SalesCopyResult:
    contract_id: str
    accepted: tuple[str, ...]
    rejected: tuple[str, ...]
    unknowns: tuple[str, ...]
    external_write_allowed: bool
    sales_copy_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise CommercialDiscoveryError(f"{name}_invalid")
    if len(value) > maximum:
        raise CommercialDiscoveryError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise CommercialDiscoveryError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise CommercialDiscoveryError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise CommercialDiscoveryError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise CommercialDiscoveryError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CommercialDiscoveryError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CommercialDiscoveryError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedCommercialDiscovery:
    """Deterministic commercial discovery contract kernel (COM-001 prep-only)."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def qualify(self, *, profile: dict[str, Any]) -> QualificationResult:
        if not isinstance(profile, Mapping):
            raise CommercialDiscoveryError("profile_invalid")
        _safe_tree(dict(profile))

        unknowns: list[str] = []
        reject_reasons: list[str] = []
        defer_reasons: list[str] = []
        icp_checks: list[dict[str, Any]] = []

        country = profile.get("country")
        if country is None:
            unknowns.append("country")
        else:
            if not isinstance(country, str):
                raise CommercialDiscoveryError("country_invalid")
            icp_checks.append({"field": "country", "value": country, "in_range": country == ICP_COUNTRY})

        for field, (lo, hi) in ICP_NUMERIC_FIELDS.items():
            value = profile.get(field)
            if value is None:
                unknowns.append(field)
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise CommercialDiscoveryError(f"{field}_invalid")
            icp_checks.append({"field": field, "value": value, "in_range": lo <= value <= hi})

        for condition, (field, trigger) in _REJECT_TRIGGERS.items():
            value = profile.get(field)
            if value is None:
                unknowns.append(field)
                continue
            if not isinstance(value, bool):
                raise CommercialDiscoveryError(f"{field}_invalid")
            if value == trigger:
                reject_reasons.append(condition)

        for condition, (field, trigger) in _DEFER_TRIGGERS.items():
            value = profile.get(field)
            if value is None:
                continue
            if not isinstance(value, bool):
                raise CommercialDiscoveryError(f"{field}_invalid")
            if value == trigger:
                defer_reasons.append(condition)

        unknowns = sorted(set(unknowns))
        reject_reasons = sorted(set(reject_reasons))
        defer_reasons = sorted(set(defer_reasons))

        if reject_reasons:
            status = "rejected"
        elif defer_reasons:
            status = "deferred"
        elif unknowns or any(not check["in_range"] for check in icp_checks):
            status = "needs_evidence"
        else:
            status = "qualified"

        document = {
            "contract_id": QUALIFICATION_CONTRACT,
            "status": status,
            "reject_reasons": reject_reasons,
            "defer_reasons": defer_reasons,
            "unknowns": unknowns,
            "icp_checks": icp_checks,
            "external_action_allowed": False,
        }
        return QualificationResult(
            status=status,
            contract_id=QUALIFICATION_CONTRACT,
            qualified=status == "qualified",
            reject_reasons=tuple(reject_reasons),
            defer_reasons=tuple(defer_reasons),
            unknowns=tuple(unknowns),
            icp_checks=tuple(icp_checks),
            external_action_allowed=False,
            result_sha256=_hash(document),
        )

    def diagnostic_scope(self) -> DiagnosticDeliverable:
        document = {
            "contract_id": DIAGNOSTIC_CONTRACT,
            "scope": DIAGNOSTIC_SCOPE,
            "outputs": DIAGNOSTIC_OUTPUTS,
            "delivery_format": DIAGNOSTIC_DELIVERY_FORMAT,
            "success_condition": DIAGNOSTIC_SUCCESS_CONDITION,
            "not_for_sale": True,
            "external_write_allowed": False,
        }
        return DiagnosticDeliverable(
            status="ADMITTED",
            contract_id=DIAGNOSTIC_CONTRACT,
            scope=DIAGNOSTIC_SCOPE,
            outputs=DIAGNOSTIC_OUTPUTS,
            delivery_format=DIAGNOSTIC_DELIVERY_FORMAT,
            success_condition=DIAGNOSTIC_SUCCESS_CONDITION,
            not_for_sale=True,
            external_write_allowed=False,
            unknowns=(),
            deliverable_sha256=_hash(document),
        )

    def pricing_hypothesis(self) -> tuple[PricingItem, ...]:
        items: list[PricingItem] = []
        for entry in PRICING_HYPOTHESIS:
            document = dict(entry)
            items.append(
                PricingItem(
                    product=entry["product"],
                    scope=entry["scope"],
                    price_cny=entry["price_cny"],
                    unit=entry["unit"],
                    not_for_sale=entry["not_for_sale"],
                    note=entry["note"],
                    item_sha256=_hash(document),
                )
            )
        return tuple(items)

    def contract_checklist(self) -> ChecklistResult:
        items = tuple({"key": item, "status": "UNKNOWN"} for item in CONTRACT_CHECKLIST_ITEMS)
        document = {
            "contract_id": CHECKLIST_CONTRACT,
            "items": [dict(item) for item in items],
        }
        return ChecklistResult(
            contract_id=CHECKLIST_CONTRACT,
            items=items,
            all_unknown=all(item["status"] == "UNKNOWN" for item in items),
            checklist_sha256=_hash(document),
        )

    def sales_copy_contract(self, *, copy: list[str]) -> SalesCopyResult:
        if not isinstance(copy, list):
            raise CommercialDiscoveryError("copy_invalid")
        _safe_tree(copy)
        accepted: list[str] = []
        rejected: list[str] = []
        unknowns: list[str] = []
        for phrase in copy:
            text = _text(phrase, "copy_phrase", maximum=200)
            normalized = text.strip().lower()
            if normalized in PROHIBITED_SALES_CLAIMS:
                rejected.append(normalized)
            elif normalized in ALLOWED_SALES_FRAMINGS:
                accepted.append(normalized)
            else:
                unknowns.append(normalized)
        document = {
            "contract_id": SALES_COPY_CONTRACT,
            "accepted": sorted(set(accepted)),
            "rejected": sorted(set(rejected)),
            "unknowns": sorted(set(unknowns)),
            "external_write_allowed": False,
        }
        return SalesCopyResult(
            contract_id=SALES_COPY_CONTRACT,
            accepted=tuple(sorted(set(accepted))),
            rejected=tuple(sorted(set(rejected))),
            unknowns=tuple(sorted(set(unknowns))),
            external_write_allowed=False,
            sales_copy_sha256=_hash(document),
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if isinstance(obj, QualificationResult):
            digest = obj.result_sha256
        elif isinstance(obj, DiagnosticDeliverable):
            digest = obj.deliverable_sha256
        elif isinstance(obj, PricingItem):
            digest = obj.item_sha256
        elif isinstance(obj, ChecklistResult):
            digest = obj.checklist_sha256
        elif isinstance(obj, SalesCopyResult):
            digest = obj.sales_copy_sha256
        else:
            raise CommercialDiscoveryError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == digest
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "ChecklistResult",
    "DiagnosticDeliverable",
    "GovernedCommercialDiscovery",
    "PricingItem",
    "QualificationResult",
    "SalesCopyResult",
    "CommercialDiscoveryError",
    "ALLOWED_SALES_FRAMINGS",
    "CHECKLIST_CONTRACT",
    "CONTRACT_CHECKLIST_ITEMS",
    "DEFER_CONDITIONS",
    "DIAGNOSTIC_CONTRACT",
    "DISCOVERY_CONTRACT",
    "ICP_COUNTRY",
    "ICP_OZON_STORES",
    "ICP_ACTIVE_SKUS",
    "ICP_TEAM_SIZE",
    "PRICING_HYPOTHESIS",
    "PROHIBITED_SALES_CLAIMS",
    "QUALIFICATION_CONTRACT",
    "QUALIFICATION_STATUSES",
    "REJECT_CONDITIONS",
    "SALES_COPY_CONTRACT",
    "ZERO_AUTHORITY_KEYS",
]
