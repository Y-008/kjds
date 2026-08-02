from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from apps.control_plane.money import FxBasis


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _currency(value: object, field: str) -> str:
    text = _required_text(value, field)
    if len(text) != 3 or not text.isascii() or not text.isalpha():
        raise ValueError(f"{field} must be a three-letter ASCII currency")
    if text != text.upper():
        raise ValueError(f"{field} must be uppercase")
    return text


def _utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")
    return value.astimezone(UTC)


def _positive_decimal(value: object, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, (bool, float)):
        raise ValueError(f"{field} must not use binary floating point")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class FxEvidenceScope:
    tenant_id: str
    legal_entity_id: str
    store_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required_text(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "legal_entity_id",
            _required_text(self.legal_entity_id, "legal_entity_id"),
        )
        object.__setattr__(self, "store_ref", _required_text(self.store_ref, "store_ref"))

    def to_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "legal_entity_id": self.legal_entity_id,
            "store_ref": self.store_ref,
        }


@dataclass(frozen=True, slots=True)
class FxEvidenceSubmission:
    scope: FxEvidenceScope
    source_currency: str
    target_currency: str
    rate: Decimal | str | int | None
    effective_at: datetime | None
    expires_at: datetime | None
    evidence_id: str
    source_type: str
    authority: str
    purposes: tuple[str, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class FxEvidenceRecord:
    scope: FxEvidenceScope
    source_currency: str
    target_currency: str
    rate: Decimal
    effective_at: datetime
    expires_at: datetime
    evidence_id: str
    source_type: str
    authority: str
    purposes: tuple[str, ...]
    idempotency_key: str
    content_hash: str

    @property
    def basis(self) -> FxBasis:
        return FxBasis(
            source_currency=self.source_currency,
            target_currency=self.target_currency,
            rate=self.rate,
            effective_at=self.effective_at,
            evidence_id=self.evidence_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "source_currency": self.source_currency,
            "target_currency": self.target_currency,
            "rate": _decimal_text(self.rate),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "authority": self.authority,
            "purposes": list(self.purposes),
            "idempotency_key": self.idempotency_key,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class FxEvidenceBlocker:
    code: str
    message: str
    evidence_id: str | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "evidence_id": self.evidence_id,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class FxEvidenceIngestResult:
    status: Literal["ready", "partial", "blocked", "no_data"]
    records: tuple[FxEvidenceRecord, ...]
    blockers: tuple[FxEvidenceBlocker, ...]
    idempotent_replays: int
    manifest_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "records": [record.to_dict() for record in self.records],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "idempotent_replays": self.idempotent_replays,
            "manifest_hash": self.manifest_hash,
        }


@dataclass(frozen=True, slots=True)
class FxSelectionRequest:
    scope: FxEvidenceScope
    source_currency: str
    target_currency: str
    occurred_at: datetime
    purpose: str
    as_of: datetime
    allow_triangulation: bool = False

    def __post_init__(self) -> None:
        source = _currency(self.source_currency, "source_currency")
        target = _currency(self.target_currency, "target_currency")
        if source == target:
            raise ValueError("FX selection requires different source and target currencies")
        object.__setattr__(self, "source_currency", source)
        object.__setattr__(self, "target_currency", target)
        object.__setattr__(self, "occurred_at", _utc_timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "purpose", _required_text(self.purpose, "purpose"))
        object.__setattr__(self, "as_of", _utc_timestamp(self.as_of, "as_of"))
        if not isinstance(self.allow_triangulation, bool):
            raise ValueError("allow_triangulation must be a boolean")


@dataclass(frozen=True, slots=True)
class FxSelectionResult:
    status: Literal["selected", "blocked", "no_data"]
    basis: FxBasis | None
    evidence_path: tuple[FxEvidenceRecord, ...]
    blockers: tuple[FxEvidenceBlocker, ...]
    selection_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fx_basis": self.basis.to_dict() if self.basis else None,
            "path_kind": (
                "direct"
                if len(self.evidence_path) == 1
                else "triangulated"
                if len(self.evidence_path) == 2
                else None
            ),
            "evidence_path": [record.to_dict() for record in self.evidence_path],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "selection_hash": self.selection_hash,
        }


