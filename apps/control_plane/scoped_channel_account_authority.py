from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .channel_account_authority import (
    ChannelAccountAuthorizationAuthority,
)
from .channel_account_runtime_identity import (
    UnboundChannelAccountRuntimeIdentityVerifier,
)
from .security import Principal

CHANNEL_ACCOUNT_WORKSPACE_ROLES = frozenset(
    {
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    }
)


class AuthenticatedStoreMatrixAuthority:
    """Resolve current store membership from the server-owned identity map."""

    CONTRACT_ID = "kjds-authenticated-store-matrix-v1"

    def __init__(self, *, identity_resolver) -> None:
        self._identity_resolver = identity_resolver

    def current(
        self,
        *,
        principal: Principal,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        try:
            authoritative = self._identity_resolver(principal.actor_id)
        except (KeyError, RuntimeError, TypeError, ValueError):
            return {
                "contract_id": self.CONTRACT_ID,
                "status": "blocked",
                "source_gaps": ["channel_account_store_matrix_identity_unavailable"],
            }
        payload = {
            "contract_id": self.CONTRACT_ID,
            "actor_id": authoritative.actor_id,
            "tenant_ref": authoritative.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "roles": sorted(authoritative.roles),
            "membership_active": store_ref in authoritative.store_refs,
            "as_of": as_of.isoformat(),
        }
        if authoritative.tenant_ref != principal.tenant_ref:
            payload["status"] = "denied"
            payload["source_gaps"] = ["channel_account_store_matrix_tenant_denied"]
        elif store_ref not in authoritative.store_refs:
            payload["status"] = "revoked"
            payload["source_gaps"] = ["channel_account_store_matrix_membership_revoked"]
        elif not authoritative.roles.intersection(CHANNEL_ACCOUNT_WORKSPACE_ROLES):
            payload["status"] = "denied"
            payload["source_gaps"] = ["channel_account_store_matrix_role_denied"]
        else:
            payload["status"] = "ready"
            payload["source_gaps"] = []
        payload["authority_sha256"] = ScopedChannelAccountAuthorityWorkspace._hash(payload)
        return payload


class UnboundStoreMatrixAuthority:
    def current(self, **_values: Any) -> dict[str, Any]:
        return {
            "contract_id": AuthenticatedStoreMatrixAuthority.CONTRACT_ID,
            "status": "blocked",
            "source_gaps": ["channel_account_store_matrix_unbound"],
        }


class ChannelAccountMutationScopeAuthority:
    """Canonical Scope Grant + Store Matrix admission for internal services."""

    def __init__(self, *, scope_grants, store_matrix) -> None:
        self.scope_grants = scope_grants
        self.store_matrix = store_matrix

    def resolve(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        store = str(store_ref or "").strip()
        if not store or not principal.can_access_store(store):
            raise PermissionError(
                "channel account mutation store scope is not authorized"
            )
        canonical = self.scope_grants.current(
            principal=principal,
            store_ref=store,
            as_of=as_of,
        )
        if canonical.get("status") != "ready":
            raise PermissionError(
                "channel account mutation canonical Scope Grant is not ready"
            )
        entity_ref = str(canonical.get("entity_ref") or "").strip()
        authority_sha256 = str(
            canonical.get("authority_sha256") or ""
        ).strip().lower()
        supplied = (
            str(entity_scope.get("tenant_ref") or "").strip(),
            str(entity_scope.get("entity_ref") or "").strip(),
            str(entity_scope.get("store_ref") or "").strip(),
            str(entity_scope.get("authority_sha256") or "").strip().lower(),
        )
        expected = (
            principal.tenant_ref,
            entity_ref,
            store,
            authority_sha256,
        )
        if (
            entity_scope.get("status") != "ready"
            or supplied != expected
            or len(authority_sha256) != 64
            or any(character not in "0123456789abcdef" for character in authority_sha256)
        ):
            raise PermissionError(
                "channel account mutation supplied scope conflicts with canonical Scope Grant"
            )
        membership = self.store_matrix.current(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store,
            as_of=as_of,
        )
        if (
            membership.get("status") != "ready"
            or membership.get("actor_id") != principal.actor_id
            or membership.get("tenant_ref") != principal.tenant_ref
            or membership.get("entity_ref") != entity_ref
            or membership.get("store_ref") != store
            or not (
                set(membership.get("roles") or [])
                & set(principal.roles)
                & set(CHANNEL_ACCOUNT_WORKSPACE_ROLES)
            )
        ):
            raise PermissionError(
                "channel account mutation Store Matrix authority is not ready"
            )
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store,
            "scope_grant_authority_sha256": authority_sha256,
        }


class ScopedChannelAccountAuthorityWorkspace:
    """One exact-scope read seam for channel runtime identity authority."""

    CONTRACT_ID = "kjds-native-exact-scope-channel-account-authority-v1"
    ARTIFACT_CONTRACT_ID = "kjds-channel-account-authority-agent-artifact-v1"
    SOURCE_CONTRACT_ID = ChannelAccountAuthorizationAuthority.SOURCE_CONTRACT_ID
    FILTER_STATES = frozenset(
        {
            "ready",
            "revoked",
            "expired",
            "verification_stale",
            "health_blocked",
            "rate_limited",
            "schema_drift",
            "unknown_outcome",
            "evidence_blocked",
        }
    )

    def __init__(
        self,
        *,
        authority,
        adapters,
        scope_grants,
        store_matrix=None,
        runtime_identity=None,
    ) -> None:
        self.authority = authority
        self.adapters = adapters
        self.scope_grants = scope_grants
        self.store_matrix = store_matrix or UnboundStoreMatrixAuthority()
        self.runtime_identity = runtime_identity or UnboundChannelAccountRuntimeIdentityVerifier()

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        platform: str | None = None,
        account_ref: str | None = None,
        adapter_id: str | None = None,
        query: str | None = None,
        state: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not principal.roles.intersection(CHANNEL_ACCOUNT_WORKSPACE_ROLES):
            raise PermissionError("channel account workspace role is not authorized")
        if not 1 <= page_size <= 100:
            raise ValueError("channel account page_size must be between 1 and 100")
        if state not in {None, *self.FILTER_STATES}:
            raise ValueError("channel account state filter is invalid")
        cutoff = self._cutoff(as_of)
        self._require_principal_store(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        canonical_scope = self.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=cutoff,
        )
        self._require_canonical_scope_match(
            supplied=entity_scope,
            canonical=canonical_scope,
            principal=principal,
            store_ref=store_ref,
        )
        canonical_status = str(canonical_scope.get("status") or "no_data")
        canonical_entity = str(canonical_scope.get("entity_ref") or "").strip()
        if canonical_status in {
            "blocked",
            "denied",
            "stale",
            "revoked",
        }:
            blocked_scope = self._scope(
                principal=principal,
                entity_scope={
                    **canonical_scope,
                    "status": "no_data",
                },
                store_ref=store_ref,
            )
            return self._payload(
                scope=blocked_scope,
                cutoff=cutoff,
                status="blocked",
                items=[],
                total=0,
                reads=["canonical_scope_grant"],
                source_gaps=[f"channel_account_scope_grant_{canonical_status}"],
                page_size=page_size,
                next_cursor=None,
                filters={
                    "platform": self._optional(platform),
                    "account_ref": self._optional(account_ref),
                    "adapter_id": self._optional(adapter_id),
                    "query": self._optional(query),
                    "state": state,
                },
            )
        if canonical_status != "ready" or not canonical_entity:
            return self._payload(
                scope={
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": None,
                    "store_ref": str(store_ref).strip(),
                    "scope_grant_authority_sha256": None,
                },
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=["canonical_scope_grant"],
                source_gaps=["channel_account_entity_scope_missing"],
                page_size=page_size,
                next_cursor=None,
                filters={
                    "platform": self._optional(platform),
                    "account_ref": self._optional(account_ref),
                    "adapter_id": self._optional(adapter_id),
                    "query": self._optional(query),
                    "state": state,
                },
            )
        membership = self.store_matrix.current(
            principal=principal,
            entity_ref=canonical_entity,
            store_ref=str(store_ref).strip(),
            as_of=cutoff,
        )
        membership_status = str(membership.get("status") or "blocked")
        if membership_status != "ready":
            return self._payload(
                scope={
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": canonical_entity,
                    "store_ref": str(store_ref).strip(),
                    "scope_grant_authority_sha256": str(
                        canonical_scope.get("authority_sha256") or ""
                    )
                    or None,
                },
                cutoff=cutoff,
                status="blocked",
                items=[],
                total=0,
                reads=[
                    "canonical_scope_grant",
                    "canonical_store_matrix",
                ],
                source_gaps=(membership.get("source_gaps") or [f"channel_account_store_matrix_{membership_status}"]),
                page_size=page_size,
                next_cursor=None,
                filters={
                    "platform": self._optional(platform),
                    "account_ref": self._optional(account_ref),
                    "adapter_id": self._optional(adapter_id),
                    "query": self._optional(query),
                    "state": state,
                },
            )
        if (
            membership.get("actor_id") != principal.actor_id
            or membership.get("tenant_ref") != principal.tenant_ref
            or membership.get("entity_ref") != canonical_entity
            or membership.get("store_ref") != str(store_ref).strip()
            or not (
                set(membership.get("roles") or [])
                & set(principal.roles)
                & set(CHANNEL_ACCOUNT_WORKSPACE_ROLES)
            )
        ):
            raise PermissionError("channel account Store Matrix binding conflicts with principal")
        scope = self._scope(
            principal=principal,
            entity_scope=canonical_scope,
            store_ref=store_ref,
        )
        filters = {
            "platform": self._optional(platform),
            "account_ref": self._optional(account_ref),
            "adapter_id": self._optional(adapter_id),
            "query": self._optional(query),
            "state": state,
        }
        if scope["entity_ref"] is None:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=[],
                source_gaps=["channel_account_entity_scope_missing"],
                page_size=page_size,
                next_cursor=None,
                filters=filters,
            )

        source = self.authority.read_scoped_sources(
            tenant_ref=scope["tenant_ref"],
            entity_ref=str(scope["entity_ref"]),
            store_ref=scope["store_ref"],
            scope_grant_authority_sha256=str(scope["scope_grant_authority_sha256"]),
            as_of=cutoff.isoformat(),
            platform=None,
            account_ref=None,
            adapter_id=None,
        )
        source_issues = self._source_issues(
            source=source,
            scope=scope,
            cutoff=cutoff,
        )
        if source_issues:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                items=[],
                total=0,
                reads=["channel_account_authority"],
                source_gaps=source_issues,
                page_size=page_size,
                next_cursor=None,
                filters=filters,
                upstream={"channel_account_authority_snapshot_sha256": (source.get("snapshot_sha256"))},
            )
        events = list(source.get("events") or [])
        if not events:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=["channel_account_authority"],
                source_gaps=["channel_account_binding_missing"],
                page_size=page_size,
                next_cursor=None,
                filters=filters,
                upstream={"channel_account_authority_snapshot_sha256": (source["snapshot_sha256"])},
            )

        grouped: dict[
            tuple[str, str, str, str],
            list[dict[str, Any]],
        ] = defaultdict(list)
        for event in events:
            grouped[
                (
                    str(event.get("platform") or ""),
                    str(event.get("account_ref") or ""),
                    str(event.get("adapter_id") or ""),
                    str(event.get("adapter_version") or ""),
                )
            ].append(event)
        items = [
            self._item(
                key=key,
                events=value,
                principal=principal,
                entity_scope=entity_scope,
                scope=scope,
                cutoff=cutoff,
            )
            for key, value in grouped.items()
        ]
        active_by_account: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            if not item["lifecycle"]["inactive_authoritatively_verified"]:
                active_by_account[(item["platform"], item["account_ref"])].append(item)
        for duplicates in active_by_account.values():
            if len(duplicates) < 2:
                continue
            for item in duplicates:
                item["state"] = "evidence_blocked"
                item["verified_native"] = False
                item["source_gaps"] = sorted(
                    {
                        *item["source_gaps"],
                        "channel_account_dual_runtime_identity_conflict",
                    }
                )
                item["next"] = self._next("evidence_blocked")
        all_items = sorted(items, key=self._sort_key)
        authority_counts = {
            "total": len(all_items),
            **{
                item_state: sum(item["state"] == item_state for item in all_items)
                for item_state in sorted(self.FILTER_STATES)
            },
        }
        collection_blocked = any(item["state"] != "ready" for item in all_items)
        collection_status = "no_data" if not all_items else "blocked" if collection_blocked else "ready"
        collection_verified = False
        collection_gaps = sorted({gap for item in all_items for gap in item["source_gaps"]})
        items = list(all_items)
        for field in ("platform", "account_ref"):
            expected = filters[field]
            if expected:
                items = [item for item in items if item[field] == expected]
        if filters["adapter_id"]:
            items = [item for item in items if item["adapter"]["adapter_id"] == filters["adapter_id"]]
        if filters["query"]:
            needle = str(filters["query"]).casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    [
                        item["platform"],
                        item["account_ref"],
                        item["adapter"]["adapter_id"],
                        item["adapter"]["adapter_version"],
                        item.get("role_ref") or "",
                        item.get("subaccount_ref") or "",
                        *item["capabilities"],
                    ]
                ).casefold()
            ]
        if state:
            items = [item for item in items if item["state"] == state]
        items.sort(key=self._sort_key)
        total = len(items)
        cursor_snapshot = self._hash(
            {
                "source_snapshot_sha256": source["snapshot_sha256"],
                "authority_counts": authority_counts,
                "collection_status": collection_status,
                "items": [
                    {
                        "key": self._sort_key(item),
                        "latest_payload_sha256": item["latest_payload_sha256"],
                    }
                    for item in all_items
                ],
            }
        )
        if cursor:
            cursor_key = self._decode_cursor(
                cursor,
                expected_snapshot=cursor_snapshot,
            )
            items = [item for item in items if self._sort_key(item) > cursor_key]
        page = items[:page_size]
        next_cursor = (
            self._encode_cursor(
                self._sort_key(page[-1]),
                snapshot=cursor_snapshot,
            )
            if len(items) > page_size and page
            else None
        )
        return self._payload(
            scope=scope,
            cutoff=cutoff,
            status=collection_status,
            items=page,
            total=len(all_items),
            reads=["channel_account_authority"],
            source_gaps=collection_gaps,
            page_size=page_size,
            next_cursor=next_cursor,
            filters=filters,
            upstream={
                "channel_account_authority_snapshot_sha256": (source["snapshot_sha256"]),
                "adapter_registry_snapshot_sha256": self.adapters.snapshot(as_of=cutoff)["snapshot_sha256"],
                "cursor_snapshot_sha256": cursor_snapshot,
            },
            authority_counts=authority_counts,
            collection_verified=collection_verified,
            filtered_total=total,
        )

    def _item(
        self,
        *,
        key: tuple[str, str, str, str],
        events: list[dict[str, Any]],
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> dict[str, Any]:
        events.sort(
            key=lambda row: (
                int(row.get("sequence") or 0),
                str(row.get("id") or ""),
            )
        )
        issues: set[str] = set()
        first_sequence = int(events[0].get("sequence") or 0)
        expected_sequences = list(
            range(
                first_sequence,
                first_sequence + len(events),
            )
        )
        if [event.get("sequence") for event in events] != expected_sequences:
            issues.add("channel_account_sequence_drift")
        if any(
            (
                event.get("platform"),
                event.get("account_ref"),
                event.get("adapter_id"),
                event.get("adapter_version"),
            )
            != key
            for event in events
        ):
            issues.add("channel_account_binding_drift")
        for event in events:
            try:
                issues.update(
                    self.authority.validate_event(
                        event=event,
                        principal=principal,
                        entity_scope={
                            **entity_scope,
                            "status": "ready",
                            "tenant_ref": scope["tenant_ref"],
                            "entity_ref": scope["entity_ref"],
                            "store_ref": scope["store_ref"],
                            "authority_sha256": scope["scope_grant_authority_sha256"],
                        },
                        scope=scope,
                        as_of=cutoff,
                    )
                )
            except (
                KeyError,
                PermissionError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                issues.add("channel_account_evidence_blocked")
        latest = events[-1]
        inactive_authoritatively_verified = (
            latest.get("event_type")
            in {
                "authorization_revoked",
                "authorization_expired",
            }
            and not issues
        )
        try:
            runtime_probe = self.runtime_identity.verify(
                scope={
                    field: str(scope[field])
                    for field in (
                        "tenant_ref",
                        "entity_ref",
                        "store_ref",
                        "scope_grant_authority_sha256",
                    )
                },
                platform=key[0],
                account_ref=key[1],
                adapter_id=key[2],
                adapter_version=key[3],
                capabilities=sorted(latest.get("capabilities") or []),
                secret_reference_sha256=str(latest.get("secret_reference_sha256") or ""),
                credential_fingerprint_sha256=str(latest.get("credential_fingerprint_sha256") or ""),
                as_of=cutoff,
            )
        except (
            KeyError,
            PermissionError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            runtime_probe = {
                "contract_id": ("kjds-channel-account-runtime-binding-probe-v1"),
                "status": "blocked",
                "source_gaps": ["channel_account_runtime_identity_probe_failed"],
            }
        required_probe_flags = (
            "managed_store_bound",
            "lease_fresh",
            "fingerprint_match",
            "scope_match",
            "capabilities_match",
            "provider_readback_fresh_passed",
            "external_verifier_fresh_passed",
        )
        if runtime_probe.get("status") != "fresh_passed" or not all(
            runtime_probe.get(flag) is True for flag in required_probe_flags
        ):
            issues.update(runtime_probe.get("source_gaps") or ["channel_account_runtime_identity_not_verified"])
        state = self._state(
            latest=latest,
            issues=issues,
            cutoff=cutoff,
        )
        if state != "ready":
            issues.add(f"channel_account_{state}")
        return {
            "platform": key[0],
            "account_ref": key[1],
            "adapter": {
                "adapter_id": key[2],
                "adapter_version": key[3],
                "adapter_contract_sha256": latest.get("adapter_contract_sha256"),
                "authorization_source": latest.get("authorization_source"),
                "official_or_explicitly_authorized": True,
                "read_only": True,
            },
            "role_ref": latest.get("role_ref"),
            "subaccount_ref": latest.get("subaccount_ref"),
            "credential_kind": latest.get("credential_kind"),
            "credential_reference": {
                "present": latest.get("secret_reference_present") is True,
                "sha256": latest.get("secret_reference_sha256"),
                "value_returned": False,
            },
            "credential_fingerprint_sha256": latest.get("credential_fingerprint_sha256"),
            "capabilities": sorted(latest.get("capabilities") or []),
            "state": state,
            "health": {
                "status": latest.get("health_status"),
                "rate_limit_state": latest.get("rate_limit_state"),
                "external_schema_version": latest.get("external_schema_version"),
                "readback_outcome": latest.get("readback_outcome"),
                "last_verified_at": latest.get("verified_at"),
                "expires_at": latest.get("expires_at"),
            },
            "runtime_identity": {
                "contract_id": runtime_probe.get("contract_id"),
                "status": runtime_probe.get("status"),
                "managed_store_bound": (runtime_probe.get("managed_store_bound") is True),
                "lease_fresh": (runtime_probe.get("lease_fresh") is True),
                "fingerprint_match": (runtime_probe.get("fingerprint_match") is True),
                "scope_match": (runtime_probe.get("scope_match") is True),
                "capabilities_match": (runtime_probe.get("capabilities_match") is True),
                "provider_readback_fresh_passed": (runtime_probe.get("provider_readback_fresh_passed") is True),
                "external_verifier_fresh_passed": (runtime_probe.get("external_verifier_fresh_passed") is True),
                "secret_values_returned": False,
            },
            "lifecycle": {
                "event_count": len(events),
                "latest_event_type": latest.get("event_type"),
                "inactive_authoritatively_verified": (
                    inactive_authoritatively_verified
                ),
                "latest_sequence": latest.get("sequence"),
                "latest_effective_at": latest.get("effective_at"),
            },
            "governance": {
                "approval_id": latest.get("approval_id"),
                "permit_evidence_id": latest.get("permit_evidence_id"),
                "readback_evidence_id": latest.get("readback_evidence_id"),
                "kill_switch_evidence_id": latest.get("kill_switch_evidence_id"),
                "compensation_evidence_id": latest.get("compensation_evidence_id"),
            },
            "latest_evidence_id": latest.get("evidence_id"),
            "latest_payload_sha256": latest.get("payload_sha256"),
            "source_gaps": sorted(issues),
            "native_implementation_status": "implemented_unverified",
            "verified_native": False,
            "next": self._next(state),
        }

    def _state(
        self,
        *,
        latest: dict[str, Any],
        issues: set[str],
        cutoff: datetime,
    ) -> str:
        if issues:
            return "evidence_blocked"
        event_type = latest.get("event_type")
        if event_type == "authorization_revoked":
            return "revoked"
        if event_type == "authorization_expired":
            return "expired"
        if event_type == "schema_drift_observed":
            return "schema_drift"
        if event_type == "unknown_outcome_observed":
            return "unknown_outcome"
        expires = self._timestamp(latest.get("expires_at"))
        if expires <= cutoff:
            return "expired"
        if latest.get("health_status") in {
            "degraded",
            "unreachable",
            "unknown",
        }:
            return "health_blocked"
        if latest.get("rate_limit_state") in {"exhausted", "unknown"}:
            return "rate_limited"
        if latest.get("readback_outcome") in {"failed", "unknown"}:
            return "unknown_outcome"
        try:
            contract = self.adapters.resolve(
                platform=str(latest.get("platform") or ""),
                adapter_id=str(latest.get("adapter_id") or ""),
                adapter_version=str(latest.get("adapter_version") or ""),
                as_of=cutoff,
            )
        except ValueError:
            return "evidence_blocked"
        verified = self._timestamp(latest.get("verified_at"))
        if verified + timedelta(hours=int(contract["verification_ttl_hours"])) < cutoff:
            return "verification_stale"
        if (
            latest.get("secret_reference_present") is not True
            or not self._valid_sha256(latest.get("secret_reference_sha256"))
            or not self._valid_sha256(latest.get("credential_fingerprint_sha256"))
        ):
            return "evidence_blocked"
        return "ready"

    @classmethod
    def _source_issues(
        cls,
        *,
        source: dict[str, Any],
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues = []
        if source.get("contract_id") != cls.SOURCE_CONTRACT_ID:
            issues.append("channel_account_source_contract_drift")
        if source.get("scope") != {
            key: scope[key]
            for key in (
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            )
        }:
            issues.append("channel_account_source_scope_drift")
        if source.get("as_of") != cutoff.isoformat():
            issues.append("channel_account_source_as_of_drift")
        if source.get("truncated") is True:
            issues.append("channel_account_source_truncated")
        expected = cls._hash({key: value for key, value in source.items() if key != "snapshot_sha256"})
        if source.get("snapshot_sha256") != expected:
            issues.append("channel_account_source_snapshot_drift")
        return issues

    def _payload(
        self,
        *,
        scope: dict[str, Any],
        cutoff: datetime,
        status: str,
        items: list[dict[str, Any]],
        total: int,
        reads: list[str],
        source_gaps: list[str],
        page_size: int,
        next_cursor: str | None,
        filters: dict[str, Any],
        upstream: dict[str, Any] | None = None,
        authority_counts: dict[str, int] | None = None,
        collection_verified: bool | None = None,
        filtered_total: int | None = None,
    ) -> dict[str, Any]:
        counts = authority_counts or {
            "total": total,
            **{state: sum(item["state"] == state for item in items) for state in sorted(self.FILTER_STATES)},
        }
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "authority": ("reauthorization_rotation_and_internal_task_suggestion_only"),
            "accounts": [
                {
                    "platform": item["platform"],
                    "account_ref": item["account_ref"],
                    "state": item["state"],
                    "next": item["next"],
                }
                for item in items
            ],
        }
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
                "filtered_total": (total if filtered_total is None else filtered_total),
            },
            "channel_accounts": items,
            "source_gaps": source_gaps,
            "upstream": upstream or {},
            "native_implementation_status": "implemented_unverified",
            "verified_native": (
                bool(items) and all(item["verified_native"] for item in items)
                if collection_verified is None
                else collection_verified
            ),
            "agent_artifact": {
                **artifact,
                "artifact_sha256": self._hash(artifact),
                "reauthorization_allowed": False,
                "credential_rotation_allowed": False,
                "secret_read_allowed": False,
                "scope_expansion_allowed": False,
                "authorization_change_allowed": False,
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
                "external_verification_allowed": False,
                "customer_contact_allowed": False,
                "platform_contact_allowed": False,
                "fictional_authority_allowed": False,
                "external_write_allowed": False,
            },
            "governed_action_contract": {
                "production_workflow_status": "mutation_gated",
                "policy_mode": "policy_only",
                "internal_governance_api_exposed": True,
                "provider_mutation_api_exposed": False,
                "provider_mutation_enabled": False,
                "actions": [
                    "authorization_grant",
                    "authorization_refresh",
                    "credential_rotation",
                    "authorization_revocation",
                    "external_verification",
                ],
                "requires": [
                    "independent_approval",
                    "one_time_permit",
                    "immutable_official_or_authorized_readback",
                    "kill_switch_release",
                    "compensation_plan",
                ],
                "projection_grants_permission": False,
                "contract_only": True,
            },
            "control_envelope": {
                "read_only_projection": True,
                "upstream_reads": reads,
                "client_recalculation_allowed": False,
                "append_only_authorization_authority": True,
                "tenant_truth_duplicated": False,
                "entity_truth_duplicated": False,
                "store_truth_duplicated": False,
                "secret_reference_returned": False,
                "plaintext_secret_stored": False,
                "cookie_allowed": False,
                "internal_token_allowed": False,
                "device_session_allowed": False,
                "private_endpoint_allowed": False,
                "captcha_bypass_allowed": False,
                "access_control_bypass_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _require_principal_store(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> None:
        store = str(store_ref or "").strip()
        if not store or not principal.can_access_store(store):
            raise PermissionError("channel account store scope is invalid")
        supplied_tenant = str(entity_scope.get("tenant_ref") or principal.tenant_ref).strip()
        supplied_store = str(entity_scope.get("store_ref") or store).strip()
        if supplied_tenant != principal.tenant_ref or supplied_store != store:
            raise PermissionError("caller-supplied channel account scope is invalid")

    @staticmethod
    def _require_canonical_scope_match(
        *,
        supplied: dict[str, Any],
        canonical: dict[str, Any],
        principal: Principal,
        store_ref: str,
    ) -> None:
        if canonical.get("status") != "ready":
            if supplied.get("status") == "ready":
                raise PermissionError("caller scope is not backed by canonical Scope Grant")
            return
        if supplied.get("status") != "ready":
            raise PermissionError("caller scope omits a canonical ready Scope Grant")
        expected = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(canonical.get("entity_ref") or "").strip(),
            "store_ref": store_ref,
            "authority_sha256": str(canonical.get("authority_sha256") or "").strip().lower(),
        }
        if any(
            str(supplied.get(key) or "").strip().lower() != str(value).strip().lower()
            for key, value in expected.items()
        ):
            raise PermissionError("caller scope conflicts with canonical Scope Grant")

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        store = str(store_ref or "").strip()
        if not store or not principal.can_access_store(store):
            raise PermissionError("channel account store scope is invalid")
        tenant_ref = str(entity_scope.get("tenant_ref") or principal.tenant_ref).strip()
        if tenant_ref != principal.tenant_ref:
            raise PermissionError("channel account tenant scope is invalid")
        granted_store = str(entity_scope.get("store_ref") or store).strip()
        if granted_store != store:
            raise PermissionError("channel account store scope is invalid")
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip().lower()
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_ref)
            and ScopedChannelAccountAuthorityWorkspace._valid_sha256(authority)
        )
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref if ready else None,
            "store_ref": store,
            "scope_grant_authority_sha256": authority if ready else None,
        }

    @staticmethod
    def _cutoff(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("channel account as_of must include timezone")
        cutoff = value.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise ValueError("channel account as_of cannot be in the future")
        return cutoff

    @staticmethod
    def _next(state: str) -> str:
        return {
            "ready": "Continue read-only monitoring; do not expose secrets.",
            "revoked": "Suggest a governed reauthorization review.",
            "expired": "Suggest a governed refresh or reauthorization review.",
            "verification_stale": "Suggest an independently governed verification.",
            "health_blocked": "Create an internal adapter-health task.",
            "rate_limited": "Wait for the official rate-limit window.",
            "schema_drift": "Block runtime use and review the adapter contract.",
            "unknown_outcome": "Reconcile immutable Readback before retry.",
            "evidence_blocked": "Repair exact-scope authority Evidence.",
        }[state]

    @staticmethod
    def _optional(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _sort_key(
        item: dict[str, Any],
    ) -> tuple[str, str, str, str]:
        return (
            item["platform"],
            item["account_ref"],
            item["adapter"]["adapter_id"],
            item["adapter"]["adapter_version"],
        )

    @classmethod
    def _encode_cursor(
        cls,
        value: tuple[str, str, str, str],
        *,
        snapshot: str,
    ) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(
                {
                    "key": list(value),
                    "snapshot_sha256": snapshot,
                },
                separators=(",", ":"),
            ).encode()
        ).decode()

    @classmethod
    def _decode_cursor(
        cls,
        value: str,
        *,
        expected_snapshot: str,
    ) -> tuple[str, str, str, str]:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value.encode()))
            key = decoded["key"]
            if (
                not isinstance(decoded, dict)
                or decoded.get("snapshot_sha256") != expected_snapshot
                or not isinstance(key, list)
                or len(key) != 4
                or not all(isinstance(item, str) for item in key)
            ):
                raise ValueError
            return key[0], key[1], key[2], key[3]
        except (
            KeyError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("channel account cursor is invalid or stale") from exc

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("channel account event timestamp is invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("channel account event timestamp must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)

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
