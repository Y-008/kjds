from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .security import Principal

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "intelligence_source_adapters.json"
)
GRADES = {"A", "B", "C", "D"}
STATUSES = {"implemented", "contract_only", "blocked", "retired"}


class IntelligenceSourceAdapterRegistry:
    """Compile source-adapter policy without becoming a data extractor."""

    CONTRACT_ID = "kjds-intelligence-source-adapter-authority-v1"

    def __init__(self, *, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path
        self._registry = self._load()

    def snapshot(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        adapters = [
            self._public_adapter(item)
            for item in self._registry["adapters"]
        ]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "registry_contract_id": self._registry["contract_id"],
            "registry_version": self._registry["version"],
            "registry_sha256": self._hash(self._registry),
            "registry_effective_from": self._registry[
                "effective_from"
            ],
            "as_of": context["as_of"],
            "scope": context["scope"],
            "status": (
                "ready"
                if context["scope"]["entity_ref"]
                and context["registry_effective"]
                else "no_data"
            ),
            "adapters": adapters,
            "counts": {
                "implemented": sum(
                    item["status"] == "implemented" for item in adapters
                ),
                "contract_only": sum(
                    item["status"] == "contract_only" for item in adapters
                ),
                "external_write_enabled": 0,
            },
            "source_gaps": sorted(
                {
                    *(
                        []
                        if context["scope"]["entity_ref"]
                        else ["entity_scope_authority_missing"]
                    ),
                    *(
                        []
                        if context["registry_effective"]
                        else ["source_adapter_registry_not_effective"]
                    ),
                }
            ),
            "control_envelope": {
                **self._registry["control_envelope"],
                "capture_requires_current_entity_scope": True,
                "capture_requires_independent_evidence_binding": True,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "sales_fact_inferred": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def observation_contract(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        source_profile: str,
        marketplace: str,
    ) -> dict[str, Any]:
        staged = self.browser_capture_contract(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            source_profile=source_profile,
            marketplace=marketplace,
        )
        if not staged["scope"]["entity_ref"]:
            raise ValueError(
                "Intelligence capture requires one current entity scope grant"
            )
        return {
            **staged,
            "capture_allowed": True,
        }

    def browser_capture_contract(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        source_profile: str,
        marketplace: str,
    ) -> dict[str, Any]:
        """Freeze a page-capture adapter without inventing entity authority."""
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if not context["registry_effective"]:
            raise ValueError(
                "Intelligence adapter registry is not effective at as_of"
            )
        candidates = [
            item
            for item in self._registry["adapters"]
            if item["ingestion_surface"] == "marketplace_observation"
            and source_profile in item["observation_profiles"]
            and marketplace in item["marketplaces"]
        ]
        if len(candidates) != 1:
            raise ValueError(
                "No unique intelligence adapter matches source and marketplace"
            )
        adapter = candidates[0]
        if adapter["status"] != "implemented":
            raise ValueError(
                "Source adapter is not admitted; a provider-specific "
                "license, original Evidence and parser contract are required"
            )
        frozen = {
            "registry_sha256": self._hash(self._registry),
            "adapter": self._public_adapter(adapter),
            "scope": context["scope"],
            "as_of": context["as_of"],
        }
        return {
            **frozen,
            "adapter_contract_sha256": self._hash(frozen),
            "staging_allowed": True,
            "capture_allowed": bool(context["scope"]["entity_ref"]),
            "external_write_allowed": False,
        }

    def catalog_contract(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        marketplace: str = "ozon",
    ) -> dict[str, Any]:
        """Freeze the one admitted Catalog Evidence adapter for this scope."""
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if not context["scope"]["entity_ref"]:
            raise ValueError(
                "Catalog import requires one current entity scope grant"
            )
        if not context["registry_effective"]:
            raise ValueError(
                "Intelligence adapter registry is not effective at as_of"
            )
        candidates = [
            item
            for item in self._registry["adapters"]
            if item["ingestion_surface"] == "catalog_evidence_import"
            and marketplace in item["marketplaces"]
        ]
        if len(candidates) != 1:
            raise ValueError(
                "No unique Catalog Evidence adapter matches marketplace"
            )
        adapter = candidates[0]
        if (
            adapter["status"] != "implemented"
            or adapter.get("source_contract") != "ozon-product-read-v1"
            or adapter.get("requires_original_evidence") is not True
            or adapter.get("requires_independent_scope_binding") is not True
        ):
            raise ValueError(
                "Catalog Evidence adapter is not admitted for native import"
            )
        frozen = {
            "registry_sha256": self._hash(self._registry),
            "adapter": self._public_adapter(adapter),
            "scope": context["scope"],
            "as_of": context["as_of"],
        }
        return {
            **frozen,
            "adapter_contract_sha256": self._hash(frozen),
            "import_allowed": True,
            "external_write_allowed": False,
        }

    def _load(self) -> dict[str, Any]:
        value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if value.get("contract_id") != (
            "kjds-intelligence-source-adapter-registry-v1"
        ):
            raise ValueError("Unknown intelligence adapter registry contract")
        adapters = value.get("adapters")
        if not isinstance(adapters, list) or not adapters:
            raise ValueError("Intelligence adapter registry cannot be empty")
        ids: set[str] = set()
        observation_keys: set[tuple[str, str]] = set()
        catalog_keys: set[str] = set()
        for item in adapters:
            adapter_id = str(item.get("adapter_id", "")).strip()
            if not adapter_id or adapter_id in ids:
                raise ValueError(
                    "Intelligence adapter IDs must be non-empty and unique"
                )
            ids.add(adapter_id)
            if item.get("status") not in STATUSES:
                raise ValueError("Unknown intelligence adapter status")
            if item.get("max_source_grade") not in GRADES:
                raise ValueError("Unknown intelligence source grade")
            allowed_hosts = item.get("allowed_hosts")
            if not isinstance(allowed_hosts, list) or any(
                not isinstance(host, str)
                or not host.strip()
                or "://" in host
                or "/" in host
                for host in allowed_hosts
            ):
                raise ValueError(
                    "Intelligence adapter allowed_hosts must be DNS names"
                )
            policy = item.get("policy")
            if not isinstance(policy, dict) or any(
                policy.get(key) is not False
                for key in (
                    "cookie_or_local_storage",
                    "internal_api",
                    "captcha_bypass",
                )
            ):
                raise ValueError(
                    "Intelligence adapters must reject unsafe acquisition"
                )
            for profile in item.get("observation_profiles", []):
                for marketplace in item.get("marketplaces", []):
                    key = (str(profile), str(marketplace))
                    if key in observation_keys:
                        raise ValueError(
                            "Observation source/profile mapping is ambiguous"
                        )
                    observation_keys.add(key)
            if item.get("ingestion_surface") == "catalog_evidence_import":
                for marketplace in item.get("marketplaces", []):
                    key = str(marketplace)
                    if key in catalog_keys:
                        raise ValueError(
                            "Catalog Evidence adapter mapping is ambiguous"
                        )
                    catalog_keys.add(key)
        effective_from = self._timestamp(
            value.get("effective_from"),
            "effective_from",
        )
        if not str(value.get("version", "")).strip():
            raise ValueError("Intelligence adapter registry needs a version")
        value["effective_from"] = effective_from.isoformat()
        return value

    @staticmethod
    def _public_adapter(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "adapter_id": item["adapter_id"],
            "adapter_version": item["adapter_version"],
            "source_class": item["source_class"],
            "max_source_grade": item["max_source_grade"],
            "status": item["status"],
            "ingestion_surface": item["ingestion_surface"],
            "marketplaces": item["marketplaces"],
            "allowed_hosts": item["allowed_hosts"],
            "observation_profiles": item["observation_profiles"],
            "semantic_authority": item["semantic_authority"],
            "requires_original_evidence": item[
                "requires_original_evidence"
            ],
            "requires_independent_scope_binding": item[
                "requires_independent_scope_binding"
            ],
            "source_contract": item["source_contract"],
            "policy": item["policy"],
        }

    def _context(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
            and bool(entity_scope.get("authority_sha256"))
        )
        cutoff = as_of.astimezone(UTC)
        effective_from = self._timestamp(
            self._registry["effective_from"],
            "effective_from",
        )
        return {
            "as_of": cutoff.isoformat(),
            "registry_effective": cutoff >= effective_from,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"]) if ready else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    str(entity_scope["authority_sha256"])
                    if ready
                    else None
                ),
            },
        }

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"Intelligence adapter {field} must be ISO-8601"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                f"Intelligence adapter {field} needs a timezone"
            )
        return parsed.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
