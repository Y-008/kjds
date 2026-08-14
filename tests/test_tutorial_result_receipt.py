"""BAS-187 tutorial result receipt admission tests (pure, in-memory)."""

from __future__ import annotations

import pytest

from apps.control_plane.media_jobs import (
    RESULT_RECEIPT_CONTRACT,
    GovernedMediaJobWorkspace,
    MediaJobEventRow,
    MediaJobRow,
    canonical_json,
    sha256_bytes,
)

TUTORIAL_TOOL = "tutorial.build"
TUTORIAL_RESULT_KIND = "tutorial_graph_and_media_evidence"


def _validate(receipt, job, event):
    return GovernedMediaJobWorkspace._validate_result_receipt(
        receipt=receipt,
        job=job,
        event=event,
    )


def _job() -> MediaJobRow:
    return MediaJobRow(
        job_ref="media-job-tutorial-1",
        tool_name=TUTORIAL_TOOL,
        provider="kjds_internal_tutorial_compiler",
        connector_ref="internal://tutorial-graph-compiler-v1",
        connector_binding_sha256="d0a0eb549be5a81cadb249bac37efce7a71768d49898c0c690dd7fd745f01a79",
    )


def _event() -> MediaJobEventRow:
    return MediaJobEventRow(
        event_ref="media_event_tutorial_1",
        event_sha256="e" * 64,
        state="SUCCEEDED",
    )


def _receipt_sha256(job, event, result_kind, refs, content_asset_ref) -> str:
    content = {
        "contract_id": RESULT_RECEIPT_CONTRACT,
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": result_kind,
        "artifact_evidence_refs": list(refs),
        "content_asset_ref": content_asset_ref,
        "event_ref": event.event_ref,
        "event_sha256": event.event_sha256,
        "job_ref": job.job_ref,
        "state": event.state,
    }
    return sha256_bytes(canonical_json(content))


def _receipt(job, event, refs, content_asset_ref=None) -> dict:
    return {
        "contract_id": RESULT_RECEIPT_CONTRACT,
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": TUTORIAL_RESULT_KIND,
        "artifact_evidence_refs": refs,
        "content_asset_ref": content_asset_ref,
        "receipt_sha256": _receipt_sha256(
            job,
            event,
            TUTORIAL_RESULT_KIND,
            refs,
            content_asset_ref,
        ),
    }


def test_tutorial_result_receipt_is_admitted() -> None:
    job = _job()
    event = _event()
    refs = ["evidence://tutorial-graph-1"]
    content, sha = _validate(_receipt(job, event, refs), job, event)
    assert content["result_kind"] == TUTORIAL_RESULT_KIND
    assert content["artifact_evidence_refs"] == refs
    assert sha == _receipt(job, event, refs)["receipt_sha256"]


def test_tutorial_result_requires_single_evidence_ref() -> None:
    job = _job()
    event = _event()
    with pytest.raises(ValueError, match="tutorial_evidence_invalid"):
        _validate(
            _receipt(job, event, ["evidence://a", "evidence://b"]),
            job,
            event,
        )


def test_tutorial_result_rejects_content_asset() -> None:
    job = _job()
    event = _event()
    with pytest.raises(ValueError, match="tutorial_evidence_invalid"):
        _validate(
            _receipt(
                job,
                event,
                ["evidence://tutorial-graph-1"],
                content_asset_ref="content-asset://x",
            ),
            job,
            event,
        )


def test_tutorial_tool_rejects_other_result_kind() -> None:
    job = _job()
    event = _event()
    receipt = {
        "contract_id": RESULT_RECEIPT_CONTRACT,
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": "video_artifact_evidence",
        "artifact_evidence_refs": ["evidence://x"],
        "content_asset_ref": None,
        "receipt_sha256": _receipt_sha256(job, event, "video_artifact_evidence", ["evidence://x"], None),
    }
    with pytest.raises(ValueError, match="result_kind_invalid"):
        _validate(receipt, job, event)


def test_blueprint_tool_rejects_tutorial_result_kind() -> None:
    job = MediaJobRow(
        job_ref="media-job-blueprint-1",
        tool_name="media.video_blueprint",
        provider="kjds_internal_blueprint_compiler",
        connector_ref="internal://editing-blueprint-compiler-v1",
        connector_binding_sha256="c" * 64,
    )
    event = _event()
    receipt = {
        "contract_id": RESULT_RECEIPT_CONTRACT,
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": TUTORIAL_RESULT_KIND,
        "artifact_evidence_refs": ["evidence://x"],
        "content_asset_ref": None,
        "receipt_sha256": _receipt_sha256(job, event, TUTORIAL_RESULT_KIND, ["evidence://x"], None),
    }
    with pytest.raises(ValueError, match="result_kind_invalid"):
        _validate(receipt, job, event)

def test_tutorial_result_skips_content_asset_binding() -> None:
    """Tutorial evidence-only results must never require a content asset."""
    job = _job()
    event = _event()
    content = {
        "contract_id": RESULT_RECEIPT_CONTRACT,
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": TUTORIAL_RESULT_KIND,
        "artifact_evidence_refs": ["evidence://tutorial-graph-1"],
        "content_asset_ref": None,
        "event_ref": event.event_ref,
        "event_sha256": event.event_sha256,
        "job_ref": job.job_ref,
        "state": event.state,
    }
    # The skip path returns before touching the session; a None session proves
    # that an evidence-only tutorial result does not require content binding.
    GovernedMediaJobWorkspace._bind_result_receipt_to_content_asset(
        session=None,
        job=job,
        event=event,
        content=content,
        receipt_sha256="r" * 64,
    )
