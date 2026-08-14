from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol

RUNTIME_LEASE_CONTRACT_ID = "kjds-channel-account-managed-credential-lease-v2"
RUNTIME_PROBE_CONTRACT_ID = "kjds-channel-account-runtime-binding-probe-v1"


class ManagedSecretLocatorPolicy:
    """Only opaque managed-store locator IDs cross the authority boundary."""

    NAMESPACE = "msl"
    PATTERN = re.compile(r"^msl_[A-Za-z0-9]{24,96}$")

    @classmethod
    def validate(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not cls.PATTERN.fullmatch(normalized):
            raise ValueError("secret_reference must be an opaque managed-store locator id in the msl namespace")
        return normalized


class UnboundChannelAccountRuntimeIdentityVerifier:
    """Production default until a managed-store/provider verifier is bound."""

    def verify(self, **_values: Any) -> dict[str, Any]:
        return {
            "contract_id": RUNTIME_PROBE_CONTRACT_ID,
            "status": "no_data",
            "managed_store_bound": False,
            "lease_fresh": False,
            "fingerprint_match": False,
            "scope_match": False,
            "capabilities_match": False,
            "provider_readback_fresh_passed": False,
            "external_verifier_fresh_passed": False,
            "source_gaps": [
                "channel_account_managed_credential_resolver_unbound",
                "channel_account_provider_readback_verifier_unbound",
                "channel_account_worker_exact_scope_lease_unbound",
            ],
        }


class UnboundScopedChannelCredentialClientFactory:
    """Production default: no grant opens a provider client until explicitly bound."""

    def open(self, *, grant: Any, as_of: datetime) -> None:
        del grant, as_of
        raise RuntimeError("Managed channel credential resolver is not bound")


@dataclass(frozen=True, repr=False)
class ManagedCredentialLeaseHandle:
    """Opaque signed handle. It never contains credential material."""

    issuer: str
    key_id: str
    lease_id: str
    envelope_sha256: str
    signature: str

    def safe_projection(self) -> dict[str, str]:
        return {
            "contract_id": RUNTIME_LEASE_CONTRACT_ID,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "lease_id_sha256": hashlib.sha256(self.lease_id.encode()).hexdigest(),
            "envelope_sha256": self.envelope_sha256,
            "credential_material_returned": "false",
        }


WORKER_GRANT_CONTRACT_ID = "kjds-channel-account-worker-credential-grant-v1"


@dataclass(frozen=True, repr=False)
class SignedWorkerCredentialGrant:
    """Non-secret worker handle; authority fields remain server-side."""

    issuer: str
    key_id: str
    grant_id: str
    required_capability: str
    envelope_sha256: str
    signature: str

    TRANSPORT_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "contract_id",
            "issuer",
            "key_id",
            "grant_id",
            "required_capability",
            "envelope_sha256",
            "signature",
        }
    )

    @classmethod
    def from_transport(cls, value: Mapping[str, Any]) -> SignedWorkerCredentialGrant:
        if not isinstance(value, Mapping) or set(value) != cls.TRANSPORT_FIELDS:
            raise PermissionError("Worker credential grant transport schema is invalid")
        if value.get("contract_id") != WORKER_GRANT_CONTRACT_ID:
            raise PermissionError("Worker credential grant contract is invalid")
        fields: dict[str, str] = {}
        for name in cls.TRANSPORT_FIELDS - {"contract_id"}:
            observed = value.get(name)
            if not isinstance(observed, str) or not observed or len(observed) > 300:
                raise PermissionError(f"Worker credential grant {name} is invalid")
            fields[name] = observed
        return cls(**fields)

    def transport_envelope(self) -> dict[str, str]:
        return {
            "contract_id": WORKER_GRANT_CONTRACT_ID,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "grant_id": self.grant_id,
            "required_capability": self.required_capability,
            "envelope_sha256": self.envelope_sha256,
            "signature": self.signature,
        }

    def safe_projection(self) -> dict[str, str]:
        return {
            "contract_id": WORKER_GRANT_CONTRACT_ID,
            "issuer": self.issuer,
            "key_id": self.key_id,
            "grant_id_sha256": hashlib.sha256(self.grant_id.encode()).hexdigest(),
            "required_capability": self.required_capability,
            "envelope_sha256": self.envelope_sha256,
            "credential_material_returned": "false",
        }