class FxEvidenceIntake:
    """Validates FX evidence and selects a replayable basis without side effects."""

    _BLOCKING_INGEST_CODES = frozenset(
        {
            "cross_scope_evidence",
            "evidence_content_drift",
            "idempotency_content_drift",
            "validity_period_conflict",
        }
    )

    def ingest(
        self,
        submissions: Sequence[FxEvidenceSubmission],
        *,
        expected_scope: FxEvidenceScope,
        prior_content_hashes: Mapping[str, str] | None = None,
    ) -> FxEvidenceIngestResult:
        prior_hashes = dict(prior_content_hashes or {})
        validated: list[FxEvidenceRecord] = []
        blockers: list[FxEvidenceBlocker] = []

        for submission in submissions:
            try:
                record = self._validate_submission(submission, expected_scope=expected_scope)
            except ValueError as exc:
                code = "cross_scope_evidence" if str(exc) == "cross-scope FX evidence rejected" else "invalid_fx_evidence"
                blockers.append(
                    FxEvidenceBlocker(
                        code=code,
                        message=str(exc),
                        evidence_id=self._optional_text(submission.evidence_id),
                        idempotency_key=self._optional_text(submission.idempotency_key),
                    )
                )
                continue
            validated.append(record)

        by_idempotency: dict[str, list[FxEvidenceRecord]] = defaultdict(list)
        for record in validated:
            by_idempotency[record.idempotency_key].append(record)

        records: list[FxEvidenceRecord] = []
        idempotent_replays = 0
        for key in sorted(by_idempotency):
            group = by_idempotency[key]
            hashes = {record.content_hash for record in group}
            prior_hash = prior_hashes.get(key)
            if len(hashes) > 1 or (prior_hash is not None and prior_hash not in hashes):
                blockers.append(
                    FxEvidenceBlocker(
                        code="idempotency_content_drift",
                        message="idempotency_key was reused with different FX evidence content",
                        evidence_id=min(record.evidence_id for record in group),
                        idempotency_key=key,
                    )
                )
                continue
            records.append(min(group, key=self._record_sort_key))
            idempotent_replays += len(group) - 1
            if prior_hash is not None:
                idempotent_replays += 1

        records = self._remove_evidence_drift(records, blockers)
        blockers.extend(self._validity_conflicts(records))
        records.sort(key=self._record_sort_key)
        blockers.sort(key=self._blocker_sort_key)

        manifest_hash = _hash_payload([record.content_hash for record in records])
        if not submissions:
            status: Literal["ready", "partial", "blocked", "no_data"] = "no_data"
        elif any(blocker.code in self._BLOCKING_INGEST_CODES for blocker in blockers):
            status = "blocked"
        elif blockers and records:
            status = "partial"
        elif blockers:
            status = "blocked"
        else:
            status = "ready"
        return FxEvidenceIngestResult(
            status=status,
            records=tuple(records),
            blockers=tuple(blockers),
            idempotent_replays=idempotent_replays,
            manifest_hash=manifest_hash,
        )

    def select(
        self,
        records: Sequence[FxEvidenceRecord],
        request: FxSelectionRequest,
    ) -> FxSelectionResult:
        ordered = tuple(sorted(records, key=self._record_sort_key))
        foreign = [record for record in ordered if record.scope != request.scope]
        if foreign:
            return self._blocked_selection(
                "cross_scope_evidence",
                "selection input contains FX evidence outside the requested tenant/legal entity/store",
                records=foreign,
                request=request,
            )
        if request.occurred_at > request.as_of:
            return self._blocked_selection(
                "future_occurrence_not_permitted",
                "occurred_at cannot be later than the selection as_of time",
                records=ordered,
                request=request,
            )

        direct = self._matching_pair(
            ordered,
            source=request.source_currency,
            target=request.target_currency,
            purpose=request.purpose,
        )
        valid_direct = [record for record in direct if self._valid_at(record, request.occurred_at)]
        if valid_direct:
            selected, conflict = self._select_pair(valid_direct)
            if conflict:
                return self._blocked_selection(
                    "validity_period_conflict",
                    "multiple FX rates conflict at the selected effective time",
                    records=valid_direct,
                    request=request,
                )
            assert selected is not None
            return self._selected_result(selected.basis, (selected,), request)

        if direct:
            if all(record.effective_at > request.occurred_at for record in direct):
                return self._blocked_selection(
                    "future_effective_rate_not_permitted",
                    "available direct FX evidence is not yet effective at occurred_at",
                    records=direct,
                    request=request,
                )
            if all(record.expires_at <= request.occurred_at for record in direct):
                return self._blocked_selection(
                    "expired_fx_evidence",
                    "available direct FX evidence expired before occurred_at",
                    records=direct,
                    request=request,
                )

        reverse = self._matching_pair(
            ordered,
            source=request.target_currency,
            target=request.source_currency,
            purpose=request.purpose,
        )
        if any(self._valid_at(record, request.occurred_at) for record in reverse):
            return self._blocked_selection(
                "inverse_rate_not_permitted",
                "reverse-direction evidence cannot be inverted or guessed",
                records=reverse,
                request=request,
            )

        if request.allow_triangulation:
            triangular = self._select_triangulation(ordered, request)
            if triangular is not None:
                return triangular

        pair_records = [
            record
            for record in ordered
            if record.source_currency == request.source_currency
            and record.target_currency == request.target_currency
        ]
        if pair_records and not direct:
            return self._blocked_selection(
                "purpose_not_covered",
                "FX evidence does not authorize the requested purpose",
                records=pair_records,
                request=request,
            )

        if request.allow_triangulation and self._has_partial_triangulation(ordered, request):
            return self._blocked_selection(
                "triangulation_evidence_incomplete",
                "triangulation requires two complete, directed, in-scope, purpose-matched FX evidence legs",
                records=ordered,
                request=request,
            )

        return self._selection_result(
            status="no_data",
            basis=None,
            path=(),
            blockers=(
                FxEvidenceBlocker(
                    code="direct_fx_evidence_missing",
                    message="no eligible direct FX evidence was found",
                ),
            ),
            request=request,
        )

    def _validate_submission(
        self,
        submission: FxEvidenceSubmission,
        *,
        expected_scope: FxEvidenceScope,
    ) -> FxEvidenceRecord:
        if submission.scope != expected_scope:
            raise ValueError("cross-scope FX evidence rejected")
        source = _currency(submission.source_currency, "source_currency")
        target = _currency(submission.target_currency, "target_currency")
        rate = _positive_decimal(submission.rate, "rate")
        effective = _utc_timestamp(submission.effective_at, "effective_at")
        expires = _utc_timestamp(submission.expires_at, "expires_at")
        if effective >= expires:
            raise ValueError("expires_at must be later than effective_at")
        evidence_id = _required_text(submission.evidence_id, "evidence_id")
        source_type = _required_text(submission.source_type, "source_type")
        authority = _required_text(submission.authority, "authority")
        idempotency_key = _required_text(submission.idempotency_key, "idempotency_key")
        purposes = tuple(sorted({_required_text(item, "purpose") for item in submission.purposes}))
        if not purposes:
            raise ValueError("purposes must contain at least one explicit purpose")

        # FxBasis is the shared monetary semantic authority, including direction and rate rules.
        basis = FxBasis(source, target, rate, effective, evidence_id)
        payload = {
            "scope": expected_scope.to_dict(),
            "source_currency": basis.source_currency,
            "target_currency": basis.target_currency,
            "rate": _decimal_text(basis.rate),
            "effective_at": basis.effective_at.isoformat(),
            "expires_at": expires.isoformat(),
            "evidence_id": evidence_id,
            "source_type": source_type,
            "authority": authority,
            "purposes": list(purposes),
        }
        return FxEvidenceRecord(
            scope=expected_scope,
            source_currency=basis.source_currency,
            target_currency=basis.target_currency,
            rate=basis.rate,
            effective_at=basis.effective_at,
            expires_at=expires,
            evidence_id=evidence_id,
            source_type=source_type,
            authority=authority,
            purposes=purposes,
            idempotency_key=idempotency_key,
            content_hash=_hash_payload(payload),
        )

    def _remove_evidence_drift(
        self,
        records: Sequence[FxEvidenceRecord],
        blockers: list[FxEvidenceBlocker],
    ) -> list[FxEvidenceRecord]:
        grouped: dict[str, list[FxEvidenceRecord]] = defaultdict(list)
        for record in records:
            grouped[record.evidence_id].append(record)
        kept: list[FxEvidenceRecord] = []
        for evidence_id in sorted(grouped):
            group = grouped[evidence_id]
            if len({record.content_hash for record in group}) > 1:
                blockers.append(
                    FxEvidenceBlocker(
                        code="evidence_content_drift",
                        message="evidence_id was reused with different FX evidence content",
                        evidence_id=evidence_id,
                        idempotency_key=min(record.idempotency_key for record in group),
                    )
                )
                continue
            kept.append(min(group, key=self._record_sort_key))
        return kept

    def _validity_conflicts(self, records: Sequence[FxEvidenceRecord]) -> list[FxEvidenceBlocker]:
        grouped: dict[tuple[object, ...], list[FxEvidenceRecord]] = defaultdict(list)
        for record in records:
            for purpose in record.purposes:
                grouped[
                    (
                        record.scope,
                        record.source_currency,
                        record.target_currency,
                        purpose,
                        record.effective_at,
                        record.expires_at,
                    )
                ].append(record)
        blockers: list[FxEvidenceBlocker] = []
        for group in grouped.values():
            if len({_decimal_text(record.rate) for record in group}) <= 1:
                continue
            first = min(group, key=self._record_sort_key)
            blockers.append(
                FxEvidenceBlocker(
                    code="validity_period_conflict",
                    message="same scope, pair, purpose, and validity period contains conflicting rates",
                    evidence_id=first.evidence_id,
                    idempotency_key=first.idempotency_key,
                )
            )
        return blockers

    def _select_triangulation(
        self,
        records: Sequence[FxEvidenceRecord],
        request: FxSelectionRequest,
    ) -> FxSelectionResult | None:
        valid = [
            record
            for record in records
            if request.purpose in record.purposes and self._valid_at(record, request.occurred_at)
        ]
        paths: list[tuple[FxEvidenceRecord, FxEvidenceRecord]] = []
        for intermediate in sorted(
            {
                record.target_currency
                for record in valid
                if record.source_currency == request.source_currency
                and record.target_currency not in {request.source_currency, request.target_currency}
            }
        ):
            first_records = self._matching_pair(
                valid,
                source=request.source_currency,
                target=intermediate,
                purpose=request.purpose,
            )
            second_records = self._matching_pair(
                valid,
                source=intermediate,
                target=request.target_currency,
                purpose=request.purpose,
            )
            if not first_records or not second_records:
                continue
            first, first_conflict = self._select_pair(first_records)
            second, second_conflict = self._select_pair(second_records)
            if first_conflict or second_conflict:
                return self._blocked_selection(
                    "triangulation_leg_conflict",
                    "a triangulation leg contains conflicting FX evidence",
                    records=(*first_records, *second_records),
                    request=request,
                )
            assert first is not None and second is not None
            paths.append((first, second))

        if not paths:
            return None
        if len(paths) > 1:
            return self._blocked_selection(
                "triangulation_path_conflict",
                "multiple complete triangulation paths require explicit human selection",
                records=tuple(record for path in paths for record in path),
                request=request,
            )

        first, second = paths[0]
        path_hash = _hash_payload([first.content_hash, second.content_hash])
        basis = FxBasis(
            source_currency=request.source_currency,
            target_currency=request.target_currency,
            rate=first.rate * second.rate,
            effective_at=max(first.effective_at, second.effective_at),
            evidence_id=f"fx-path:{path_hash}",
        )
        return self._selected_result(basis, (first, second), request)

    @staticmethod
    def _select_pair(records: Sequence[FxEvidenceRecord]) -> tuple[FxEvidenceRecord | None, bool]:
        if not records:
            return None, False
        latest_effective = max(record.effective_at for record in records)
        latest = [record for record in records if record.effective_at == latest_effective]
        if len({_decimal_text(record.rate) for record in latest}) > 1:
            return None, True
        return max(
            latest,
            key=lambda record: (
                record.expires_at,
                record.authority,
                record.source_type,
                record.evidence_id,
                record.content_hash,
            ),
        ), False

    @staticmethod
    def _matching_pair(
        records: Sequence[FxEvidenceRecord],
        *,
        source: str,
        target: str,
        purpose: str,
    ) -> list[FxEvidenceRecord]:
        return [
            record
            for record in records
            if record.source_currency == source
            and record.target_currency == target
            and purpose in record.purposes
        ]

    @staticmethod
    def _valid_at(record: FxEvidenceRecord, occurred_at: datetime) -> bool:
        return record.effective_at <= occurred_at < record.expires_at

    @staticmethod
    def _has_partial_triangulation(
        records: Sequence[FxEvidenceRecord],
        request: FxSelectionRequest,
    ) -> bool:
        eligible = [
            record
            for record in records
            if request.purpose in record.purposes and FxEvidenceIntake._valid_at(record, request.occurred_at)
        ]
        return any(
            record.source_currency == request.source_currency
            or record.target_currency == request.target_currency
            for record in eligible
        )

    def _selected_result(
        self,
        basis: FxBasis,
        path: tuple[FxEvidenceRecord, ...],
        request: FxSelectionRequest,
    ) -> FxSelectionResult:
        return self._selection_result(
            status="selected",
            basis=basis,
            path=path,
            blockers=(),
            request=request,
        )

    def _blocked_selection(
        self,
        code: str,
        message: str,
        *,
        records: Sequence[FxEvidenceRecord],
        request: FxSelectionRequest,
    ) -> FxSelectionResult:
        first = min(records, key=self._record_sort_key) if records else None
        return self._selection_result(
            status="blocked",
            basis=None,
            path=(),
            blockers=(
                FxEvidenceBlocker(
                    code=code,
                    message=message,
                    evidence_id=first.evidence_id if first else None,
                    idempotency_key=first.idempotency_key if first else None,
                ),
            ),
            request=request,
        )

    @staticmethod
    def _selection_result(
        *,
        status: Literal["selected", "blocked", "no_data"],
        basis: FxBasis | None,
        path: tuple[FxEvidenceRecord, ...],
        blockers: tuple[FxEvidenceBlocker, ...],
        request: FxSelectionRequest,
    ) -> FxSelectionResult:
        payload = {
            "status": status,
            "scope": request.scope.to_dict(),
            "source_currency": request.source_currency,
            "target_currency": request.target_currency,
            "occurred_at": request.occurred_at.isoformat(),
            "purpose": request.purpose,
            "as_of": request.as_of.isoformat(),
            "allow_triangulation": request.allow_triangulation,
            "basis": basis.to_dict() if basis else None,
            "path": [record.content_hash for record in path],
            "blockers": [blocker.code for blocker in blockers],
        }
        return FxSelectionResult(
            status=status,
            basis=basis,
            evidence_path=path,
            blockers=blockers,
            selection_hash=_hash_payload(payload),
        )

    @staticmethod
    def _record_sort_key(record: FxEvidenceRecord) -> tuple[object, ...]:
        return (
            record.scope,
            record.source_currency,
            record.target_currency,
            record.effective_at,
            record.expires_at,
            record.evidence_id,
            record.idempotency_key,
            record.content_hash,
        )

    @staticmethod
    def _blocker_sort_key(blocker: FxEvidenceBlocker) -> tuple[str, str, str, str]:
        return (
            blocker.code,
            blocker.evidence_id or "",
            blocker.idempotency_key or "",
            blocker.message,
        )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None
