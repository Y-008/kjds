from pathlib import Path

from apps.control_plane.media_worker import run_governed_once

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "apps" / "control_plane" / "runtime.py"
WORKER = ROOT / "apps" / "control_plane" / "media_worker.py"


def test_runtime_composes_one_job_truth_and_distinct_execution_authorities():
    source = RUNTIME.read_text(encoding="utf-8")

    assert "media_jobs = GovernedMediaJobWorkspace(" in source
    assert "authority=scope_grants" in source
    assert "content_assets=repo" in source
    assert "media_jobs=media_jobs" in source
    assert "media_connector_contract = MediaConnectorContract()" in source
    assert "contract=media_connector_contract" in source
    assert "editing_blueprint = GovernedEditingBlueprintWorkspace(" in source
    assert "product_content=scoped_product_content" in source
    assert "media_workbench=media_workbench" in source
    assert "ffmpeg_adapter = FfmpegMediaWorker()" in source
    assert "ffmpeg_adapter=ffmpeg_adapter" in source
    assert "media_connector_contract=media_connector_contract" in source
    assert "editing_blueprint=editing_blueprint" in source
    assert source.count("GovernedMediaJobWorkspace(") == 1
    assert source.count("MediaConnectorContract()") == 1


class _Outcome:
    status = "EXECUTED"
    job_ref = "media-job-1"
    result_state = "SUCCEEDED"
    content_asset_ref = "asset-1"


class _EditingWorkspace:
    def __init__(self):
        self.calls = []

    def process(self, principal, store_ref, job_ref):
        self.calls.append((principal, store_ref, job_ref))
        return _Outcome()


def test_governed_worker_uses_explicit_job_without_legacy_queue_or_retry():
    workspace = _EditingWorkspace()

    result = run_governed_once(
        workspace,
        principal="principal",
        store_ref="store-1",
        job_ref="media-job-1",
        worker_id="worker-1",
    )

    assert workspace.calls == [("principal", "store-1", "media-job-1")]
    assert result == {
        "status": "executed",
        "worker_id": "worker-1",
        "job_ref": "media-job-1",
        "result_state": "SUCCEEDED",
        "content_asset_ref": "asset-1",
        "external_marketplace_write": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }
    worker_source = WORKER.read_text(encoding="utf-8")
    governed_body = worker_source.split("def run_governed_once", 1)[1].split(
        "def run_once", 1
    )[0]
    assert "claim_video" not in governed_body
    assert "execute_video" not in governed_body