@dataclass(frozen=True, repr=False)
class _WorkerCredentialGrantRecord:
    grant_id: str
    issuer: str
    key_id: str
    tenant_ref: str
    entity_ref: str
    store_ref: str
    platform: str
    account_ref: str
    adapter_id: str
    adapter_version: str
    required_capability: str
    purpose: str
    authorization_epoch: int
    lease_handle: ManagedCredentialLeaseHandle
    secret_reference_sha256: str
    credential_fingerprint_sha256: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    consumed_at: datetime | None


class WorkerCredentialGrantStore(Protocol):
    def get(self, grant_id: str) -> _WorkerCredentialGrantRecord | None: ...

    def consume_once(
        self,
        *,
        grant_id: str,
        consumed_at: datetime,
        expected_envelope_sha256: str,
    ) -> _WorkerCredentialGrantRecord: ...


class SignedWorkerCredentialGrantAuthority:
    """Signs only already-persisted canonical grant rows."""

    def __init__(
        self,
        *,
        issuer: str,
        key_id: str,
        signing_key: bytes,
        store: WorkerCredentialGrantStore,
    ) -> None:
        self.issuer = SignedManagedCredentialLeaseResolver._required(issuer, "grant issuer")
        self.key_id = SignedManagedCredentialLeaseResolver._required(key_id, "grant key id")
        if len(signing_key) < 32:
            raise ValueError("Worker grant signing key must be at least 256 bits")
        self._signing_key = bytes(signing_key)
        self._store = store

    def issue(self, record: _WorkerCredentialGrantRecord) -> SignedWorkerCredentialGrant:
        if self._store.get(record.grant_id) != record:
            raise PermissionError("Worker credential grant must be persisted before issuance")
        if record.issuer != self.issuer or record.key_id != self.key_id:
            raise PermissionError("Worker credential grant authority is invalid")
        envelope = self._envelope(record)
        encoded = SignedManagedCredentialLeaseResolver._canonical_bytes(envelope)
        return SignedWorkerCredentialGrant(
            issuer=self.issuer,
            key_id=self.key_id,
            grant_id=record.grant_id,
            required_capability=record.required_capability,
            envelope_sha256=hashlib.sha256(encoded).hexdigest(),
            signature=hmac.new(self._signing_key, encoded, hashlib.sha256).hexdigest(),
        )

    def require_current(
        self,
        *,
        grant: SignedWorkerCredentialGrant,
        as_of: datetime,
    ) -> tuple[_WorkerCredentialGrantRecord, str]:
        cutoff = SignedManagedCredentialLeaseResolver._aware(as_of)
        if type(grant) is not SignedWorkerCredentialGrant:
            raise PermissionError("Worker credential grant type is not authoritative")
        if grant.issuer != self.issuer or grant.key_id != self.key_id:
            raise PermissionError("Worker credential grant issuer is unknown")
        record = self._store.get(grant.grant_id)
        if record is None:
            raise PermissionError("Worker credential grant does not exist")
        encoded = SignedManagedCredentialLeaseResolver._canonical_bytes(self._envelope(record))
        envelope_sha256 = hashlib.sha256(encoded).hexdigest()
        signature = hmac.new(self._signing_key, encoded, hashlib.sha256).hexdigest()
        if grant.envelope_sha256 != envelope_sha256 or not hmac.compare_digest(grant.signature, signature):
            raise PermissionError("Worker credential grant signature is invalid")
        if record.issuer != self.issuer or record.key_id != self.key_id:
            raise PermissionError("Worker credential grant authority drift")
        if grant.required_capability != record.required_capability:
            raise PermissionError("Worker credential grant capability drift")
        if record.consumed_at is not None:
            raise PermissionError("Worker credential grant was already consumed")
        if record.revoked_at is not None and SignedManagedCredentialLeaseResolver._aware(record.revoked_at) <= cutoff:
            raise PermissionError("Worker credential grant is revoked")
        if SignedManagedCredentialLeaseResolver._aware(record.issued_at) > cutoff:
            raise PermissionError("Worker credential grant is not yet effective")
        if SignedManagedCredentialLeaseResolver._aware(record.expires_at) <= cutoff:
            raise PermissionError("Worker credential grant is expired")
        if record.authorization_epoch < 1:
            raise PermissionError("Worker credential grant authorization epoch is invalid")
        for name, value in (
            ("secret reference", record.secret_reference_sha256),
            ("credential fingerprint", record.credential_fingerprint_sha256),
        ):
            if not SignedManagedCredentialLeaseResolver._valid_sha256(value):
                raise PermissionError(f"Worker credential grant {name} hash is invalid")
        return record, envelope_sha256

    @staticmethod
    def _envelope(record: _WorkerCredentialGrantRecord) -> dict[str, Any]:
        return {
            "contract_id": WORKER_GRANT_CONTRACT_ID,
            "issuer": record.issuer,
            "key_id": record.key_id,
            "grant_id": record.grant_id,
            "scope": {
                "tenant_ref": record.tenant_ref,
                "entity_ref": record.entity_ref,
                "store_ref": record.store_ref,
            },
            "platform": record.platform,
            "account_ref": record.account_ref,
            "adapter_id": record.adapter_id,
            "adapter_version": record.adapter_version,
            "required_capability": record.required_capability,
            "purpose": record.purpose,
            "authorization_epoch": record.authorization_epoch,
            "lease": record.lease_handle.safe_projection(),
            "secret_reference_sha256": record.secret_reference_sha256,
            "credential_fingerprint_sha256": record.credential_fingerprint_sha256,
            "issued_at": SignedManagedCredentialLeaseResolver._aware(record.issued_at).isoformat(),
            "expires_at": SignedManagedCredentialLeaseResolver._aware(record.expires_at).isoformat(),
            "revoked_at": (
                SignedManagedCredentialLeaseResolver._aware(record.revoked_at).isoformat()
                if record.revoked_at is not None
                else None
            ),
        }


