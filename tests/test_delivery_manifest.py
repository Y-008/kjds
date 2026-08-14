"""BAS-188 DeliveryManifest assembly contract tests (first slice)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from apps.control_plane.delivery_manifest import (
    DeliveryManifestError,
    GovernedDeliveryManifestWorkspace,
)

AS_OF = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _workspace() -> GovernedDeliveryManifestWorkspace:
    return GovernedDeliveryManifestWorkspace()


def _scope(**overrides: str) -> dict[str, str]:
    scope = {"tenant_ref": "tenant-1", "entity_ref": "entity-1", "store_ref": "store-1"}
    scope.update(overrides)
    return scope


def _image(ref: str = "img-1") -> dict:
    return {
        "kind": "image",
        "artifact_ref": ref,
        "contract_id": "kjds-media-job-artifact-reference-v1",
        "contract_version": "1.0.0",
        "sha256": _sha(f"image:{ref}"),
        "metadata": {"width": 1080, "height": 1920},
    }


def _video(ref: str = "vid-1", deps: list[str] | None = None) -> dict:
    return {
        "kind": "video",
        "artifact_ref": ref,
        "contract_id": "kjds-media-job-artifact-reference-v1",
        "contract_version": "1.0.0",
        "sha256": _sha(f"video:{ref}"),
        "metadata": {
            "width": 1080,
            "height": 1920,
            "duration_ms": 3000,
            "encoder_manifest_sha256": _sha("encoder-1"),
        },
        "depends_on": deps if deps is not None else ["img-1"],
    }


def _blueprint(ref: str = "bp-1", deps: list[str] | None = None) -> dict:
    return {
        "kind": "editing_blueprint",
        "artifact_ref": ref,
        "contract_id": "kjds-editing-blueprint-v1",
        "contract_version": "1.0.0",
        "sha256": _sha(f"blueprint:{ref}"),
        "metadata": {"schema_version": "1.0.0", "source_asset_refs": ["img-1"]},
        "depends_on": deps if deps is not None else ["vid-1"],
    }


def _tutorial(ref: str = "tut-1", deps: list[str] | None = None) -> dict:
    return {
        "kind": "tutorial",
        "artifact_ref": ref,
        "contract_id": "kjds-tutorial-graph-v1",
        "contract_version": "1.0.0",
        "sha256": _sha(f"tutorial:{ref}"),
        "metadata": {
            "tutorial_graph_version": _sha("tutorial-graph-1"),
            "capture_manifest_sha256": _sha("capture-1"),
        },
        "depends_on": deps if deps is not None else ["bp-1"],
    }


def _all_artifacts() -> list[dict]:
    return [_image(), _video(), _blueprint(), _tutorial()]


def _assemble(workspace=None, artifacts=None, scope=None, target=None, key="k1"):
    workspace = workspace or _workspace()
    return workspace.assemble(
        scope=scope or _scope(),
        as_of=AS_OF,
        artifact_refs=artifacts if artifacts is not None else _all_artifacts(),
        delivery_target=target,
        idempotency_key=key,
    )


def test_assembles_full_manifest_proposal_only():
    outcome = _assemble()
    assert outcome.status == "PROPOSAL_ONLY"
    assert outcome.reason_code == "social_delivery_target_not_admitted"
    assert outcome.delivery_target_admitted is False
    assert outcome.external_write_allowed is False
    assert outcome.listing_eligible is False
    assert len(outcome.manifest_sha256) == 64
    assert len(outcome.artifacts) == 4
    assert all(not value for value in outcome.zero_authority.values())


def test_deterministic_replay():
    first = _assemble()
    second = _assemble()
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.status == second.status


def test_topological_order_is_deterministic_and_respects_deps():
    shuffled = [_tutorial(), _image(), _blueprint(), _video()]
    outcome = _assemble(artifacts=shuffled)
    ordered_refs = [a.artifact_ref for a in outcome.artifacts]
    assert ordered_refs.index("img-1") < ordered_refs.index("vid-1")
    assert ordered_refs.index("vid-1") < ordered_refs.index("bp-1")
    assert ordered_refs.index("bp-1") < ordered_refs.index("tut-1")


def test_different_scope_changes_manifest():
    first = _assemble()
    second = _assemble(scope=_scope(store_ref="store-2"))
    assert first.manifest_sha256 != second.manifest_sha256


def test_different_idempotency_key_changes_manifest():
    first = _assemble(key="k1")
    second = _assemble(key="k2")
    assert first.manifest_sha256 != second.manifest_sha256


def test_empty_artifacts_rejected():
    with pytest.raises(DeliveryManifestError):
        _assemble(artifacts=[])


def test_duplicate_artifact_ref_rejected():
    artifacts = [_image(), _image()]
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=artifacts)
    assert "duplicate_artifact_ref" in str(exc.value)


def test_unknown_kind_rejected():
    bad = _image()
    bad["kind"] = "unknown_kind"
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[bad])
    assert "artifact_kind_not_recognized" in str(exc.value)


def test_missing_metadata_rejected():
    bad = _image()
    bad["metadata"] = {"width": 1080}
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[bad])
    assert "metadata_missing_key" in str(exc.value)


def test_sensitive_metadata_rejected():
    bad = _image()
    bad["metadata"] = {"width": 1080, "height": "authorization: Bearer xyz"}
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[bad])
    assert "sensitive_value_rejected" in str(exc.value)


def test_sensitive_scope_rejected():
    with pytest.raises(DeliveryManifestError):
        _assemble(scope=_scope(tenant_ref="api_key=secret"))


def test_bad_sha256_rejected():
    bad = _image()
    bad["sha256"] = "not-a-hex"
    with pytest.raises(DeliveryManifestError):
        _assemble(artifacts=[bad])


def test_unknown_dependency_rejected():
    bad = _image()
    bad["depends_on"] = ["missing-ref"]
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[bad])
    assert "dependency_unknown" in str(exc.value)


def test_self_dependency_rejected():
    bad = _image()
    bad["depends_on"] = ["img-1"]
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[bad])
    assert "self_dependency" in str(exc.value)


def test_dependency_cycle_rejected():
    a = _image()
    a["depends_on"] = ["vid-1"]
    b = _video(deps=["img-1"])
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(artifacts=[a, b])
    assert "dependency_cycle" in str(exc.value)


def test_scope_unknown_key_rejected():
    with pytest.raises(DeliveryManifestError) as exc:
        _assemble(scope={**_scope(), "authority_sha256": "x"})
    assert "scope_unknown_key" in str(exc.value)


def test_readback_pending_and_verified_and_invalidated():
    outcome = _assemble()
    pending = _workspace().readback(outcome)
    assert pending["readback_state"] == "PENDING"
    assert pending["integrity_ok"] is True

    verified = _workspace().readback(outcome, observed_manifest_sha256=outcome.manifest_sha256)
    assert verified["readback_state"] == "VERIFIED"
    assert verified["integrity_ok"] is True

    invalidated = _workspace().readback(outcome, observed_manifest_sha256=_sha("other"))
    assert invalidated["readback_state"] == "INVALIDATED"
    assert invalidated["integrity_ok"] is False


def test_invalidate():
    outcome = _assemble()
    result = _workspace().invalidate(outcome, reason="scope_revoked")
    assert result.status == "INVALIDATED"
    assert result.reason_code == "scope_revoked"
    assert result.manifest_sha256 == outcome.manifest_sha256


def test_mark_stale():
    outcome = _assemble()
    result = _workspace().mark_stale(outcome, reason="source_rotated")
    assert result.status == "STALE"
    assert result.reason_code == "source_rotated"


def test_social_target_never_admitted():
    outcome = _assemble(target={"channel_ref": "social://channel-1", "contract_id": "kjds-social-delivery-target-v1", "contract_version": "1.0.0"})
    assert outcome.delivery_target_admitted is False
    assert outcome.external_write_allowed is False
    assert outcome.status == "PROPOSAL_ONLY"
