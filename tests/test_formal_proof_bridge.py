import hashlib
import json

import pytest

from apps.control_plane.formal_proof_manifest import (
    load_manifest,
    manifest_metadata,
    manifest_sha256,
    validate_manifest_artifacts,
    validate_manifest_examples,
    validate_manifest_modules,
)
from apps.control_plane.formal_theorem_runner import run_manifest
from apps.control_plane.proof_artifact_validator import (
    ProofArtifactReceipt,
    replay_proof_receipt,
    validate_artifact,
    validate_proof_receipt,
)
from apps.control_plane.proof_evidence_bridge import (
    bind_evidence,
    evidence_payload_sha256,
    validate_binding,
    validate_evidence_payload,
)


def test_manifest_is_loadable_and_hashed():
    entries = load_manifest("formal_proof_manifest.json")
    assert entries[0].stable_key == "order.settlement.profit.closed"
    assert len(manifest_sha256(entries)) == 64
    assert validate_manifest_modules(entries, root=".") == ()


def test_manifest_requires_theorem_declaration(tmp_path):
    module = tmp_path / "Empty.lean"
    module.write_text("namespace KJDS\nend KJDS\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"entries":[{"stable_key":"k","theorem":"missing","module":"Empty.lean","status":"blocked"}]}',
        encoding="utf-8",
    )
    entries = load_manifest(manifest)
    assert validate_manifest_modules(entries, root=tmp_path) == ("missing_theorem:k:missing",)


def test_runner_fails_closed_when_toolchain_missing():
    result = run_manifest("formal_proof_manifest.json")
    assert result["status"] in {"blocked", "ready_for_build"}
    assert result["manifest_sha256"]


def test_runner_admits_only_a_successful_lake_build(monkeypatch):
    from apps.control_plane import formal_theorem_runner

    class Completed:
        returncode = 0
        stdout = "build ok"
        stderr = ""

    monkeypatch.setattr(
        formal_theorem_runner,
        "toolchain_status",
        lambda: {"status": "ready", "lean": "lean", "lake": "lake", "reason": None},
    )
    monkeypatch.setattr(formal_theorem_runner.subprocess, "run", lambda *args, **kwargs: Completed())
    result = formal_theorem_runner.run_manifest("formal_proof_manifest.json")
    assert result["status"] == "blocked"
    assert result["reason"] == "proof_evidence_binding_missing"
    assert result["proved"] == []


def test_runner_can_prove_only_an_evidence_bound_entry(tmp_path, monkeypatch):
    module = tmp_path / "Proof.lean"
    module.write_text("theorem t : True := by trivial\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"entries":[{"stable_key":"k","theorem":"t","module":"Proof.lean",'
        '"status":"proposed","evidence_refs":["evidence://k"]}]}',
        encoding="utf-8",
    )
    from apps.control_plane import formal_theorem_runner

    monkeypatch.setattr(
        formal_theorem_runner,
        "toolchain_status",
        lambda: {"status": "ready", "lean": "lean", "lake": "lake", "reason": None},
    )
    monkeypatch.setattr(
        formal_theorem_runner.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 0, "stdout": "ok", "stderr": ""})(),
    )
    result = formal_theorem_runner.run_manifest(manifest)
    assert result["status"] == "proved"
    assert result["proved"] == ["k"]


def test_runner_does_not_promote_blocked_entry(tmp_path, monkeypatch):
    module = tmp_path / "Proof.lean"
    module.write_text("theorem t : True := by trivial\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"entries":[{"stable_key":"k","theorem":"t","module":"Proof.lean",'
        '"status":"blocked","evidence_refs":["evidence://k"]}]}',
        encoding="utf-8",
    )
    from apps.control_plane import formal_theorem_runner

    monkeypatch.setattr(
        formal_theorem_runner,
        "toolchain_status",
        lambda: {"status": "ready", "lean": "lean", "lake": "lake", "reason": None},
    )
    result = formal_theorem_runner.run_manifest(manifest)
    assert result["status"] == "blocked"
    assert result["reason"] == "proof_status_not_eligible"
    assert result["blocked"] == ["k"]


