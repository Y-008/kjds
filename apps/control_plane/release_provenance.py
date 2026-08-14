from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft7Validator, FormatChecker

RELEASE_BUNDLE_CONTRACT_ID = "kjds-release-evidence-bundle-v1"
RELEASE_VERIFICATION_CONTRACT_ID = "kjds-release-evidence-verification-v1"
SLSA_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
SLSA_PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
CYCLONEDX_SPEC_VERSION = "1.7"
LOCAL_SIGNER_ENVIRONMENT = "g1_ephemeral"
HOSTED_SIGNER_ENVIRONMENT = "hosted_release"

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_MIGRATION_HEAD = re.compile(r"^[0-9]{8}_[0-9]{4}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,511}$")
_AI_NAME = re.compile(r"^(?:runtime|model|adapter|eval)-contract-[0-9a-f]{12}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bank_account",
        "client_secret",
        "cookie",
        "cookies",
        "customer_email",
        "model_input",
        "model_output",
        "password",
        "private_key",
        "prompt",
        "prompt_text",
        "provider_request_id",
        "raw_prompt",
        "refresh_token",
        "secret",
    }
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*[^\s,;]{6,}"
    ),
)
_AI_COMPONENT_TYPES = {
    "runtime": "application",
    "model": "machine-learning-model",
    "adapter": "application",
    "eval": "data",
}


class ReleaseEvidenceError(ValueError):
    """Fail-closed release evidence validation error."""


@dataclass(frozen=True)
class ImageSubject:
    name: str
    digest_sha256: str
    version: str
    labels: Mapping[str, str]


@dataclass(frozen=True)
class SoftwareComponent:
    name: str
    version: str
    purl: str


@dataclass(frozen=True)
class AIContract:
    kind: str
    name: str
    version: str
    digest_sha256: str
    classification: str = "restricted"


