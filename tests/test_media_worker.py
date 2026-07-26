from apps.control_plane.media_worker import run_once


class FakeWorkbench:
    def __init__(self, *, claimed=None, failure: Exception | None = None):
        self.claimed = claimed
        self.failure = failure
        self.executed = []

    def claim_video(self, *, worker_id):
        return self.claimed

    def execute_video(self, execution_id, *, worker_id):
        self.executed.append((execution_id, worker_id))
        if self.failure:
            raise self.failure
        return {"id": execution_id, "status": "generated"}


def test_worker_stays_idle_without_synthetic_jobs():
    result = run_once(FakeWorkbench(), worker_id="worker-1")

    assert result == {
        "status": "idle",
        "worker_id": "worker-1",
        "execution_id": None,
        "external_marketplace_write": False,
    }


def test_worker_executes_only_the_postgresql_lease_it_claimed():
    workbench = FakeWorkbench(claimed={"id": "mex-1"})

    result = run_once(workbench, worker_id="worker-1")

    assert result["status"] == "completed"
    assert result["execution_id"] == "mex-1"
    assert result["external_marketplace_write"] is False
    assert workbench.executed == [("mex-1", "worker-1")]


def test_worker_reports_ffmpeg_failure_without_platform_side_effect():
    workbench = FakeWorkbench(
        claimed={"id": "mex-2"},
        failure=RuntimeError("ffmpeg failed"),
    )

    result = run_once(workbench, worker_id="worker-2")

    assert result["status"] == "failed"
    assert result["error_code"] == "RuntimeError"
    assert result["external_marketplace_write"] is False