class ScopedChannelCredentialClientFactory:
    """Authenticates and atomically consumes one grant before client creation."""

    def __init__(
        self,
        *,
        grant_authority: SignedWorkerCredentialGrantAuthority,
        grant_store: WorkerCredentialGrantStore,
        lease_resolver: SignedManagedCredentialLeaseResolver,
        client_builder: Callable[[ResolvedChannelCredentialMaterial], AbstractContextManager[Any]],
    ) -> None:
        self._grant_authority = grant_authority
        self._grant_store = grant_store
        self._lease_resolver = lease_resolver
        self._client_builder = client_builder

    def open(
        self,
        *,
        grant: SignedWorkerCredentialGrant | Mapping[str, Any],
        as_of: datetime,
    ) -> AbstractContextManager[Any]:
        cutoff = SignedManagedCredentialLeaseResolver._aware(as_of)
        authoritative_grant = (
            grant
            if type(grant) is SignedWorkerCredentialGrant
            else SignedWorkerCredentialGrant.from_transport(grant)
        )
        record, envelope_sha256 = self._grant_authority.require_current(
            grant=authoritative_grant,
            as_of=cutoff,
        )
        consumed = self._grant_store.consume_once(
            grant_id=record.grant_id,
            consumed_at=cutoff,
            expected_envelope_sha256=envelope_sha256,
        )
        if consumed.consumed_at is None:
            raise PermissionError("Worker credential grant consumption was not persisted")
        material = self._lease_resolver.resolve(
            handle=consumed.lease_handle,
            scope={
                "tenant_ref": consumed.tenant_ref,
                "entity_ref": consumed.entity_ref,
                "store_ref": consumed.store_ref,
            },
            platform=consumed.platform,
            account_ref=consumed.account_ref,
            adapter_id=consumed.adapter_id,
            adapter_version=consumed.adapter_version,
            required_capability=consumed.required_capability,
            secret_reference_sha256=consumed.secret_reference_sha256,
            credential_fingerprint_sha256=consumed.credential_fingerprint_sha256,
            as_of=cutoff,
        )
        if not self._lease_resolver.accepts(material):
            raise PermissionError("Managed credential material is no longer authoritative")
        return self._client_builder(material)


