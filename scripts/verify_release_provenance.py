from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.control_plane.agent_runtime import (
    ROUTING_POLICY_VERSION,
    RUNTIME_CONTRACT_ID,
)
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

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs/project/contracts/release-provenance-policy-v1.json"
AGENT_REGISTRY_PATH = ROOT / "docs/project/registries/agent_task_registry.json"
ADAPTER_REGISTRY_PATH = ROOT / "docs/project/registries/channel_account_adapters.json"
EVAL_FIXTURE_ROOT = ROOT / "tests/fixtures/agent_runtime"


def _run(*arguments: str) -> str:
    completed = subprocess.run(
        list(arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseEvidenceError(f"Expected JSON object: {path.name}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _image_document(image: str) -> dict[str, Any]:
    payload = json.loads(_run("docker", "image", "inspect", image))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ReleaseEvidenceError(f"Docker image is not uniquely inspectable: {image}")
    document = payload[0]
    if not isinstance(document, dict):
        raise ReleaseEvidenceError(f"Docker image metadata is invalid: {image}")
    return document


def _image_digest(document: dict[str, Any]) -> str:
    image_id = str(document.get("Id") or "")
    if not image_id.startswith("sha256:"):
        raise ReleaseEvidenceError("Docker image has no content-addressed image ID")
    return image_id.removeprefix("sha256:")


def _software_components(api_image: str) -> tuple[SoftwareComponent, ...]:
    program = (
        "import importlib.metadata as m,json;"
        "rows=sorted({(d.metadata.get('Name') or d.name,d.version) for d in m.distributions()});"
        "print(json.dumps(rows,separators=(',',':')))"
    )
    rows = json.loads(
        _run(
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            api_image,
            "-c",
            program,
        ).splitlines()[-1]
    )
    if not isinstance(rows, list):
        raise ReleaseEvidenceError("API image package inventory is invalid")
    return tuple(
        SoftwareComponent(
            name=str(name),
            version=str(version),
            purl=f"pkg:pypi/{quote(str(name).lower(), safe='._-')}@{quote(str(version), safe='._+-')}",
        )
        for name, version in rows
    )


def _contract(kind: str, payload: Any, version: str) -> AIContract:
    digest = _digest(payload)
    return AIContract(
        kind=kind,
        name=f"{kind}-contract-{digest[:12]}",
        version=version,
        digest_sha256=digest,
    )


def _ai_contracts() -> tuple[AIContract, ...]:
    agent_registry = _load_json(AGENT_REGISTRY_PATH)
    adapter_registry = _load_json(ADAPTER_REGISTRY_PATH)
    contracts = [
        _contract(
            "runtime",
            {
                "runtime_contract": RUNTIME_CONTRACT_ID,
                "routing_policy": ROUTING_POLICY_VERSION,
                "agent_registry_sha256": _sha256_file(AGENT_REGISTRY_PATH),
            },
            RUNTIME_CONTRACT_ID,
        )
    ]
    providers = agent_registry.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ReleaseEvidenceError("Agent model contract registry is empty")
    contracts.extend(
        _contract(
            "model",
            {"provider_contract": provider, "definition": definition},
            str(agent_registry.get("schema_version") or "UNKNOWN"),
        )
        for provider, definition in sorted(providers.items())
    )
    adapters = adapter_registry.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        raise ReleaseEvidenceError("Agent adapter contract registry is empty")
    contracts.extend(
        _contract(
            "adapter",
            adapter,
            str(adapter.get("adapter_version") or "UNKNOWN"),
        )
        for adapter in adapters
        if isinstance(adapter, dict)
    )
    fixtures = sorted(EVAL_FIXTURE_ROOT.glob("*_eval_*.json"))
    if not fixtures:
        raise ReleaseEvidenceError("Agent eval contract inventory is empty")
    for path in fixtures:
        fixture = _load_json(path)
        contracts.append(
            _contract(
                "eval",
                fixture,
                str(fixture.get("eval_version") or "UNKNOWN"),
            )
        )
    return tuple(contracts)


def _postgres_version(image: str) -> str:
    output = _run("docker", "run", "--rm", image, "postgres", "--version")
    parts = output.split()
    if len(parts) < 3:
        raise ReleaseEvidenceError("PostgreSQL image did not report its version")
    return parts[2]


def _project_version() -> str:
    value = _run(
        sys.executable,
        "-c",
        "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])",
    )
    if not value:
        raise ReleaseEvidenceError("Project version is unavailable")
    return value


def _image_subjects(
    *,
    api_image: str,
    postgres_image: str,
) -> tuple[ImageSubject, ImageSubject]:
    api = _image_document(api_image)
    postgres = _image_document(postgres_image)
    labels = (api.get("Config") or {}).get("Labels") or {}
    if not isinstance(labels, dict):
        raise ReleaseEvidenceError("API image labels are invalid")
    return (
        ImageSubject(
            name=api_image,
            digest_sha256=_image_digest(api),
            version=_project_version(),
            labels={str(key): str(value) for key, value in labels.items()},
        ),
        ImageSubject(
            name=postgres_image,
            digest_sha256=_image_digest(postgres),
            version=_postgres_version(postgres_image),
            labels={},
        ),
    )


def _source_files() -> dict[str, str]:
    paths = (
        "Dockerfile",
        "pyproject.toml",
        "uv.lock",
        "docs/project/registries/agent_task_registry.json",
        "docs/project/registries/channel_account_adapters.json",
        "tests/fixtures/agent_runtime/listing_quality_qa_v1_eval_v1.json",
    )
    return {path: _sha256_file(ROOT / path) for path in paths}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _g1(args: argparse.Namespace) -> dict[str, Any]:
    policy = _load_json(args.policy)
    cyclonedx = policy.get("standards", {}).get("cyclonedx", {})
    schema_path = ROOT / str(cyclonedx.get("schema_path") or "")
    expected_schema_sha256 = str(cyclonedx.get("schema_file_sha256") or "")
    if _sha256_file(schema_path) != expected_schema_sha256:
        raise ReleaseEvidenceError("Pinned CycloneDX schema file digest drift")
    schema = _load_json(schema_path)
    authority = ReleaseEvidenceAuthority(
        cyclonedx_schema=schema,
        cyclonedx_schema_sha256=expected_schema_sha256,
    )
    api_subject, postgres_subject = _image_subjects(
        api_image=args.api_image,
        postgres_image=args.postgres_image,
    )
    now = datetime.now(UTC)
    snapshot = ReleaseSnapshot(
        source_commit=args.source_commit,
        migration_head=args.migration_head,
        api_image=api_subject,
        postgres_image=postgres_subject,
        software_components=_software_components(args.api_image),
        ai_contracts=_ai_contracts(),
        source_files_sha256=_source_files(),
        builder_id=str(policy["builder"]["local_g1_id"]),
        invocation_id=f"g1-{args.source_commit[:12]}-{api_subject.digest_sha256[:12]}",
        started_at=now,
        finished_at=datetime.now(UTC),
    )
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    signer_policy = policy["signers"][LOCAL_SIGNER_ENVIRONMENT]
    bundle = authority.issue(
        snapshot,
        signing_key=private_bytes,
        signer_key_id=str(signer_policy["key_id"]),
        signer_environment=LOCAL_SIGNER_ENVIRONMENT,
    )
    expectations = ReleaseExpectations(
        source_commit=args.source_commit,
        migration_head=args.migration_head,
        api_image_name=args.api_image,
        api_digest_sha256=api_subject.digest_sha256,
        postgres_image_name=args.postgres_image,
        postgres_digest_sha256=postgres_subject.digest_sha256,
        builder_id=str(policy["builder"]["local_g1_id"]),
        signer_key_id=str(signer_policy["key_id"]),
        public_key_sha256=str(bundle["signer"]["publicKeySha256"]),
        signer_environment=LOCAL_SIGNER_ENVIRONMENT,
        minimum_postgres_version=tuple(
            int(part) for part in str(policy["subjects"]["minimum_postgres_version"]).split(".")
        ),
        enforce_deployment=False,
    )
    receipt = authority.verify(bundle, expectations)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / "release-evidence-bundle.json", bundle)
    _write_json(output / "software.cdx.json", bundle["artifacts"]["softwareBom"])
    _write_json(output / "ai.cdx.json", bundle["artifacts"]["aiBom"])
    _write_json(output / "verification.json", receipt)
    return {
        "status": receipt["status"],
        "contract_id": receipt["contractId"],
        "source_commit": receipt["sourceCommit"],
        "migration_head": receipt["migrationHead"],
        "api_image_sha256": receipt["apiImageSha256"],
        "postgres_image_sha256": receipt["postgresImageSha256"],
        "postgres_version": postgres_subject.version,
        "cryptographic_verification": receipt["cryptographicVerification"],
        "subject_verification": receipt["subjectVerification"],
        "cyclonedx_schema_validation": receipt["cycloneDxSchemaValidation"],
        "secret_free": receipt["secretFree"],
        "slsa_build_level": receipt["slsaBuildLevel"],
        "deployment_policy_status": receipt["deploymentPolicyStatus"],
        "production_dependency_allowed": receipt["productionDependencyAllowed"],
        "business_truth_gate_promoted": receipt["businessTruthGatePromoted"],
        "formal_fact_created": receipt["formalFactCreated"],
        "external_write_allowed": receipt["externalWriteAllowed"],
        "software_component_count": len(snapshot.software_components),
        "ai_contract_count": len(snapshot.ai_contracts),
        "bundle_sha256": receipt["bundleSha256"],
        "output_dir": str(output),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Issue and verify KJDS release evidence")
    subcommands = root.add_subparsers(dest="command", required=True)
    g1 = subcommands.add_parser("g1", help="Run the local G1 release evidence gate")
    g1.add_argument("--api-image", required=True)
    g1.add_argument("--postgres-image", required=True)
    g1.add_argument("--source-commit", required=True)
    g1.add_argument("--migration-head", required=True)
    g1.add_argument("--output-dir", type=Path, required=True)
    g1.add_argument("--policy", type=Path, default=POLICY_PATH)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command != "g1":
            raise ReleaseEvidenceError("Release evidence command is unsupported")
        result = _g1(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_code": "release_evidence_gate_failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