@dataclass(frozen=True)
class ReleaseSnapshot:
    source_commit: str
    migration_head: str
    api_image: ImageSubject
    postgres_image: ImageSubject
    software_components: Sequence[SoftwareComponent]
    ai_contracts: Sequence[AIContract]
    source_files_sha256: Mapping[str, str]
    builder_id: str
    invocation_id: str
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class ReleaseExpectations:
    source_commit: str
    migration_head: str
    api_image_name: str
    api_digest_sha256: str
    postgres_image_name: str
    postgres_digest_sha256: str
    builder_id: str
    signer_key_id: str
    public_key_sha256: str
    signer_environment: str
    minimum_postgres_version: tuple[int, int] = (17, 10)
    enforce_deployment: bool = False


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleaseEvidenceError("Release evidence is not canonical JSON") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class ReleaseEvidenceAuthority:
    """Issue and verify a signed, secret-free release evidence bundle."""

    def __init__(
        self,
        *,
        cyclonedx_schema: Mapping[str, Any],
        cyclonedx_schema_sha256: str,
    ) -> None:
        self._schema = dict(cyclonedx_schema)
        self._schema_sha256 = _sha256(cyclonedx_schema_sha256, "CycloneDX schema")
        self._schema_validator = Draft7Validator(
            self._schema,
            format_checker=FormatChecker(),
        )

    def issue(
        self,
        snapshot: ReleaseSnapshot,
        *,
        signing_key: bytes,
        signer_key_id: str,
        signer_environment: str,
    ) -> dict[str, Any]:
        normalized = self._snapshot(snapshot)
        signer_key_id = _name(signer_key_id, "Signer key ID")
        if signer_environment not in {
            LOCAL_SIGNER_ENVIRONMENT,
            HOSTED_SIGNER_ENVIRONMENT,
        }:
            raise ReleaseEvidenceError("Signer environment is not governed")
        if len(signing_key) != 32:
            raise ReleaseEvidenceError("Ed25519 signing key must contain 32 bytes")

        software_bom = self._software_bom(normalized)
        ai_bom = self._ai_bom(normalized)
        self._validate_bom(software_bom, "Software SBOM")
        self._validate_bom(ai_bom, "AI BOM")
        self._verify_ai_bom(ai_bom)
        software_bom_sha256 = sha256_json(software_bom)
        ai_bom_sha256 = sha256_json(ai_bom)

        private_key = Ed25519PrivateKey.from_private_bytes(signing_key)
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        public_key_sha256 = hashlib.sha256(public_key).hexdigest()
        issued_at = _iso(normalized.finished_at)
        unsigned = {
            "contractId": RELEASE_BUNDLE_CONTRACT_ID,
            "issuedAt": issued_at,
            "signer": {
                "algorithm": "Ed25519",
                "environment": signer_environment,
                "keyId": signer_key_id,
                "publicKeyBase64": base64.b64encode(public_key).decode("ascii"),
                "publicKeySha256": public_key_sha256,
            },
            "releaseSubjects": [
                _subject(normalized.api_image),
                _subject(normalized.postgres_image),
            ],
            "statement": self._statement(
                normalized,
                software_bom_sha256=software_bom_sha256,
                ai_bom_sha256=ai_bom_sha256,
            ),
            "artifacts": {
                "softwareBom": software_bom,
                "softwareBomSha256": software_bom_sha256,
                "aiBom": ai_bom,
                "aiBomSha256": ai_bom_sha256,
            },
            "controls": {
                "cycloneDxSchemaSha256": self._schema_sha256,
                "slsaBuildLevelClaim": "L1",
                "hostedBuildPlatform": (signer_environment == HOSTED_SIGNER_ENVIRONMENT),
                "businessTruthGatePromoted": False,
                "formalFactCreated": False,
                "externalWriteAllowed": False,
            },
        }
        _assert_secret_free(unsigned)
        signature = private_key.sign(canonical_json(unsigned))
        return {
            **unsigned,
            "signature": {
                "algorithm": "Ed25519",
                "valueBase64": base64.b64encode(signature).decode("ascii"),
            },
        }

    def verify(
        self,
        bundle: Mapping[str, Any],
        expectations: ReleaseExpectations,
    ) -> dict[str, Any]:
        document = _mapping(bundle, "Release evidence bundle")
        _assert_secret_free(document)
        if document.get("contractId") != RELEASE_BUNDLE_CONTRACT_ID:
            raise ReleaseEvidenceError("Release evidence contract is unknown")
        controls = _mapping(document.get("controls"), "Release controls")
        if controls.get("cycloneDxSchemaSha256") != self._schema_sha256:
            raise ReleaseEvidenceError("CycloneDX schema authority drift")
        if controls.get("slsaBuildLevelClaim") != "L1":
            raise ReleaseEvidenceError("Local release evidence may only claim SLSA L1")
        signer = _mapping(document.get("signer"), "Release signer")
        if controls.get("hostedBuildPlatform") is not (
            signer.get("environment") == HOSTED_SIGNER_ENVIRONMENT
        ):
            raise ReleaseEvidenceError("Hosted build signer control drift")
        if any(
            controls.get(field) is not False
            for field in (
                "businessTruthGatePromoted",
                "formalFactCreated",
                "externalWriteAllowed",
            )
        ):
            raise ReleaseEvidenceError("Release evidence crossed a business authority gate")

        signature = _mapping(document.get("signature"), "Release signature")
        if signature.get("algorithm") != "Ed25519":
            raise ReleaseEvidenceError("Release signature algorithm is unsupported")
        public_key = _decode_base64(signer.get("publicKeyBase64"), "Signer public key")
        if len(public_key) != 32:
            raise ReleaseEvidenceError("Signer public key is invalid")
        public_key_sha256 = hashlib.sha256(public_key).hexdigest()
        if signer.get("publicKeySha256") != public_key_sha256:
            raise ReleaseEvidenceError("Signer public key hash is invalid")
        if (
            signer.get("keyId") != expectations.signer_key_id
            or public_key_sha256 != expectations.public_key_sha256
            or signer.get("environment") != expectations.signer_environment
        ):
            raise ReleaseEvidenceError("Release signer identity drift")
        unsigned = {key: value for key, value in document.items() if key != "signature"}
        signature_bytes = _decode_base64(signature.get("valueBase64"), "Signature")
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature_bytes,
                canonical_json(unsigned),
            )
        except InvalidSignature as exc:
            raise ReleaseEvidenceError("Release evidence signature is invalid") from exc

        artifacts = _mapping(document.get("artifacts"), "Release artifacts")
        software_bom = _mapping(artifacts.get("softwareBom"), "Software SBOM")
        ai_bom = _mapping(artifacts.get("aiBom"), "AI BOM")
        self._validate_bom(software_bom, "Software SBOM")
        self._validate_bom(ai_bom, "AI BOM")
        if artifacts.get("softwareBomSha256") != sha256_json(software_bom):
            raise ReleaseEvidenceError("Software SBOM digest drift")
        if artifacts.get("aiBomSha256") != sha256_json(ai_bom):
            raise ReleaseEvidenceError("AI BOM digest drift")
        self._verify_ai_bom(ai_bom)
        self._verify_statement(
            document,
            expectations,
            software_bom_sha256=str(artifacts["softwareBomSha256"]),
            ai_bom_sha256=str(artifacts["aiBomSha256"]),
        )

        hosted = signer.get("environment") == HOSTED_SIGNER_ENVIRONMENT
        if expectations.enforce_deployment and not hosted:
            raise ReleaseEvidenceError("Deployment requires the configured hosted release signer")
        return {
            "contractId": RELEASE_VERIFICATION_CONTRACT_ID,
            "status": "PASS",
            "cryptographicVerification": True,
            "subjectVerification": True,
            "cycloneDxSchemaValidation": True,
            "secretFree": True,
            "postgresVersionVerified": True,
            "slsaBuildLevel": "L1",
            "deploymentPolicyStatus": ("verified_for_deployment" if hosted else "not_for_deployment"),
            "productionDependencyAllowed": hosted,
            "businessTruthGatePromoted": False,
            "formalFactCreated": False,
            "externalWriteAllowed": False,
            "sourceCommit": expectations.source_commit,
            "migrationHead": expectations.migration_head,
            "apiImageSha256": expectations.api_digest_sha256,
            "postgresImageSha256": expectations.postgres_digest_sha256,
            "publicKeySha256": public_key_sha256,
            "bundleSha256": sha256_json(document),
        }

    def _snapshot(self, snapshot: ReleaseSnapshot) -> ReleaseSnapshot:
        source_commit = snapshot.source_commit.strip().lower()
        if not _GIT_COMMIT.fullmatch(source_commit):
            raise ReleaseEvidenceError("Source commit must be a full Git object ID")
        migration_head = snapshot.migration_head.strip()
        if not _MIGRATION_HEAD.fullmatch(migration_head):
            raise ReleaseEvidenceError("Migration head is invalid")
        api_image = _image(snapshot.api_image, "API image")
        postgres_image = _image(snapshot.postgres_image, "PostgreSQL image")
        if api_image.name == postgres_image.name:
            raise ReleaseEvidenceError("Release image subjects must be distinct")
        if api_image.labels.get("org.opencontainers.image.revision") != source_commit:
            raise ReleaseEvidenceError("API image source revision label drift")
        if api_image.labels.get("io.kjds.migration.head") != migration_head:
            raise ReleaseEvidenceError("API image migration label drift")
        if (
            api_image.labels.get("io.kjds.release.provenance.contract")
            != RELEASE_BUNDLE_CONTRACT_ID
        ):
            raise ReleaseEvidenceError("API image provenance contract label drift")
        _postgres_version(postgres_image.version)
        software = tuple(_software(item) for item in snapshot.software_components)
        if not software:
            raise ReleaseEvidenceError("Software SBOM inventory cannot be empty")
        if len({item.purl for item in software}) != len(software):
            raise ReleaseEvidenceError("Software SBOM contains duplicate package identities")
        ai_contracts = tuple(_ai_contract(item) for item in snapshot.ai_contracts)
        if not ai_contracts:
            raise ReleaseEvidenceError("AI BOM inventory cannot be empty")
        if len({item.name for item in ai_contracts}) != len(ai_contracts):
            raise ReleaseEvidenceError("AI BOM contains duplicate contract identities")
        source_files = {
            _name(name, "Source file"): _sha256(digest, "Source file digest")
            for name, digest in snapshot.source_files_sha256.items()
        }
        if {"Dockerfile", "uv.lock"} - source_files.keys():
            raise ReleaseEvidenceError("Release source inventory is incomplete")
        started = _aware(snapshot.started_at, "Build start")
        finished = _aware(snapshot.finished_at, "Build finish")
        if finished < started:
            raise ReleaseEvidenceError("Build finish precedes build start")
        return ReleaseSnapshot(
            source_commit=source_commit,
            migration_head=migration_head,
            api_image=api_image,
            postgres_image=postgres_image,
            software_components=tuple(sorted(software, key=lambda item: item.purl)),
            ai_contracts=tuple(sorted(ai_contracts, key=lambda item: item.name)),
            source_files_sha256=dict(sorted(source_files.items())),
            builder_id=_name(snapshot.builder_id, "Builder ID"),
            invocation_id=_name(snapshot.invocation_id, "Invocation ID"),
            started_at=started,
            finished_at=finished,
        )

    def _software_bom(self, snapshot: ReleaseSnapshot) -> dict[str, Any]:
        root_ref = f"pkg:oci/{snapshot.api_image.name}@sha256:{snapshot.api_image.digest_sha256}"
        components = [
            {
                "type": "library",
                "bom-ref": item.purl,
                "name": item.name,
                "version": item.version,
                "purl": item.purl,
                "scope": "required",
            }
            for item in snapshot.software_components
        ]
        return {
            "$schema": "http://cyclonedx.org/schema/bom-1.7.schema.json",
            "bomFormat": "CycloneDX",
            "specVersion": CYCLONEDX_SPEC_VERSION,
            "serialNumber": _serial("software", snapshot.api_image.digest_sha256),
            "version": 1,
            "metadata": {
                "timestamp": _iso(snapshot.finished_at),
                "lifecycles": [{"phase": "post-build"}],
                "tools": {
                    "components": [
                        {
                            "type": "application",
                            "name": "kjds-release-evidence",
                            "version": "1",
                        }
                    ]
                },
                "component": {
                    "type": "application",
                    "bom-ref": root_ref,
                    "name": snapshot.api_image.name,
                    "version": snapshot.source_commit[:12],
                    "hashes": [
                        {
                            "alg": "SHA-256",
                            "content": snapshot.api_image.digest_sha256,
                        }
                    ],
                },
                "distributionConstraints": {"tlp": "AMBER_AND_STRICT"},
            },
            "components": components,
            "dependencies": [
                {"ref": root_ref, "dependsOn": [item["bom-ref"] for item in components]},
                *[{"ref": item["bom-ref"], "dependsOn": []} for item in components],
            ],
            "properties": [
                {"name": "kjds:classification", "value": "restricted"},
                {"name": "kjds:contains-secrets", "value": "false"},
            ],
        }

    def _ai_bom(self, snapshot: ReleaseSnapshot) -> dict[str, Any]:
        root_ref = f"kjds:agent-runtime:{snapshot.source_commit[:12]}"
        components = [
            {
                "type": _AI_COMPONENT_TYPES[item.kind],
                "bom-ref": f"kjds:{item.name}",
                "name": item.name,
                "version": item.version,
                "hashes": [{"alg": "SHA-256", "content": item.digest_sha256}],
                "scope": "required",
                "properties": [
                    {"name": "kjds:classification", "value": item.classification},
                    {"name": "kjds:identifier-retention", "value": "hash-only"},
                ],
            }
            for item in snapshot.ai_contracts
        ]
        return {
            "$schema": "http://cyclonedx.org/schema/bom-1.7.schema.json",
            "bomFormat": "CycloneDX",
            "specVersion": CYCLONEDX_SPEC_VERSION,
            "serialNumber": _serial("ai", snapshot.api_image.digest_sha256),
            "version": 1,
            "metadata": {
                "timestamp": _iso(snapshot.finished_at),
                "lifecycles": [{"phase": "post-build"}],
                "tools": {
                    "components": [
                        {
                            "type": "application",
                            "name": "kjds-release-evidence",
                            "version": "1",
                        }
                    ]
                },
                "component": {
                    "type": "application",
                    "bom-ref": root_ref,
                    "name": "governed-agent-runtime-contract",
                    "version": snapshot.source_commit[:12],
                },
                "distributionConstraints": {"tlp": "AMBER_AND_STRICT"},
            },
            "components": components,
            "dependencies": [
                {"ref": root_ref, "dependsOn": [item["bom-ref"] for item in components]},
                *[{"ref": item["bom-ref"], "dependsOn": []} for item in components],
            ],
            "properties": [
                {"name": "kjds:classification", "value": "restricted"},
                {"name": "kjds:raw-prompt-retained", "value": "false"},
                {"name": "kjds:model-identifier-retained", "value": "false"},
                {"name": "kjds:provider-identifier-retained", "value": "false"},
            ],
        }

    def _statement(
        self,
        snapshot: ReleaseSnapshot,
        *,
        software_bom_sha256: str,
        ai_bom_sha256: str,
    ) -> dict[str, Any]:
        dependencies = [
            {
                "uri": f"git+https://github.com/Y-008/kjds@{snapshot.source_commit}",
                "digest": {"gitCommit": snapshot.source_commit},
            },
            *[
                {"uri": f"file:{name}", "digest": {"sha256": digest}}
                for name, digest in snapshot.source_files_sha256.items()
            ],
            {
                "uri": f"oci:{snapshot.postgres_image.name}",
                "digest": {"sha256": snapshot.postgres_image.digest_sha256},
            },
            {
                "uri": "file:software.cdx.json",
                "digest": {"sha256": software_bom_sha256},
            },
            {
                "uri": "file:ai.cdx.json",
                "digest": {"sha256": ai_bom_sha256},
            },
        ]
        return {
            "_type": SLSA_STATEMENT_TYPE,
            "subject": [
                {
                    "name": snapshot.api_image.name,
                    "digest": {"sha256": snapshot.api_image.digest_sha256},
                }
            ],
            "predicateType": SLSA_PREDICATE_TYPE,
            "predicate": {
                "buildDefinition": {
                    "buildType": "https://kjds.local/build-types/docker-compose-api/v1",
                    "externalParameters": {
                        "sourceCommit": snapshot.source_commit,
                        "migrationHead": snapshot.migration_head,
                        "target": "api",
                    },
                    "resolvedDependencies": dependencies,
                },
                "runDetails": {
                    "builder": {"id": snapshot.builder_id},
                    "metadata": {
                        "invocationId": snapshot.invocation_id,
                        "startedOn": _iso(snapshot.started_at),
                        "finishedOn": _iso(snapshot.finished_at),
                    },
                },
            },
        }

    def _validate_bom(self, bom: Mapping[str, Any], label: str) -> None:
        errors = sorted(
            self._schema_validator.iter_errors(bom),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.absolute_path) or "$"
            raise ReleaseEvidenceError(f"{label} violates CycloneDX 1.7 at {path}")

    def _verify_statement(
        self,
        document: Mapping[str, Any],
        expectations: ReleaseExpectations,
        *,
        software_bom_sha256: str,
        ai_bom_sha256: str,
    ) -> None:
        source_commit = expectations.source_commit.strip().lower()
        if not _GIT_COMMIT.fullmatch(source_commit):
            raise ReleaseEvidenceError("Expected source commit is invalid")
        migration_head = expectations.migration_head.strip()
        if not _MIGRATION_HEAD.fullmatch(migration_head):
            raise ReleaseEvidenceError("Expected migration head is invalid")
        api_digest = _sha256(expectations.api_digest_sha256, "Expected API digest")
        postgres_digest = _sha256(
            expectations.postgres_digest_sha256,
            "Expected PostgreSQL digest",
        )
        statement = _mapping(document.get("statement"), "SLSA statement")
        if statement.get("_type") != SLSA_STATEMENT_TYPE or statement.get("predicateType") != SLSA_PREDICATE_TYPE:
            raise ReleaseEvidenceError("SLSA statement contract drift")
        subjects = statement.get("subject")
        if subjects != [
            {
                "name": expectations.api_image_name,
                "digest": {"sha256": api_digest},
            }
        ]:
            raise ReleaseEvidenceError("SLSA API subject drift")
        release_subjects = document.get("releaseSubjects")
        if not isinstance(release_subjects, list) or len(release_subjects) != 2:
            raise ReleaseEvidenceError("Verified release subject set is incomplete")
        by_name = {str(item.get("name")): item for item in release_subjects if isinstance(item, Mapping)}
        if set(by_name) != {
            expectations.api_image_name,
            expectations.postgres_image_name,
        }:
            raise ReleaseEvidenceError("Verified release subject names drift")
        api_subject = _mapping(
            by_name[expectations.api_image_name],
            "API release subject",
        )
        postgres_subject = _mapping(
            by_name[expectations.postgres_image_name],
            "PostgreSQL release subject",
        )
        if (
            api_subject.get("kind") != "oci-image"
            or postgres_subject.get("kind") != "oci-image"
        ):
            raise ReleaseEvidenceError("Verified release subject kind drift")
        api_subject_digest = _mapping(
            api_subject.get("digest"),
            "API release subject digest",
        )
        postgres_subject_digest = _mapping(
            postgres_subject.get("digest"),
            "PostgreSQL release subject digest",
        )
        if api_subject_digest.get("sha256") != api_digest:
            raise ReleaseEvidenceError("API release subject digest drift")
        if postgres_subject_digest.get("sha256") != postgres_digest:
            raise ReleaseEvidenceError("PostgreSQL release subject digest drift")
        labels = _mapping(api_subject.get("labels"), "API image labels")
        if labels.get("org.opencontainers.image.revision") != source_commit:
            raise ReleaseEvidenceError("API image source label drift")
        if labels.get("io.kjds.migration.head") != migration_head:
            raise ReleaseEvidenceError("API image migration label drift")
        if (
            labels.get("io.kjds.release.provenance.contract")
            != RELEASE_BUNDLE_CONTRACT_ID
        ):
            raise ReleaseEvidenceError("API image provenance contract label drift")
        version = _postgres_version(str(postgres_subject.get("version") or ""))
        if version < expectations.minimum_postgres_version:
            raise ReleaseEvidenceError("PostgreSQL image patch level is below policy")

        predicate = _mapping(statement.get("predicate"), "SLSA predicate")
        definition = _mapping(predicate.get("buildDefinition"), "Build definition")
        if (
            definition.get("buildType")
            != "https://kjds.local/build-types/docker-compose-api/v1"
        ):
            raise ReleaseEvidenceError("Build type drift")
        external = _mapping(
            definition.get("externalParameters"),
            "Build external parameters",
        )
        if (
            external.get("sourceCommit") != source_commit
            or external.get("migrationHead") != migration_head
            or external.get("target") != "api"
        ):
            raise ReleaseEvidenceError("Build parameter drift")
        run_details = _mapping(predicate.get("runDetails"), "Build run details")
        builder = _mapping(run_details.get("builder"), "Build identity")
        if builder.get("id") != expectations.builder_id:
            raise ReleaseEvidenceError("Build identity drift")
        dependencies = definition.get("resolvedDependencies")
        if not isinstance(dependencies, list):
            raise ReleaseEvidenceError("Resolved dependency set is missing")
        postgres_dependencies = [
            item
            for item in dependencies
            if isinstance(item, Mapping) and item.get("uri") == f"oci:{expectations.postgres_image_name}"
        ]
        if postgres_dependencies != [
            {
                "uri": f"oci:{expectations.postgres_image_name}",
                "digest": {"sha256": postgres_digest},
            }
        ]:
            raise ReleaseEvidenceError("PostgreSQL provenance dependency drift")
        bom_dependencies = {
            str(item.get("uri")): item.get("digest")
            for item in dependencies
            if isinstance(item, Mapping)
            and item.get("uri")
            in {"file:software.cdx.json", "file:ai.cdx.json"}
        }
        if bom_dependencies != {
            "file:software.cdx.json": {"sha256": software_bom_sha256},
            "file:ai.cdx.json": {"sha256": ai_bom_sha256},
        }:
            raise ReleaseEvidenceError(
                "CycloneDX artifacts are not bound to provenance"
            )

    @staticmethod
    def _verify_ai_bom(ai_bom: Mapping[str, Any]) -> None:
        components = ai_bom.get("components")
        if not isinstance(components, list) or not components:
            raise ReleaseEvidenceError("AI BOM has no governed contracts")
        for component in components:
            item = _mapping(component, "AI BOM component")
            if set(item) != {
                "type",
                "bom-ref",
                "name",
                "version",
                "hashes",
                "scope",
                "properties",
            }:
                raise ReleaseEvidenceError("AI BOM component profile is not restricted")
            name = str(item.get("name") or "")
            if not _AI_NAME.fullmatch(name):
                raise ReleaseEvidenceError("AI BOM exposed an ungoverned identifier")
            prefix = name.split("-", 1)[0]
            if item.get("type") != _AI_COMPONENT_TYPES[prefix]:
                raise ReleaseEvidenceError("AI BOM component type drift")
            if prefix == "model" and not re.fullmatch(
                r"(?:[0-9]+(?:\.[0-9]+)*|UNKNOWN)",
                str(item.get("version") or ""),
            ):
                raise ReleaseEvidenceError("AI BOM exposed a raw model version")
            if item.get("bom-ref") != f"kjds:{name}" or item.get("scope") != "required":
                raise ReleaseEvidenceError("AI BOM component identity drift")
            hashes = item.get("hashes")
            if not isinstance(hashes, list) or len(hashes) != 1:
                raise ReleaseEvidenceError("AI BOM component hash profile drift")
            digest = _mapping(hashes[0], "AI BOM component hash")
            if digest.get("alg") != "SHA-256" or not _HEX_64.fullmatch(
                str(digest.get("content") or "")
            ):
                raise ReleaseEvidenceError("AI BOM component hash profile drift")
            if name.rsplit("-", 1)[1] != str(digest["content"])[:12]:
                raise ReleaseEvidenceError("AI BOM component identifier hash drift")
            properties = item.get("properties")
            if not isinstance(properties, list) or len(properties) != 2:
                raise ReleaseEvidenceError("AI BOM classification is missing")
            if any(
                not isinstance(prop, Mapping) or set(prop) != {"name", "value"}
                for prop in properties
            ):
                raise ReleaseEvidenceError("AI BOM component properties drift")
            values = {
                str(prop.get("name")): str(prop.get("value"))
                for prop in properties
                if isinstance(prop, Mapping)
            }
            if set(values) != {
                "kjds:classification",
                "kjds:identifier-retention",
            }:
                raise ReleaseEvidenceError("AI BOM component properties drift")
            if values.get("kjds:classification") not in {"public", "restricted"}:
                raise ReleaseEvidenceError("AI BOM classification drift")
            if values.get("kjds:identifier-retention") != "hash-only":
                raise ReleaseEvidenceError("AI BOM identifier retention drift")


