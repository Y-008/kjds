from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_ID = "kjds-ozon-finance-allocation-proposal-v1"


class OzonFinanceAllocationConflict(ValueError):
    """Raised when a stable source identity is reused with different content."""


class OzonFinanceAllocationInvariantError(ValueError):
    """Raised when exact scope or source-retention invariants do not hold."""


class OzonFinanceAllocationWorkspace:
    """Build read-only, exact-SKU allocation proposals for Ozon finance operations.

    The module is deliberately pure. It neither creates FinanceEntry records nor
    promotes facts; callers must independently review and persist any proposal.
    """

    CONTRACT_ID = CONTRACT_ID

    def project(
        self,
        *,
        scope: Mapping[str, Any],
        operations: Mapping[str, Any],
        listing_mappings: Mapping[str, Any],
        currency_evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_scope = self._scope(scope)
        operation_values, operation_envelope_evidence = self._envelope(
            operations,
            expected_scope=normalized_scope,
            item_keys=("operations", "items"),
            label="finance operations",
        )
        mapping_values, _ = self._envelope(
            listing_mappings,
            expected_scope=normalized_scope,
            item_keys=("mappings", "items"),
            label="listing mappings",
        )
        if currency_evidence is None:
            currency_values: list[Any] = []
        else:
            currency_values, _ = self._envelope(
                currency_evidence,
                expected_scope=normalized_scope,
                item_keys=("records", "evidence", "items"),
                label="currency evidence",
            )

        mapping_inventory, exact_mappings, mapping_duplicate_count = self._mappings(
            mapping_values,
            expected_scope=normalized_scope,
        )
        currency_inventory, currency_duplicate_count = self._currency_records(
            currency_values,
            expected_scope=normalized_scope,
        )
        normalized_operations, operation_duplicate_count = self._operations(
            operation_values,
            expected_scope=normalized_scope,
            envelope_evidence=operation_envelope_evidence,
        )
        posting_groups = self._posting_groups(normalized_operations, exact_mappings)
        currency_matches = self._currency_matches(
            normalized_operations,
            currency_inventory,
        )

        projected_operations = [
            self._project_operation(
                operation,
                exact_mappings=exact_mappings,
                posting_groups=posting_groups,
                currency_match=currency_matches[operation["operation_key"]],
            )
            for operation in normalized_operations
        ]
        projected_operations.sort(key=self._operation_sort_key)
        finance_entry_proposals = [
            item["finance_entry_proposal"]
            for item in projected_operations
            if item["finance_entry_proposal"] is not None
        ]
        accepted = [item for item in projected_operations if item["disposition"] == "accepted"]
        quarantined = [item for item in projected_operations if item["disposition"] == "quarantined"]
        unallocated = [item for item in projected_operations if item["disposition"] == "unallocated"]
        reconciliation = self._reconciliation(
            projected_operations,
            accepted=accepted,
            quarantined=quarantined,
            unallocated=unallocated,
        )
        posting_inventory = self._posting_inventory(posting_groups)
        input_payload = {
            "scope": normalized_scope,
            "operations": normalized_operations,
            "listing_mappings": mapping_inventory,
            "currency_evidence": currency_inventory,
        }
        input_sha256 = self._hash(input_payload)
        return {
            "contract_id": self.CONTRACT_ID,
            "proposal_id": f"ofap_{input_sha256[:24]}",
            "input_sha256": input_sha256,
            "scope": normalized_scope,
            "status": self._status(
                source_total=len(projected_operations),
                accepted=len(accepted),
            ),
            "summary": {
                "source_total": len(projected_operations),
                "accepted": len(accepted),
                "quarantined": len(quarantined),
                "unallocated": len(unallocated),
                "finance_entry_proposals": len(finance_entry_proposals),
                "posting_groups": len(posting_inventory),
                "exact_listing_mappings": len(exact_mappings),
                "duplicate_operation_inputs": operation_duplicate_count,
                "duplicate_mapping_inputs": mapping_duplicate_count,
                "duplicate_currency_evidence_inputs": currency_duplicate_count,
            },
            "reconciliation": reconciliation,
            "posting_inventory": posting_inventory,
            "listing_mapping_inventory": mapping_inventory,
            "currency_evidence_inventory": currency_inventory,
            "operations": projected_operations,
            "accepted_operations": accepted,
            "quarantined_operations": quarantined,
            "unallocated_operations": unallocated,
            "finance_entry_proposals": finance_entry_proposals,
            "control_envelope": {
                "read_model_only": True,
                "proposal_only": True,
                "formal_fact_promoted": False,
                "finance_entry_persisted": False,
                "external_write_allowed": False,
                "proportional_allocation_performed": False,
                "currency_inferred_from_marketplace": False,
                "cross_currency_aggregation_performed": False,
                "raw_source_retained": True,
            },
        }

    @classmethod
    def _mappings(
        cls,
        values: Iterable[Any],
        *,
        expected_scope: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
        unique: dict[str, tuple[str, dict[str, Any]]] = {}
        duplicates = 0
        for position, value in enumerate(values):
            raw = cls._mapping(value)
            cls._assert_item_scope(expected_scope, raw, f"listing mapping at position {position}")
            platform_sku = cls._text(cls._first(raw, "platform_sku", "marketplace_sku", "ozon_sku", "source_sku"))
            canonical_sku = cls._text(cls._first(raw, "canonical_sku", "product_sku", "internal_sku", "sku"))
            evidence_refs = cls._evidence_refs(raw)
            mapping_id = cls._text(cls._first(raw, "mapping_id", "id"))
            if not mapping_id:
                mapping_id = (
                    "map_"
                    + cls._hash(
                        {
                            "scope": expected_scope,
                            "platform_sku": platform_sku,
                            "canonical_sku": canonical_sku,
                            "evidence_refs": evidence_refs,
                        }
                    )[:24]
                )
            reasons: list[str] = []
            if not cls._numeric_sku(platform_sku):
                reasons.append("platform_sku_not_numeric")
            if not canonical_sku:
                reasons.append("canonical_sku_missing")
            if not evidence_refs:
                reasons.append("listing_mapping_evidence_missing")
            normalized = {
                "mapping_id": mapping_id,
                "scope": expected_scope,
                "platform_sku": platform_sku or None,
                "canonical_sku": canonical_sku or None,
                "evidence_refs": evidence_refs,
                "status": "quarantined" if reasons else "exact",
                "reason_codes": sorted(set(reasons)),
                "raw_mapping": cls._json_safe(raw),
            }
            fingerprint = cls._hash(normalized)
            previous = unique.get(mapping_id)
            if previous:
                if previous[0] != fingerprint:
                    raise OzonFinanceAllocationConflict(
                        f"Listing mapping {mapping_id} has conflicting immutable content"
                    )
                duplicates += 1
                continue
            unique[mapping_id] = (fingerprint, normalized)

        inventory = [value[1] for value in unique.values()]
        inventory.sort(key=lambda item: item["mapping_id"])
        by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in inventory:
            if item["status"] == "exact":
                by_platform[item["platform_sku"]].append(item)
        exact: dict[str, dict[str, Any]] = {}
        for platform_sku, candidates in by_platform.items():
            canonical_skus = {item["canonical_sku"] for item in candidates}
            if len(canonical_skus) == 1:
                exact[platform_sku] = {
                    "platform_sku": platform_sku,
                    "canonical_sku": next(iter(canonical_skus)),
                    "mapping_ids": sorted(item["mapping_id"] for item in candidates),
                    "evidence_refs": sorted(
                        {evidence_ref for item in candidates for evidence_ref in item["evidence_refs"]}
                    ),
                }
                continue
            for item in candidates:
                item["status"] = "quarantined"
                item["reason_codes"] = ["platform_sku_mapping_conflict"]
        return inventory, exact, duplicates

    @classmethod
    def _currency_records(
        cls,
        values: Iterable[Any],
        *,
        expected_scope: dict[str, str],
    ) -> tuple[list[dict[str, Any]], int]:
        unique: dict[str, tuple[str, dict[str, Any]]] = {}
        duplicates = 0
        for position, value in enumerate(values):
            raw = cls._mapping(value)
            cls._assert_item_scope(expected_scope, raw, f"currency evidence at position {position}")
            evidence_id = cls._text(cls._first(raw, "currency_evidence_id", "evidence_id", "id"))
            currency = cls._currency(raw.get("currency"))
            operation_ids = cls._texts(raw.get("operation_ids"))
            operation_id = cls._text(raw.get("operation_id"))
            if operation_id:
                operation_ids = sorted({*operation_ids, operation_id})
            posting_numbers = cls._texts(raw.get("posting_numbers"))
            posting_number = cls._text(raw.get("posting_number"))
            if posting_number:
                posting_numbers = sorted({*posting_numbers, posting_number})
            reasons: list[str] = []
            if not evidence_id:
                reasons.append("currency_evidence_id_missing")
                evidence_id = "fxev_" + cls._hash({"position": position, "raw": cls._json_safe(raw)})[:24]
            if not currency:
                reasons.append("currency_invalid")
            if not operation_ids and not posting_numbers:
                reasons.append("currency_evidence_target_missing")
            normalized = {
                "currency_evidence_id": evidence_id,
                "scope": expected_scope,
                "currency": currency,
                "operation_ids": operation_ids,
                "posting_numbers": posting_numbers,
                "effective_at_raw": cls._raw_text(raw.get("effective_at")),
                "source_evidence_refs": sorted({evidence_id, *cls._evidence_refs(raw)}),
                "status": "quarantined" if reasons else "accepted",
                "reason_codes": sorted(set(reasons)),
                "raw_evidence": cls._json_safe(raw),
            }
            fingerprint = cls._hash(normalized)
            previous = unique.get(evidence_id)
            if previous:
                if previous[0] != fingerprint:
                    raise OzonFinanceAllocationConflict(
                        f"Currency evidence {evidence_id} has conflicting immutable content"
                    )
                duplicates += 1
                continue
            unique[evidence_id] = (fingerprint, normalized)
        inventory = [value[1] for value in unique.values()]
        inventory.sort(key=lambda item: item["currency_evidence_id"])
        return inventory, duplicates

    @classmethod
    def _operations(
        cls,
        values: Iterable[Any],
        *,
        expected_scope: dict[str, str],
        envelope_evidence: list[str],
    ) -> tuple[list[dict[str, Any]], int]:
        unique: dict[str, tuple[str, dict[str, Any]]] = {}
        missing_identity: list[dict[str, Any]] = []
        duplicates = 0
        for position, value in enumerate(values):
            raw = cls._mapping(value)
            cls._assert_item_scope(expected_scope, raw, f"finance operation at position {position}")
            operation_id = cls._text(raw.get("operation_id"))
            operation_key = operation_id
            reasons: list[str] = []
            if not operation_id:
                reasons.append("operation_id_missing")
                operation_key = "missing_" + cls._hash({"position": position, "raw": cls._json_safe(raw)})[:24]
            posting = raw.get("posting")
            posting_mapping = posting if isinstance(posting, Mapping) else {}
            posting_number = cls._text(
                cls._first(raw, "posting_number")
                or cls._first(posting_mapping, "posting_number", "number")
                or (posting if isinstance(posting, str) else None)
            )
            raw_items = raw.get("items")
            if raw_items is None:
                raw_items = posting_mapping.get("items", [])
            if not isinstance(raw_items, list):
                raw_items = []
                reasons.append("operation_items_invalid")
            platform_skus: list[str] = []
            invalid_item_skus: list[str] = []
            for raw_item in raw_items:
                if isinstance(raw_item, Mapping):
                    item_sku = cls._text(cls._first(raw_item, "sku", "platform_sku", "marketplace_sku"))
                else:
                    item_sku = cls._text(raw_item)
                if cls._numeric_sku(item_sku):
                    platform_skus.append(item_sku)
                else:
                    invalid_item_skus.append(item_sku or "<missing>")
            amount_raw = cls._raw_text(raw.get("amount"))
            amount = cls._decimal(amount_raw)
            if amount_raw is None:
                reasons.append("operation_amount_missing")
            elif amount is None:
                reasons.append("operation_amount_invalid")
            occurred_at_raw = cls._raw_text(cls._first(raw, "operation_date", "occurred_at", "effective_at", "date"))
            occurred_at = cls._timestamp(occurred_at_raw)
            if occurred_at_raw is None:
                reasons.append("operation_time_missing")
            elif occurred_at is None:
                reasons.append("operation_time_invalid")
            evidence_refs = sorted({*envelope_evidence, *cls._evidence_refs(raw)})
            if not evidence_refs:
                reasons.append("operation_source_evidence_missing")
            embedded_currency_raw = cls._raw_text(raw.get("currency"))
            embedded_currency = cls._currency(embedded_currency_raw)
            if embedded_currency_raw and not embedded_currency:
                reasons.append("embedded_currency_invalid")
            normalized = {
                "operation_key": operation_key,
                "operation_id": operation_id or None,
                "scope": expected_scope,
                "posting_number": posting_number or None,
                "operation_type": cls._text(cls._first(raw, "operation_type", "operation_kind", "type")) or None,
                "operation_name": cls._text(raw.get("operation_name")) or None,
                "is_fee": cls._is_fee(raw),
                "platform_skus": sorted(set(platform_skus)),
                "invalid_item_skus": sorted(set(invalid_item_skus)),
                "has_items": bool(raw_items),
                "amount_raw": amount_raw,
                "amount_decimal": cls._decimal_text(amount) if amount is not None else None,
                "occurred_at_raw": occurred_at_raw,
                "occurred_at": occurred_at.isoformat() if occurred_at else None,
                "source_evidence_refs": evidence_refs,
                "embedded_currency": embedded_currency,
                "normalization_reason_codes": sorted(set(reasons)),
                "raw_operation": cls._json_safe(raw),
            }
            fingerprint = cls._hash(normalized)
            if operation_id:
                previous = unique.get(operation_id)
                if previous:
                    if previous[0] != fingerprint:
                        raise OzonFinanceAllocationConflict(
                            f"Finance operation {operation_id} has conflicting immutable content"
                        )
                    duplicates += 1
                    continue
                unique[operation_id] = (fingerprint, normalized)
            else:
                missing_identity.append(normalized)
        result = [value[1] for value in unique.values()]
        result.extend(missing_identity)
        result.sort(key=lambda item: item["operation_key"])
        return result, duplicates

    @classmethod
    def _posting_groups(
        cls,
        operations: list[dict[str, Any]],
        exact_mappings: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for operation in operations:
            if operation["posting_number"]:
                grouped[operation["posting_number"]].append(operation)
        result: dict[str, dict[str, Any]] = {}
        for posting_number, members in grouped.items():
            referenced = sorted({platform_sku for member in members for platform_sku in member["platform_skus"]})
            invalid = sorted({item for member in members for item in member["invalid_item_skus"]})
            unresolved = sorted(item for item in referenced if item not in exact_mappings)
            confirmed = sorted(item for item in referenced if item in exact_mappings)
            if invalid:
                status = "blocked"
                reason = "posting_contains_invalid_item_sku"
            elif unresolved:
                status = "blocked"
                reason = "posting_contains_unmapped_platform_sku"
            elif len(confirmed) == 0:
                status = "blocked"
                reason = "posting_exact_sku_missing"
            elif len(confirmed) > 1:
                status = "blocked"
                reason = "posting_contains_multiple_exact_skus"
            else:
                status = "single_exact_sku"
                reason = None
            result[posting_number] = {
                "posting_number": posting_number,
                "status": status,
                "reason": reason,
                "operation_keys": sorted(member["operation_key"] for member in members),
                "confirmed_platform_skus": confirmed,
                "unresolved_platform_skus": unresolved,
                "invalid_item_skus": invalid,
                "inheritable_platform_sku": confirmed[0] if status == "single_exact_sku" else None,
            }
        return result

    @classmethod
    def _currency_matches(
        cls,
        operations: list[dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for operation in operations:
            matches = [
                record
                for record in records
                if operation["operation_id"] in record["operation_ids"]
                or (operation["posting_number"] and operation["posting_number"] in record["posting_numbers"])
            ]
            valid = [record for record in matches if record["status"] == "accepted"]
            currencies = {record["currency"] for record in valid}
            if operation["embedded_currency"]:
                currencies.add(operation["embedded_currency"])
            evidence_refs = sorted(
                {evidence_ref for record in valid for evidence_ref in record["source_evidence_refs"]}
            )
            if operation["embedded_currency"]:
                evidence_refs = sorted({*evidence_refs, *operation["source_evidence_refs"]})
            if len(currencies) > 1:
                result[operation["operation_key"]] = {
                    "status": "conflict",
                    "currency": None,
                    "evidence_refs": evidence_refs,
                    "reason": "currency_evidence_conflict",
                }
            elif len(currencies) == 1:
                result[operation["operation_key"]] = {
                    "status": "evidenced",
                    "currency": next(iter(currencies)),
                    "evidence_refs": evidence_refs,
                    "reason": None,
                }
            elif matches:
                result[operation["operation_key"]] = {
                    "status": "blocked",
                    "currency": None,
                    "evidence_refs": sorted(
                        {evidence_ref for record in matches for evidence_ref in record["source_evidence_refs"]}
                    ),
                    "reason": "currency_evidence_invalid",
                }
            else:
                result[operation["operation_key"]] = {
                    "status": "missing",
                    "currency": None,
                    "evidence_refs": [],
                    "reason": "finance_currency_missing",
                }
        return result

    @classmethod
    def _project_operation(
        cls,
        operation: dict[str, Any],
        *,
        exact_mappings: dict[str, dict[str, Any]],
        posting_groups: dict[str, dict[str, Any]],
        currency_match: dict[str, Any],
    ) -> dict[str, Any]:
        reasons = list(operation["normalization_reason_codes"])
        allocation_basis: str | None = None
        platform_sku: str | None = None
        if operation["has_items"]:
            if operation["invalid_item_skus"]:
                reasons.append("operation_contains_invalid_item_sku")
            unresolved = sorted(item for item in operation["platform_skus"] if item not in exact_mappings)
            if unresolved:
                reasons.append("operation_platform_sku_unmapped")
            if len(operation["platform_skus"]) > 1:
                reasons.append("multi_sku_operation_requires_explicit_line_allocation")
            if not operation["invalid_item_skus"] and not unresolved and len(operation["platform_skus"]) == 1:
                platform_sku = operation["platform_skus"][0]
                allocation_basis = "direct_exact_platform_sku"
        else:
            posting = posting_groups.get(operation["posting_number"] or "")
            if not operation["is_fee"]:
                reasons.append("itemless_operation_not_confirmed_as_fee")
            elif posting is None:
                reasons.append("itemless_fee_posting_missing")
            elif posting["status"] != "single_exact_sku":
                reasons.append(posting["reason"] or "posting_exact_sku_unresolved")
            else:
                platform_sku = posting["inheritable_platform_sku"]
                allocation_basis = "itemless_fee_inherited_from_single_exact_posting_sku"

        mapping = exact_mappings.get(platform_sku or "")
        canonical_sku = mapping["canonical_sku"] if mapping else None
        fundamental_reasons = set(reasons).intersection(
            {
                "operation_id_missing",
                "operation_amount_missing",
                "operation_amount_invalid",
                "operation_time_missing",
                "operation_time_invalid",
                "operation_source_evidence_missing",
                "operation_items_invalid",
                "embedded_currency_invalid",
            }
        )
        allocation_reasons = {
            "operation_contains_invalid_item_sku",
            "operation_platform_sku_unmapped",
            "multi_sku_operation_requires_explicit_line_allocation",
            "itemless_operation_not_confirmed_as_fee",
            "itemless_fee_posting_missing",
            "posting_contains_invalid_item_sku",
            "posting_contains_unmapped_platform_sku",
            "posting_exact_sku_missing",
            "posting_contains_multiple_exact_skus",
            "posting_exact_sku_unresolved",
        }
        if platform_sku is None and not reasons:
            reasons.append("exact_platform_sku_missing")
            allocation_reasons.add("exact_platform_sku_missing")
        if fundamental_reasons:
            disposition = "quarantined"
        elif any(reason in allocation_reasons for reason in reasons) or platform_sku is None:
            disposition = "unallocated"
        else:
            if currency_match["reason"]:
                reasons.append(currency_match["reason"])
            disposition = "accepted" if not currency_match["reason"] else "quarantined"
        reasons = sorted(set(reasons))
        lineage_evidence = sorted(
            {
                *operation["source_evidence_refs"],
                *currency_match["evidence_refs"],
                *(mapping["evidence_refs"] if mapping else []),
            }
        )
        proposal = None
        if disposition == "accepted":
            proposal_payload = {
                "proposal_kind": "finance_entry_candidate",
                "source": "ozon_finance_operation",
                "source_ref": operation["operation_id"],
                "operation_id": operation["operation_id"],
                "posting_number": operation["posting_number"],
                "platform_sku": platform_sku,
                "sku": canonical_sku,
                "amount": operation["amount_decimal"],
                "amount_raw": operation["amount_raw"],
                "currency": currency_match["currency"],
                "occurred_at": operation["occurred_at"],
                "allocation_basis": allocation_basis,
                "evidence_refs": lineage_evidence,
                "requires_independent_review": True,
                "formal_fact": False,
                "persisted": False,
            }
            proposal = {
                "proposal_id": "fep_" + cls._hash(proposal_payload)[:24],
                **proposal_payload,
            }
        return {
            "operation_key": operation["operation_key"],
            "operation_id": operation["operation_id"],
            "posting_number": operation["posting_number"],
            "operation_type": operation["operation_type"],
            "operation_name": operation["operation_name"],
            "amount_raw": operation["amount_raw"],
            "amount_decimal": operation["amount_decimal"],
            "currency": currency_match["currency"],
            "currency_status": currency_match["status"],
            "occurred_at_raw": operation["occurred_at_raw"],
            "occurred_at": operation["occurred_at"],
            "platform_sku": platform_sku,
            "sku": canonical_sku,
            "allocation_basis": allocation_basis,
            "disposition": disposition,
            "profit_eligibility": "proposal_ready" if proposal else "blocked_raw",
            "reason_codes": reasons,
            "source_evidence_refs": operation["source_evidence_refs"],
            "lineage_evidence_refs": lineage_evidence,
            "raw_operation": operation["raw_operation"],
            "finance_entry_proposal": proposal,
        }

    @classmethod
    def _reconciliation(
        cls,
        operations: list[dict[str, Any]],
        *,
        accepted: list[dict[str, Any]],
        quarantined: list[dict[str, Any]],
        unallocated: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_total = len(operations)
        count_total = len(accepted) + len(quarantined) + len(unallocated)
        if count_total != source_total:
            raise OzonFinanceAllocationInvariantError(
                "Allocation violates accepted + quarantined + unallocated = source_total"
            )
        sums: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {
                "source": Decimal("0"),
                "accepted": Decimal("0"),
                "quarantined": Decimal("0"),
                "unallocated": Decimal("0"),
            }
        )
        non_summable_known_currency = 0
        unknown_currency = 0
        for operation in operations:
            currency = operation["currency"]
            amount = cls._decimal(operation["amount_decimal"])
            if not currency:
                unknown_currency += 1
                continue
            if amount is None:
                non_summable_known_currency += 1
                continue
            sums[currency]["source"] += amount
            sums[currency][operation["disposition"]] += amount
        amount_conservation = []
        for currency, values in sorted(sums.items()):
            retained = values["accepted"] + values["quarantined"] + values["unallocated"]
            amount_conservation.append(
                {
                    "currency": currency,
                    "source_amount": cls._decimal_text(values["source"]),
                    "accepted_amount": cls._decimal_text(values["accepted"]),
                    "quarantined_amount": cls._decimal_text(values["quarantined"]),
                    "unallocated_amount": cls._decimal_text(values["unallocated"]),
                    "retained_amount": cls._decimal_text(retained),
                    "conservation_passed": retained == values["source"],
                }
            )
        return {
            "source_total": source_total,
            "accepted": len(accepted),
            "quarantined": len(quarantined),
            "unallocated": len(unallocated),
            "accepted_plus_quarantined_plus_unallocated": count_total,
            "count_conservation_passed": count_total == source_total,
            "all_source_operations_retained": True,
            "known_currency_amount_conservation": amount_conservation,
            "all_known_currency_amounts_conserved": all(item["conservation_passed"] for item in amount_conservation),
            "non_summable_known_currency_operations": non_summable_known_currency,
            "unknown_currency_operations": unknown_currency,
        }

    @staticmethod
    def _status(*, source_total: int, accepted: int) -> str:
        if source_total == 0:
            return "no_data"
        if accepted == source_total:
            return "ready"
        if accepted:
            return "partial"
        return "blocked"

    @staticmethod
    def _posting_inventory(values: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [values[key] for key in sorted(values)]

    @staticmethod
    def _operation_sort_key(value: Mapping[str, Any]) -> tuple[str, str]:
        return (str(value.get("posting_number") or ""), str(value["operation_key"]))

    @classmethod
    def _envelope(
        cls,
        value: Mapping[str, Any],
        *,
        expected_scope: dict[str, str],
        item_keys: tuple[str, ...],
        label: str,
    ) -> tuple[list[Any], list[str]]:
        if not isinstance(value, Mapping):
            raise OzonFinanceAllocationInvariantError(f"{label} must be a scoped envelope")
        envelope_scope = value.get("scope")
        if not isinstance(envelope_scope, Mapping):
            raise OzonFinanceAllocationInvariantError(f"{label} scope is required")
        cls._assert_scope(expected_scope, cls._scope(envelope_scope), label)
        items: Any = None
        for key in item_keys:
            if key in value:
                items = value[key]
                break
        if items is None:
            items = []
        if not isinstance(items, list):
            raise OzonFinanceAllocationInvariantError(f"{label} items must be a list")
        return items, cls._evidence_refs(value)

    @classmethod
    def _scope(cls, value: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise OzonFinanceAllocationInvariantError("Scope must be an object")
        entity_ref = cls._text(value.get("entity_ref"))
        legal_entity_ref = cls._text(value.get("legal_entity_ref"))
        if entity_ref and legal_entity_ref and entity_ref != legal_entity_ref:
            raise OzonFinanceAllocationInvariantError("Scope entity_ref and legal_entity_ref conflict")
        normalized = {
            "tenant_ref": cls._text(value.get("tenant_ref")),
            "entity_ref": entity_ref or legal_entity_ref,
            "store_ref": cls._text(value.get("store_ref")),
        }
        if not all(normalized.values()):
            raise OzonFinanceAllocationInvariantError("Exact tenant, legal entity, and store scope is required")
        authority = cls._text(value.get("scope_grant_authority_sha256"))
        if authority:
            if len(authority) != 64 or any(character not in "0123456789abcdef" for character in authority.lower()):
                raise OzonFinanceAllocationInvariantError("scope_grant_authority_sha256 must be a SHA-256 digest")
            normalized["scope_grant_authority_sha256"] = authority.lower()
        return normalized

    @classmethod
    def _assert_scope(
        cls,
        expected: Mapping[str, str],
        actual: Mapping[str, str],
        label: str,
    ) -> None:
        if dict(actual) != dict(expected):
            raise OzonFinanceAllocationInvariantError(
                f"{label} crosses tenant, legal entity, store, or scope authority"
            )

    @classmethod
    def _assert_item_scope(
        cls,
        expected: dict[str, str],
        value: Mapping[str, Any],
        label: str,
    ) -> None:
        embedded = value.get("scope")
        has_direct_scope = any(key in value for key in ("tenant_ref", "entity_ref", "legal_entity_ref", "store_ref"))
        if embedded is None and not has_direct_scope:
            return
        candidate = embedded if isinstance(embedded, Mapping) else value
        cls._assert_scope(expected, cls._scope(candidate), label)

    @staticmethod
    def _is_fee(value: Mapping[str, Any]) -> bool:
        if isinstance(value.get("is_fee"), bool):
            return bool(value["is_fee"])
        operation_type = (
            str(value.get("operation_kind") or value.get("operation_type") or value.get("type") or "").strip().lower()
        )
        return operation_type in {"fee", "platform_fee", "service_fee", "commission"} or (
            operation_type.startswith("operationmarketplaceservice")
        )

    @staticmethod
    def _numeric_sku(value: str) -> bool:
        return bool(value) and value.isascii() and value.isdecimal()

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {"raw_value": value}
        return dict(value)

    @staticmethod
    def _first(value: Mapping[str, Any], *keys: str) -> Any:
        for key in keys:
            if value.get(key) is not None:
                return value[key]
        return None

    @classmethod
    def _evidence_refs(cls, value: Mapping[str, Any]) -> list[str]:
        refs: set[str] = set()
        for key in ("source_evidence_refs", "source_evidence_ids", "evidence_refs", "evidence_ids"):
            refs.update(cls._texts(value.get(key)))
        for key in ("source_evidence_ref", "source_evidence_id", "evidence_ref", "evidence_id"):
            item = cls._text(value.get(key))
            if item:
                refs.add(item)
        return sorted(refs)

    @classmethod
    def _texts(cls, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
        return sorted({item for raw in values if (item := cls._text(raw))})

    @staticmethod
    def _text(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _raw_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _currency(value: Any) -> str | None:
        text = str(value or "").strip().upper()
        return text if len(text) == 3 and text.isascii() and text.isalpha() else None

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            result = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
        return result if result.is_finite() else None

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value, "f")

    @staticmethod
    def _timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, set | frozenset):
            return sorted(cls._json_safe(item) for item in value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if value is None or isinstance(value, str | int | float | bool):
            return value
        return str(value)

    @classmethod
    def _hash(cls, value: Any) -> str:
        payload = json.dumps(
            cls._json_safe(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()
