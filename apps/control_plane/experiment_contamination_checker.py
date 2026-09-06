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


@dataclass(frozen=True, slots=True)
class ExperimentFactAdmission:
    """Admission state for a fact that may belong to an experiment.

    Long-term analytics may consume ordinary operating facts and reviewed
    experiment results.  A fact carrying an experiment context is admitted
    only when the context proves that the experiment is review eligible and
    includes both causal evidence and a stopping rule.  Keeping this decision
    separate from the numeric fact quality prevents an unfinished experiment
    from masquerading as a normal ``VALID`` observation.
    """

    status: str
    experiment_id: str | None
    blocked_reasons: tuple[str, ...]
    snapshot_sha256: str

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        return {
            "status": self.status,
            "experiment_id": self.experiment_id,
            "blocked_reasons": self.blocked_reasons,
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


def _has_evidence(value: Any) -> bool:
    """Return whether a transport value contains at least one reference."""

    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_evidence(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_has_evidence(item) for item in value)
    return False


def _first_present(item: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def evaluate_experiment_fact_admission(
    fact: Mapping[str, Any],
) -> ExperimentFactAdmission:
    """Evaluate whether one fact may enter a long-term analytics projection.

    Facts without an explicit experiment marker remain ``unmarked`` for
    backwards compatibility.  Once a marker is present, omission is treated
    as an unsafe/incomplete experiment rather than as permission to include
    the row.  The accepted aliases mirror protocol and transport names used
    by the causal experiment service while keeping the decision deterministic.
    """

    if not isinstance(fact, Mapping):
        raise TypeError("experiment fact must be an object")

    context: Any = fact.get("experiment_context", fact.get("experiment"))
    marker_names = (
        "experiment_context",
        "experiment",
        "experiment_id",
        "protocol_id",
        "review_eligible",
        "causal_evidence",
        "causal_evidence_refs",
        "causal_evidence_id",
        "stop_rule",
        "stop_rule_ref",
        "stop_rule_id",
    )
    marked = context is not None or any(name in fact for name in marker_names[2:])
    if not marked:
        return _experiment_admission("unmarked", None, ())

    if context is None:
        context = fact
    if not isinstance(context, Mapping):
        return _experiment_admission(
            "blocked",
            None,
            ("experiment_context_invalid",),
        )

    experiment_id_value = _first_present(
        context,
        ("experiment_id", "protocol_id", "id"),
    )
    experiment_id = (
        str(experiment_id_value).strip()
        if experiment_id_value is not None
        else ""
    )
    reasons: list[str] = []
    if not experiment_id:
        reasons.append("experiment_id_missing")

    review_eligible = context.get("review_eligible")
    if review_eligible is not True:
        reasons.append("experiment_not_review_eligible")

    causal_evidence = _first_present(
        context,
        ("causal_evidence", "causal_evidence_refs", "causal_evidence_id"),
    )
    if not _has_evidence(causal_evidence):
        reasons.append("experiment_causal_evidence_missing")

    stop_rule = _first_present(
        context,
        ("stop_rule", "stop_rule_ref", "stop_rule_id"),
    )
    if not _has_evidence(stop_rule):
        reasons.append("experiment_stop_rule_missing")

    if reasons:
        return _experiment_admission(
            "blocked",
            experiment_id or None,
            tuple(sorted(set(reasons))),
        )
    return _experiment_admission("eligible", experiment_id, ())


def _experiment_admission(
    status: str,
    experiment_id: str | None,
    reasons: tuple[str, ...],
) -> ExperimentFactAdmission:
    canonical = {
        "contract_id": "kjds-experiment-fact-admission-v1",
        "status": status,
        "experiment_id": experiment_id,
        "blocked_reasons": list(reasons),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ExperimentFactAdmission(status, experiment_id, reasons, digest)


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
check_experiment_fact_admission = evaluate_experiment_fact_admission


__all__ = [
    "ContaminationResult",
    "ExperimentFactAdmission",
    "check_experiment_contamination",
    "check_experiment_fact_admission",
    "detect_experiment_contamination",
    "evaluate_experiment_contamination",
    "evaluate_experiment_fact_admission",
]
