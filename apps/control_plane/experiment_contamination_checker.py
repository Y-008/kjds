"""Fail-closed overlap checks for concurrent operating experiments."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ContaminationResult:
    status: str
    blocked_reasons: tuple[str, ...]
    findings: tuple[dict[str, Any], ...]
    snapshot_sha256: str

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        return {
            "status": self.status,
            "blocked_reasons": self.blocked_reasons,
            "findings": self.findings,
            "snapshot_sha256": self.snapshot_sha256,
        }


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _participants(item: Mapping[str, Any]) -> set[str]:
    value = item.get("population", item.get("participants", item.get("audience")))
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(entry) for entry in value if str(entry).strip()}
    return set()


def check_experiment_contamination(experiments: Sequence[Mapping[str, Any]]) -> ContaminationResult:
    reasons: list[str] = []
    findings: list[dict[str, Any]] = []
    normalized: list[tuple[str, set[str], datetime, datetime, str]] = []
    for index, item in enumerate(experiments):
        experiment_id = str(item.get("id", item.get("experiment_id", ""))).strip()
        start = _time(item.get("exposure_start", item.get("start_at", item.get("exposure_from"))))
        end = _time(item.get("exposure_end", item.get("end_at", item.get("exposure_to"))))
        participants = _participants(item)
        treatment = str(item.get("treatment", item.get("variant", item.get("treatment_id", "")))).strip()
        if not experiment_id or not participants or start is None or end is None or end <= start or not treatment:
            reasons.append(f"incomplete_experiment:{index}")
            continue
        normalized.append((experiment_id, participants, start, end, treatment))
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            overlap = left[1] & right[1]
            window_start = max(left[2], right[2])
            window_end = min(left[3], right[3])
            if overlap and window_start < window_end:
                findings.append({
                    "left": left[0],
                    "right": right[0],
                    "overlap_population": sorted(overlap),
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "treatments": [left[4], right[4]],
                })
    if findings:
        reasons.append("population_exposure_overlap")
    status = "blocked" if reasons else "clear"
    canonical = {"status": status, "blocked_reasons": sorted(set(reasons)), "findings": findings}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ContaminationResult(status, tuple(sorted(set(reasons))), tuple(findings), digest)


detect_experiment_contamination = check_experiment_contamination
evaluate_experiment_contamination = check_experiment_contamination
