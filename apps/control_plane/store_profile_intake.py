from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from .security import Principal

CONTRACT_ID = "kjds-evidence-backed-store-profile-proposal-v1"
POLICY_KERNEL_ID = "kjds-store-profile-intake-kernel-v1"
SUPPORTED_EVIDENCE_TYPES = frozenset({"catalog", "listing", "order", "profit", "category"})
DATA_GRADE_ORDER = ("A", "B", "C", "D", "E")
QUALITY_ORDER = ("missing", "ambiguous", "probable", "high", "exact", "not_applicable")
SELLER_TIER_ALIASES = {
    "beginner": "novice",
    "novice": "novice",
    "individual": "solo",
    "solo": "solo",
    "small_team": "small_team",
    "mid_market": "mid_market",
    "enterprise": "enterprise",
}
SCALAR_ATTRIBUTE_FIELDS = frozenset({"store_positioning", "assortment_mode", "price_band"})
LIST_ATTRIBUTE_FIELDS = frozenset(
    {
        "target_regions",
        "fulfillment_models",
        "planned_growth_channels",
        "customer_segments",
        "operational_capabilities",
    }
)
ATTRIBUTE_FIELDS = SCALAR_ATTRIBUTE_FIELDS | LIST_ATTRIBUTE_FIELDS

_GRADE_WEIGHT = {
    "A": Decimal("1.00"),
    "B": Decimal("0.85"),
    "C": Decimal("0.65"),
    "D": Decimal("0.40"),
    "E": Decimal("0.20"),
}
_QUALITY_WEIGHT = {
    "missing": Decimal("0.00"),
    "ambiguous": Decimal("0.25"),
    "probable": Decimal("0.60"),
    "high": Decimal("0.85"),
    "exact": Decimal("1.00"),
    "not_applicable": Decimal("1.00"),
}
_QUALITY_ALIASES = {
    "none": "missing",
    "unknown": "missing",
    "low": "ambiguous",
    "medium": "probable",
    "matched": "high",
    "verified": "exact",
    "n/a": "not_applicable",
    "na": "not_applicable",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _instant(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return _utc(value, field)
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    return _utc(parsed, field)


def _required(value: Any, field: str, maximum: int = 300) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return parsed


def _decimal_text(value: Decimal, places: str = "0.0000") -> str:
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze(item) for item in value), key=str))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class StoreProfileProposal(Mapping[str, Any]):
    """Deeply immutable projection returned by the intake module."""

    _payload: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    @property
    def proposal_id(self) -> str:
        return str(self._payload["proposal_id"])

    @property
    def proposal_sha256(self) -> str:
        return str(self._payload["proposal_sha256"])

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._payload)

    def is_expired(self, as_of: datetime) -> bool:
        cutoff = _utc(as_of, "as_of")
        expires_at = _instant(self._payload["time_window"]["expires_at"], "expires_at")
        return cutoff >= expires_at

    def status_at(self, as_of: datetime) -> str:
        return "expired" if self.is_expired(as_of) else str(self._payload["status"])