def test_manifest_rejects_invalid_artifact_digest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"entries":[{"stable_key":"k","theorem":"t","module":"Proof.lean",'
        '"artifact_sha256":"nope"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="artifact_sha256"):
        load_manifest(manifest)


def test_artifact_hash_and_explicit_binding(tmp_path):
    artifact = tmp_path / "proof.txt"
    artifact.write_text("receipt", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert validate_artifact(artifact, digest)
    binding = bind_evidence("t.order", ("ev-1", "ev-1"), ("currency_explicit",))
    assert binding.evidence_refs == ("ev-1",)
    with pytest.raises(ValueError):
        bind_evidence("t.empty", (), ())


def test_manifest_artifact_digest_is_checked_against_module_bytes(tmp_path):
    module = tmp_path / "Proof.lean"
    module.write_text("theorem t : True := by trivial\n", encoding="utf-8")
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"entries": [{"stable_key": "k", "theorem": "t", "module": "Proof.lean", "artifact_sha256": digest}]}),
        encoding="utf-8",
    )
    entries = load_manifest(manifest)
    assert validate_manifest_artifacts(entries, root=tmp_path) == ()
    module.write_text("theorem t : True := by decide\n", encoding="utf-8")
    assert validate_manifest_artifacts(entries, root=tmp_path) == (
        "artifact_hash_mismatch:k:Proof.lean",
    )


def test_manifest_examples_are_explicit_but_legacy_entries_remain_compatible(tmp_path):
    module = tmp_path / "Proof.lean"
    module.write_text("theorem t : True := by trivial\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_id": "kjds-formal-proof-manifest-v2",
                "example_policy": {
                    "require_positive": True,
                    "require_counterexample": True,
                },
                "entries": [
                    {
                        "stable_key": "k",
                        "theorem": "t",
                        "module": "Proof.lean",
                        "positive_refs": ["example:k:1"],
                        "counterexample_refs": ["counterexample:k:1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = load_manifest(manifest)
    assert validate_manifest_examples(entries) == ()
    assert manifest_metadata(manifest)["example_policy"]["require_positive"] is True


def test_manifest_example_policy_reports_missing_counterexample(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"entries":[{"stable_key":"k","theorem":"t","module":"Proof.lean",'
        '"positive_refs":["example:k:1"]}],"example_policy":'
        '{"require_positive":true,"require_counterexample":true}}',
        encoding="utf-8",
    )
    entries = load_manifest(manifest)
    assert validate_manifest_examples(entries) == ("counterexample_missing:k",)


def test_evidence_binding_carries_stable_digests_and_rejects_tamper():
    digest = evidence_payload_sha256("payload")
    binding = bind_evidence(
        "t.order",
        ("evidence://order-1",),
        ("currency_explicit",),
        evidence_digests={"evidence://order-1": digest},
    )
    assert validate_binding(binding, require_evidence=True, require_assumptions=True) == ()
    assert len(binding.binding_sha256) == 64
    assert validate_evidence_payload("payload", digest)
    with pytest.raises(ValueError, match="payload hash"):
        validate_evidence_payload("tampered", digest)
    persisted = binding.as_dict()
    persisted["binding_sha256"] = "0" * 64
    assert "binding_digest_mismatch" in validate_binding(persisted)


def test_proof_receipt_replay_detects_module_revision(tmp_path):
    module = tmp_path / "Proof.lean"
    module.write_text("theorem t : True := by trivial\n", encoding="utf-8")
    artifact_digest = hashlib.sha256(module.read_bytes()).hexdigest()
    receipt = ProofArtifactReceipt(
        stable_key="k",
        theorem="t",
        module="Proof.lean",
        manifest_sha256="a" * 64,
        artifact_sha256=artifact_digest,
        build_output_sha256="b" * 64,
        status="proved",
    )
    assert validate_proof_receipt(receipt, root=tmp_path) == ()
    replayed = replay_proof_receipt(receipt, root=tmp_path, expected_manifest_sha256="a" * 64)
    assert replayed["status"] == "replayable"
    module.write_text("theorem t : True := by decide\n", encoding="utf-8")
    stale = replay_proof_receipt(receipt, root=tmp_path, expected_manifest_sha256="a" * 64)
    assert stale["status"] == "stale"
    assert stale["replay_allowed"] is False
