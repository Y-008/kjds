from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.control_plane.release_provenance import (
    LOCAL_SIGNER_ENVIRONMENT,
    AIContract,
    ImageSubject,
    ReleaseEvidenceAuthority,
    ReleaseEvidenceError,
    ReleaseExpectations,
    ReleaseSnapshot,
    SoftwareComponent,
    canonical_json,
)

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "docs/project/contracts/cyclonedx-bom-1.7.schema.json"
POLICY = ROOT / "docs/project/contracts/release-provenance-policy-v1.json"
KEY = bytes(range(32))


def authority() -> ReleaseEvidenceAuthority:
    return ReleaseEvidenceAuthority(
        cyclonedx_schema=json.loads(SCHEMA.read_text(encoding="utf-8")),
        cyclonedx_schema_sha256=hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
    )


def snapshot(*, postgres_version: str = "17.10") -> ReleaseSnapshot:
    started = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)
    return ReleaseSnapshot(
        source_commit="1" * 40,
        migration_head="20260803_0090",
        api_image=ImageSubject(
            name="kjds-api:latest",
            digest_sha256="a" * 64,
            version="0.60.0",
            labels={
                "org.opencontainers.image.revision": "1" * 40,
                "io.kjds.migration.head": "20260803_0090",
                "io.kjds.release.provenance.contract": (
                    "kjds-release-evidence-bundle-v1"
                ),
            },
        ),
        postgres_image=ImageSubject(
            name="postgres:17-alpine",
            digest_sha256="b" * 64,
            version=postgres_version,
            labels={},
        ),
        software_components=(
            SoftwareComponent(
                name="fastapi",
                version="0.116.0",
                purl="pkg:pypi/fastapi@0.116.0",
            ),
            SoftwareComponent(
                name="sqlalchemy",
                version="2.0.43",
                purl="pkg:pypi/sqlalchemy@2.0.43",
            ),
        ),
        ai_contracts=(
            AIContract(
                kind="runtime",
                name="runtime-contract-111111111111",
                version="kjds-governed-agent-runtime-v1",
                digest_sha256="1" * 64,
            ),
            AIContract(
                kind="model",
                name="model-contract-222222222222",
                version="1.0",
                digest_sha256="2" * 64,
            ),
            AIContract(
                kind="adapter",
                name="adapter-contract-333333333333",
                version="v1",
                digest_sha256="3" * 64,
            ),
            AIContract(
                kind="eval",
                name="eval-contract-444444444444",
                version="eval-v1",
                digest_sha256="4" * 64,
            ),
        ),
        source_files_sha256={"Dockerfile": "c" * 64, "uv.lock": "d" * 64},
        builder_id="https://kjds.local/builders/g1/v1",
        invocation_id="g1-test-release",
        started_at=started,
        finished_at=started + timedelta(minutes=2),
    )


def issue(
    value: ReleaseSnapshot | None = None,
    *,
    key: bytes = KEY,
) -> tuple[ReleaseEvidenceAuthority, dict]:
    instance = authority()
    bundle = instance.issue(
        value or snapshot(),
        signing_key=key,
        signer_key_id="kjds-g1-ephemeral-ed25519",
        signer_environment=LOCAL_SIGNER_ENVIRONMENT,
    )
    return instance, bundle


def expectations(bundle: dict, **changes) -> ReleaseExpectations:
    values = {
        "source_commit": "1" * 40,
        "migration_head": "20260803_0090",
        "api_image_name": "kjds-api:latest",
        "api_digest_sha256": "a" * 64,
        "postgres_image_name": "postgres:17-alpine",
        "postgres_digest_sha256": "b" * 64,
        "builder_id": "https://kjds.local/builders/g1/v1",
        "signer_key_id": "kjds-g1-ephemeral-ed25519",
        "public_key_sha256": bundle["signer"]["publicKeySha256"],
        "signer_environment": LOCAL_SIGNER_ENVIRONMENT,
    }
    values.update(changes)
    return ReleaseExpectations(**values)


def test_signed_release_bundle_validates_both_boms_and_stays_non_deployable():
    instance, bundle = issue()

    receipt = instance.verify(bundle, expectations(bundle))

    assert receipt["status"] == "PASS"
    assert receipt["cryptographicVerification"] is True
    assert receipt["cycloneDxSchemaValidation"] is True
    assert receipt["deploymentPolicyStatus"] == "not_for_deployment"
    assert receipt["productionDependencyAllowed"] is False
    assert receipt["businessTruthGatePromoted"] is False
    assert receipt["formalFactCreated"] is False
    assert receipt["externalWriteAllowed"] is False
    assert bundle["statement"]["subject"] == [
        {"name": "kjds-api:latest", "digest": {"sha256": "a" * 64}}
    ]
    assert {item["name"] for item in bundle["releaseSubjects"]} == {
        "kjds-api:latest",
        "postgres:17-alpine",
    }
    resolved = bundle["statement"]["predicate"]["buildDefinition"][
        "resolvedDependencies"
    ]
    assert {
        "uri": "file:software.cdx.json",
        "digest": {"sha256": bundle["artifacts"]["softwareBomSha256"]},
    } in resolved
    assert {
        "uri": "file:ai.cdx.json",
        "digest": {"sha256": bundle["artifacts"]["aiBomSha256"]},
    } in resolved
    serialized = canonical_json(bundle).decode("utf-8")
    assert "qwen" not in serialized
    assert "openai" not in serialized
    assert "raw prompt" not in serialized.lower()


