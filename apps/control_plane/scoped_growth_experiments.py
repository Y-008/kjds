from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class ScopedGrowthExperimentWorkspace:
    """Project governed growth readiness behind one exact-scope seam."""

    CONTRACT_ID = "kjds-native-exact-scope-growth-experiment-v1"
    ARTIFACT_CONTRACT_ID = "kjds-growth-experiment-agent-artifact-v1"
    ACTIONS = frozenset({"price", "promotion", "advertising"})

    UPSTREAM_CONTRACTS = {
        "pim": "kjds-native-exact-scope-pim-workspace-v1",
        "listing": "kjds-native-exact-scope-listing-lifecycle-v1",
        "inventory": "kjds-native-scoped-inventory-fulfillment-v1",
        "oms": "kjds-native-scoped-oms-v1",
        "profit": "kjds-native-exact-scope-actual-profit-ledger-v1",
        "market": "kjds-scoped-marketplace-observation-v1",
        "customer_service": "kjds-native-exact-scope-customer-service-v1",
    }

    def __init__(
        self,
        *,
        pim,
        listing,
        inventory,
        oms,
        profit,
        market,
        customer_service,
    ) -> None:
        self.pim = pim
        self.listing = listing
        self.inventory = inventory
        self.oms = oms
        self.profit = profit
        self.market = market
        self.customer_service = customer_service

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        query: str | None = None,
        action: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if action not in {None, *self.ACTIONS}:
            raise ValueError("growth experiment action filter is invalid")
        if not 1 <= page_size <= 100:
            raise ValueError("growth experiment page_size must be between 1 and 100")
        cutoff = self._cutoff(as_of)
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        filters = {"query": str(query or "").strip() or None, "action": action}
        if scope["entity_ref"] is None:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                filters=filters,
                experiments=[],
                counts=self._counts([]),
                page_size=page_size,
                next_cursor=None,
                source_gaps=["growth_entity_scope_missing"],
                upstream_read=False,
            )

        upstream = {
            "pim": self.pim.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                query=filters["query"],
                page_size=100,
            ),
            "listing": self.listing.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                query=filters["query"],
                page_size=100,
            ),
            "inventory": self.inventory.workspace(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=500,
            ),
            "oms": self.oms.workspace(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=500,
            ),
            "profit": self.profit.snapshot(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                grain="sku",
                page_size=500,
                query=filters["query"],
            ),
            "market": self.market.latest(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                marketplace="ozon",
                limit=1000,
            ),
            "customer_service": self.customer_service.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                query=filters["query"],
                page_size=100,
            ),
        }
        issues = self._upstream_issues(
            upstream=upstream,
            scope=scope,
            cutoff=cutoff,
        )
        if issues:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                filters=filters,
                experiments=[],
                counts=self._counts([]),
                page_size=page_size,
                next_cursor=None,
                source_gaps=issues,
                upstream_read=True,
                upstream_snapshots=self._snapshots(upstream),
            )

        pim = upstream["pim"]
        groups = list(pim.get("product_groups", []))
        if not groups:
            gaps = {
                gap
                for projection in upstream.values()
                for gap in projection.get("source_gaps", [])
            }
            gaps.add("canonical_pim_product_missing")
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                filters=filters,
                experiments=[],
                counts=self._counts([]),
                page_size=page_size,
                next_cursor=None,
                source_gaps=sorted(gaps),
                upstream_read=True,
                upstream_snapshots=self._snapshots(upstream),
            )
        if pim.get("status") == "no_data":
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                filters=filters,
                experiments=[],
                counts=self._counts([]),
                page_size=page_size,
                next_cursor=None,
                source_gaps=["growth_pim_status_data_conflict"],
                upstream_read=True,
                upstream_snapshots=self._snapshots(upstream),
            )
        groups.sort(
            key=lambda item: (
                str(item.get("product", {}).get("sku") or ""),
                str(item.get("product", {}).get("id") or ""),
            )
        )
        cursor_key = self._cursor(cursor)
        if cursor_key:
            groups = [
                item
                for item in groups
                if self._group_key(item) > cursor_key
            ]
        page = groups[:page_size]
        if not page:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                filters=filters,
                experiments=[],
                counts=self._counts([]),
                page_size=page_size,
                next_cursor=None,
                source_gaps=["growth_page_empty"],
                upstream_read=True,
                upstream_snapshots=self._snapshots(upstream),
            )
        next_cursor = (
            self._encode_cursor(self._group_key(page[-1]))
            if len(groups) > page_size and page
            else None
        )
        indexes = self._indexes(upstream)
        experiments = [
            self._experiment(group, action=action, indexes=indexes)
            for group in page
        ]
        counts = self._counts(experiments)
        gaps = {
            gap
            for projection in upstream.values()
            for gap in projection.get("source_gaps", [])
        }
        status = (
            "blocked"
            if experiments and counts["blocked"] == len(experiments)
            else "partial"
            if gaps or counts["partial"]
            else "ready"
        )
        return self._payload(
            scope=scope,
            cutoff=cutoff,
            status=status,
            filters=filters,
            experiments=experiments,
            counts=counts,
            page_size=page_size,
            next_cursor=next_cursor,
            source_gaps=sorted(gaps),
            upstream_read=True,
            upstream_snapshots=self._snapshots(upstream),
        )

    def _upstream_issues(
        self,
        *,
        upstream: dict[str, dict[str, Any]],
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues: set[str] = set()
        for name, projection in upstream.items():
            if projection.get("contract_id") != self.UPSTREAM_CONTRACTS[name]:
                issues.add(f"growth_{name}_contract_drift")
            actual_scope = projection.get("scope", {})
            if any(
                actual_scope.get(key) != scope[key]
                for key in ("tenant_ref", "entity_ref", "store_ref")
            ):
                issues.add(f"growth_{name}_scope_drift")
            if projection.get("as_of") != cutoff.isoformat():
                issues.add(f"growth_{name}_as_of_drift")
            snapshot = projection.get("snapshot_sha256")
            if not isinstance(snapshot, str) or len(snapshot) != 64:
                issues.add(f"growth_{name}_snapshot_invalid")
            if projection.get("status") == "blocked":
                issues.add(f"growth_{name}_blocked")
        return sorted(issues)

    @staticmethod
    def _snapshots(
        upstream: dict[str, dict[str, Any]],
    ) -> dict[str, str | None]:
        return {
            f"{name}_snapshot_sha256": projection.get("snapshot_sha256")
            for name, projection in sorted(upstream.items())
        }

    @staticmethod
    def _indexes(
        upstream: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}
        sources = {
            "listing": upstream["listing"].get("items", []),
            "inventory": upstream["inventory"].get("sku_summaries", []),
            "oms": upstream["oms"].get("orders", []),
            "profit": upstream["profit"].get("items", []),
            "market": upstream["market"].get("items", []),
            "customer_service": upstream["customer_service"].get("cases", []),
        }
        for name, rows in sources.items():
            by_product: dict[str, list[dict[str, Any]]] = {}
            by_sku: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                product = row.get("product") or {}
                product_id = str(
                    row.get("product_id")
                    or row.get("target_product_id")
                    or product.get("id")
                    or ""
                )
                sku = str(row.get("sku") or product.get("sku") or "")
                if product_id:
                    by_product.setdefault(product_id, []).append(row)
                if sku:
                    by_sku.setdefault(sku, []).append(row)
            indexes[name] = {"product": by_product, "sku": by_sku}
        return indexes

    @staticmethod
    def _matches(
        indexes: dict[str, dict[str, list[dict[str, Any]]]],
        name: str,
        product_id: str,
        sku: str,
    ) -> list[dict[str, Any]]:
        rows = indexes[name]["product"].get(product_id, [])
        return rows or indexes[name]["sku"].get(sku, [])

    def _experiment(
        self,
        group: dict[str, Any],
        *,
        action: str | None,
        indexes: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> dict[str, Any]:
        product = group.get("product", {})
        product_id = str(product.get("id") or "")
        sku = str(product.get("sku") or "")
        signals = {
            name: self._matches(indexes, name, product_id, sku)
            for name in indexes
        }
        missing = [
            name
            for name, rows in signals.items()
            if not rows
        ]
        if not group.get("listings"):
            missing.append("canonical_listing")
        actions = {}
        for name in sorted(self.ACTIONS):
            if action is None or action == name:
                actions[name] = {
                    "status": "ready" if not missing else "blocked",
                    "missing_authorities": sorted(missing),
                    "shadow_experiment_allowed": True,
                    "external_write_allowed": False,
                }
        row_status = "ready" if not missing else "blocked"
        return {
            "product": {
                "id": product_id,
                "sku": sku,
                "name": product.get("name"),
            },
            "listings": group.get("listings", []),
            "pim_readiness": group.get("readiness", {}),
            "signals": {
                "listing_lifecycle": signals["listing"],
                "inventory": signals["inventory"],
                "orders": signals["oms"],
                "actual_cm3_downside_15": signals["profit"],
                "formal_market_observations": signals["market"],
                "redacted_customer_service_reviews": signals[
                    "customer_service"
                ],
            },
            "actions": actions,
            "status": row_status,
            "owner": "growth_operator",
            "next": (
                "independent experiment review"
                if row_status == "ready"
                else "collect missing exact-scope authorities"
            ),
        }

    @staticmethod
    def _group_key(group: dict[str, Any]) -> tuple[str, str]:
        product = group.get("product", {})
        return str(product.get("sku") or ""), str(product.get("id") or "")

    def _cursor(self, cursor: str | None) -> tuple[str, str] | None:
        if not cursor:
            return None
        try:
            value = json.loads(
                __import__("base64").urlsafe_b64decode(
                    cursor.encode()
                ).decode()
            )
        except Exception as exc:
            raise ValueError("growth experiment cursor is invalid") from exc
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("growth experiment cursor is invalid")
        return str(value[0]), str(value[1])

    @staticmethod
    def _encode_cursor(key: tuple[str, str]) -> str:
        import base64

        return base64.urlsafe_b64encode(
            json.dumps(list(key), separators=(",", ":")).encode()
        ).decode()

    @staticmethod
    def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(rows),
            "ready": sum(row["status"] == "ready" for row in rows),
            "partial": sum(row["status"] == "partial" for row in rows),
            "blocked": sum(row["status"] == "blocked" for row in rows),
        }

    def _payload(
        self,
        *,
        scope: dict[str, Any],
        cutoff: datetime,
        status: str,
        filters: dict[str, Any],
        experiments: list[dict[str, Any]],
        counts: dict[str, int],
        page_size: int,
        next_cursor: str | None,
        source_gaps: list[str],
        upstream_read: bool,
        upstream_snapshots: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        artifact_basis = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "products": [
                {"id": row["product"]["id"], "status": row["status"]}
                for row in experiments
            ],
            "authority": "recommendation_shadow_internal_task_only",
        }
        artifact_sha = self._hash(artifact_basis)
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": cutoff.isoformat(),
            "scope": scope,
            "filters": filters,
            "counts": counts,
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "experiments": experiments,
            "source_gaps": source_gaps,
            "agent_artifact": {
                **artifact_basis,
                "artifact_sha256": artifact_sha,
                "price_write_allowed": False,
                "promotion_create_allowed": False,
                "advertising_spend_allowed": False,
                "customer_contact_allowed": False,
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
                "external_write_allowed": False,
            },
            "control_envelope": {
                "read_only_projection": True,
                "upstream_read": upstream_read,
                "client_recalculation_allowed": False,
                "legacy_marketplace_growth_used": False,
                "price_changed": False,
                "promotion_created": False,
                "advertising_spend_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
                "private_erp_interface_allowed": False,
            },
            "upstream": upstream_snapshots or {},
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        tenant_ref = str(
            entity_scope.get("tenant_ref") or principal.tenant_ref
        ).strip()
        entity_ref = str(entity_scope.get("entity_ref") or "").strip() or None
        granted_store = str(
            entity_scope.get("store_ref") or store_ref
        ).strip()
        if not tenant_ref or tenant_ref != principal.tenant_ref:
            raise PermissionError("growth tenant scope is invalid")
        if granted_store and granted_store != store_ref:
            raise PermissionError("growth store scope is invalid")
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
        }

    @staticmethod
    def _cutoff(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("growth as_of must include timezone")
        value = value.astimezone(UTC)
        if value > datetime.now(UTC):
            raise ValueError("growth as_of cannot be in the future")
        return value

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