class StoreProfileIntake:
    """Turns scoped observations into a review-only store profile proposal."""

    def __init__(self, *, default_ttl: timedelta = timedelta(hours=24)) -> None:
        if default_ttl <= timedelta(0):
            raise ValueError("default_ttl must be positive")
        self.default_ttl = default_ttl

    def propose(
        self,
        observations: Sequence[Mapping[str, Any]],
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        seller_tier: str,
        as_of: datetime,
        destination_profiles: Sequence[Mapping[str, Any]] = (),
        expires_at: datetime | None = None,
    ) -> StoreProfileProposal:
        cutoff = _utc(as_of, "as_of")
        scope = self._scope(principal, entity_scope, store_ref)
        tier_input, tier = self._seller_tier(seller_tier)
        requested_expiry = _utc(expires_at, "expires_at") if expires_at is not None else cutoff + self.default_ttl
        if requested_expiry <= cutoff:
            raise ValueError("expires_at must be after as_of")
        if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
            raise ValueError("observations must be a sequence")

        active, stale = self._observations(observations, scope=scope, as_of=cutoff)
        destinations = self._destinations(
            destination_profiles,
            principal=principal,
            source_scope=scope,
        )
        evidence_expiries = [signal["valid_until"] for signal in active if signal["valid_until"] is not None]
        proposal_expiry = min([requested_expiry, *evidence_expiries])

        contradictions: list[dict[str, Any]] = []
        attributes, profile, attribute_conflicts = self._attributes(active)
        contradictions.extend(attribute_conflicts)
        categories, category_conflicts = self._categories(active)
        contradictions.extend(category_conflicts)
        contradictions = self._unique_contradictions(contradictions)
        recommendations = self._recommendations(
            categories,
            destinations=destinations,
            scope=scope,
            contradictions=contradictions,
        )

        evidence_refs = sorted(
            {evidence_ref for signal in [*active, *stale] for evidence_ref in signal["evidence_refs"]}
        )
        active_evidence_refs = sorted({evidence_ref for signal in active for evidence_ref in signal["evidence_refs"]})
        evidence_types = sorted({signal["evidence_type"] for signal in active})
        data_grade = self._aggregate_grade(active, evidence_types)
        confidence = self._aggregate_confidence(active)
        identity_quality = self._aggregate_quality(active, "identity_quality")
        variant_quality = self._aggregate_quality(active, "variant_quality")
        status = (
            "no_data"
            if not active
            else "needs_review"
            if any(item["blocking"] for item in contradictions)
            else "ready_for_review"
        )
        reason_codes = []
        if not active:
            reason_codes.append("store_evidence_missing" if not stale else "store_evidence_expired")
        if contradictions:
            reason_codes.append("contradictory_evidence_requires_review")
        if set(evidence_types) != SUPPORTED_EVIDENCE_TYPES:
            reason_codes.append("evidence_type_coverage_incomplete")

        reviewer_gates = self._reviewer_gates(
            status=status,
            tier=tier,
            data_grade=data_grade,
            identity_quality=identity_quality,
            variant_quality=variant_quality,
            contradictions=contradictions,
            categories=categories,
            recommendations=recommendations,
        )
        observed_times = [signal["observed_at"] for signal in active]
        time_window = {
            "observed_from": min(observed_times).isoformat() if observed_times else None,
            "observed_through": max(observed_times).isoformat() if observed_times else None,
            "as_of": cutoff.isoformat(),
            "expires_at": proposal_expiry.isoformat(),
        }
        evidence_projection = [self._signal_projection(signal) for signal in active]
        stale_projection = [self._signal_projection(signal) for signal in stale]
        core = {
            "contract_id": CONTRACT_ID,
            "policy_kernel_id": POLICY_KERNEL_ID,
            "status": status,
            "truth_status": "proposal_only",
            "scope": scope,
            "seller_tier": tier,
            "seller_tier_input": tier_input,
            "time_window": time_window,
            "quality": {
                "confidence": confidence,
                "data_grade": data_grade,
                "identity_quality": identity_quality,
                "variant_quality": variant_quality,
                "evidence_type_coverage": evidence_types,
                "required_evidence_types": sorted(SUPPORTED_EVIDENCE_TYPES),
            },
            "evidence_refs": evidence_refs,
            "active_evidence_refs": active_evidence_refs,
            "evidence_observations": evidence_projection,
            "stale_evidence_observations": stale_projection,
            "store_attributes": attributes,
            "proposed_profile": profile,
            "category_role_assignments": categories,
            "placement_recommendations": recommendations,
            "contradictions": contradictions,
            "reviewer_gates": reviewer_gates,
            "reason_codes": sorted(set(reason_codes)),
            "control_envelope": {
                "proposal_only": True,
                "formal_fact": False,
                "formal_fact_promoted": False,
                "automatic_publish_allowed": False,
                "automatic_cross_store_publish": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
                "same_business_kernel_for_all_seller_tiers": True,
                "seller_tier_applies_to_review_envelope_only": True,
            },
        }
        proposal_sha256 = _sha256(core)
        payload = {
            **core,
            "proposal_id": f"spi_{proposal_sha256[:32]}",
            "proposal_sha256": proposal_sha256,
        }
        return StoreProfileProposal(_freeze(payload))

    @staticmethod
    def _scope(
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
    ) -> dict[str, str]:
        store = _required(store_ref, "store_ref", 160)
        if not principal.can_access_store(store):
            raise PermissionError("Store is outside the authenticated scope")
        if entity_scope.get("status") != "ready":
            raise PermissionError("Entity scope authority is not ready")
        entity = _required(entity_scope.get("entity_ref"), "entity_ref", 160)
        authority = _required(
            entity_scope.get("authority_sha256"),
            "scope_grant_authority_sha256",
            64,
        ).lower()
        if len(authority) != 64 or any(character not in "0123456789abcdef" for character in authority):
            raise PermissionError("Scope grant authority hash is invalid")
        return {
            "tenant_ref": _required(principal.tenant_ref, "tenant_ref", 160),
            "entity_ref": entity,
            "store_ref": store,
            "scope_grant_authority_sha256": authority,
        }

    @staticmethod
    def _seller_tier(value: str) -> tuple[str, str]:
        tier_input = _required(value, "seller_tier", 40).lower()
        try:
            return tier_input, SELLER_TIER_ALIASES[tier_input]
        except KeyError as exc:
            raise ValueError(
                "seller_tier must be beginner/novice, individual/solo, small_team, mid_market, or enterprise"
            ) from exc

    def _observations(
        self,
        values: Sequence[Mapping[str, Any]],
        *,
        scope: Mapping[str, str],
        as_of: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        active: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        for position, value in enumerate(values):
            signal = self._observation(value, scope=scope, position=position)
            if signal["observed_at"] > as_of:
                raise ValueError(f"observations[{position}].observed_at cannot be in the future")
            target = stale if signal["valid_until"] is not None and signal["valid_until"] <= as_of else active
            target.append(signal)

        def key(signal: Mapping[str, Any]) -> tuple[Any, ...]:
            return (
                signal["observed_at"],
                signal["evidence_type"],
                signal["evidence_refs"],
                _sha256(self._signal_projection(signal)),
            )

        return sorted(active, key=key), sorted(stale, key=key)

    def _observation(
        self,
        value: Mapping[str, Any],
        *,
        scope: Mapping[str, str],
        position: int,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"observations[{position}] must be an object")
        prefix = f"observations[{position}]"
        evidence_type = _required(value.get("evidence_type"), f"{prefix}.evidence_type", 40).lower()
        if evidence_type not in SUPPORTED_EVIDENCE_TYPES:
            raise ValueError(f"{prefix}.evidence_type is unsupported")
        evidence_refs = self._evidence_refs(value, prefix)
        observed_at = _instant(value.get("observed_at"), f"{prefix}.observed_at")
        valid_until = (
            _instant(value["valid_until"], f"{prefix}.valid_until") if value.get("valid_until") is not None else None
        )
        if valid_until is not None and valid_until <= observed_at:
            raise ValueError(f"{prefix}.valid_until must be after observed_at")
        data_grade = _required(value.get("data_grade"), f"{prefix}.data_grade", 1).upper()
        if data_grade not in DATA_GRADE_ORDER:
            raise ValueError(f"{prefix}.data_grade must be A, B, C, D, or E")
        confidence = _decimal(value.get("confidence"), f"{prefix}.confidence")
        if confidence < 0 or confidence > 1:
            raise ValueError(f"{prefix}.confidence must be between 0 and 1")
        signal_scope = value.get("scope")
        if not isinstance(signal_scope, Mapping):
            raise ValueError(f"{prefix}.scope is required")
        observed_scope = (
            _required(signal_scope.get("tenant_ref"), f"{prefix}.scope.tenant_ref", 160),
            _required(signal_scope.get("entity_ref"), f"{prefix}.scope.entity_ref", 160),
            _required(signal_scope.get("store_ref"), f"{prefix}.scope.store_ref", 160),
        )
        expected_scope = (scope["tenant_ref"], scope["entity_ref"], scope["store_ref"])
        if observed_scope != expected_scope:
            raise PermissionError("Observation scope does not match the authorized store scope")
        attributes = value.get("attributes", value.get("store_attributes", {}))
        normalized_attributes = self._normalize_attributes(attributes, prefix)
        category = self._normalize_category(value["category"], prefix) if value.get("category") is not None else None
        return {
            "evidence_type": evidence_type,
            "evidence_refs": tuple(evidence_refs),
            "observed_at": observed_at,
            "valid_until": valid_until,
            "data_grade": data_grade,
            "confidence": confidence,
            "identity_quality": self._quality(value.get("identity_quality"), f"{prefix}.identity_quality"),
            "variant_quality": self._quality(value.get("variant_quality"), f"{prefix}.variant_quality"),
            "attributes": normalized_attributes,
            "category": category,
            "metrics": self._normalize_metrics(value.get("metrics", {}), prefix),
        }

    @staticmethod
    def _evidence_refs(value: Mapping[str, Any], prefix: str) -> list[str]:
        raw = value.get("evidence_refs")
        if raw is None:
            raw = [value.get("evidence_ref")]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError(f"{prefix}.evidence_refs must be a sequence")
        refs = sorted({_required(item, f"{prefix}.evidence_ref", 240) for item in raw})
        if not refs:
            raise ValueError(f"{prefix}.evidence_refs requires at least one reference")
        return refs

    @staticmethod
    def _quality(value: Any, field: str) -> str:
        quality = _required(value, field, 40).lower()
        quality = _QUALITY_ALIASES.get(quality, quality)
        if quality not in QUALITY_ORDER:
            raise ValueError(f"{field} must be missing, ambiguous, probable, high, exact, or not_applicable")
        return quality

    @staticmethod
    def _normalize_attributes(value: Any, prefix: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError(f"{prefix}.attributes must be an object")
        unknown = sorted(set(value) - ATTRIBUTE_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported store attribute fields: {', '.join(unknown)}")
        result: dict[str, Any] = {}
        for field, raw in value.items():
            if field in SCALAR_ATTRIBUTE_FIELDS:
                result[field] = _required(raw, f"{prefix}.attributes.{field}")
                continue
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise ValueError(f"{prefix}.attributes.{field} must be a sequence")
            result[field] = tuple(sorted({_required(item, f"{prefix}.attributes.{field}") for item in raw}))
        return result

    def _normalize_category(self, value: Any, prefix: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{prefix}.category must be an object")
        category_id = _required(
            value.get("category_id") or value.get("leaf_category_id") or value.get("source_category_id"),
            f"{prefix}.category.category_id",
            160,
        )
        category_name = str(value.get("category_name") or value.get("name") or category_id).strip()
        is_derived = bool(value.get("is_derived")) or str(value.get("kind") or "").lower() == "derived"
        ancestry = self._ancestry(value.get("ancestry", ()), prefix)
        if any(item["category_id"] == category_id for item in ancestry):
            raise ValueError(f"{prefix}.category.ancestry must contain ancestors only")
        official_ancestor = value.get("official_ancestor_category_id") or value.get("derived_from_category_id")
        role_hint = value.get("role_hint")
        if role_hint is not None:
            role_hint = _required(role_hint, f"{prefix}.category.role_hint", 40).lower()
            if role_hint not in {"primary", "secondary", "tertiary", "derived"}:
                raise ValueError(f"{prefix}.category.role_hint is unsupported")
        return {
            "category_id": category_id,
            "category_name": _required(category_name, f"{prefix}.category.category_name"),
            "is_derived": is_derived,
            "ancestry": ancestry,
            "official_ancestor_category_id": (
                _required(official_ancestor, f"{prefix}.category.official_ancestor_category_id", 160)
                if official_ancestor is not None
                else None
            ),
            "role_hint": role_hint,
        }

    @staticmethod
    def _ancestry(value: Any, prefix: str) -> tuple[dict[str, str], ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError(f"{prefix}.category.ancestry must be a sequence")
        result = []
        seen = set()
        for position, item in enumerate(value):
            if isinstance(item, Mapping):
                category_id = _required(
                    item.get("category_id") or item.get("id"),
                    f"{prefix}.category.ancestry[{position}].category_id",
                    160,
                )
                name = _required(
                    item.get("category_name") or item.get("name") or category_id,
                    f"{prefix}.category.ancestry[{position}].category_name",
                )
            else:
                category_id = _required(item, f"{prefix}.category.ancestry[{position}]", 160)
                name = category_id
            if category_id in seen:
                raise ValueError(f"{prefix}.category.ancestry contains a duplicate category")
            seen.add(category_id)
            result.append({"category_id": category_id, "category_name": name})
        return tuple(result)

    @staticmethod
    def _normalize_metrics(value: Any, prefix: str) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError(f"{prefix}.metrics must be an object")
        result = {}
        for field, raw in value.items():
            metric = _decimal(raw, f"{prefix}.metrics.{field}")
            result[_required(field, f"{prefix}.metrics field", 80)] = format(metric, "f")
        return dict(sorted(result.items()))

    def _destinations(
        self,
        values: Sequence[Mapping[str, Any]],
        *,
        principal: Principal,
        source_scope: Mapping[str, str],
    ) -> list[dict[str, Any]]:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError("destination_profiles must be a sequence")
        result = []
        seen = set()
        for position, value in enumerate(values):
            if not isinstance(value, Mapping):
                raise ValueError(f"destination_profiles[{position}] must be an object")
            scope = value.get("scope")
            if not isinstance(scope, Mapping):
                raise ValueError(f"destination_profiles[{position}].scope is required")
            tenant = _required(scope.get("tenant_ref"), "destination tenant_ref", 160)
            entity = _required(scope.get("entity_ref"), "destination entity_ref", 160)
            store = _required(scope.get("store_ref"), "destination store_ref", 160)
            if tenant != source_scope["tenant_ref"] or entity != source_scope["entity_ref"]:
                raise PermissionError("Destination profile is outside the authorized tenant/entity scope")
            if not principal.can_access_store(store):
                raise PermissionError("Destination store is outside the authenticated scope")
            if store in seen:
                raise ValueError("destination_profiles contains a duplicate store_ref")
            seen.add(store)
            refs = self._evidence_refs(value, f"destination_profiles[{position}]")
            paths = value.get("category_paths", value.get("categories", ()))
            if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
                raise ValueError(f"destination_profiles[{position}].category_paths must be a sequence")
            categories = [
                self._destination_category(path, prefix=f"destination_profiles[{position}].category_paths[{index}]")
                for index, path in enumerate(paths)
            ]
            result.append(
                {
                    "store_ref": store,
                    "status": str(value.get("status") or "ready"),
                    "evidence_refs": refs,
                    "categories": sorted(categories, key=lambda item: (item["category_id"], item["role"])),
                }
            )
        return sorted(result, key=lambda item: item["store_ref"])

    def _destination_category(self, value: Any, *, prefix: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{prefix} must be an object")
        category_id = value.get("category_id") or value.get("leaf_category_id")
        if category_id is None:
            for level in ("level_3", "level_2", "level_1"):
                item = value.get(level)
                if isinstance(item, Mapping) and item.get("id"):
                    category_id = item["id"]
                    break
        role = str(value.get("role") or "tertiary").lower()
        role = {
            "core": "primary",
            "adjacent": "secondary",
            "experimental": "tertiary",
        }.get(role, role)
        if role not in {"primary", "secondary", "tertiary", "excluded"}:
            raise ValueError(f"{prefix}.role is unsupported")
        ancestry = list(self._ancestry(value.get("ancestry", ()), prefix))
        for level in ("level_1", "level_2", "level_3"):
            item = value.get(level)
            if isinstance(item, Mapping) and item.get("id") and item.get("id") != category_id:
                normalized = {
                    "category_id": _required(item.get("id"), f"{prefix}.{level}.id", 160),
                    "category_name": _required(item.get("name") or item.get("id"), f"{prefix}.{level}.name"),
                }
                if normalized["category_id"] not in {ancestor["category_id"] for ancestor in ancestry}:
                    ancestry.append(normalized)
        return {
            "category_id": _required(category_id, f"{prefix}.category_id", 160),
            "role": role,
            "ancestry": tuple(ancestry),
        }

    @classmethod
    def _signal_weight(cls, signal: Mapping[str, Any]) -> Decimal:
        return (
            _GRADE_WEIGHT[signal["data_grade"]]
            * signal["confidence"]
            * _QUALITY_WEIGHT[signal["identity_quality"]]
            * _QUALITY_WEIGHT[signal["variant_quality"]]
        )

    @classmethod
    def _attributes(
        cls, signals: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        assignments = []
        profile: dict[str, Any] = {}
        contradictions = []
        for field in sorted(ATTRIBUTE_FIELDS):
            supporting = [signal for signal in signals if field in signal["attributes"]]
            if not supporting:
                continue
            if field in LIST_ATTRIBUTE_FIELDS:
                values = sorted({item for signal in supporting for item in signal["attributes"][field]})
                refs = sorted({evidence_ref for signal in supporting for evidence_ref in signal["evidence_refs"]})
                assignment = cls._assignment_quality(field, values, supporting, refs)
                assignments.append(assignment)
                profile[field] = values
                continue
            alternatives: dict[str, dict[str, Any]] = {}
            for signal in supporting:
                value = signal["attributes"][field]
                item = alternatives.setdefault(value, {"score": Decimal("0"), "evidence_refs": set()})
                item["score"] += cls._signal_weight(signal)
                item["evidence_refs"].update(signal["evidence_refs"])
            ranked = sorted(alternatives.items(), key=lambda item: (-item[1]["score"], item[0]))
            refs = sorted({evidence_ref for signal in supporting for evidence_ref in signal["evidence_refs"]})
            if len(ranked) > 1:
                contradictions.append(
                    {
                        "code": "attribute_signal_conflict",
                        "field": field,
                        "values": [item[0] for item in ranked],
                        "evidence_refs": refs,
                        "blocking": True,
                    }
                )
                assignment = cls._assignment_quality(field, None, supporting, refs)
                assignment["alternatives"] = [
                    {
                        "value": value,
                        "support_score": _decimal_text(details["score"]),
                        "evidence_refs": sorted(details["evidence_refs"]),
                    }
                    for value, details in ranked
                ]
                assignments.append(assignment)
                continue
            value = ranked[0][0]
            assignments.append(cls._assignment_quality(field, value, supporting, refs))
            profile[field] = value
        return assignments, profile, contradictions

    @classmethod
    def _assignment_quality(
        cls,
        field: str,
        value: Any,
        signals: Sequence[Mapping[str, Any]],
        refs: list[str],
    ) -> dict[str, Any]:
        total_weight = sum((cls._signal_weight(signal) for signal in signals), Decimal("0"))
        return {
            "field": field,
            "value": value,
            "confidence": cls._weighted_confidence(signals),
            "data_grade": cls._worst_grade(signals),
            "support_score": _decimal_text(total_weight),
            "evidence_refs": refs,
        }

    @classmethod
    def _categories(cls, signals: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for signal in signals:
            category = signal["category"]
            if category is not None:
                grouped.setdefault(category["category_id"], []).append(signal)
        contradictions = []
        candidates = []
        for category_id, supporting in sorted(grouped.items()):
            categories = [signal["category"] for signal in supporting]
            names = sorted({category["category_name"] for category in categories})
            kinds = sorted({category["is_derived"] for category in categories})
            ancestry_keys = {tuple(item["category_id"] for item in category["ancestry"]) for category in categories}
            ancestor_ids = sorted(
                {
                    category["official_ancestor_category_id"]
                    for category in categories
                    if category["official_ancestor_category_id"]
                }
            )
            refs = sorted({evidence_ref for signal in supporting for evidence_ref in signal["evidence_refs"]})
            if len(names) > 1 or len(kinds) > 1 or len(ancestry_keys) > 1 or len(ancestor_ids) > 1:
                contradictions.append(
                    {
                        "code": "category_identity_conflict",
                        "field": category_id,
                        "values": names,
                        "evidence_refs": refs,
                        "blocking": True,
                    }
                )
                continue
            role_hints = sorted({category["role_hint"] for category in categories if category["role_hint"]})
            if len(role_hints) > 1:
                contradictions.append(
                    {
                        "code": "category_role_signal_conflict",
                        "field": category_id,
                        "values": role_hints,
                        "evidence_refs": refs,
                        "blocking": True,
                    }
                )
            score = sum((cls._category_signal_score(signal) for signal in supporting), Decimal("0"))
            category = categories[0]
            candidates.append(
                {
                    "category_id": category_id,
                    "category_name": category["category_name"],
                    "is_derived": category["is_derived"],
                    "ancestry": list(category["ancestry"]),
                    "official_ancestor_category_id": ancestor_ids[0] if ancestor_ids else None,
                    "role_hints": role_hints,
                    "score": score,
                    "confidence": cls._weighted_confidence(supporting),
                    "data_grade": cls._worst_grade(supporting),
                    "identity_quality": cls._aggregate_quality(supporting, "identity_quality"),
                    "variant_quality": cls._aggregate_quality(supporting, "variant_quality"),
                    "evidence_refs": refs,
                    "basis_evidence_types": sorted({signal["evidence_type"] for signal in supporting}),
                }
            )

        official = sorted(
            (candidate for candidate in candidates if not candidate["is_derived"]),
            key=lambda item: (-item["score"], item["category_id"]),
        )
        official_ids = {item["category_id"] for item in official} | {
            ancestor["category_id"] for item in official for ancestor in item["ancestry"]
        }
        assignments = []
        for position, candidate in enumerate(official):
            assignments.append(
                cls._category_projection(
                    candidate,
                    role="primary" if position == 0 else "secondary" if position == 1 else "tertiary",
                )
            )
        for candidate in sorted(
            (candidate for candidate in candidates if candidate["is_derived"]),
            key=lambda item: (-item["score"], item["category_id"]),
        ):
            ancestry_ids = [item["category_id"] for item in candidate["ancestry"]]
            ancestor = candidate["official_ancestor_category_id"]
            if ancestor is None:
                ancestor = next(
                    (item for item in reversed(ancestry_ids) if item in official_ids),
                    None,
                )
            if ancestor is None or ancestor not in official_ids or ancestor not in ancestry_ids:
                contradictions.append(
                    {
                        "code": "derived_category_ancestry_missing",
                        "field": candidate["category_id"],
                        "values": ancestry_ids,
                        "evidence_refs": candidate["evidence_refs"],
                        "blocking": True,
                    }
                )
                continue
            candidate["official_ancestor_category_id"] = ancestor
            assignments.append(cls._category_projection(candidate, role="derived"))
        return assignments, contradictions

    @classmethod
    def _category_projection(cls, candidate: Mapping[str, Any], *, role: str) -> dict[str, Any]:
        return {
            "category_id": candidate["category_id"],
            "category_name": candidate["category_name"],
            "role": role,
            "official_ancestor_category_id": candidate["official_ancestor_category_id"],
            "ancestry": candidate["ancestry"],
            "confidence": candidate["confidence"],
            "data_grade": candidate["data_grade"],
            "identity_quality": candidate["identity_quality"],
            "variant_quality": candidate["variant_quality"],
            "support_score": _decimal_text(candidate["score"]),
            "basis_evidence_types": candidate["basis_evidence_types"],
            "evidence_refs": candidate["evidence_refs"],
            "derived_category_is_official_taxonomy": False if role == "derived" else None,
        }

    @classmethod
    def _category_signal_score(cls, signal: Mapping[str, Any]) -> Decimal:
        score = cls._signal_weight(signal)
        metrics = {key: Decimal(value) for key, value in signal["metrics"].items()}
        order_count = max(Decimal("0"), metrics.get("order_count", Decimal("0")))
        listing_count = max(Decimal("0"), metrics.get("listing_count", Decimal("0")))
        cash_cm3 = metrics.get("cash_cm3", Decimal("0"))
        score *= Decimal("1") + min(order_count, Decimal("1000")) / Decimal("1000")
        score *= Decimal("1") + min(listing_count, Decimal("1000")) / Decimal("2000")
        if cash_cm3 > 0:
            score *= Decimal("1.20")
        elif cash_cm3 < 0:
            score *= Decimal("0.50")
        return score

    @classmethod
    def _recommendations(
        cls,
        categories: Sequence[Mapping[str, Any]],
        *,
        destinations: Sequence[Mapping[str, Any]],
        scope: Mapping[str, str],
        contradictions: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        blocked_categories = {
            item["field"]
            for item in contradictions
            if item["blocking"] and str(item["code"]).startswith(("category_", "derived_category_"))
        }
        recommendations = []
        for category in categories:
            if category["category_id"] in blocked_categories:
                continue
            target_category = (
                category["official_ancestor_category_id"] if category["role"] == "derived" else category["category_id"]
            )
            acceptable_quality = {"exact", "high", "not_applicable"}
            if (
                not target_category
                or category["data_grade"] not in {"A", "B", "C"}
                or category["identity_quality"] not in acceptable_quality
                or category["variant_quality"] not in acceptable_quality
            ):
                continue
            self_recommendation = {
                "source_category_id": category["category_id"],
                "target_store_ref": scope["store_ref"],
                "target_category_id": target_category,
                "category_role": category["role"],
                "placement_basis": (
                    "derived_advisory_under_official_ancestor"
                    if category["role"] == "derived"
                    else "observed_exact_store_category"
                ),
                "eligible": True,
                "cross_store_handoff_required": False,
                "evidence_refs": category["evidence_refs"],
                "automatic_publish_allowed": False,
                "external_write_allowed": False,
            }
            recommendations.append(cls._recommendation_id(self_recommendation))
            for destination in destinations:
                if destination["store_ref"] == scope["store_ref"] or destination["status"] != "ready":
                    continue
                matches = [
                    path
                    for path in destination["categories"]
                    if path["role"] != "excluded" and path["category_id"] == target_category
                ]
                for match in matches:
                    recommendation = {
                        "source_category_id": category["category_id"],
                        "target_store_ref": destination["store_ref"],
                        "target_category_id": match["category_id"],
                        "category_role": category["role"],
                        "placement_basis": (
                            "derived_advisory_under_destination_official_ancestor"
                            if category["role"] == "derived"
                            else "destination_official_category_match"
                        ),
                        "eligible": True,
                        "cross_store_handoff_required": True,
                        "evidence_refs": sorted(set(category["evidence_refs"]) | set(destination["evidence_refs"])),
                        "automatic_publish_allowed": False,
                        "external_write_allowed": False,
                    }
                    recommendations.append(cls._recommendation_id(recommendation))
        unique = {item["recommendation_id"]: item for item in recommendations}
        return sorted(
            unique.values(),
            key=lambda item: (
                item["source_category_id"],
                item["target_store_ref"],
                item["target_category_id"],
            ),
        )

    @staticmethod
    def _recommendation_id(value: dict[str, Any]) -> dict[str, Any]:
        return {**value, "recommendation_id": f"spr_{_sha256(value)[:24]}"}

    @classmethod
    def _reviewer_gates(
        cls,
        *,
        status: str,
        tier: str,
        data_grade: str,
        identity_quality: str,
        variant_quality: str,
        contradictions: Sequence[Mapping[str, Any]],
        categories: Sequence[Mapping[str, Any]],
        recommendations: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        gates: dict[str, str] = {
            "human_store_profile_review": "required",
            "evidence_scope_review": "required",
            "formal_fact_promotion_separate_command": "required",
            "external_publish_separate_approval": "required",
        }
        if status == "no_data":
            gates["evidence_collection"] = "blocked"
        if contradictions:
            gates["contradiction_resolution"] = "blocked"
        if DATA_GRADE_ORDER.index(data_grade) > DATA_GRADE_ORDER.index("B"):
            gates["data_quality_upgrade"] = "blocked"
        if identity_quality not in {"exact", "high", "not_applicable"}:
            gates["identity_resolution"] = "blocked"
        if variant_quality not in {"exact", "high", "not_applicable"}:
            gates["variant_resolution"] = "blocked"
        if any(item["role"] == "derived" for item in categories):
            gates["derived_category_ancestry_review"] = "required"
        if any(item["cross_store_handoff_required"] for item in recommendations):
            gates["destination_store_owner_review"] = "required"
        if tier in {"small_team", "mid_market", "enterprise"}:
            gates["role_separated_category_review"] = "required"
        if tier in {"mid_market", "enterprise"}:
            gates["data_steward_review"] = "required"
        if tier == "enterprise":
            gates["segregation_of_duties_review"] = "required"
        return [
            {
                "gate": gate,
                "status": gate_status,
                "auto_satisfied": False,
            }
            for gate, gate_status in sorted(gates.items())
        ]

    @staticmethod
    def _unique_contradictions(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        unique = {_sha256(value): dict(value) for value in values}
        return sorted(
            unique.values(),
            key=lambda item: (item["code"], item["field"], item["evidence_refs"]),
        )

    @classmethod
    def _aggregate_grade(
        cls,
        signals: Sequence[Mapping[str, Any]],
        evidence_types: Sequence[str],
    ) -> str:
        if not signals:
            return "E"
        coverage_grade = (
            "A"
            if len(evidence_types) == 5
            else "B"
            if len(evidence_types) == 4
            else "C"
            if len(evidence_types) >= 2
            else "D"
        )
        worst_source = cls._worst_grade(signals)
        return DATA_GRADE_ORDER[max(DATA_GRADE_ORDER.index(coverage_grade), DATA_GRADE_ORDER.index(worst_source))]

    @staticmethod
    def _worst_grade(signals: Sequence[Mapping[str, Any]]) -> str:
        return DATA_GRADE_ORDER[max(DATA_GRADE_ORDER.index(signal["data_grade"]) for signal in signals)]

    @classmethod
    def _aggregate_confidence(cls, signals: Sequence[Mapping[str, Any]]) -> str:
        if not signals:
            return "0.0000"
        return cls._weighted_confidence(signals)

    @classmethod
    def _weighted_confidence(cls, signals: Sequence[Mapping[str, Any]]) -> str:
        weights = [
            _GRADE_WEIGHT[signal["data_grade"]]
            * _QUALITY_WEIGHT[signal["identity_quality"]]
            * _QUALITY_WEIGHT[signal["variant_quality"]]
            for signal in signals
        ]
        denominator = sum(weights, Decimal("0"))
        if denominator == 0:
            return "0.0000"
        value = (
            sum(
                (signal["confidence"] * weight for signal, weight in zip(signals, weights, strict=True)),
                Decimal("0"),
            )
            / denominator
        )
        return _decimal_text(value)

    @staticmethod
    def _aggregate_quality(signals: Sequence[Mapping[str, Any]], field: str) -> str:
        if not signals:
            return "missing"
        values = [signal[field] for signal in signals if signal[field] != "not_applicable"]
        if not values:
            return "not_applicable"
        return min(values, key=QUALITY_ORDER.index)

    @staticmethod
    def _signal_projection(signal: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "evidence_type": signal["evidence_type"],
            "evidence_refs": list(signal["evidence_refs"]),
            "observed_at": signal["observed_at"].isoformat(),
            "valid_until": signal["valid_until"].isoformat() if signal["valid_until"] else None,
            "data_grade": signal["data_grade"],
            "confidence": _decimal_text(signal["confidence"]),
            "identity_quality": signal["identity_quality"],
            "variant_quality": signal["variant_quality"],
            "attributes": {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in sorted(signal["attributes"].items())
            },
            "category": (
                {
                    **signal["category"],
                    "ancestry": list(signal["category"]["ancestry"]),
                }
                if signal["category"]
                else None
            ),
            "metrics": signal["metrics"],
        }