def _image(subject: ImageSubject, label: str) -> ImageSubject:
    labels = {_name(str(name), f"{label} label"): str(value) for name, value in subject.labels.items()}
    return ImageSubject(
        name=_name(subject.name, label),
        digest_sha256=_sha256(subject.digest_sha256, label),
        version=_name(subject.version, f"{label} version"),
        labels=dict(sorted(labels.items())),
    )


def _software(item: SoftwareComponent) -> SoftwareComponent:
    name = _name(item.name, "Software package")
    version = _name(item.version, "Software package version")
    purl = _name(item.purl, "Software package URL")
    if not purl.startswith("pkg:"):
        raise ReleaseEvidenceError("Software package URL must be a purl")
    return SoftwareComponent(name=name, version=version, purl=purl)


def _ai_contract(item: AIContract) -> AIContract:
    if item.kind not in _AI_COMPONENT_TYPES:
        raise ReleaseEvidenceError("AI contract kind is unsupported")
    name = _name(item.name, "AI contract")
    if not _AI_NAME.fullmatch(name) or not name.startswith(f"{item.kind}-contract-"):
        raise ReleaseEvidenceError("AI contract identifier must be hash-derived")
    if item.classification not in {"public", "restricted"}:
        raise ReleaseEvidenceError("AI contract classification is unsupported")
    return AIContract(
        kind=item.kind,
        name=name,
        version=_name(item.version, "AI contract version"),
        digest_sha256=_sha256(item.digest_sha256, "AI contract"),
        classification=item.classification,
    )