@dataclass(frozen=True, repr=False)
class _ManagedCredentialLeaseRecord:
    lease_id: str
    issuer: str
    key_id: str
    tenant_ref: str
    entity_ref: str
    store_ref: str
    platform: str
    account_ref: str
    adapter_id: str
    adapter_version: str
    capabilities: frozenset[str]
    secret_reference_sha256: str
    credential_fingerprint_sha256: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    client_id: str
    api_key: str
    provider_readback_sha256: str
    provider_readback_verified_at: datetime
    external_verifier_observation_sha256: str
    external_verifier_verified_at: datetime
    authorization_epoch: int = 1


@dataclass(frozen=True, repr=False)
class ResolvedChannelCredentialMaterial:
    """Resolver-produced, process-local credential material."""

    client_id: str
    api_key: str
    lease_id: str
    tenant_ref: str
    entity_ref: str
    store_ref: str
    platform: str
    account_ref: str
    adapter_id: str
    adapter_version: str
    required_capability: str
    secret_reference_sha256: str
    credential_fingerprint_sha256: str
    _resolver_attestation: bytes


class ManagedCredentialLeaseStore(Protocol):
    def get(self, lease_id: str) -> _ManagedCredentialLeaseRecord | None: ...


class SignedManagedCredentialLeaseResolver:
    """Contract verifier; it is not itself a production Worker trust root."""

    VERIFIER_TTL_SECONDS = 900

    def __init_subclass__(cls, **_kwargs: Any) -> None:
        raise TypeError(
            "SignedManagedCredentialLeaseResolver is final; "
            "production trust cannot be supplied by subclassing"
        )

    def __init__(
        self,
        *,
        issuer: str,
        key_id: str,
        signing_key: bytes,
        store: ManagedCredentialLeaseStore,
    ) -> None:
        self.issuer = self._required(issuer, "issuer")
        self.key_id = self._required(key_id, "key_id")
        if len(signing_key) < 32:
            raise ValueError("Lease signing key must be at least 256 bits")
        self._signing_key = bytes(signing_key)
        self._store = store
        self._attestation = hmac.digest(
            self._signing_key,
            b"kjds-channel-account-resolver-attestation-v1",
            "sha256",
        )

    def resolve(
        self,
        *,
        handle: ManagedCredentialLeaseHandle,
        scope: Mapping[str, str],
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        required_capability: str,
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        as_of: datetime,
    ) -> ResolvedChannelCredentialMaterial:
        cutoff = self._aware(as_of)
        record = self._current_record_for_handle(
            handle=handle,
            cutoff=cutoff,
        )
        expected = (
            scope.get("tenant_ref"),
            scope.get("entity_ref"),
            scope.get("store_ref"),
            platform,
            account_ref,
            adapter_id,
            adapter_version,
        )
        actual = (
            record.tenant_ref,
            record.entity_ref,
            record.store_ref,
            record.platform,
            record.account_ref,
            record.adapter_id,
            record.adapter_version,
        )
        if actual != expected:
            raise PermissionError("Managed credential lease exact-scope binding is invalid")
        if record.secret_reference_sha256 != secret_reference_sha256:
            raise PermissionError("Managed credential lease secret reference drift")
        if record.credential_fingerprint_sha256 != credential_fingerprint_sha256:
            raise PermissionError("Managed credential lease fingerprint mismatch")
        if required_capability not in record.capabilities:
            raise PermissionError("Managed credential lease lacks required capability")
        for name, value in (
            ("secret reference", record.secret_reference_sha256),
            ("credential fingerprint", record.credential_fingerprint_sha256),
            ("provider readback", record.provider_readback_sha256),
            (
                "external verifier",
                record.external_verifier_observation_sha256,
            ),
        ):
            if not self._valid_sha256(value):
                raise PermissionError(f"Managed lease {name} hash is invalid")
        if (
            self._aware(record.provider_readback_verified_at) > cutoff
            or self._aware(record.external_verifier_verified_at) > cutoff
            or (cutoff - self._aware(record.provider_readback_verified_at)).total_seconds() > self.VERIFIER_TTL_SECONDS
            or (cutoff - self._aware(record.external_verifier_verified_at)).total_seconds() > self.VERIFIER_TTL_SECONDS
        ):
            raise PermissionError("Managed credential lease verifier observation is stale")
        actual_fingerprint = self.credential_fingerprint(
            client_id=record.client_id,
            api_key=record.api_key,
            platform=record.platform,
            account_ref=record.account_ref,
        )
        if actual_fingerprint != record.credential_fingerprint_sha256:
            raise PermissionError("Managed credential lease material fingerprint drift")
        unsigned_material = ResolvedChannelCredentialMaterial(
            client_id=record.client_id,
            api_key=record.api_key,
            lease_id=record.lease_id,
            tenant_ref=record.tenant_ref,
            entity_ref=record.entity_ref,
            store_ref=record.store_ref,
            platform=record.platform,
            account_ref=record.account_ref,
            adapter_id=record.adapter_id,
            adapter_version=record.adapter_version,
            required_capability=required_capability,
            secret_reference_sha256=record.secret_reference_sha256,
            credential_fingerprint_sha256=actual_fingerprint,
            _resolver_attestation=b"",
        )
        return ResolvedChannelCredentialMaterial(
            client_id=unsigned_material.client_id,
            api_key=unsigned_material.api_key,
            lease_id=unsigned_material.lease_id,
            tenant_ref=unsigned_material.tenant_ref,
            entity_ref=unsigned_material.entity_ref,
            store_ref=unsigned_material.store_ref,
            platform=unsigned_material.platform,
            account_ref=unsigned_material.account_ref,
            adapter_id=unsigned_material.adapter_id,
            adapter_version=unsigned_material.adapter_version,
            required_capability=unsigned_material.required_capability,
            secret_reference_sha256=(
                unsigned_material.secret_reference_sha256
            ),
            credential_fingerprint_sha256=(unsigned_material.credential_fingerprint_sha256),
            _resolver_attestation=self._material_attestation(unsigned_material),
        )

    def require_current_handle(
        self,
        *,
        handle: ManagedCredentialLeaseHandle,
        as_of: datetime,
    ) -> None:
        """Verify issuer/signature/revocation/expiry before caller env access."""

        self._current_record_for_handle(
            handle=handle,
            cutoff=self._aware(as_of),
        )

    def _current_record_for_handle(
        self,
        *,
        handle: ManagedCredentialLeaseHandle,
        cutoff: datetime,
    ) -> _ManagedCredentialLeaseRecord:
        if handle.issuer != self.issuer or handle.key_id != self.key_id:
            raise PermissionError("Managed credential lease issuer is unknown")
        record = self._store.get(handle.lease_id)
        if record is None:
            raise PermissionError("Managed credential lease does not exist")
        envelope = self._envelope(record)
        envelope_bytes = self._canonical_bytes(envelope)
        envelope_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
        signature = hmac.new(
            self._signing_key,
            envelope_bytes,
            hashlib.sha256,
        ).hexdigest()
        if handle.envelope_sha256 != envelope_sha256 or not hmac.compare_digest(handle.signature, signature):
            raise PermissionError("Managed credential lease signature is invalid")
        if record.issuer != self.issuer or record.key_id != self.key_id:
            raise PermissionError("Managed credential lease authority drift")
        if record.revoked_at is not None and self._aware(record.revoked_at) <= cutoff:
            raise PermissionError("Managed credential lease is revoked")
        if self._aware(record.issued_at) > cutoff:
            raise PermissionError("Managed credential lease is not yet effective")
        if self._aware(record.expires_at) <= cutoff:
            raise PermissionError("Managed credential lease is expired")
        return record

    def accepts(
        self,
        material: ResolvedChannelCredentialMaterial,
    ) -> bool:
        if not hmac.compare_digest(
            material._resolver_attestation,
            self._material_attestation(material),
        ):
            return False
        record = self._store.get(material.lease_id)
        if record is None:
            return False
        cutoff = datetime.now(UTC)
        return not (
            record.issuer != self.issuer
            or record.key_id != self.key_id
            or self._aware(record.issued_at) > cutoff
            or self._aware(record.expires_at) <= cutoff
            or (
                record.revoked_at is not None
                and self._aware(record.revoked_at) <= cutoff
            )
            or (
                record.tenant_ref,
                record.entity_ref,
                record.store_ref,
                record.platform,
                record.account_ref,
                record.adapter_id,
                record.adapter_version,
            )
            != (
                material.tenant_ref,
                material.entity_ref,
                material.store_ref,
                material.platform,
                material.account_ref,
                material.adapter_id,
                material.adapter_version,
            )
            or material.required_capability not in record.capabilities
            or record.secret_reference_sha256
            != material.secret_reference_sha256
            or record.credential_fingerprint_sha256
            != material.credential_fingerprint_sha256
            or record.client_id != material.client_id
            or record.api_key != material.api_key
            or self.credential_fingerprint(
                client_id=record.client_id,
                api_key=record.api_key,
                platform=record.platform,
                account_ref=record.account_ref,
            )
            != material.credential_fingerprint_sha256
            or self._aware(record.provider_readback_verified_at) > cutoff
            or self._aware(record.external_verifier_verified_at) > cutoff
            or (
                cutoff - self._aware(record.provider_readback_verified_at)
            ).total_seconds()
            > self.VERIFIER_TTL_SECONDS
            or (
                cutoff - self._aware(
                    record.external_verifier_verified_at
                )
            ).total_seconds()
            > self.VERIFIER_TTL_SECONDS
        )

    def _material_attestation(
        self,
        material: ResolvedChannelCredentialMaterial,
    ) -> bytes:
        """Bind the process-local attestation to every credential field."""

        return hmac.new(
            self._attestation,
            self._canonical_bytes(
                {
                    "client_id": material.client_id,
                    "api_key_sha256": hashlib.sha256(material.api_key.encode()).hexdigest(),
                    "lease_id": material.lease_id,
                    "tenant_ref": material.tenant_ref,
                    "entity_ref": material.entity_ref,
                    "store_ref": material.store_ref,
                    "platform": material.platform,
                    "account_ref": material.account_ref,
                    "adapter_id": material.adapter_id,
                    "adapter_version": material.adapter_version,
                    "required_capability": material.required_capability,
                    "secret_reference_sha256": (
                        material.secret_reference_sha256
                    ),
                    "credential_fingerprint_sha256": (material.credential_fingerprint_sha256),
                }
            ),
            hashlib.sha256,
        ).digest()

    def sign_authoritative_record(
        self,
        record: _ManagedCredentialLeaseRecord,
    ) -> ManagedCredentialLeaseHandle:
        """Server-side issuance hook; the record must already exist in store."""

        stored = self._store.get(record.lease_id)
        if stored != record:
            raise PermissionError("Lease must be persisted before a handle is issued")
        envelope_bytes = self._canonical_bytes(self._envelope(record))
        return ManagedCredentialLeaseHandle(
            issuer=self.issuer,
            key_id=self.key_id,
            lease_id=record.lease_id,
            envelope_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
            signature=hmac.new(
                self._signing_key,
                envelope_bytes,
                hashlib.sha256,
            ).hexdigest(),
        )

    @classmethod
    def _envelope(
        cls,
        record: _ManagedCredentialLeaseRecord,
    ) -> dict[str, Any]:
        return {
            "contract_id": RUNTIME_LEASE_CONTRACT_ID,
            "issuer": record.issuer,
            "key_id": record.key_id,
            "lease_id": record.lease_id,
            "scope": {
                "tenant_ref": record.tenant_ref,
                "entity_ref": record.entity_ref,
                "store_ref": record.store_ref,
            },
            "platform": record.platform,
            "account_ref": record.account_ref,
            "adapter_id": record.adapter_id,
            "adapter_version": record.adapter_version,
            "capabilities": sorted(record.capabilities),
            "secret_reference_sha256": record.secret_reference_sha256,
            "credential_fingerprint_sha256": (record.credential_fingerprint_sha256),
            "issued_at": cls._aware(record.issued_at).isoformat(),
            "expires_at": cls._aware(record.expires_at).isoformat(),
            "revoked_at": (cls._aware(record.revoked_at).isoformat() if record.revoked_at is not None else None),
            "provider_readback_sha256": record.provider_readback_sha256,
            "provider_readback_verified_at": cls._aware(record.provider_readback_verified_at).isoformat(),
            "external_verifier_observation_sha256": (record.external_verifier_observation_sha256),
            "external_verifier_verified_at": cls._aware(record.external_verifier_verified_at).isoformat(),
        }

    @staticmethod
    def credential_fingerprint(
        *,
        client_id: str,
        api_key: str,
        platform: str,
        account_ref: str,
    ) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "client_id": client_id,
                    "api_key_sha256": hashlib.sha256(api_key.encode()).hexdigest(),
                    "platform": platform,
                    "account_ref": account_ref,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _canonical_bytes(value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def _required(value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 160:
            raise ValueError(f"Managed lease {field} is invalid")
        return normalized

    @staticmethod
    def _valid_sha256(value: str) -> bool:
        normalized = str(value or "")
        return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


# Server-owned registry of production Worker trust roots.  Only the process
# composition root may admit a resolver through
# ``register_server_bound_worker_resolver``; admission requires the exact final
# resolver type (subclassing is already blocked), so payload-driven or duck-typed
# values can never become a Worker trust root.
_SERVER_BOUND_WORKER_RESOLVER_IDS: set[int] = set()


def register_server_bound_worker_resolver(resolver: object) -> None:
    """Composition-root admission for one exact-scope Worker trust root."""
    if type(resolver) is not SignedManagedCredentialLeaseResolver:
        raise TypeError(
            "Only exact SignedManagedCredentialLeaseResolver instances "
            "can be registered as server-bound worker resolvers"
        )
    _SERVER_BOUND_WORKER_RESOLVER_IDS.add(id(resolver))


def _is_server_bound_worker_resolver(
    resolver: object,
) -> bool:
    """Non-overridable production admission predicate used by Workers."""

    return (
        type(resolver) is SignedManagedCredentialLeaseResolver
        and id(resolver) in _SERVER_BOUND_WORKER_RESOLVER_IDS
    )


def require_managed_channel_credential_resolution() -> tuple[
    SignedManagedCredentialLeaseResolver,
    ManagedCredentialLeaseHandle,
]:
    """Legacy environment seam stays closed; grants are the only production path.

    A server-bound resolver alone cannot authorize a worker: a worker must also
    present a server-issued one-time grant and resolve it through the control
    plane, never through process environment variables.
    """
    raise RuntimeError(
        "Environment-only channel credential resolution is closed; "
        "use the server-issued one-time grant flow"
    )
