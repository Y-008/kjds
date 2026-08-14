from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from .managed_credential_leases import (
    ManagedCredentialLeaseProvision,
    SqlManagedCredentialLeaseStore,
)
from .provider_readback_verifier import (
    PROVIDER_READBACK_CONTRACT_ID,
    ProviderReadbackVerifier,
)


class LeaseProvisioningSeam:
    """Provision one authoritative managed lease from verified readback artifacts.

    The seam re-runs the pure ProviderReadbackVerifier on the captured bundle
    and summary with the exact lease facts, requires a passing, fresh,
    independently-verified observation, and only then calls the store's sole
    write seam.  Every input is server-owned or artifact-bound; the operator
    never supplies scope/fingerprint/capability hashes by hand.
    """

    def __init__(
        self,
        *,
        store: SqlManagedCredentialLeaseStore,
        verifier: ProviderReadbackVerifier,
    ) -> None:
        self._store = store
        self._verifier = verifier

    def preflight(
        self,
        *,
        readback_dir: Path,
        lease_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        capabilities: set[str],
        authorization_epoch: int,
        secret_reference: str,
        client_id: str,
        api_key: str,
        verifier_actor: str,
        provisioner_actor: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Return a verdict; no row is written and no secret is returned."""
        bundle = (readback_dir / "readback-bundle.json").read_bytes()
        summary = json.loads(
            (readback_dir / "readback-summary.json").read_text(encoding="utf-8")
        )
        observation_path = readback_dir / "readback-observation.json"
        if not observation_path.is_file():
            return self._verdict(False, ["READBACK_OBSERVATION_MISSING"], None)
        stored_observation = json.loads(observation_path.read_text(encoding="utf-8"))
        try:
            verification_as_of = self._parse_timestamp(
                stored_observation.get("observed_at") or as_of
            )
        except (TypeError, ValueError):
            verification_as_of = self._aware(as_of)
        bundle_sha256 = hashlib.sha256(bundle).hexdigest()
        fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
            client_id=client_id,
            api_key=api_key,
            platform=platform,
            account_ref=account_ref,
        )
        facts = {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "platform": platform,
            "account_ref": account_ref,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "required_capability": summary.get("required_capability"),
            "credential_fingerprint_sha256": fingerprint,
            "secret_reference_sha256": hashlib.sha256(
                secret_reference.encode()
            ).hexdigest(),
            "provider_readback_verified_at": summary.get("observed_at"),
        }
        observation = self._verifier.verify(
            summary=summary,
            bundle_bytes=bundle,
            facts=facts,
            verifier_actor=verifier_actor,
            provisioner_actor=provisioner_actor,
            as_of=verification_as_of,
        )
        blockers = list(observation.get("blockers") or [])
        if observation.get("contract_id") != PROVIDER_READBACK_CONTRACT_ID:
            blockers.append("READBACK_VERIFIER_CONTRACT_DRIFT")
        if stored_observation.get("observation_sha256") != observation.get(
            "observation_sha256"
        ):
            blockers.append("READBACK_OBSERVATION_HASH_DRIFT")
        if (
            self._aware(as_of) - verification_as_of
        ).total_seconds() > 900:
            blockers.append("READBACK_OBSERVATION_STALE")
        if self._store.get(lease_id) is not None:
            blockers.append("MANAGED_LEASE_ALREADY_EXISTS")
        if str(summary.get("response_bundle_sha256") or "") != bundle_sha256:
            blockers.append("READBACK_BUNDLE_SUMMARY_DRIFT")
        if str(summary.get("credential_fingerprint_sha256") or "") != fingerprint:
            blockers.append("READBACK_FINGERPRINT_MATERIAL_DRIFT")
        if blockers:
            return self._verdict(False, sorted(set(blockers)), observation)
        return self._verdict(True, [], observation)

    def provision(
        self,
        *,
        readback_dir: Path,
        lease_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        capabilities: set[str],
        authorization_epoch: int,
        secret_reference: str,
        client_id: str,
        api_key: str,
        verifier_actor: str,
        provisioner_actor: str,
        created_by: str,
        as_of: datetime,
        lease_ttl_seconds: int = 86_400,
    ) -> dict[str, Any]:
        verdict = self.preflight(
            readback_dir=readback_dir,
            lease_id=lease_id,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            capabilities=capabilities,
            authorization_epoch=authorization_epoch,
            secret_reference=secret_reference,
            client_id=client_id,
            api_key=api_key,
            verifier_actor=verifier_actor,
            provisioner_actor=provisioner_actor,
            as_of=as_of,
        )
        if not verdict["provision_allowed"]:
            raise PermissionError(
                "Managed lease provisioning is blocked: "
                + ", ".join(verdict["blockers"])
            )
        summary = json.loads(
            (readback_dir / "readback-summary.json").read_text(encoding="utf-8")
        )
        bundle_sha256 = hashlib.sha256(
            (readback_dir / "readback-bundle.json").read_bytes()
        ).hexdigest()
        observed_at = self._parse_timestamp(summary.get("observed_at"))
        provision = ManagedCredentialLeaseProvision(
            lease_id=lease_id,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            capabilities=capabilities,
            authorization_epoch=authorization_epoch,
            secret_reference=secret_reference,
            client_id=client_id,
            api_key=api_key,
            issued_at=as_of,
            expires_at=self._aware(as_of) + timedelta(seconds=lease_ttl_seconds),
            provider_readback_sha256=bundle_sha256,
            provider_readback_verified_at=observed_at,
            external_verifier_observation_sha256=verdict["observation_sha256"],
            external_verifier_verified_at=self._aware(as_of),
        )
        record = self._store.upsert_authoritative(
            provision,
            created_by=created_by,
        )
        return {
            "lease_id": record.lease_id,
            "tenant_ref": record.tenant_ref,
            "entity_ref": record.entity_ref,
            "store_ref": record.store_ref,
            "platform": record.platform,
            "account_ref": record.account_ref,
            "adapter_id": record.adapter_id,
            "adapter_version": record.adapter_version,
            "capabilities": sorted(record.capabilities),
            "authorization_epoch": record.authorization_epoch,
            "credential_fingerprint_sha256": record.credential_fingerprint_sha256,
            "provider_readback_sha256": record.provider_readback_sha256,
            "external_verifier_observation_sha256": (
                record.external_verifier_observation_sha256
            ),
            "credential_material_returned": False,
        }

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _verdict(
        allowed: bool,
        blockers: list[str],
        observation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "provision_allowed": allowed,
            "blockers": blockers,
            "observation_sha256": (
                observation.get("observation_sha256") if observation else None
            ),
        }
