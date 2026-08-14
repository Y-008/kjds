import sys
from types import SimpleNamespace

from apps.control_plane.media_worker import main, run_governed_once, run_once


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


class FakeEditingBlueprint:
    def __init__(self, *, outcome=None, failure: Exception | None = None):
        self.outcome = outcome
        self.failure = failure
        self.calls = []

    def process(self, principal, store_ref, job_ref):
        self.calls.append((principal, store_ref, job_ref))
        if self.failure:
            raise self.failure
        return self.outcome


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


def test_governed_worker_processes_one_explicit_job_without_second_queue():
    principal = object()
    editing = FakeEditingBlueprint(
        outcome=SimpleNamespace(
            status="SUCCEEDED",
            job_ref="job-1",
            result_state="SUCCEEDED",
            content_asset_ref="asset-1",
        )
    )

    result = run_governed_once(
        editing,
        principal=principal,
        store_ref="store-1",
        job_ref="job-1",
        worker_id="worker-3",
    )

    assert editing.calls == [(principal, "store-1", "job-1")]
    assert result == {
        "status": "succeeded",
        "worker_id": "worker-3",
        "job_ref": "job-1",
        "result_state": "SUCCEEDED",
        "content_asset_ref": "asset-1",
        "external_marketplace_write": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }


def test_governed_worker_failure_is_safe_and_never_retried_or_failed_over():
    secret = "provider-secret-must-not-escape"
    editing = FakeEditingBlueprint(failure=RuntimeError(secret))

    result = run_governed_once(
        editing,
        principal=object(),
        store_ref="store-1",
        job_ref="job-2",
        worker_id="worker-4",
    )

    assert len(editing.calls) == 1
    assert result == {
        "status": "failed",
        "worker_id": "worker-4",
        "job_ref": "job-2",
        "error_code": "RuntimeError",
        "external_marketplace_write": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }
    assert secret not in repr(result)


def test_main_routes_explicit_governed_job_through_configured_identity(monkeypatch):
    principal = object()
    editing = FakeEditingBlueprint(
        outcome=SimpleNamespace(
            status="READBACK",
            job_ref="job-main",
            result_state="SUCCEEDED",
            content_asset_ref="asset-main",
        )
    )
    authenticator = SimpleNamespace(
        resolve_actor=lambda actor_id: principal if actor_id == "actor-main" else None
    )
    runtime_module = SimpleNamespace(
        runtime=SimpleNamespace(
            authenticator=authenticator,
            editing_blueprint=editing,
        )
    )
    monkeypatch.setitem(sys.modules, "apps.control_plane.runtime", runtime_module)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "media-worker",
            "--once",
            "--worker-id",
            "worker-main",
            "--governed-job-ref",
            "job-main",
            "--actor-id",
            "actor-main",
            "--store-ref",
            "store-main",
        ],
    )

    assert main() == 0
    assert editing.calls == [(principal, "store-main", "job-main")]