def _subject(subject: ImageSubject) -> dict[str, Any]:
    return {
        "kind": "oci-image",
        "name": subject.name,
        "digest": {"sha256": subject.digest_sha256},
        "version": subject.version,
        "labels": dict(subject.labels),
    }


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseEvidenceError(f"{label} must be an object")
    return dict(value)


def _sha256(value: str, label: str) -> str:
    normalized = str(value).strip().lower().removeprefix("sha256:")
    if not _HEX_64.fullmatch(normalized):
        raise ReleaseEvidenceError(f"{label} must be a SHA-256 digest")
    return normalized


def _name(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_NAME.fullmatch(normalized):
        raise ReleaseEvidenceError(f"{label} contains an unsafe identifier")
    return normalized


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None:
        raise ReleaseEvidenceError(f"{label} must include a timezone")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value, "Timestamp").isoformat().replace("+00:00", "Z")


def _serial(kind: str, digest: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"kjds:{kind}:{digest}")
    return f"urn:uuid:{value}"


def _decode_base64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ReleaseEvidenceError(f"{label} is missing")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReleaseEvidenceError(f"{label} is invalid") from exc


def _postgres_version(value: str) -> tuple[int, int]:
    match = re.search(r"(?:PostgreSQL\s+)?([0-9]+)\.([0-9]+)", value)
    if match is None:
        raise ReleaseEvidenceError("PostgreSQL image version is invalid")
    return int(match.group(1)), int(match.group(2))


def _assert_secret_free(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower()
            if normalized in _FORBIDDEN_KEYS:
                raise ReleaseEvidenceError(f"Release evidence contains forbidden field {path}.{key}")
            _assert_secret_free(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_secret_free(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise ReleaseEvidenceError(f"Release evidence contains secret-like content at {path}")
