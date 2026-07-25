from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from .domain import new_id

MARKETPLACE_GROWTH_SOURCES = frozenset(
    {"ozon_seller_api", "ozon_export", "operator_verified"}
)


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class InMemoryMarketplaceGrowthStore:
    """Test adapter for the marketplace growth workspace interface."""

    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, str], dict[str, Any]] = {}

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        key = (snapshot["source"], snapshot["idempotency_key"])
        existing = self.snapshots.get(key)
        if existing is not None:
            if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
                raise ValueError(
                    "Marketplace growth snapshot idempotency conflict; "
                    "changed facts require a new idempotency key"
                )
            return deepcopy(existing)
        self.snapshots[key] = deepcopy(snapshot)
        return deepcopy(snapshot)

    def latest_observations(self, *, limit: int) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for snapshot in self.snapshots.values():
            for observation in snapshot["observations"]:
                candidates.append(
                    {
                        **deepcopy(observation),
                        "snapshot_id": snapshot["id"],
                        "snapshot_source": snapshot["source"],
                        "captured_by": snapshot["captured_by"],
                        "captured_at": snapshot["captured_at"],
                    }
                )
        candidates.sort(
            key=lambda row: (
                row["marketplace_sku"],
                row["observed_at"],
                row["captured_at"],
                row["snapshot_id"],
            ),
            reverse=True,
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in candidates:
            latest.setdefault(row["marketplace_sku"], row)
        return sorted(
            latest.values(),
            key=lambda row: (row["observed_at"], row["marketplace_sku"]),
            reverse=True,
        )[:limit]


class SqlMarketplaceGrowthStore:
    """PostgreSQL adapter; all persistence stays behind the workspace seam."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self.engine.begin() as connection:
            inserted_id = connection.execute(
                text(
                    """
                    INSERT INTO marketplace_growth_snapshots (
                        id, source, idempotency_key, snapshot_hash, captured_by,
                        captured_at, observation_count
                    ) VALUES (
                        :id, :source, :idempotency_key, :snapshot_hash, :captured_by,
                        :captured_at, :observation_count
                    )
                    ON CONFLICT (source, idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    key: snapshot[key]
                    for key in (
                        "id",
                        "source",
                        "idempotency_key",
                        "snapshot_hash",
                        "captured_by",
                        "captured_at",
                        "observation_count",
                    )
                },
            ).scalar_one_or_none()
            if inserted_id is None:
                existing = (
                    connection.execute(
                        text(
                            """
                            SELECT id, snapshot_hash
                            FROM marketplace_growth_snapshots
                            WHERE source = :source
                              AND idempotency_key = :idempotency_key
                            """
                        ),
                        {
                            "source": snapshot["source"],
                            "idempotency_key": snapshot["idempotency_key"],
                        },
                    )
                    .mappings()
                    .one()
                )
                if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
                    raise ValueError(
                        "Marketplace growth snapshot idempotency conflict; "
                        "changed facts require a new idempotency key"
                    )
                return self._snapshot(connection, existing["id"])
            connection.execute(
                text(
                    """
                    INSERT INTO marketplace_growth_observations (
                        snapshot_id, marketplace_sku, scenario_id, category,
                        competitor_prices_rub_json, stock, review_count, orders_14d,
                        rating_decimal, content_score_decimal, conversion_rate_decimal,
                        compliance_risk, observed_at, evidence_ids_json, observation_hash
                    ) VALUES (
                        :snapshot_id, :marketplace_sku, :scenario_id, :category,
                        CAST(:competitor_prices_rub_json AS jsonb), :stock, :review_count,
                        :orders_14d, :rating, :content_score, :conversion_rate,
                        :compliance_risk, :observed_at,
                        CAST(:evidence_ids_json AS jsonb), :observation_hash
                    )
                    """
                ),
                [
                    {
                        **observation,
                        "snapshot_id": snapshot["id"],
                        "competitor_prices_rub_json": json.dumps(
                            observation["competitor_prices_rub"]
                        ),
                        "evidence_ids_json": json.dumps(observation["evidence_ids"]),
                    }
                    for observation in snapshot["observations"]
                ],
            )
            return deepcopy(snapshot)

    def latest_observations(self, *, limit: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM (
                            SELECT
                                observation.*,
                                snapshot.source AS snapshot_source,
                                snapshot.captured_by,
                                snapshot.captured_at,
                                row_number() OVER (
                                    PARTITION BY observation.marketplace_sku
                                    ORDER BY observation.observed_at DESC,
                                             snapshot.captured_at DESC,
                                             snapshot.id DESC
                                ) AS latest_rank
                            FROM marketplace_growth_observations AS observation
                            JOIN marketplace_growth_snapshots AS snapshot
                              ON snapshot.id = observation.snapshot_id
                        ) AS ranked
                        WHERE latest_rank = 1
                        ORDER BY observed_at DESC, marketplace_sku
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
        return [self._observation(row) for row in rows]

    def _snapshot(self, connection, snapshot_id: str) -> dict[str, Any]:
        snapshot = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM marketplace_growth_snapshots
                    WHERE id = :snapshot_id
                    """
                ),
                {"snapshot_id": snapshot_id},
            )
            .mappings()
            .one()
        )
        observations = (
            connection.execute(
                text(
                    """
                    SELECT *
                    FROM marketplace_growth_observations
                    WHERE snapshot_id = :snapshot_id
                    ORDER BY marketplace_sku
                    """
                ),
                {"snapshot_id": snapshot_id},
            )
            .mappings()
            .all()
        )
        return {
            "id": snapshot["id"],
            "source": snapshot["source"],
            "idempotency_key": snapshot["idempotency_key"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "captured_by": snapshot["captured_by"],
            "captured_at": snapshot["captured_at"].isoformat(),
            "observation_count": snapshot["observation_count"],
            "observations": [self._observation(row) for row in observations],
        }

    @staticmethod
    def _observation(row) -> dict[str, Any]:
        return {
            "scenario_id": row["scenario_id"],
            "marketplace_sku": row["marketplace_sku"],
            "category": row["category"],
            "competitor_prices_rub": [
                str(value) for value in row["competitor_prices_rub_json"]
            ],
            "stock": row["stock"],
            "review_count": row["review_count"],
            "orders_14d": row["orders_14d"],
            "rating": str(row["rating_decimal"]),
            "content_score": str(row["content_score_decimal"]),
            "conversion_rate": (
                str(row["conversion_rate_decimal"])
                if row["conversion_rate_decimal"] is not None
                else None
            ),
            "compliance_risk": row["compliance_risk"],
            "observed_at": row["observed_at"].isoformat(),
            "evidence_ids": list(row["evidence_ids_json"]),
            "observation_hash": row["observation_hash"],
            "snapshot_id": row["snapshot_id"],
            **(
                {
                    "snapshot_source": row["snapshot_source"],
                    "captured_by": row["captured_by"],
                    "captured_at": row["captured_at"].isoformat(),
                }
                if "snapshot_source" in row
                else {}
            ),
        }


class MarketplaceGrowthWorkspace:
    """Capture facts and build latest-store plans through one small interface."""

    def __init__(self, *, planner, store) -> None:
        self.planner = planner
        self.store = store

    def capture_snapshot(
        self,
        *,
        source: str,
        idempotency_key: str,
        observations: list[dict[str, Any]],
        captured_by: str,
    ) -> dict[str, Any]:
        normalized_source = source.strip().lower()
        if normalized_source not in MARKETPLACE_GROWTH_SOURCES:
            raise ValueError("Unsupported marketplace growth snapshot source")
        key = idempotency_key.strip()
        if not key:
            raise ValueError("Marketplace growth snapshot requires an idempotency key")
        actor = captured_by.strip()
        if not actor:
            raise ValueError("Marketplace growth snapshot requires an accountable actor")
        if not observations:
            raise ValueError("Marketplace growth snapshot requires observations")

        captured_at = datetime.now(UTC).isoformat()
        normalized = [
            self.planner.normalize_observation(
                observation, evaluated_at=captured_at
            )
            for observation in observations
        ]
        duplicate_skus = self.planner._duplicates(
            item["marketplace_sku"] for item in normalized
        )
        if duplicate_skus:
            raise ValueError(
                "Marketplace growth snapshot contains duplicate SKUs: "
                + ", ".join(duplicate_skus)
            )
        normalized.sort(key=lambda item: item["marketplace_sku"])
        normalized_with_hashes = [
            {**item, "observation_hash": _canonical_hash(item)} for item in normalized
        ]
        snapshot_hash = _canonical_hash(
            {
                "source": normalized_source,
                "observations": normalized_with_hashes,
            }
        )
        snapshot = {
            "id": new_id("mgs"),
            "source": normalized_source,
            "idempotency_key": key,
            "snapshot_hash": snapshot_hash,
            "captured_by": actor,
            "captured_at": captured_at,
            "observation_count": len(normalized_with_hashes),
            "observations": normalized_with_hashes,
        }
        return self.store.save_snapshot(snapshot)

    def plan_portfolio(self, **kwargs) -> dict[str, Any]:
        """Keep the original manual-planning contract behind the same module."""
        return self.planner.plan_portfolio(**kwargs)

    def latest_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("Marketplace growth observation limit must be 1 to 1000")
        return self.store.latest_observations(limit=limit)

    def plan_latest(
        self,
        *,
        target_cm3_rate: Decimal,
        created_by: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        observations = self.latest_observations(limit=1000)
        if not observations:
            raise ValueError(
                "No persisted marketplace observations are available for planning"
            )
        return self.planner.plan_portfolio(
            observations=observations,
            target_cm3_rate=target_cm3_rate,
            created_by=created_by,
            as_of=as_of,
        )
