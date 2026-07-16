from __future__ import annotations

from decimal import Decimal

from .domain import MarketObservation, OpportunityInsight
from .repository import Repository


class MarketIntelligenceService:
    """Turns source-attributed observations into reproducible opportunity scores."""

    def __init__(self, repository: Repository) -> None:
        self.repo = repository

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
        if not source_ref.strip():
            raise ValueError("Market data requires a source reference")
        if confidence < 0 or confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
        observation = MarketObservation(
            source=source,
            market=market,
            category=category,
            metric=metric,
            value=value,
            observed_at=observed_at,
            source_ref=source_ref,
            confidence=confidence,
            dimensions=dimensions or {},
        )
        self.repo.add_observation(observation)
        self.repo.append_event("market.observation_ingested", observation.id, {"metric": metric, "source": source})
        return observation

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
        self.repo.add_opportunity(insight)
        self.repo.append_event("market.opportunity_scored", insight.id, {"score": str(score)})
        return insight
