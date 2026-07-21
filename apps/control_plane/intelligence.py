from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlparse

from .action_policies import ActionAuthorizationService, require_action_authorization
from .domain import ApprovalStatus, MarketObservation, OpportunityInsight, Product
from .evidence import EvidenceGrade, EvidenceRecord
from .numeric_semantics import finite_decimal
from .repository import Repository


class MarketIntelligenceService:
    """Turns source-attributed observations into reproducible opportunity scores."""

    CANDIDATE_METRICS = (
        "demand_signal",
        "competition_gap",
        "supplier_available",
        "compliance_redline",
        "return_risk",
    )
    CANDIDATE_MEASUREMENT_POLICY_ID = "ozon-ru-candidate-measurement-v1"
    CANDIDATE_QUOTE_POLICY_ID = "ozon-ru-quote-screen-v1"
    CANDIDATE_QUOTE_POLICY_STATUS = "engineering_default_requires_owner_review"
    CANDIDATE_MEASUREMENT_CONTRACTS = {
        "demand_signal": {
            "method": "category_demand_percentile",
            "unit": "percentile",
            "min_window_days": 28,
            "max_window_days": 90,
            "min_sample_size": 30,
        },
        "competition_gap": {
            "method": "demand_supply_gap_percentile",
            "unit": "percentile",
            "min_window_days": 28,
            "max_window_days": 90,
            "min_sample_size": 30,
        },
        "supplier_available": {
            "method": "verified_supplier_exists",
            "unit": "boolean",
            "min_window_days": 1,
            "max_window_days": 90,
            "min_sample_size": 1,
        },
        "compliance_redline": {
            "method": "official_rule_redline",
            "unit": "boolean",
            "min_window_days": 1,
            "max_window_days": 90,
            "min_sample_size": 1,
        },
        "return_risk": {
            "method": "expected_30d_return_rate_pct",
            "unit": "percent",
            "min_window_days": 28,
            "max_window_days": 90,
            "min_sample_size": 30,
        },
    }
    CANDIDATE_QUOTE_THRESHOLDS = {
        "demand_signal": {"operator": "gte", "value": Decimal("50")},
        "competition_gap": {"operator": "gte", "value": Decimal("50")},
        "return_risk": {"operator": "lte", "value": Decimal("30")},
    }
    CANDIDATE_MINIMUM_EVIDENCE_GRADES = {
        "demand_signal": frozenset({EvidenceGrade.A, EvidenceGrade.B}),
        "competition_gap": frozenset({EvidenceGrade.A, EvidenceGrade.B}),
        "supplier_available": frozenset({EvidenceGrade.A, EvidenceGrade.B}),
        "compliance_redline": frozenset({EvidenceGrade.A}),
        "return_risk": frozenset({EvidenceGrade.A, EvidenceGrade.B}),
    }

    def __init__(
        self,
        repository: Repository,
        *,
        evidence_validator: Callable[[list[str]], None] | None = None,
        evidence_lookup: Callable[[str], EvidenceRecord] | None = None,
        demand_report_validator: Callable[[str], None] | None = None,
        evidence_authority_lookup: Callable[[str, str], EvidenceGrade] | None = None,
        action_authorization: ActionAuthorizationService | None = None,
    ) -> None:
        self.repo = repository
        self.evidence_validator = evidence_validator
        self.evidence_lookup = evidence_lookup
        self.demand_report_validator = demand_report_validator
        self.evidence_authority_lookup = evidence_authority_lookup
        self.action_authorization = action_authorization or ActionAuthorizationService()

    def ingest(
        self,
        *,
        source: str,
        market: str,
        category: str,
        metric: str,
        value: Decimal,
        observed_at: str,
        source_ref: str,
        confidence: Decimal,
        dimensions: dict[str, str] | None = None,
    ) -> MarketObservation:
        observation = self._build_observation(
            source=source,
            market=market,
            category=category,
            metric=metric,
            value=value,
            observed_at=observed_at,
            source_ref=source_ref,
            confidence=confidence,
            dimensions=dimensions,
        )
        with self.repo.transaction():
            self.repo.add_observation(observation)
            self.repo.append_event("market.observation_ingested", observation.id, {"metric": metric, "source": source})
        return observation

    def submit_candidate_research(
        self,
        *,
        candidate_ref: str,
        candidate_name: str,
        market: str,
        category: str,
        as_of: str,
        demand_report_evidence_id: str,
        observations: list[dict],
        max_age_days: int = 90,
    ) -> dict:
        """Verify a complete candidate packet, write it atomically, then run the preflight."""
        candidate_ref = candidate_ref.strip()
        candidate_name = candidate_name.strip()
        market = market.strip()
        category = category.strip()
        if not candidate_ref or not candidate_name or not market or not category:
            raise ValueError("Candidate research requires candidate_ref, candidate_name, market and category")
        if max_age_days < 1 or max_age_days > 365:
            raise ValueError("Candidate research max_age_days must be between 1 and 365")
        self._parse_time("as_of", as_of)
        if self.evidence_validator is None or self.evidence_lookup is None:
            raise ValueError("Candidate research requires Evidence Ledger integration")
        demand_report_evidence_id = self._accepted_demand_report(demand_report_evidence_id)

        metrics = [str(item.get("metric", "")).strip() for item in observations]
        if len(metrics) != len(self.CANDIDATE_METRICS) or set(metrics) != set(self.CANDIDATE_METRICS):
            raise ValueError("Candidate research requires each of the five fixed metrics exactly once")
        evidence_ids = [str(item.get("evidence_id", "")).strip() for item in observations]
        if any(not evidence_id for evidence_id in evidence_ids):
            raise ValueError("Each candidate metric requires an evidence_id")

        self.evidence_validator(evidence_ids)
        records = {evidence_id: self.evidence_lookup(evidence_id) for evidence_id in evidence_ids}
        rows: list[MarketObservation] = []
        for item, metric, evidence_id in zip(observations, metrics, evidence_ids, strict=True):
            record = records[evidence_id]
            self._parse_time("evidence effective_at", record.effective_at)
            if record.effective_until is not None:
                self._parse_time("evidence effective_until", record.effective_until)
            value = finite_decimal(item.get("value"), f"Candidate metric {metric} value")
            confidence = finite_decimal(item.get("confidence"), f"Candidate metric {metric} confidence")
            dimensions = self.candidate_measurement_dimensions(
                candidate_ref=candidate_ref,
                evidence_id=evidence_id,
                demand_report_evidence_id=demand_report_evidence_id,
                metric=metric,
                window_days=item.get("window_days"),
                sample_size=item.get("sample_size"),
            )
            digest_input = json.dumps(
                {
                    "candidate_ref": candidate_ref,
                    "market": market,
                    "category": category,
                    "metric": metric,
                    "evidence_id": evidence_id,
                    "demand_report_evidence_id": demand_report_evidence_id,
                    "value": format(value.normalize(), "f"),
                    "confidence": format(confidence.normalize(), "f"),
                    "measurement_policy_id": dimensions["measurement_policy_id"],
                    "window_days": dimensions["window_days"],
                    "sample_size": dimensions["sample_size"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            rows.append(
                self._build_observation(
                    source=record.source,
                    market=market,
                    category=category,
                    metric=metric,
                    value=value,
                    observed_at=record.effective_at,
                    source_ref=record.source_ref,
                    confidence=confidence,
                    dimensions=dimensions,
                    observation_id=f"obs-{hashlib.sha256(digest_input).hexdigest()[:32]}",
                )
            )

        existing_ids = {row.id for row in self.repo.observations_for(market, category)}
        with self.repo.transaction():
            for row in rows:
                if row.id in existing_ids:
                    continue
                self.repo.add_observation(row)
                self.repo.append_event(
                    "market.observation_ingested",
                    row.id,
                    {"metric": row.metric, "source": row.source},
                    source_evidence_id=row.dimensions["evidence_id"],
                )
        return self.assess_candidate_research(
            candidate_ref=candidate_ref,
            candidate_name=candidate_name,
            market=market,
            category=category,
            as_of=as_of,
            demand_report_evidence_id=demand_report_evidence_id,
            max_age_days=max_age_days,
        )

    def score_opportunity(
        self,
        *,
        market: str,
        category: str,
        weights: dict[str, Decimal],
        recommended_action: str,
    ) -> OpportunityInsight:
        evidence: list[str] = []
        rationale: list[str] = []
        weighted_total = Decimal("0")
        weight_total = Decimal("0")
        for metric, weight in weights.items():
            weight = finite_decimal(weight, f"Opportunity weight {metric}")
            rows = self.repo.observations_for(market, category, metric)
            if not rows:
                continue
            confidence_weight = sum((row.confidence for row in rows), Decimal("0"))
            if confidence_weight == 0:
                continue
            mean = sum((row.value * row.confidence for row in rows), Decimal("0")) / confidence_weight
            weighted_total += mean * weight
            weight_total += abs(weight)
            evidence.extend(row.id for row in rows)
            rationale.append(f"{metric}={mean.normalize()} based on {len(rows)} sourced observation(s)")
        if not evidence or weight_total == 0:
            raise ValueError("Insufficient sourced data to score opportunity")
        score = max(Decimal("0"), min(Decimal("100"), weighted_total / weight_total))
        insight = OpportunityInsight(
            market=market,
            category=category,
            title=f"{market}/{category} opportunity",
            score=score,
            rationale=rationale,
            evidence_ids=evidence,
            recommended_action=recommended_action,
        )
        with self.repo.transaction():
            self.repo.add_opportunity(insight)
            self.repo.append_event("market.opportunity_scored", insight.id, {"score": str(score)})
        return insight

    def assess_candidate_research(
        self,
        *,
        candidate_ref: str,
        candidate_name: str,
        market: str,
        category: str,
        as_of: str,
        demand_report_evidence_id: str,
        max_age_days: int = 90,
    ) -> dict:
        """Fail-closed preflight before a candidate may request three supplier quotes."""
        candidate_ref = candidate_ref.strip()
        candidate_name = candidate_name.strip()
        if not candidate_ref or not candidate_name:
            raise ValueError("Candidate research requires candidate_ref and candidate_name")
        if max_age_days < 1 or max_age_days > 365:
            raise ValueError("Candidate research max_age_days must be between 1 and 365")
        demand_report_evidence_id = self._accepted_demand_report(demand_report_evidence_id)
        cutoff = self._parse_time("as_of", as_of)
        required_metrics = self.CANDIDATE_METRICS
        by_metric: dict[str, list[MarketObservation]] = {}
        for metric in required_metrics:
            by_metric[metric] = [
                row
                for row in self.repo.observations_for(market, category, metric)
                if row.dimensions.get("candidate_ref") == candidate_ref
            ]

        missing_metrics = [metric for metric, rows in by_metric.items() if not rows]
        stale_evidence: list[str] = []
        invalid_evidence: list[str] = []
        low_authority_evidence: list[str] = []
        current_rows: list[MarketObservation] = []
        evidence_records: dict[str, EvidenceRecord] = {}
        for metric, rows in by_metric.items():
            for row in rows:
                observed_at = self._parse_time("observed_at", row.observed_at)
                age_days = (cutoff - observed_at).total_seconds() / 86400
                if age_days < 0 or age_days > max_age_days:
                    stale_evidence.append(row.id)
                    continue
                if row.confidence <= 0:
                    invalid_evidence.append(row.id)
                    continue
                if row.value < 0 or row.value > 100:
                    invalid_evidence.append(row.id)
                    continue
                if metric in {"supplier_available", "compliance_redline"} and row.value not in {0, 1}:
                    invalid_evidence.append(row.id)
                    continue
                if not self._measurement_contract_matches(metric, row.dimensions):
                    invalid_evidence.append(row.id)
                    continue
                if row.dimensions.get("demand_report_evidence_id") != demand_report_evidence_id:
                    invalid_evidence.append(row.id)
                    continue
                evidence_id = row.dimensions.get("evidence_id", "").strip()
                if not evidence_id or self.evidence_validator is None or self.evidence_lookup is None:
                    invalid_evidence.append(row.id)
                    continue
                try:
                    self.evidence_validator([evidence_id])
                    record = self.evidence_lookup(evidence_id)
                except (KeyError, RuntimeError, ValueError):
                    invalid_evidence.append(row.id)
                    continue
                if record.source.strip() != row.source.strip() or record.source_ref.strip() != row.source_ref.strip():
                    invalid_evidence.append(row.id)
                    continue
                try:
                    evidence_grade = (
                        self.evidence_authority_lookup(evidence_id, metric)
                        if self.evidence_authority_lookup is not None
                        else EvidenceGrade.UNKNOWN
                    )
                except (KeyError, RuntimeError, ValueError):
                    low_authority_evidence.append(row.id)
                    continue
                if evidence_grade not in self.CANDIDATE_MINIMUM_EVIDENCE_GRADES[metric]:
                    low_authority_evidence.append(row.id)
                    continue
                effective_at = self._parse_time("evidence effective_at", record.effective_at)
                evidence_age_days = (cutoff - effective_at).total_seconds() / 86400
                if evidence_age_days < 0 or evidence_age_days > max_age_days:
                    stale_evidence.append(row.id)
                    continue
                if record.effective_until is not None:
                    effective_until = self._parse_time("evidence effective_until", record.effective_until)
                    if cutoff > effective_until:
                        stale_evidence.append(row.id)
                        continue
                current_rows.append(row)
                evidence_records[row.id] = record

        current_ids = {row.id for row in current_rows}
        current_by_metric = {
            metric: [row for row in rows if row.id in current_ids] for metric, rows in by_metric.items()
        }
        missing_current_metrics = [metric for metric, rows in current_by_metric.items() if not rows]
        source_families = sorted(
            {
                family
                for row in current_rows
                if (family := self._source_family(evidence_records[row.id].source_ref, evidence_records[row.id].source))
            }
        )
        supplier_available = any(row.value == 1 for row in current_by_metric["supplier_available"])
        compliance_redline = any(row.value == 1 for row in current_by_metric["compliance_redline"])
        metric_values = {
            metric: self._weighted_metric_value(rows)
            for metric, rows in current_by_metric.items()
            if rows
        }
        threshold_failures: list[dict[str, str]] = []
        for metric, threshold in self.CANDIDATE_QUOTE_THRESHOLDS.items():
            actual = metric_values.get(metric)
            if actual is None:
                continue
            operator = str(threshold["operator"])
            target = threshold["value"]
            passed = actual >= target if operator == "gte" else actual <= target
            if not passed:
                threshold_failures.append(
                    {
                        "metric": metric,
                        "operator": operator,
                        "threshold": self._decimal_text(target),
                        "actual": self._decimal_text(actual),
                    }
                )

        reasons: list[str] = []
        if compliance_redline:
            decision = "reject"
            reasons.append("A current compliance redline blocks the candidate")
        else:
            if missing_metrics or missing_current_metrics:
                reasons.append("Required candidate evidence is missing or not current")
            if stale_evidence:
                reasons.append("Some candidate evidence is stale or dated after as_of")
            if invalid_evidence:
                reasons.append("Some candidate observations violate the metric contract")
            if low_authority_evidence:
                reasons.append("Some candidate evidence is below the required authority grade")
            if len(source_families) < 2:
                reasons.append("At least two independent source families are required")
            if not supplier_available:
                reasons.append("No current supplier availability signal is confirmed")
            if reasons:
                decision = "collect_evidence"
            elif threshold_failures:
                decision = "reject"
                reasons.append("One or more measured metrics do not meet the quote-screen thresholds")
            else:
                decision = "request_three_quotes"

        return {
            "candidate_ref": candidate_ref,
            "candidate_name": candidate_name,
            "demand_report_evidence_id": demand_report_evidence_id,
            "market": market,
            "category": category,
            "decision": decision,
            "reasons": reasons,
            "required_metrics": list(required_metrics),
            "missing_metrics": sorted(set(missing_metrics + missing_current_metrics)),
            "source_family_count": len(source_families),
            "source_families": source_families,
            "observation_ids": sorted(current_ids),
            "evidence_ids": sorted({record.id for record in evidence_records.values()}),
            "stale_evidence_ids": sorted(stale_evidence),
            "invalid_evidence_ids": sorted(invalid_evidence),
            "low_authority_evidence_ids": sorted(low_authority_evidence),
            "minimum_evidence_grades": {
                metric: sorted(grade.value for grade in grades)
                for metric, grades in self.CANDIDATE_MINIMUM_EVIDENCE_GRADES.items()
            },
            "measurement_policy_id": self.CANDIDATE_MEASUREMENT_POLICY_ID,
            "quote_policy_id": self.CANDIDATE_QUOTE_POLICY_ID,
            "quote_policy_status": self.CANDIDATE_QUOTE_POLICY_STATUS,
            "metric_values": {metric: self._decimal_text(value) for metric, value in metric_values.items()},
            "threshold_failures": threshold_failures,
            "measurement_contracts": self.CANDIDATE_MEASUREMENT_CONTRACTS,
            "required_supplier_quotes": 3,
            "automatic_product_creation": False,
            "automatic_listing": False,
            "next_gate": "sourcing_comparison_intake" if decision == "request_three_quotes" else None,
        }

    @classmethod
    def candidate_measurement_dimensions(
        cls,
        *,
        candidate_ref: str,
        evidence_id: str,
        demand_report_evidence_id: str,
        metric: str,
        window_days: object,
        sample_size: object,
    ) -> dict[str, str]:
        contract = cls.CANDIDATE_MEASUREMENT_CONTRACTS.get(metric)
        if contract is None:
            raise ValueError(f"Unknown candidate metric: {metric}")
        window = cls._positive_int(window_days, f"Candidate metric {metric} window_days")
        sample = cls._positive_int(sample_size, f"Candidate metric {metric} sample_size")
        if window < contract["min_window_days"] or window > contract["max_window_days"]:
            raise ValueError(
                f"Candidate metric {metric} window_days must be between "
                f"{contract['min_window_days']} and {contract['max_window_days']}"
            )
        if sample < contract["min_sample_size"]:
            raise ValueError(
                f"Candidate metric {metric} sample_size must be at least {contract['min_sample_size']}"
            )
        return {
            "candidate_ref": candidate_ref,
            "evidence_id": evidence_id,
            "demand_report_evidence_id": demand_report_evidence_id,
            "measurement_policy_id": cls.CANDIDATE_MEASUREMENT_POLICY_ID,
            "method": str(contract["method"]),
            "unit": str(contract["unit"]),
            "window_days": str(window),
            "sample_size": str(sample),
        }

    @classmethod
    def _measurement_contract_matches(cls, metric: str, dimensions: dict[str, str]) -> bool:
        contract = cls.CANDIDATE_MEASUREMENT_CONTRACTS.get(metric)
        if contract is None:
            return False
        if dimensions.get("measurement_policy_id") != cls.CANDIDATE_MEASUREMENT_POLICY_ID:
            return False
        if dimensions.get("method") != contract["method"] or dimensions.get("unit") != contract["unit"]:
            return False
        try:
            window = cls._positive_int(dimensions.get("window_days"), "window_days")
            sample = cls._positive_int(dimensions.get("sample_size"), "sample_size")
        except ValueError:
            return False
        return (
            contract["min_window_days"] <= window <= contract["max_window_days"]
            and sample >= contract["min_sample_size"]
        )

    @staticmethod
    def _weighted_metric_value(rows: list[MarketObservation]) -> Decimal:
        confidence_total = sum((row.confidence for row in rows), Decimal("0"))
        return sum((row.value * row.confidence for row in rows), Decimal("0")) / confidence_total

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a positive integer")
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive integer") from exc
        if parsed < 1 or str(parsed) != str(value).strip():
            raise ValueError(f"{name} must be a positive integer")
        return parsed

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")

    def handoff_candidate_to_sourcing(
        self,
        *,
        candidate_ref: str,
        candidate_name: str,
        market: str,
        category: str,
        as_of: str,
        demand_report_evidence_id: str,
        sku: str,
        confirmed: bool,
        confirmed_by: str,
        max_age_days: int = 90,
    ) -> dict:
        """Create only the candidate Product needed by the existing three-quote gate."""
        if not confirmed:
            raise ValueError("Candidate sourcing handoff requires explicit human confirmation")
        sku = sku.strip()
        confirmed_by = confirmed_by.strip()
        if not sku or not confirmed_by:
            raise ValueError("Candidate sourcing handoff requires sku and confirmed_by")
        if market.strip().upper() != "RU":
            raise ValueError("Candidate sourcing handoff currently supports the Ozon RU vertical slice only")

        approval_payload = {
            "candidate_ref": candidate_ref,
            "candidate_name": candidate_name,
            "market": "RU",
            "category": category,
            "as_of": as_of,
            "demand_report_evidence_id": demand_report_evidence_id,
            "sku": sku,
            "max_age_days": max_age_days,
        }
        require_action_authorization(
            self.action_authorization,
            self.repo,
            action="candidate_promote",
            subject_id=candidate_ref,
            actor_id=confirmed_by,
            occurred_at=datetime.now(UTC),
            phase="request",
        )

        assessment = self.assess_candidate_research(
            candidate_ref=candidate_ref,
            candidate_name=candidate_name,
            market=market,
            category=category,
            as_of=as_of,
            demand_report_evidence_id=demand_report_evidence_id,
            max_age_days=max_age_days,
        )
        if assessment["decision"] != "request_three_quotes":
            raise ValueError("Candidate is not eligible for the three-quote sourcing gate")

        identity = json.dumps(
            {
                "candidate_ref": assessment["candidate_ref"],
                "market": assessment["market"].strip().upper(),
                "category": assessment["category"],
                "sku": sku,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        product_id = f"prd_{hashlib.sha256(identity).hexdigest()[:32]}"
        approval = next(
            (
                item
                for item in self.repo.list_approvals()
                if item.action == "candidate.promote"
                and item.resource_type == "market_candidate"
                and item.resource_id == candidate_ref
                and item.requested_by == confirmed_by
                and item.payload == approval_payload
                and item.status == ApprovalStatus.APPROVED
                and item.decided_by
            ),
            None,
        )
        require_action_authorization(
            self.action_authorization,
            self.repo,
            action="candidate_promote",
            subject_id=candidate_ref,
            actor_id=confirmed_by,
            occurred_at=datetime.now(UTC),
            phase="execute",
            approval_actor_ids=[approval.decided_by] if approval and approval.decided_by else [],
            executor_id="control_plane",
        )
        existing = next((item for item in self.repo.list_products() if item.sku == sku), None)
        if existing is not None:
            if (
                existing.id != product_id
                or existing.name != assessment["candidate_name"]
                or existing.market != "RU"
                or existing.channel != "OZON"
            ):
                raise ValueError(f"SKU already belongs to a different product: {sku}")
            product = existing
            created = False
        else:
            product = Product(
                id=product_id,
                sku=sku,
                name=assessment["candidate_name"],
                market="RU",
                channel="OZON",
            )
            with self.repo.transaction():
                self.repo.add_product(product)
                self.repo.append_event(
                    "product.candidate_sourcing_workspace_created",
                    product.id,
                    {
                        "sku": product.sku,
                        "candidate_ref": assessment["candidate_ref"],
                        "category": assessment["category"],
                        "confirmed_by": confirmed_by,
                    },
                    source_evidence_id=assessment["demand_report_evidence_id"],
                )
            created = True

        return {
            "product": product,
            "created": created,
            "candidate_ref": assessment["candidate_ref"],
            "demand_report_evidence_id": assessment["demand_report_evidence_id"],
            "evidence_ids": assessment["evidence_ids"],
            "next_gate": "sourcing_comparison_intake",
            "automatic_procurement": False,
            "automatic_listing": False,
        }

    def _accepted_demand_report(self, evidence_id: str) -> str:
        evidence_id = evidence_id.strip()
        if not evidence_id or self.demand_report_validator is None:
            raise ValueError("Candidate research requires an accepted SKU-000 demand report")
        self.demand_report_validator(evidence_id)
        return evidence_id

    @staticmethod
    def _build_observation(
        *,
        source: str,
        market: str,
        category: str,
        metric: str,
        value: Decimal,
        observed_at: str,
        source_ref: str,
        confidence: Decimal,
        dimensions: dict[str, str] | None = None,
        observation_id: str | None = None,
    ) -> MarketObservation:
        if not source_ref.strip():
            raise ValueError("Market data requires a source reference")
        value = finite_decimal(value, "Market observation value")
        confidence = finite_decimal(confidence, "Market observation confidence")
        if confidence < 0 or confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
        kwargs = {"id": observation_id} if observation_id else {}
        return MarketObservation(
            source=source,
            market=market,
            category=category,
            metric=metric,
            value=value,
            observed_at=observed_at,
            source_ref=source_ref,
            confidence=confidence,
            dimensions=dimensions or {},
            **kwargs,
        )

    @staticmethod
    def _parse_time(name: str, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _source_family(source_ref: str, source: str) -> str:
        host = urlparse(source_ref).hostname
        family = (host or source).strip().lower().strip(".")
        labels = family.split(".")
        # ponytail: two-label grouping is enough for current RU/CN sources; use a PSL only if multi-part TLDs enter scope.
        return ".".join(labels[-2:]) if len(labels) >= 2 else family
