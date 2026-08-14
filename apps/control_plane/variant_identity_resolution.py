from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

CONTRACT_ID = "kjds-variant-identity-resolution-v1"
POLICY_VERSION = "2026-08-02.1"

_EXACT_ANCHORS = ("offer_id", "platform_sku", "barcode")
_CONTROLLED_ATTRIBUTE_PREFIXES = (
    "attr:",
    "attribute:",
    "attribute_id:",
    "id:",
    "ozon:",
)
_TITLE_WITH_CATEGORY_THRESHOLD_BPS = 5_500
_TITLE_ONLY_THRESHOLD_BPS = 8_500


class VariantIdentityConflict(ValueError):
    """Raised when a stable source or replay identity carries changed content."""


class VariantIdentityInvariantError(ValueError):
    """Raised when identity source retention or reconciliation would be violated."""


class VariantIdentityResolutionWorkspace:
    """Project exact variant links and review-only relationship candidates.

    The module is pure and fail-closed. It does not read a database, promote a
    fact, merge catalog records, or write to a marketplace. Exact resolution is
    limited to controlled identifiers: offer ID, platform SKU, and barcode.
    Model IDs, category, title, and descriptive attributes can only create a
    review proposal.
    """

    CONTRACT_ID = CONTRACT_ID
    POLICY_VERSION = POLICY_VERSION

    def project(
        self,
        *,
        scope: Mapping[str, Any],
        sources: Iterable[Mapping[str, Any]],
        expected_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        normalized_scope = self._scope(scope, "scope")
        normalized_sources, duplicate_count = self._sources(
            sources,
            expected_scope=normalized_scope,
        )
        input_payload = {
            "scope": normalized_scope,
            "sources": [self._source_projection(source) for source in normalized_sources],
        }
        input_sha256 = self._sha256(input_payload)
        self._assert_expected_hash(expected_input_sha256, input_sha256)

        pairs = self._pair_analyses(normalized_sources)
        components = self._components(normalized_sources, pairs)
        exact_resolutions, quarantines, source_status = self._classify_components(
            components,
            pairs,
        )
        proposals = self._candidate_proposals(
            normalized_sources,
            pairs,
            source_status=source_status,
        )
        proposals_by_source: dict[str, list[str]] = defaultdict(list)
        for proposal in proposals:
            for source_ref in proposal["source_refs"]:
                proposals_by_source[source_ref].append(proposal["proposal_id"])

        source_inventory = []
        for source in normalized_sources:
            status = source_status[source["source_ref"]]
            reasons = set(source["validation_reasons"])
            if status == "unresolved":
                reasons.add("no_exact_controlled_identifier_match")
                if proposals_by_source[source["source_ref"]]:
                    reasons.add("candidate_review_available")
            source_inventory.append(
                {
                    "source_ref": source["source_ref"],
                    "source_kind": source["source_kind"],
                    "platform_namespace": source["platform_namespace"],
                    "status": status,
                    "reason_codes": sorted(reasons),
                    "source_sha256": source["source_sha256"],
                    "evidence_refs": list(source["evidence_refs"]),
                    "original_identifiers": source["original_identifiers"],
                    "normalized_identifiers": self._public_identifiers(source),
                    "candidate_proposal_ids": sorted(proposals_by_source[source["source_ref"]]),
                }
            )

        counts = {
            "source_total": len(normalized_sources),
            "accepted": sum(item["status"] == "accepted" for item in source_inventory),
            "quarantined": sum(item["status"] == "quarantined" for item in source_inventory),
            "unresolved": sum(item["status"] == "unresolved" for item in source_inventory),
        }
        reconciled = counts["accepted"] + counts["quarantined"] + counts["unresolved"]
        if reconciled != counts["source_total"]:
            raise VariantIdentityInvariantError("accepted + quarantined + unresolved must equal source_total")

        output_core = {
            "contract_id": self.CONTRACT_ID,
            "policy_version": self.POLICY_VERSION,
            "input_sha256": input_sha256,
            "scope": normalized_scope,
            "summary": {
                **counts,
                "exact_resolution_count": len(exact_resolutions),
                "candidate_proposal_count": len(proposals),
                "quarantine_group_count": len(quarantines),
                "duplicate_input_occurrences": duplicate_count,
            },
            "reconciliation": {
                **counts,
                "accepted_plus_quarantined_plus_unresolved": reconciled,
                "conservation_passed": reconciled == counts["source_total"],
                "all_source_refs_retained": {item["source_ref"] for item in source_inventory}
                == {source["source_ref"] for source in normalized_sources},
            },
            "exact_resolutions": exact_resolutions,
            "candidate_proposals": proposals,
            "quarantine": quarantines,
            "source_inventory": source_inventory,
            "control_envelope": {
                "read_only_projection": True,
                "formal_fact_promoted": False,
                "automatic_merge_allowed": False,
                "external_write_allowed": False,
                "model_id_can_establish_exact_variant": False,
                "title_or_category_can_establish_exact_variant": False,
                "descriptive_attributes_can_establish_exact_variant": False,
                "all_source_records_retained": True,
            },
        }
        return {
            **output_core,
            "projection_sha256": self._sha256(output_core),
        }

    @classmethod
    def _sources(
        cls,
        values: Iterable[Mapping[str, Any]],
        *,
        expected_scope: dict[str, str],
    ) -> tuple[list[dict[str, Any]], int]:
        unique: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        for position, value in enumerate(values):
            if not isinstance(value, Mapping):
                raise ValueError(f"sources[{position}] must be an object")
            source = cls._source(value, position=position, expected_scope=expected_scope)
            existing = unique.get(source["source_ref"])
            if existing is None:
                unique[source["source_ref"]] = source
                continue
            if existing["source_sha256"] != source["source_sha256"]:
                raise VariantIdentityConflict(
                    f"Source {source['source_ref']} has conflicting immutable identity content"
                )
            duplicate_count += 1
        return sorted(unique.values(), key=lambda source: source["source_ref"]), duplicate_count

    @classmethod
    def _source(
        cls,
        value: Mapping[str, Any],
        *,
        position: int,
        expected_scope: dict[str, str],
    ) -> dict[str, Any]:
        source_scope_value = value.get("scope") if isinstance(value.get("scope"), Mapping) else value
        source_scope = cls._scope(source_scope_value, f"sources[{position}].scope")
        if source_scope != expected_scope:
            raise PermissionError(f"sources[{position}] is outside the authorized tenant/legal_entity/store scope")

        payload_value = value.get("payload_json", value.get("payload", value))
        payload = payload_value if isinstance(payload_value, Mapping) else {}
        source_ref = cls._required(
            value.get("source_ref")
            or value.get("source_item_id")
            or value.get("record_ref")
            or value.get("id")
            or payload.get("source_ref"),
            f"sources[{position}].source_ref",
            500,
        )
        source_kind = cls._required(
            value.get("source_kind") or value.get("artifact_kind") or value.get("record_kind"),
            f"sources[{position}].source_kind",
            100,
        ).lower()
        containers = cls._identity_containers(value, payload)
        declared_namespace = cls._first_text(
            containers,
            "platform_namespace",
            "marketplace",
            "platform",
            "channel",
        ).lower()
        platform_namespace = (
            "ozon" if declared_namespace == "ozon" or "ozon" in source_kind else declared_namespace or "unverified"
        )
        ozon_context = platform_namespace == "ozon"
        original_identifiers = cls._original_identifiers(containers, payload, source_kind)

        raw_offer_ids = cls._collect(containers, "offer_id", "offer_ids")
        explicit_ozon_offer_ids = cls._collect(
            containers,
            "ozon_offer_id",
            "ozon_offer_ids",
        )
        offer_ids = cls._texts(
            [*explicit_ozon_offer_ids, *(raw_offer_ids if ozon_context else [])],
            upper=False,
        )
        explicit_ozon = cls._collect(containers, "ozon_sku", "ozon_skus")
        raw_source_skus = cls._collect(containers, "source_sku", "source_skus")
        raw_finance_skus = cls._collect(containers, "finance_item_sku", "finance_item_skus")
        explicit_source = list(raw_source_skus) if ozon_context else []
        explicit_finance = list(raw_finance_skus) if ozon_context else []
        top_level_sku = cls._collect(containers, "sku")
        nested_source_skus = [
            item.get("sku")
            for item in payload.get("sources", [])
            if isinstance(item, Mapping) and item.get("sku") not in (None, "")
        ]
        finance_item_skus = [
            item.get("sku")
            for item in payload.get("items", [])
            if isinstance(item, Mapping) and item.get("sku") not in (None, "")
        ]
        if ozon_context and "finance" in source_kind:
            explicit_finance.extend(top_level_sku)
            explicit_finance.extend(finance_item_skus)
        elif ozon_context:
            explicit_ozon.extend(top_level_sku)
        if ozon_context:
            explicit_source.extend(nested_source_skus)

        ozon_skus, invalid_ozon = cls._numeric_identifiers(explicit_ozon)
        source_skus, invalid_source = cls._numeric_identifiers(explicit_source)
        finance_skus, invalid_finance = cls._numeric_identifiers(explicit_finance)
        if not ozon_context:
            _, invalid_unscoped_source = cls._numeric_identifiers(raw_source_skus)
            _, invalid_unscoped_finance = cls._numeric_identifiers(raw_finance_skus)
            invalid_source = sorted({*invalid_source, *invalid_unscoped_source})
            invalid_finance = sorted({*invalid_finance, *invalid_unscoped_finance})
        barcodes = cls._texts(
            cls._collect(containers, "barcode", "barcodes"),
            upper=True,
        )
        model_values = cls._collect(containers, "model_id", "model_ids")
        for container in containers:
            model_info = container.get("model_info")
            if isinstance(model_info, Mapping):
                model_values.append(model_info.get("model_id"))
        model_ids, invalid_models = cls._numeric_identifiers(model_values)
        controlled_attributes, descriptive_attributes, attribute_reasons = cls._attributes(containers)
        title = cls._first_text(containers, "title", "name")
        categories = cls._categories(containers)
        evidence_refs = cls._evidence_refs(value, payload)

        validation_reasons = set(attribute_reasons)
        if raw_offer_ids and not ozon_context and not explicit_ozon_offer_ids:
            validation_reasons.add("offer_id_namespace_unverified")
        if top_level_sku and not ozon_context:
            validation_reasons.add("sku_namespace_unverified")
        if (raw_source_skus or nested_source_skus) and not ozon_context:
            validation_reasons.add("source_sku_namespace_unverified")
        if (raw_finance_skus or finance_item_skus) and not ozon_context:
            validation_reasons.add("finance_item_sku_namespace_unverified")
        if invalid_ozon:
            validation_reasons.add("invalid_ozon_sku")
        if invalid_source:
            validation_reasons.add("invalid_source_sku")
        if invalid_finance:
            validation_reasons.add("invalid_finance_item_sku")
        if invalid_models:
            validation_reasons.add("invalid_model_id")
        if len(offer_ids) > 1:
            validation_reasons.add("source_offer_id_ambiguous")
        if len(ozon_skus) > 1:
            validation_reasons.add("source_ozon_sku_ambiguous")
        if len(source_skus) > 1:
            validation_reasons.add("source_platform_source_sku_ambiguous")
        if len(finance_skus) > 1:
            validation_reasons.add("source_finance_item_sku_ambiguous")
        if len(model_ids) > 1:
            validation_reasons.add("source_model_id_ambiguous")
        if ozon_skus and source_skus and set(ozon_skus).isdisjoint(source_skus):
            validation_reasons.add("source_platform_sku_conflict")

        source = {
            "source_ref": source_ref,
            "source_kind": source_kind,
            "platform_namespace": platform_namespace,
            "scope": source_scope,
            "evidence_refs": tuple(evidence_refs),
            "offer_ids": tuple(offer_ids),
            "ozon_skus": tuple(ozon_skus),
            "source_skus": tuple(source_skus),
            "finance_item_skus": tuple(finance_skus),
            "barcodes": tuple(barcodes),
            "model_ids": tuple(model_ids),
            "controlled_attributes": controlled_attributes,
            "descriptive_attributes": descriptive_attributes,
            "title": title,
            "title_tokens": tuple(cls._title_tokens(title)),
            "categories": tuple(categories),
            "original_identifiers": original_identifiers,
            "validation_reasons": tuple(sorted(validation_reasons)),
        }
        source["source_sha256"] = cls._sha256(cls._source_projection(source))
        return source

    @classmethod
    def _pair_analyses(cls, sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        pairs: list[dict[str, Any]] = []
        for left_position, left in enumerate(sources):
            for right in sources[left_position + 1 :]:
                anchors: dict[str, tuple[str, ...]] = {}
                offer_matches = sorted(set(left["offer_ids"]) & set(right["offer_ids"]))
                if offer_matches:
                    anchors["offer_id"] = tuple(offer_matches)
                platform_matches = sorted(
                    cls._platform_skus(left) & cls._platform_skus(right),
                    key=cls._numeric_sort_key,
                )
                if platform_matches:
                    anchors["platform_sku"] = tuple(platform_matches)
                barcode_matches = sorted(set(left["barcodes"]) & set(right["barcodes"]))
                if barcode_matches:
                    anchors["barcode"] = tuple(barcode_matches)

                conflicts: set[str] = set()
                controlled_matches: list[str] = []
                if anchors:
                    if left["offer_ids"] and right["offer_ids"] and not offer_matches:
                        conflicts.add("offer_id_conflict")
                    left_platform = cls._platform_skus(left)
                    right_platform = cls._platform_skus(right)
                    if left_platform and right_platform and not platform_matches:
                        conflicts.add("platform_sku_conflict")
                    if (
                        left["model_ids"]
                        and right["model_ids"]
                        and set(left["model_ids"]).isdisjoint(right["model_ids"])
                    ):
                        conflicts.add("model_group_conflict_on_exact_anchor")
                    common_attributes = set(left["controlled_attributes"]) & set(right["controlled_attributes"])
                    for key in sorted(common_attributes):
                        if left["controlled_attributes"][key] == right["controlled_attributes"][key]:
                            controlled_matches.append(key)
                        else:
                            conflicts.add(f"controlled_attribute_conflict:{key}")

                common_models = tuple(
                    sorted(
                        set(left["model_ids"]) & set(right["model_ids"]),
                        key=cls._numeric_sort_key,
                    )
                )
                common_categories = tuple(sorted(set(left["categories"]) & set(right["categories"])))
                title_similarity_bps = cls._jaccard_bps(left["title_tokens"], right["title_tokens"])
                pairs.append(
                    {
                        "left_ref": left["source_ref"],
                        "right_ref": right["source_ref"],
                        "anchors": anchors,
                        "conflicts": tuple(sorted(conflicts)),
                        "controlled_attribute_matches": tuple(controlled_matches),
                        "common_model_ids": common_models,
                        "common_categories": common_categories,
                        "title_similarity_bps": title_similarity_bps,
                    }
                )
        return pairs

    @classmethod
    def _components(
        cls,
        sources: Sequence[dict[str, Any]],
        pairs: Sequence[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        by_ref = {source["source_ref"]: source for source in sources}
        parent = {source_ref: source_ref for source_ref in by_ref}

        def find(source_ref: str) -> str:
            while parent[source_ref] != source_ref:
                parent[source_ref] = parent[parent[source_ref]]
                source_ref = parent[source_ref]
            return source_ref

        def union(left_ref: str, right_ref: str) -> None:
            left_root = find(left_ref)
            right_root = find(right_ref)
            if left_root == right_root:
                return
            first, second = sorted((left_root, right_root))
            parent[second] = first

        for pair in pairs:
            if pair["anchors"]:
                union(pair["left_ref"], pair["right_ref"])

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source_ref, source in by_ref.items():
            grouped[find(source_ref)].append(source)
        return sorted(
            (sorted(group, key=lambda source: source["source_ref"]) for group in grouped.values()),
            key=lambda group: tuple(source["source_ref"] for source in group),
        )

    @classmethod
    def _classify_components(
        cls,
        components: Sequence[Sequence[dict[str, Any]]],
        pairs: Sequence[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
        pair_index = {frozenset((pair["left_ref"], pair["right_ref"])): pair for pair in pairs}
        exact_resolutions: list[dict[str, Any]] = []
        quarantines: list[dict[str, Any]] = []
        source_status: dict[str, str] = {}
        for component in components:
            source_refs = tuple(source["source_ref"] for source in component)
            component_pairs = [
                pair_index[frozenset((left, right))]
                for position, left in enumerate(source_refs)
                for right in source_refs[position + 1 :]
            ]
            anchors = {
                field: sorted(
                    {value for pair in component_pairs for value in pair["anchors"].get(field, ())},
                    key=cls._numeric_sort_key if field == "platform_sku" else None,
                )
                for field in _EXACT_ANCHORS
            }
            conflicts = {reason for pair in component_pairs for reason in pair["conflicts"]}
            conflicts.update(
                reason
                for source in component
                for reason in source["validation_reasons"]
                if cls._quarantine_reason(reason)
            )
            if len(component) > 1:
                conflicts.update(cls._component_conflicts(component))
            has_exact_edge = any(pair["anchors"] for pair in component_pairs)
            if conflicts:
                for source_ref in source_refs:
                    source_status[source_ref] = "quarantined"
                core = {
                    "source_refs": list(source_refs),
                    "reason_codes": sorted(conflicts),
                    "matched_anchor_values": anchors,
                    "evidence_refs": sorted({ref for source in component for ref in source["evidence_refs"]}),
                    "sources": [
                        {
                            "source_ref": source["source_ref"],
                            "source_kind": source["source_kind"],
                            "platform_namespace": source["platform_namespace"],
                            "source_sha256": source["source_sha256"],
                            "original_identifiers": source["original_identifiers"],
                            "normalized_identifiers": cls._public_identifiers(source),
                        }
                        for source in component
                    ],
                    "automatic_merge_allowed": False,
                    "formal_fact_promoted": False,
                }
                quarantines.append(
                    {
                        "quarantine_id": f"viq_{cls._sha256(core)[:24]}",
                        **core,
                    }
                )
                continue
            if len(component) >= 2 and has_exact_edge:
                for source_ref in source_refs:
                    source_status[source_ref] = "accepted"
                identity = cls._component_identity(component)
                core = {
                    "status": "exact",
                    "source_refs": list(source_refs),
                    "source_kinds": sorted({source["source_kind"] for source in component}),
                    "platform_namespaces": sorted({source["platform_namespace"] for source in component}),
                    "matched_on": {field: values for field, values in anchors.items() if values},
                    "controlled_attribute_matches": sorted(
                        {key for pair in component_pairs for key in pair["controlled_attribute_matches"]}
                    ),
                    "identity": identity,
                    "evidence_refs": sorted({ref for source in component for ref in source["evidence_refs"]}),
                    "source_sha256s": {source["source_ref"]: source["source_sha256"] for source in component},
                    "model_id_used_as_exact_anchor": False,
                    "automatic_merge_allowed": False,
                    "formal_fact_promoted": False,
                }
                exact_resolutions.append(
                    {
                        "resolution_id": f"vir_{cls._sha256(core)[:24]}",
                        **core,
                    }
                )
                continue
            source = component[0]
            source_status[source["source_ref"]] = (
                "quarantined"
                if any(cls._quarantine_reason(reason) for reason in source["validation_reasons"])
                else "unresolved"
            )
            if source_status[source["source_ref"]] == "quarantined":
                core = {
                    "source_refs": [source["source_ref"]],
                    "reason_codes": sorted(source["validation_reasons"]),
                    "matched_anchor_values": {field: [] for field in _EXACT_ANCHORS},
                    "evidence_refs": list(source["evidence_refs"]),
                    "sources": [
                        {
                            "source_ref": source["source_ref"],
                            "source_kind": source["source_kind"],
                            "platform_namespace": source["platform_namespace"],
                            "source_sha256": source["source_sha256"],
                            "original_identifiers": source["original_identifiers"],
                            "normalized_identifiers": cls._public_identifiers(source),
                        }
                    ],
                    "automatic_merge_allowed": False,
                    "formal_fact_promoted": False,
                }
                quarantines.append(
                    {
                        "quarantine_id": f"viq_{cls._sha256(core)[:24]}",
                        **core,
                    }
                )
        exact_resolutions.sort(key=lambda item: (item["source_refs"], item["resolution_id"]))
        quarantines.sort(key=lambda item: (item["source_refs"], item["quarantine_id"]))
        return exact_resolutions, quarantines, source_status

    @classmethod
    def _component_conflicts(cls, component: Sequence[dict[str, Any]]) -> set[str]:
        conflicts: set[str] = set()
        offer_ids = {value for source in component for value in source["offer_ids"]}
        platform_skus = {value for source in component for value in cls._platform_skus(source)}
        model_ids = {value for source in component for value in source["model_ids"]}
        if len(offer_ids) > 1:
            conflicts.add("transitive_offer_id_conflict")
        if len(platform_skus) > 1:
            conflicts.add("transitive_platform_sku_conflict")
        if len(model_ids) > 1:
            conflicts.add("transitive_model_group_conflict")
        keys = sorted({key for source in component for key in source["controlled_attributes"]})
        for key in keys:
            observed = {
                source["controlled_attributes"][key] for source in component if key in source["controlled_attributes"]
            }
            if len(observed) > 1:
                conflicts.add(f"transitive_controlled_attribute_conflict:{key}")
        return conflicts

    @classmethod
    def _candidate_proposals(
        cls,
        sources: Sequence[dict[str, Any]],
        pairs: Sequence[dict[str, Any]],
        *,
        source_status: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        by_ref = {source["source_ref"]: source for source in sources}
        proposals: list[dict[str, Any]] = []
        for pair in pairs:
            if pair["anchors"] or pair["conflicts"]:
                continue
            left = by_ref[pair["left_ref"]]
            right = by_ref[pair["right_ref"]]
            if (
                source_status[left["source_ref"]] == "quarantined"
                or source_status[right["source_ref"]] == "quarantined"
            ):
                continue
            model_group_match = bool(pair["common_model_ids"])
            category_match = bool(pair["common_categories"])
            title_similarity_bps = pair["title_similarity_bps"]
            if not (
                model_group_match
                or (category_match and title_similarity_bps >= _TITLE_WITH_CATEGORY_THRESHOLD_BPS)
                or title_similarity_bps >= _TITLE_ONLY_THRESHOLD_BPS
            ):
                continue
            signals = []
            score_bps = min(title_similarity_bps * 35 // 100, 3_500)
            if model_group_match:
                score_bps += 5_000
                signals.append("model_group_match")
            if category_match:
                score_bps += 1_500
                signals.append("category_similarity")
            if title_similarity_bps:
                signals.append("title_similarity")
            score_bps = min(score_bps, 10_000)
            relationship = "model_group_sibling_candidate" if model_group_match else "descriptive_similarity_candidate"
            core = {
                "status": "candidate_proposal",
                "relationship": relationship,
                "source_refs": [left["source_ref"], right["source_ref"]],
                "signals": sorted(signals),
                "score_bps": score_bps,
                "model_group_ids": list(pair["common_model_ids"]),
                "common_categories": list(pair["common_categories"]),
                "title_similarity_bps": title_similarity_bps,
                "reason_codes": [
                    "controlled_exact_identifier_match_missing",
                    *(["model_id_is_group_not_variant"] if model_group_match else []),
                    "human_review_required",
                ],
                "evidence_refs": sorted({*left["evidence_refs"], *right["evidence_refs"]}),
                "exact_variant": False,
                "automatic_merge_allowed": False,
                "formal_fact_promoted": False,
            }
            proposals.append(
                {
                    "proposal_id": f"vic_{cls._sha256(core)[:24]}",
                    **core,
                }
            )
        return sorted(
            proposals,
            key=lambda proposal: (
                -proposal["score_bps"],
                proposal["source_refs"],
                proposal["proposal_id"],
            ),
        )

    @classmethod
    def _component_identity(cls, component: Sequence[dict[str, Any]]) -> dict[str, Any]:
        offer_ids = sorted({value for source in component for value in source["offer_ids"]})
        platform_skus = sorted(
            {value for source in component for value in cls._platform_skus(source)},
            key=cls._numeric_sort_key,
        )
        barcodes = sorted({value for source in component for value in source["barcodes"]})
        model_ids = sorted(
            {value for source in component for value in source["model_ids"]},
            key=cls._numeric_sort_key,
        )
        attributes: dict[str, list[str]] = {}
        for source in component:
            for key, values in source["controlled_attributes"].items():
                attributes[key] = list(values)
        return {
            "offer_id": offer_ids[0] if len(offer_ids) == 1 else None,
            "platform_sku": platform_skus[0] if len(platform_skus) == 1 else None,
            "barcodes": barcodes,
            "model_group_id": model_ids[0] if len(model_ids) == 1 else None,
            "controlled_attributes": dict(sorted(attributes.items())),
        }

    @classmethod
    def _attributes(
        cls,
        containers: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], set[str]]:
        controlled: dict[str, tuple[str, ...]] = {}
        descriptive: dict[str, tuple[str, ...]] = {}
        reasons: set[str] = set()

        def record_controlled(key: str, values: tuple[str, ...]) -> None:
            existing = controlled.get(key)
            if existing is not None and existing != values:
                reasons.add(f"source_controlled_attribute_conflict:{key}")
                return
            controlled[key] = values

        for container in containers:
            declared = container.get("controlled_attributes")
            if isinstance(declared, Mapping):
                for key, raw_values in declared.items():
                    values = cls._attribute_values(raw_values)
                    if values:
                        record_controlled(
                            f"declared:{cls._normalized_text(key)}",
                            values,
                        )
            attributes = container.get("attributes")
            if isinstance(attributes, Mapping):
                for key, raw_values in attributes.items():
                    values = cls._attribute_values(raw_values)
                    if not values:
                        continue
                    normalized_key = cls._normalized_text(key)
                    if cls._controlled_attribute_key(normalized_key):
                        record_controlled(f"attr:{normalized_key}", values)
                    else:
                        descriptive[normalized_key] = values
            elif isinstance(attributes, Sequence) and not isinstance(attributes, (str, bytes)):
                for position, attribute in enumerate(attributes):
                    if not isinstance(attribute, Mapping):
                        reasons.add("invalid_controlled_attribute_shape")
                        continue
                    attribute_id = attribute.get("id")
                    if attribute_id in (None, ""):
                        reasons.add("controlled_attribute_id_missing")
                        continue
                    complex_id = attribute.get("complex_id", 0)
                    key = f"ozon:{attribute_id}:{complex_id}"
                    raw_values = attribute.get("values", [])
                    values = []
                    if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
                        for raw_value in raw_values:
                            if isinstance(raw_value, Mapping):
                                dictionary_id = raw_value.get("dictionary_value_id")
                                if dictionary_id not in (None, "", 0, "0"):
                                    values.append(f"dict:{dictionary_id}")
                                elif raw_value.get("value") not in (None, ""):
                                    values.append(f"text:{cls._normalized_text(raw_value.get('value'))}")
                            elif raw_value not in (None, ""):
                                values.append(f"text:{cls._normalized_text(raw_value)}")
                    normalized_values = tuple(sorted(set(values)))
                    if normalized_values:
                        record_controlled(key, normalized_values)
                    elif raw_values:
                        reasons.add(f"controlled_attribute_values_invalid:{position}")
        return dict(sorted(controlled.items())), dict(sorted(descriptive.items())), reasons

    @classmethod
    def _original_identifiers(
        cls,
        containers: Sequence[Mapping[str, Any]],
        payload: Mapping[str, Any],
        source_kind: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in (
            "offer_id",
            "offer_ids",
            "ozon_offer_id",
            "ozon_offer_ids",
            "sku",
            "ozon_sku",
            "ozon_skus",
            "source_sku",
            "source_skus",
            "finance_item_sku",
            "finance_item_skus",
            "barcode",
            "barcodes",
            "model_id",
            "model_ids",
            "model_info",
            "platform_namespace",
            "marketplace",
            "platform",
            "channel",
        ):
            values = [container[field] for container in containers if field in container]
            if values:
                result[field] = cls._json_safe(values[0] if len(values) == 1 else values)
        if payload.get("sources") is not None:
            result["sources"] = cls._json_safe(payload.get("sources"))
        if "finance" in source_kind and payload.get("items") is not None:
            result["finance_items"] = cls._json_safe(payload.get("items"))
        return dict(sorted(result.items()))

    @classmethod
    def _public_identifiers(cls, source: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "offer_ids": list(source["offer_ids"]),
            "ozon_skus": list(source["ozon_skus"]),
            "source_skus": list(source["source_skus"]),
            "finance_item_skus": list(source["finance_item_skus"]),
            "barcodes": list(source["barcodes"]),
            "model_ids": list(source["model_ids"]),
            "controlled_attributes": {key: list(values) for key, values in source["controlled_attributes"].items()},
            "categories": list(source["categories"]),
            "title": source["title"],
        }

    @classmethod
    def _source_projection(cls, source: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_ref": source["source_ref"],
            "source_kind": source["source_kind"],
            "platform_namespace": source["platform_namespace"],
            "scope": source["scope"],
            "evidence_refs": list(source["evidence_refs"]),
            "identifiers": cls._public_identifiers(source),
            "descriptive_attributes": {key: list(values) for key, values in source["descriptive_attributes"].items()},
            "original_identifiers": source["original_identifiers"],
            "validation_reasons": list(source["validation_reasons"]),
        }

    @staticmethod
    def _quarantine_reason(reason: str) -> bool:
        return "ambiguous" in reason or "conflict" in reason or reason == "invalid_controlled_attribute_shape"

    @staticmethod
    def _platform_skus(source: Mapping[str, Any]) -> set[str]:
        return {
            *source["ozon_skus"],
            *source["source_skus"],
            *source["finance_item_skus"],
        }

    @classmethod
    def _scope(cls, value: Mapping[str, Any], field: str) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")
        entity_ref = value.get("entity_ref")
        legal_entity_ref = value.get("legal_entity_ref")
        if (
            entity_ref not in (None, "")
            and legal_entity_ref not in (None, "")
            and str(entity_ref).strip() != str(legal_entity_ref).strip()
        ):
            raise ValueError(f"{field} has conflicting entity_ref and legal_entity_ref")
        return {
            "tenant_ref": cls._required(value.get("tenant_ref"), f"{field}.tenant_ref", 160),
            "entity_ref": cls._required(
                entity_ref or legal_entity_ref,
                f"{field}.legal_entity_ref",
                160,
            ),
            "store_ref": cls._required(value.get("store_ref"), f"{field}.store_ref", 160),
        }

    @staticmethod
    def _identity_containers(
        value: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        containers: list[Mapping[str, Any]] = []
        for candidate in (
            value,
            value.get("identifiers"),
            payload,
            payload.get("identifiers"),
            payload.get("product_identity"),
        ):
            if isinstance(candidate, Mapping) and not any(candidate is item for item in containers):
                containers.append(candidate)
        return containers

    @staticmethod
    def _collect(
        containers: Sequence[Mapping[str, Any]],
        *keys: str,
    ) -> list[Any]:
        values: list[Any] = []
        for container in containers:
            for key in keys:
                value = container.get(key)
                if value in (None, ""):
                    continue
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    values.extend(value)
                else:
                    values.append(value)
        return values

    @classmethod
    def _texts(cls, values: Sequence[Any], *, upper: bool) -> list[str]:
        normalized = []
        for value in values:
            if isinstance(value, (bool, Mapping)):
                continue
            text = unicodedata.normalize("NFKC", str(value)).strip()
            if text:
                normalized.append(text.upper() if upper else text)
        return sorted(set(normalized))

    @classmethod
    def _numeric_identifiers(cls, values: Sequence[Any]) -> tuple[list[str], list[str]]:
        valid: set[str] = set()
        invalid: set[str] = set()
        for value in values:
            if value in (None, ""):
                continue
            if isinstance(value, (bool, Mapping)):
                invalid.add(str(value))
                continue
            text = unicodedata.normalize("NFKC", str(value)).strip()
            if re.fullmatch(r"[0-9]+", text) and int(text) > 0:
                valid.add(str(int(text)))
            else:
                invalid.add(text)
        return sorted(valid, key=cls._numeric_sort_key), sorted(invalid)

    @classmethod
    def _evidence_refs(
        cls,
        value: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> list[str]:
        raw = []
        for container in (value, payload):
            raw.extend(
                cls._collect(
                    [container],
                    "evidence_ref",
                    "evidence_refs",
                    "evidence_id",
                    "evidence_ids",
                    "artifact_evidence_id",
                )
            )
        return cls._texts(raw, upper=False)

    @classmethod
    def _categories(cls, containers: Sequence[Mapping[str, Any]]) -> list[str]:
        categories = set()
        for container in containers:
            for field in ("category_id", "description_category_id", "type_id", "category"):
                value = container.get(field)
                if value in (None, "") or isinstance(value, Mapping):
                    continue
                categories.add(f"{field}:{cls._normalized_text(value)}")
            category_identity = container.get("category_identity")
            if isinstance(category_identity, Mapping):
                for field, value in category_identity.items():
                    if value not in (None, "") and not isinstance(
                        value,
                        (Mapping, list, tuple, set),
                    ):
                        categories.add(f"category_identity.{field}:{cls._normalized_text(value)}")
        return sorted(categories)

    @classmethod
    def _first_text(cls, containers: Sequence[Mapping[str, Any]], *keys: str) -> str:
        for container in containers:
            for key in keys:
                if container.get(key) not in (None, ""):
                    return unicodedata.normalize("NFKC", str(container[key])).strip()
        return ""

    @classmethod
    def _attribute_values(cls, value: Any) -> tuple[str, ...]:
        raw_values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
        return tuple(
            sorted(
                {
                    cls._normalized_text(item)
                    for item in raw_values
                    if item not in (None, "") and not isinstance(item, Mapping)
                }
            )
        )

    @staticmethod
    def _controlled_attribute_key(value: str) -> bool:
        return value.isdigit() or value.startswith(_CONTROLLED_ATTRIBUTE_PREFIXES)

    @staticmethod
    def _normalized_text(value: Any) -> str:
        return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())

    @classmethod
    def _title_tokens(cls, value: str) -> list[str]:
        return sorted(
            {token for token in re.findall(r"[^\W_]+", cls._normalized_text(value), flags=re.UNICODE) if len(token) > 1}
        )

    @staticmethod
    def _jaccard_bps(left: Sequence[str], right: Sequence[str]) -> int:
        left_set = set(left)
        right_set = set(right)
        if not left_set or not right_set:
            return 0
        return len(left_set & right_set) * 10_000 // len(left_set | right_set)

    @staticmethod
    def _required(value: Any, field: str, maximum: int) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} is required")
        if len(normalized) > maximum:
            raise ValueError(f"{field} exceeds {maximum} characters")
        return normalized

    @classmethod
    def _assert_expected_hash(cls, expected: str | None, actual: str) -> None:
        if expected is None:
            return
        normalized = str(expected).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("expected_input_sha256 must be a lowercase SHA-256 value")
        if normalized != actual:
            raise VariantIdentityConflict("Variant identity replay content drift conflicts with expected_input_sha256")

    @classmethod
    def _sha256(cls, value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                cls._json_safe(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Identity content contains a non-finite decimal")
            return format(value, "f")
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Identity content contains a non-finite float")
            return repr(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Mapping):
            return {
                str(key): cls._json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, set | frozenset):
            return sorted((cls._json_safe(item) for item in value), key=lambda item: str(item))
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [cls._json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _numeric_sort_key(value: str) -> tuple[int, str]:
        return (int(value), value) if value.isdigit() else (2**63 - 1, value)