def test_subject_and_statement_drift_fail_closed():
    instance, bundle = issue()

    with pytest.raises(ReleaseEvidenceError, match="API subject drift"):
        instance.verify(
            bundle,
            expectations(bundle, api_digest_sha256="e" * 64),
        )

    tampered = copy.deepcopy(bundle)
    tampered["statement"]["predicate"]["buildDefinition"]["externalParameters"][
        "migrationHead"
    ] = "20260803_9999"
    with pytest.raises(ReleaseEvidenceError, match="signature"):
        instance.verify(tampered, expectations(bundle))


def test_valid_signature_from_a_drifted_signer_is_rejected():
    instance, trusted = issue()
    _, drifted = issue(key=bytes(reversed(range(32))))

    with pytest.raises(ReleaseEvidenceError, match="signer identity drift"):
        instance.verify(drifted, expectations(trusted))


def test_local_signer_cannot_satisfy_deployment_policy():
    instance, bundle = issue()

    with pytest.raises(ReleaseEvidenceError, match="hosted release signer"):
        instance.verify(
            bundle,
            expectations(bundle, enforce_deployment=True),
        )


def test_postgres_patch_level_is_verified_without_claiming_it_as_a_build_output():
    instance, bundle = issue(snapshot(postgres_version="17.9"))

    with pytest.raises(ReleaseEvidenceError, match="patch level"):
        instance.verify(bundle, expectations(bundle))

    resolved = bundle["statement"]["predicate"]["buildDefinition"][
        "resolvedDependencies"
    ]
    assert {
        "uri": "oci:postgres:17-alpine",
        "digest": {"sha256": "b" * 64},
    } in resolved


def test_secret_like_content_and_raw_ai_identifiers_are_rejected_before_signing():
    value = snapshot()
    labels = dict(value.api_image.labels)
    labels["release.note"] = "api_key=super-secret-value"
    value = replace(value, api_image=replace(value.api_image, labels=labels))
    with pytest.raises(ReleaseEvidenceError, match="secret-like"):
        issue(value)

    value = snapshot()
    contracts = list(value.ai_contracts)
    contracts[1] = replace(contracts[1], name="model-contract-qwen-provider")
    with pytest.raises(ReleaseEvidenceError, match="hash-derived"):
        issue(replace(value, ai_contracts=contracts))

    value = snapshot()
    contracts = list(value.ai_contracts)
    contracts[1] = replace(contracts[1], version="qwen2.5:3b")
    with pytest.raises(ReleaseEvidenceError, match="raw model version"):
        issue(replace(value, ai_contracts=contracts))


def test_provenance_contract_label_is_required_before_signing():
    value = snapshot()
    labels = dict(value.api_image.labels)
    labels["io.kjds.release.provenance.contract"] = "unknown-contract"
    value = replace(value, api_image=replace(value.api_image, labels=labels))

    with pytest.raises(ReleaseEvidenceError, match="provenance contract label drift"):
        issue(value)


def test_ai_bom_identity_is_derived_from_its_sha256_contract():
    value = snapshot()
    contracts = list(value.ai_contracts)
    contracts[1] = replace(
        contracts[1],
        name="model-contract-999999999999",
    )

    with pytest.raises(ReleaseEvidenceError, match="identifier hash drift"):
        issue(replace(value, ai_contracts=contracts))


def test_release_policy_pins_schema_and_keeps_production_signer_unknown():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["standards"]["slsa"]["version"] == "1.2"
    assert policy["standards"]["slsa"]["maximum_claimed_build_level"] == "L1"
    assert policy["standards"]["cyclonedx"]["version"] == "1.7"
    assert policy["standards"]["cyclonedx"]["schema_file_sha256"] == (
        hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
    )
    assert policy["signers"]["hosted_release"]["state"] == "UNKNOWN"
    assert policy["signers"]["hosted_release"]["deployment_allowed"] is False
    assert policy["deployment_policy"]["business_truth_gate_promoted"] is False
    assert policy["deployment_policy"]["external_write_allowed"] is False


def test_api_image_and_g1_are_wired_to_the_same_release_evidence_contract():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    g1 = (ROOT / "scripts/verify-g1.ps1").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'org.opencontainers.image.revision="${KJDS_BUILD_COMMIT}"' in dockerfile
    assert 'io.kjds.migration.head="${KJDS_MIGRATION_HEAD}"' in dockerfile
    assert "kjds-release-evidence-bundle-v1" in dockerfile
    assert "KJDS_BUILD_COMMIT: ${KJDS_BUILD_COMMIT:-UNKNOWN}" in compose
    assert "KJDS_MIGRATION_HEAD: ${KJDS_MIGRATION_HEAD:-UNKNOWN}" in compose
    assert "scripts/verify_release_provenance.py g1" in g1
    assert "release_deployment_policy = $true" in g1
    assert 'deployment_policy_status -ne "not_for_deployment"' in g1
    assert '"cryptography>=49,<50"' in project
    assert '"jsonschema>=4.26,<5"' in project
