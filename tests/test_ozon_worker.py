import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from apps.control_plane import ozon_worker
from apps.control_plane.ozon_read_worker import (
    ControlPlanePilotReaderClient,
    OzonFinanceReadOnlyWorker,
    OzonReadOnlyWorker,
)
from apps.control_plane.ozon_worker import (
    ControlPlaneExecutorClient,
    ExecutionCheckpointError,
    OzonApiError,
    OzonCredentials,
    OzonExecutionWorker,
    OzonSellerClient,
    offline_execution_preflight,
)


class FakeControlPlane:
    def __init__(self, commands):
        self.commands = commands
        self.claims = []
        self.receipts = []
        self.checkpoints = []
        self.trace_ids = []

    def get_command(self, command_id, *, trace_id):
        self.trace_ids.append(trace_id)
        return next(item for item in self.commands if item["id"] == command_id)

    def claim(self, command_id, state_hash, *, trace_id):
        self.trace_ids.append(trace_id)
        self.claims.append((command_id, state_hash))
        original = next(item for item in self.commands if item["id"] == command_id)
        return {**original, "status": "claimed"}

    def begin_write_attempt(self, command_id, *, trace_id):
        self.trace_ids.append(trace_id)
        original = next(item for item in self.commands if item["id"] == command_id)
        return {
            **original,
            "status": "write_started",
            "write_attempt_consumed": True,
        }

    def checkpoint_response(
        self,
        command_id,
        *,
        artifact_kind,
        content,
        sequence_number,
        trace_id,
    ):
        self.trace_ids.append(trace_id)
        evidence_id = f"evd-{artifact_kind}-{sequence_number if sequence_number is not None else 'single'}"
        self.checkpoints.append(
            {
                "command_id": command_id,
                "artifact_kind": artifact_kind,
                "content": content,
                "sequence_number": sequence_number,
                "evidence_id": evidence_id,
            }
        )
        return {
            "evidence_id": evidence_id,
            "artifact_kind": artifact_kind,
            "sequence_number": sequence_number,
            "immutable": True,
        }

    def receipt(self, command_id, body, *, trace_id):
        self.trace_ids.append(trace_id)
        self.receipts.append((command_id, body))
        return {"command_id": command_id, "trace_id": trace_id, **body}


def execution_environment():
    return {
        "KJDS_EXECUTOR_API_KEY": "executor-private-key",
        "KJDS_OZON_EXECUTION_IDENTITY_REF": "ozon-worker-private-id",
        "OZON_CLIENT_ID": "write-client-private-id",
        "OZON_API_KEY": "write-api-private-key",
        "OZON_API_URL": "https://api-seller.ozon.ru",
        "OZON_PRODUCT_ATTRIBUTES_PATH": "/v4/product/info/attributes",
        "KJDS_CONTROL_PLANE_URL": "http://127.0.0.1:8000",
    }


class RecordingEnvironment(dict):
    def __init__(self, values):
        super().__init__(values)
        self.reads = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.reads.append(key)
        return super().__getitem__(key)


def command():
    value = {
        "id": "lxc-1",
        "plan_id": "gxp-1",
        "parent_command_id": None,
        "command_kind": "execute",
        "status": "queued",
        "adapter_id": "ozon.product.import.v3",
        "action_id": "listing_publish",
        "action_policy_version": "2026-07-21.2",
        "decision_hash": "a" * 64,
        "permit_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "risk_limits": {
            "max_daily_runs": "5",
            "max_expected_loss": "500",
            "max_quantity": "1",
        },
        "risk_values": {"expected_loss": "300", "quantity": "1"},
        "risk_currency": "CNY",
        "portfolio_risk": {
            "schema_version": "action-budget-snapshot-v1",
            "mode": "queue_reservation",
            "occurred_at": datetime.now(UTC).isoformat(),
            "utc_day": datetime.now(UTC).date().isoformat(),
            "action_id": "listing_publish",
            "currency": "CNY",
            "prior_command_ids": [],
            "command_count": 1,
            "max_daily_runs": 5,
            "risk_totals": {"expected_loss": "300", "quantity": "1"},
            "derived_daily_limits": {"expected_loss": "2500", "quantity": "5"},
            "coverage": "action_utc_day_currency",
            "unmodeled_axes": ["sku", "category", "store", "legal_entity", "cash_floor"],
            "allowed": True,
            "blocking_reasons": [],
        },
        "target": {"offer_id": "offer-1"},
        "patch": {"item": {"offer_id": "offer-1", "name": "Updated name"}},
    }
    value["portfolio_risk"]["snapshot_hash"] = OzonExecutionWorker._hash(value["portfolio_risk"])
    value["authorization_hash"] = OzonExecutionWorker._authorization_hash(value)
    return value


def test_execution_preflight_is_offline_hashed_and_single_command():
    environment = execution_environment()
    report = offline_execution_preflight(
        command_id="command-private-id",
        offer_id="offer-private-id",
        evidence_ids=["evidence-private-id"],
        environment=environment,
    )

    assert report["status"] == "ready_for_explicit_execution"
    assert report["network_calls_performed"] is False
    assert report["target_count"] == 1
    assert report["evidence_count"] == 1
    assert report["credential_values_read"] is False
    assert report["required_credentials_present"] == 0
    assert report["provider_credentials_from_environment"] is False
    serialized = json.dumps(report)
    for private_value in (
        "command-private-id",
        "offer-private-id",
        "evidence-private-id",
        *environment.values(),
    ):
        assert private_value not in serialized


@pytest.mark.parametrize("mode_args", [[], ["--preflight", "--execute"]])
def test_execution_cli_requires_exactly_one_mode_before_clients(monkeypatch, mode_args):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_worker",
            *mode_args,
            "--command-id",
            "lxc-1",
            "--offer-id",
            "offer-1",
            "--evidence-id",
            "evd-1",
        ],
    )
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("execution intent must fail before client construction")
        ),
    )
    with pytest.raises(SystemExit) as caught:
        ozon_worker.main()
    assert caught.value.code == 2


def test_execution_preflight_cli_returns_before_http_clients(monkeypatch, capsys):
    for name, value in execution_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_worker",
            "--preflight",
            "--command-id",
            "command-private-id",
            "--offer-id",
            "offer-private-id",
            "--evidence-id",
            "evidence-private-id",
        ],
    )
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline preflight must not construct an HTTP client")
        ),
    )

    ozon_worker.main()

    output = capsys.readouterr().out
    assert json.loads(output)["network_calls_performed"] is False
    assert "private" not in output


@pytest.mark.parametrize("mode", ["--preflight", "--execute"])
def test_worker_modes_do_not_read_credentials_before_runtime_admission(monkeypatch, mode):
    environment = RecordingEnvironment(execution_environment())
    monkeypatch.setattr(ozon_worker.os, "environ", environment)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_worker",
            mode,
            "--command-id",
            "command-private-id",
            "--offer-id",
            "offer-private-id",
            "--evidence-id",
            "evidence-private-id",
        ],
    )
    if mode == "--execute":
        with pytest.raises(RuntimeError, match="resolver is not bound"):
            ozon_worker.main()
    else:
        ozon_worker.main()
    forbidden = {
        "KJDS_EXECUTOR_API_KEY",
        "KJDS_API_KEY",
        "KJDS_PILOT_READER_API_KEY",
        "OZON_CLIENT_ID",
        "OZON_API_KEY",
        "KJDS_CHANNEL_SECRET_LOCATOR",
        "KJDS_CHANNEL_CREDENTIAL_FINGERPRINT",
    }
    assert forbidden.isdisjoint(environment.reads)


def test_unbound_runtime_resolver_blocks_before_any_worker_client(monkeypatch):
    for name, value in execution_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_worker",
            "--execute",
            "--command-id",
            "command-private-id",
            "--offer-id",
            "offer-private-id",
            "--evidence-id",
            "evidence-private-id",
        ],
    )
    constructed = []
    monkeypatch.setattr(
        ozon_worker,
        "ControlPlaneExecutorClient",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    monkeypatch.setattr(
        ozon_worker,
        "OzonSellerClient",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    with pytest.raises(RuntimeError, match="resolver is not bound"):
        ozon_worker.main()
    assert constructed == []


def test_execution_worker_compose_and_script_require_explicit_one_shot_intent():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    worker = compose.split("  ozon-worker:", maxsplit=1)[1].split("  ozon-read-worker:", maxsplit=1)[0]
    script = Path("scripts/run-ozon-worker.ps1").read_text(encoding="utf-8")

    assert "      - --execute" in worker
    assert "      - --command-id" in worker
    assert "      - --offer-id" in worker
    assert "KJDS_EXECUTION_EVIDENCE_IDS" in worker
    assert "KJDS_EXECUTION_EVIDENCE_ID:-" not in worker
    assert "KJDS_EXECUTION_EVIDENCE_ID =" not in script
    assert "OZON_WRITE_CLIENT_ID" not in worker
    assert "OZON_WRITE_API_KEY" not in worker
    assert "OZON_CLIENT_ID" not in worker
    assert "OZON_API_KEY" not in worker
    assert "[switch]$Execute" in script
    assert "--rm --no-deps ozon-worker" in script
    assert script.index("--preflight") < script.index("if (-not $Execute)")


def test_ozon_worker_isolates_credentials_reads_state_and_confirms_async_import():
    calls = []
    state_version = {"value": 1}

    def handler(request: httpx.Request):
        calls.append((request.url.path, request.headers, request.read()))
        assert request.headers["Client-Id"] == "client-1"
        assert request.headers["Api-Key"] == "secret-key"
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(200, json={"items": [{"offer_id": "offer-1", "version": state_version["value"]}]})
        if request.url.path == "/v4/product/info/attributes":
            name = "Name" if state_version["value"] == 1 else "Updated name"
            return httpx.Response(200, json={"result": [{"offer_id": "offer-1", "name": name}]})
        if request.url.path == "/v3/product/import":
            state_version["value"] = 2
            return httpx.Response(200, json={"result": {"task_id": 42}})
        if request.url.path == "/v1/product/import/info":
            return httpx.Response(
                200,
                json={"result": {"items": [{"offer_id": "offer-1", "status": "imported", "errors": []}]}},
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    credentials = OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key")
    assert "secret-key" not in repr(credentials)
    ozon = OzonSellerClient(credentials, transport=httpx.MockTransport(handler))
    control = FakeControlPlane([command()])
    worker = OzonExecutionWorker(control_plane=control, ozon=ozon)
    try:
        receipt = worker.run_once(
            command_id="lxc-1",
            offer_id="offer-1",
            evidence_ids=["evd-1"],
        )
    finally:
        ozon.close()

    assert receipt["outcome"] == "succeeded"
    assert receipt["mutation_applied"] is True
    assert receipt["remote_operation_id"] == "42"
    assert control.claims[0][0] == "lxc-1"
    assert control.claims[0][1] != receipt["resulting_state_hash"]
    assert [path for path, _, _ in calls].count("/v3/product/import") == 1
    assert [item["artifact_kind"] for item in control.checkpoints] == [
        "before_read",
        "product_import_response",
        "import_status_response",
        "after_read",
    ]
    assert control.checkpoints[2]["sequence_number"] == 0
    assert control.receipts[0][1]["evidence_ids"] == [
        "evd-1",
        "evd-before_read-single",
        "evd-product_import_response-single",
        "evd-import_status_response-0",
        "evd-after_read-single",
    ]
    assert len(set(control.trace_ids)) == 1


def test_ozon_worker_rejects_expired_or_tampered_execution_permits():
    expired = {**command(), "status": "claimed"}
    expired["permit_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    expired["authorization_hash"] = OzonExecutionWorker._authorization_hash(expired)
    with pytest.raises(ValueError, match="expired"):
        OzonExecutionWorker._validate_claimed_command(expired)

    tampered = {**command(), "status": "claimed"}
    tampered["risk_values"] = {"expected_loss": "900", "quantity": "1"}
    with pytest.raises(ValueError, match="authorization hash"):
        OzonExecutionWorker._validate_claimed_command(tampered)

    internally_tampered = {**command(), "status": "claimed"}
    internally_tampered["portfolio_risk"] = {
        **internally_tampered["portfolio_risk"],
        "risk_totals": {"expected_loss": "1", "quantity": "1"},
    }
    internally_tampered["authorization_hash"] = OzonExecutionWorker._authorization_hash(internally_tampered)
    with pytest.raises(ValueError, match="portfolio risk snapshot"):
        OzonExecutionWorker._validate_claimed_command(internally_tampered)


def test_ozon_write_transport_failure_is_never_blindly_retried():
    calls = {"writes": 0}

    def handler(request: httpx.Request):
        if request.url.path == "/v3/product/import":
            calls["writes"] += 1
            raise httpx.ConnectError("connection lost after send", request=request)
        return httpx.Response(200, json={})

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OzonApiError, match="outcome is uncertain") as caught:
            client.import_product({"offer_id": "offer-1", "name": "Name"})
    finally:
        client.close()
    assert caught.value.retryable is False
    assert calls["writes"] == 1


class FailingImportCheckpointControlPlane(FakeControlPlane):
    def checkpoint_response(self, command_id, **values):
        if values["artifact_kind"] == "product_import_response":
            raise ExecutionCheckpointError("durable checkpoint unavailable")
        return super().checkpoint_response(command_id, **values)


class ScriptedExecutionOzon:
    def __init__(self, *, import_result=None, import_error=None, status_result=None, status_error=None, after=None):
        self.import_result = import_result or {
            "task_id": "42",
            "response_evidence_bytes": b"import-response",
        }
        self.import_error = import_error
        self.status_result = status_result or {
            "status": "succeeded",
            "response_evidence_bytes": [b"status-response"],
        }
        self.status_error = status_error
        self.after = after
        self.offer_reads = 0
        self.import_calls = 0

    def offer_state(self, offer_id):
        self.offer_reads += 1
        if self.offer_reads == 1:
            state = {
                "contract_version": "ozon-product-read-v1",
                "offer_id": offer_id,
                "info": {"items": [{"offer_id": offer_id, "version": 1}]},
                "attributes": {"result": [{"offer_id": offer_id, "name": "Name"}]},
            }
            return {
                "state": state,
                "state_hash": OzonSellerClient.state_hash(state),
                "response_evidence_bytes": b"before-response",
            }
        if isinstance(self.after, Exception):
            raise self.after
        state = self.after or {
            "contract_version": "ozon-product-read-v1",
            "offer_id": offer_id,
            "info": {"items": [{"offer_id": offer_id, "version": 2}]},
            "attributes": {"result": [{"offer_id": offer_id, "name": "Updated name"}]},
        }
        return {
            "state": state,
            "state_hash": OzonSellerClient.state_hash(state),
            "response_evidence_bytes": b"after-response",
        }

    def import_product(self, _item):
        self.import_calls += 1
        if self.import_error is not None:
            raise self.import_error
        return self.import_result

    def wait_for_import(self, task_id, *, on_response=None):
        assert task_id == "42"
        captures = self.status_result.get("response_evidence_bytes", [])
        for index, content in enumerate(captures):
            if on_response is not None:
                on_response(content, index)
        if self.status_error is not None:
            if self.status_error.response_evidence_bytes is not None and on_response is not None:
                on_response(self.status_error.response_evidence_bytes, len(captures))
            raise self.status_error
        return {key: value for key, value in self.status_result.items() if key != "response_evidence_bytes"}


def test_worker_records_uncertainty_when_import_response_checkpoint_fails():
    calls = {"writes": 0}
    state_version = {"value": 1}

    def handler(request: httpx.Request):
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(
                200,
                json={"items": [{"offer_id": "offer-1", "version": state_version["value"]}]},
            )
        if request.url.path == "/v4/product/info/attributes":
            return httpx.Response(
                200,
                json={"result": [{"offer_id": "offer-1", "name": "Name"}]},
            )
        if request.url.path == "/v3/product/import":
            calls["writes"] += 1
            state_version["value"] = 2
            return httpx.Response(200, json={"result": {"task_id": 42}})
        raise AssertionError(f"Unexpected path after lost import checkpoint: {request.url.path}")

    ozon = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    control = FailingImportCheckpointControlPlane([command()])
    try:
        receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
            command_id="lxc-1",
            offer_id="offer-1",
            evidence_ids=["evd-1"],
        )
    finally:
        ozon.close()

    assert calls["writes"] == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["remote_operation_id"] == "42"
    assert receipt["error_code"] == "CONTROL_PLANE_CHECKPOINT_FAILED"
    assert receipt["evidence_ids"] == ["evd-1", "evd-before_read-single"]


def test_worker_write_transport_ambiguity_records_uncertain_without_replay():
    ozon = ScriptedExecutionOzon(
        import_error=OzonApiError(
            "Ozon write outcome is uncertain after transport failure",
            code="OZON_WRITE_UNCERTAIN",
            retryable=False,
        )
    )
    control = FakeControlPlane([command()])

    receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
        command_id="lxc-1",
        offer_id="offer-1",
        evidence_ids=["evd-1"],
    )

    assert ozon.import_calls == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["remote_operation_id"] is None
    assert receipt["error_code"] == "OZON_WRITE_UNCERTAIN"
    assert [item["artifact_kind"] for item in control.checkpoints] == ["before_read"]


def test_worker_preserves_known_task_and_terminal_status_evidence_after_poll_failure():
    ozon = ScriptedExecutionOzon(
        status_result={
            "status": "uncertain",
            "response_evidence_bytes": [b"prior-status-response"],
        },
        status_error=OzonApiError(
            "Ozon status read failed",
            code="OZON_HTTP_503",
            status_code=503,
            retryable=True,
            response_evidence_bytes=b"terminal-status-response",
        ),
    )
    control = FakeControlPlane([command()])

    receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
        command_id="lxc-1",
        offer_id="offer-1",
        evidence_ids=["evd-1"],
    )

    assert ozon.import_calls == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["remote_operation_id"] == "42"
    assert receipt["error_code"] == "OZON_HTTP_503"
    assert [item["artifact_kind"] for item in control.checkpoints] == [
        "before_read",
        "product_import_response",
        "import_status_response",
        "import_status_response",
    ]
    assert [item["sequence_number"] for item in control.checkpoints[-2:]] == [0, 1]


def test_worker_poll_timeout_is_uncertain_and_never_reads_after_state():
    ozon = ScriptedExecutionOzon(
        status_result={
            "status": "uncertain",
            "response_evidence_bytes": [b"pending-status-response"],
        }
    )
    control = FakeControlPlane([command()])

    receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
        command_id="lxc-1",
        offer_id="offer-1",
        evidence_ids=["evd-1"],
    )

    assert ozon.import_calls == 1
    assert ozon.offer_reads == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["remote_operation_id"] == "42"
    assert receipt["error_code"] == "OZON_IMPORT_NOT_CONFIRMED"


def test_worker_after_read_failure_cannot_report_success():
    ozon = ScriptedExecutionOzon(
        after=OzonApiError(
            "Ozon after-state read failed",
            code="OZON_READ_TRANSPORT",
            retryable=True,
        )
    )
    control = FakeControlPlane([command()])

    receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
        command_id="lxc-1",
        offer_id="offer-1",
        evidence_ids=["evd-1"],
    )

    assert ozon.import_calls == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["error_code"] == "OZON_AFTER_READ_UNCERTAIN"
    assert "evd-after_read-single" not in receipt["evidence_ids"]


def test_worker_readback_divergence_is_uncertain_with_after_evidence():
    divergent_state = {
        "contract_version": "ozon-product-read-v1",
        "offer_id": "offer-1",
        "info": {"items": [{"offer_id": "offer-1", "version": 2}]},
        "attributes": {"result": [{"offer_id": "offer-1", "name": "Unexpected name"}]},
    }
    ozon = ScriptedExecutionOzon(after=divergent_state)
    control = FakeControlPlane([command()])

    receipt = OzonExecutionWorker(control_plane=control, ozon=ozon).run_once(
        command_id="lxc-1",
        offer_id="offer-1",
        evidence_ids=["evd-1"],
    )

    assert ozon.import_calls == 1
    assert receipt["outcome"] == "uncertain"
    assert receipt["mutation_applied"] is True
    assert receipt["error_code"] == "OZON_READBACK_DIVERGENT"
    assert receipt["evidence_ids"][-1] == "evd-after_read-single"


def test_ozon_read_retries_rate_limit_without_leaking_response_body(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr("apps.control_plane.ozon_worker.time.sleep", lambda _: None)

    def handler(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "secret upstream detail"})
        return httpx.Response(200, json={"result": {"items": []}})

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.import_status("42")
    finally:
        client.close()
    assert result["response"] == {"result": {"items": []}}
    assert calls["count"] == 2


def test_offer_state_falls_back_to_v3_attributes_contract_on_not_found():
    paths = []

    def handler(request: httpx.Request):
        paths.append(request.url.path)
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(200, json={"items": [{"offer_id": "offer-1"}]})
        if request.url.path == "/v4/product/info/attributes":
            return httpx.Response(404, json={"message": "method version unavailable"})
        if request.url.path == "/v3/products/info/attributes":
            return httpx.Response(200, json={"result": [{"offer_id": "offer-1"}]})
        raise AssertionError(request.url.path)

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        state = client.offer_state("offer-1")
    finally:
        client.close()
    assert len(state["state_hash"]) == 64
    assert state["contract_version"] == "ozon-product-read-v1"
    assert paths[-2:] == ["/v4/product/info/attributes", "/v3/products/info/attributes"]


def test_finance_transactions_use_bounded_official_contract_and_capture_raw_evidence():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.read())
        calls.append((request.url.path, body))
        return httpx.Response(
            200,
            json={
                "result": {
                    "operations": [{"operation_id": 123, "amount": 42.5, "posting": "private-order"}],
                    "page_count": 4,
                }
            },
        )

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.finance_transactions(
            date_from="2026-07-01T08:00:00+08:00",
            date_to="2026-07-02T08:00:00+08:00",
            page=2,
            page_size=500,
        )
    finally:
        client.close()

    assert calls == [
        (
            "/v3/finance/transaction/list",
            {
                "filter": {
                    "date": {
                        "from": "2026-07-01T00:00:00Z",
                        "to": "2026-07-02T00:00:00Z",
                    },
                    "operation_type": [],
                    "posting_number": "",
                    "transaction_type": "all",
                },
                "page": 2,
                "page_size": 500,
            },
        )
    ]
    assert result["contract_version"] == "ozon-finance-transactions-v1"
    assert result["operation_count"] == 1
    assert result["page_count"] == 4
    assert len(result["query_window_sha256"]) == 64
    bundle = json.loads(result["response_evidence_bytes"])
    assert bundle["contract_version"] == "ozon-finance-transactions-v1"
    assert b"private-order" in base64.b64decode(bundle["responses"][0]["body_base64"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"date_from": "2026-07-01T00:00:00"}, "timezone"),
        ({"date_to": "2026-07-01T00:00:00Z"}, "before"),
        ({"date_to": "2026-08-02T00:00:00Z"}, "31 days"),
        ({"page": 0}, "positive integer"),
        ({"page_size": 1001}, "between 1 and 1000"),
    ],
)
def test_finance_transactions_reject_unsafe_query_shapes_before_network(overrides, message):
    calls = []
    values = {
        "date_from": "2026-07-01T00:00:00Z",
        "date_to": "2026-07-02T00:00:00Z",
        "page": 1,
        "page_size": 1000,
    }
    values.update(overrides)
    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    )
    try:
        with pytest.raises(ValueError, match=message):
            client.finance_transactions(**values)
    finally:
        client.close()
    assert calls == []


def test_finance_transactions_fail_closed_on_schema_drift():
    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"result": {"transactions": []}})),
    )
    try:
        with pytest.raises(OzonApiError) as caught:
            client.finance_transactions(
                date_from="2026-07-01T00:00:00Z",
                date_to="2026-07-02T00:00:00Z",
            )
    finally:
        client.close()
    assert caught.value.code == "OZON_SCHEMA_DRIFT"


@pytest.mark.parametrize(
    ("info_items", "attribute_items", "error_code"),
    [
        ([], [{"offer_id": "offer-1"}], "OZON_TARGET_NOT_FOUND"),
        (
            [{"offer_id": "offer-1"}, {"offer_id": "other-offer"}],
            [{"offer_id": "offer-1"}],
            "OZON_TARGET_AMBIGUOUS",
        ),
        ([{"offer_id": "other-offer"}], [{"offer_id": "offer-1"}], "OZON_TARGET_MISMATCH"),
        ([{"offer_id": "offer-1"}], [{"offer_id": "other-offer"}], "OZON_TARGET_MISMATCH"),
        ([{"offer_id": "offer-1"}], [{"name": "missing target"}], "OZON_SCHEMA_DRIFT"),
    ],
)
def test_offer_state_fails_closed_when_single_target_binding_is_not_proven(
    info_items,
    attribute_items,
    error_code,
):
    def handler(request: httpx.Request):
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(200, json={"items": info_items})
        if request.url.path == "/v4/product/info/attributes":
            return httpx.Response(200, json={"result": attribute_items})
        raise AssertionError(request.url.path)

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OzonApiError) as caught:
            client.offer_state("offer-1")
    finally:
        client.close()
    assert caught.value.code == error_code
    assert caught.value.retryable is False
    assert "offer-1" not in str(caught.value)
    assert "other-offer" not in str(caught.value)


class FakePilotControlPlane:
    def __init__(self):
        self.start_calls = []
        self.completion_bodies = []
        self.response_captures = []
        self.trace_ids = []

    def start(self, pilot_id, *, trace_id, **body):
        self.trace_ids.append(trace_id)
        self.start_calls.append((pilot_id, body))
        return {
            "id": "ror-1",
            "status": "started",
            "execution_granted": True,
            "idempotency_replay": False,
        }

    def complete(self, run_id, body, *, trace_id):
        self.trace_ids.append(trace_id)
        self.completion_bodies.append((run_id, body))
        return {
            "id": run_id,
            "status": "completed",
            "outcome": body["outcome"],
            "evidence_id": "evd-summary",
        }

    def checkpoint_response(
        self,
        run_id,
        *,
        content,
        response_sha256,
        response_byte_size,
        record_count,
        summary,
        trace_id,
    ):
        self.trace_ids.append(trace_id)
        self.response_captures.append((run_id, content, response_sha256))
        self.completion_bodies.append(
            (
                run_id,
                {
                    "outcome": "succeeded",
                    "response_sha256": response_sha256,
                    "response_byte_size": response_byte_size,
                    "record_count": record_count,
                    "summary": summary,
                    "error_code": None,
                },
            )
        )
        return {"id": run_id, "status": "response_captured"}

    def finalize(self, run_id, *, trace_id):
        self.trace_ids.append(trace_id)
        return {
            "id": run_id,
            "status": "completed",
            "outcome": "succeeded",
            "evidence_id": "evd-summary",
            "raw_response_stored": True,
        }


def test_read_only_worker_calls_only_read_contract_and_returns_sanitized_summary():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        assert request.headers["Client-Id"] == "client-1"
        assert request.headers["Api-Key"] == "secret-key"
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(
                200,
                json={"items": [{"offer_id": "private-offer", "name": "sensitive product"}]},
            )
        if request.url.path == "/v4/product/info/attributes":
            return httpx.Response(
                200,
                json={"result": [{"offer_id": "private-offer", "attribute": "sensitive"}]},
            )
        raise AssertionError(request.url.path)

    ozon = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    control = FakePilotControlPlane()
    try:
        result = OzonReadOnlyWorker(control_plane=control, ozon=ozon).run_once(
            pilot_id="rop-1",
            offer_id="private-offer",
            idempotency_key="read-1",
        )
    finally:
        ozon.close()
    assert result["outcome"] == "succeeded"
    assert calls == ["/v3/product/info/list", "/v4/product/info/attributes"]
    assert all("import" not in path for path in calls)
    completion = control.completion_bodies[0][1]
    serialized = str(completion)
    assert "private-offer" not in serialized
    assert "sensitive product" not in serialized
    assert "secret-key" not in serialized
    assert completion["summary"]["info_item_count"] == 1
    assert completion["summary"]["attribute_item_count"] == 1
    assert completion["summary"]["contract_version"] == "ozon-product-read-v1"
    assert len(completion["response_sha256"]) == 64
    assert len(set(control.trace_ids)) == 1
    raw_capture = control.response_captures[0][1]
    assert b"secret-key" not in raw_capture
    bundle = json.loads(raw_capture)
    assert bundle["schema_version"] == "ozon-response-bundle-v2"
    assert bundle["contract_version"] == "ozon-product-read-v1"
    bodies = [base64.b64decode(item["body_base64"]) for item in bundle["responses"]]
    assert any(b"private-offer" in body for body in bodies)
    assert any(b"sensitive product" in body for body in bodies)


def test_finance_read_worker_checkpoints_raw_response_and_only_safe_summary():
    def handler(request: httpx.Request):
        assert request.url.path == "/v3/finance/transaction/list"
        return httpx.Response(
            200,
            json={
                "result": {
                    "operations": [{"operation_id": "private-transaction", "amount": "999.99"}],
                    "page_count": 1,
                }
            },
        )

    ozon = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    control = FakePilotControlPlane()
    try:
        result = OzonFinanceReadOnlyWorker(control_plane=control, ozon=ozon).run_once(
            pilot_id="rop-finance",
            date_from="2026-07-01T00:00:00Z",
            date_to="2026-07-02T00:00:00Z",
            page=1,
            page_size=1000,
            idempotency_key="finance-read-1",
        )
    finally:
        ozon.close()
    assert result["outcome"] == "succeeded"
    start = control.start_calls[0][1]
    assert start["operation"] == "ozon.finance.read"
    assert len(start["target_ref"]) == 64
    completion = control.completion_bodies[0][1]
    assert completion["record_count"] == 1
    assert completion["summary"] == {
        "contract_version": "ozon-finance-transactions-v1",
        "query_window_sha256": start["target_ref"],
        "page": 1,
        "page_size": 1000,
        "page_count": 1,
        "operation_count": 1,
    }
    assert "private-transaction" not in str(completion)
    assert "999.99" not in str(completion)
    bundle = json.loads(control.response_captures[0][1])
    assert b"private-transaction" in base64.b64decode(bundle["responses"][0]["body_base64"])


def test_finance_worker_uses_managed_client_factory_without_instance_client():
    class GrantingControl(FakePilotControlPlane):
        def start(self, pilot_id, *, trace_id, **body):
            self.trace_ids.append(trace_id)
            self.start_calls.append((pilot_id, body))
            return {
                "id": "ror-finance-factory",
                "status": "started",
                "execution_granted": True,
                "credential_grant": {"required_capability": "finance.read"},
                "idempotency_replay": False,
            }

    class FakeOzon:
        def finance_transactions(self, *, date_from, date_to, page, page_size):
            return {
                "contract_version": "ozon-finance-transactions-v1",
                "query_window_sha256": "q" * 64,
                "page": 1,
                "page_size": 1000,
                "page_count": 1,
                "operation_count": 1,
                "response_evidence_bytes": json.dumps(
                    {
                        "result": {
                            "operations": [
                                {"operation_id": "op-factory"}
                            ]
                        }
                    }
                ).encode(),
            }

    class Factory:
        def __init__(self, ozon):
            self.ozon = ozon

        def open(self, *, grant, as_of):
            return self

        def __enter__(self):
            return self.ozon

        def __exit__(self, *exc):
            return False

    control = GrantingControl()
    worker = OzonFinanceReadOnlyWorker(
        control_plane=control,
        ozon_client_factory=Factory(FakeOzon()),
    )
    result = worker.run_once(
        pilot_id="rop-finance-factory",
        date_from="2026-07-01T00:00:00Z",
        date_to="2026-07-02T00:00:00Z",
        page=1,
        page_size=1000,
        idempotency_key="finance-factory-1",
    )
    assert result["outcome"] == "succeeded"
    assert control.start_calls[0][1]["operation"] == "ozon.finance.read"
    assert len(control.start_calls[0][1]["target_ref"]) == 64


def test_read_only_worker_returns_replay_without_calling_ozon_or_completing_again():
    class ReplayControl(FakePilotControlPlane):
        def start(self, pilot_id, *, trace_id, **body):
            self.trace_ids.append(trace_id)
            self.start_calls.append((pilot_id, body))
            return {
                "id": "ror-existing",
                "status": "completed",
                "outcome": "succeeded",
                "evidence_id": "evd-existing",
                "execution_granted": False,
                "idempotency_replay": True,
            }

    class MustNotCallOzon:
        def offer_state(self, offer_id):
            raise AssertionError("Ozon must not be called for an idempotency replay")

    control = ReplayControl()
    result = OzonReadOnlyWorker(control_plane=control, ozon=MustNotCallOzon()).run_once(
        pilot_id="rop-1",
        offer_id="private-offer",
        idempotency_key="read-existing",
    )
    assert result["id"] == "ror-existing"
    assert result["execution_granted"] is False
    assert result["idempotency_replay"] is True
    assert control.response_captures == []
    assert control.completion_bodies == []


class _ClientLease:
    def __init__(self, client, events, capability):
        self.client = client
        self.events = events
        self.capability = capability

    def __enter__(self):
        self.events.append(("client_enter", self.capability))
        return self.client

    def __exit__(self, *_exc):
        self.events.append(("client_exit", self.capability))


class _GrantBoundClientFactory:
    def __init__(self, clients, events):
        self.clients = clients
        self.events = events
        self.opens = []

    def open(self, *, grant, as_of):
        capability = grant["required_capability"]
        self.events.append(("client_open", capability))
        self.opens.append((grant, as_of))
        return _ClientLease(self.clients[capability], self.events, capability)


class _ReadGrantClient:
    def offer_state(self, _offer_id):
        payload = b'{"responses":[]}'
        return {
            "contract_version": "ozon-product-read-v1",
            "state": {"info": {"items": []}, "attributes": {"result": []}},
            "state_hash": "a" * 64,
            "response_evidence_bytes": payload,
        }


def test_read_worker_opens_exact_scope_client_only_after_execution_grant():
    events = []
    grant = {
        "grant_id": "read-grant-1",
        "required_capability": "catalog.read",
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
    }

    class GrantedControl(FakePilotControlPlane):
        def start(self, pilot_id, *, trace_id, **body):
            events.append(("control_start", pilot_id))
            result = super().start(pilot_id, trace_id=trace_id, **body)
            events.append(("execution_granted", result["execution_granted"]))
            return {**result, "credential_grant": grant}

    factory = _GrantBoundClientFactory(
        {"catalog.read": _ReadGrantClient()},
        events,
    )
    result = OzonReadOnlyWorker(
        control_plane=GrantedControl(),
        ozon_client_factory=factory,
    ).run_once(
        pilot_id="pilot-1",
        offer_id="offer-1",
        idempotency_key="read-grant-order-1",
    )

    assert result["outcome"] == "succeeded"
    assert events.index(("execution_granted", True)) < events.index(
        ("client_open", "catalog.read")
    )
    assert factory.opens[0][0] is grant


def test_read_worker_missing_credential_grant_fails_before_client_factory():
    events = []
    factory = _GrantBoundClientFactory(
        {"catalog.read": _ReadGrantClient()},
        events,
    )

    with pytest.raises(PermissionError, match="credential grant"):
        OzonReadOnlyWorker(
            control_plane=FakePilotControlPlane(),
            ozon_client_factory=factory,
        ).run_once(
            pilot_id="pilot-1",
            offer_id="offer-1",
            idempotency_key="missing-read-grant",
        )

    assert factory.opens == []


def test_read_only_worker_batch_is_bounded_cursored_and_does_not_leak_targets():
    class BatchControl:
        def __init__(self):
            self.index = 0
            self.starts = []

        def start(self, pilot_id, *, trace_id, **body):
            self.index += 1
            self.starts.append((pilot_id, body))
            return {
                "id": f"ror-{self.index}",
                "status": "started",
                "execution_granted": True,
                "idempotency_replay": False,
            }

        def complete(self, run_id, body, *, trace_id):
            return {
                "id": run_id,
                "status": "completed",
                "outcome": body["outcome"],
                "evidence_id": f"evd-{run_id}",
                "raw_response_stored": body["outcome"] == "succeeded",
            }

        def checkpoint_response(self, run_id, **kwargs):
            return {"id": run_id, "status": "response_captured"}

        def finalize(self, run_id, *, trace_id):
            return {
                "id": run_id,
                "status": "completed",
                "outcome": "succeeded",
                "evidence_id": f"evd-{run_id}",
                "raw_response_stored": True,
            }

    class BatchOzon:
        def offer_state(self, offer_id):
            state = {
                "contract_version": "ozon-product-read-v1",
                "offer_id": offer_id,
                "info": {"items": [offer_id]},
                "attributes": {"result": []},
            }
            return {
                "contract_version": "ozon-product-read-v1",
                "state": state,
                "state_hash": OzonSellerClient.state_hash(state),
                "response_evidence_bytes": str(state).encode(),
            }

    control = BatchControl()
    result = OzonReadOnlyWorker(control_plane=control, ozon=BatchOzon()).run_batch(
        pilot_id="rop-1",
        offer_ids=["offer-1", "offer-2", "offer-3"],
        batch_idempotency_key="batch-1",
        page_size=2,
    )
    assert result["cursor"] == "0"
    assert result["next_cursor"] == "2"
    assert result["page_count"] == 2
    assert result["succeeded_count"] == 2
    assert result["raw_response_stored"] is True
    assert all(item["raw_response_stored"] is True for item in result["results"])
    assert all("offer-1" not in str(item) and "offer-2" not in str(item) for item in result["results"])
    assert all(len(item["target_sha256"]) == 64 for item in result["results"])
    assert [item[1]["target_ref"] for item in control.starts] == ["offer-1", "offer-2"]
    with pytest.raises(ValueError, match="duplicate"):
        OzonReadOnlyWorker(control_plane=control, ozon=BatchOzon()).run_batch(
            pilot_id="rop-1",
            offer_ids=["offer-1", "offer-1"],
            batch_idempotency_key="batch-2",
        )


def test_read_only_worker_records_target_mismatch_without_raw_capture_or_target_leak():
    def handler(request: httpx.Request):
        if request.url.path == "/v3/product/info/list":
            return httpx.Response(200, json={"items": [{"offer_id": "unexpected-private"}]})
        raise AssertionError(request.url.path)

    ozon = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    control = FakePilotControlPlane()
    try:
        result = OzonReadOnlyWorker(control_plane=control, ozon=ozon).run_once(
            pilot_id="rop-1",
            offer_id="expected-private",
            idempotency_key="read-mismatch",
        )
    finally:
        ozon.close()
    assert result["outcome"] == "failed"
    assert control.response_captures == []
    completion = control.completion_bodies[0][1]
    assert completion["error_code"] == "OZON_TARGET_MISMATCH"
    assert completion["summary"]["connector_error_code"] == "OZON_TARGET_MISMATCH"
    assert "expected-private" not in str(completion)
    assert "unexpected-private" not in str(completion)


def test_control_plane_client_propagates_one_trace_with_bounded_request_ids():
    headers = []

    def handler(request: httpx.Request):
        headers.append(request.headers)
        return httpx.Response(201, json={"id": "ror-1", "status": "started"})

    client = ControlPlanePilotReaderClient(
        base_url="http://control-plane.test",
        api_key="reader-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        client.start(
            "rop-1",
            idempotency_key="run-1",
            operation="ozon.product.read",
            target_ref="offer-1",
            trace_id="trace-worker-read",
        )
        client.complete("ror-1", {"outcome": "succeeded"}, trace_id="trace-worker-read")
        client.capture_response(
            "ror-1",
            content=b'{"responses":[]}',
            response_sha256="a" * 64,
            trace_id="trace-worker-read",
        )
    finally:
        client.close()

    assert [item["X-Trace-ID"] for item in headers] == ["trace-worker-read"] * 3
    assert all(item["X-Request-ID"].startswith("req_") for item in headers)
    assert len({item["X-Request-ID"] for item in headers}) == 3


def test_control_plane_checkpoint_and_finalize_retry_5xx_without_platform_replay():
    calls = {"checkpoint": 0, "finalize": 0}

    def handler(request: httpx.Request):
        operation = "checkpoint" if request.url.path.endswith("response-checkpoint") else "finalize"
        calls[operation] += 1
        if calls[operation] < 3:
            return httpx.Response(503, json={"detail": "temporary"})
        status = "response_captured" if operation == "checkpoint" else "completed"
        return httpx.Response(200, json={"id": "ror-1", "status": status})

    client = ControlPlanePilotReaderClient(
        base_url="http://control-plane.test",
        api_key="reader-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        checkpoint = client.checkpoint_response(
            "ror-1",
            content=b'{"responses":[]}',
            response_sha256="a" * 64,
            response_byte_size=16,
            record_count=2,
            summary={"contract_version": "ozon-product-read-v1"},
            trace_id="trace-checkpoint-retry",
        )
        completed = client.finalize("ror-1", trace_id="trace-checkpoint-retry")
    finally:
        client.close()
    assert checkpoint["status"] == "response_captured"
    assert completed["status"] == "completed"
    assert calls == {"checkpoint": 3, "finalize": 3}


def test_execution_checkpoint_retries_idempotent_control_plane_failures():
    calls = {"count": 0}

    def handler(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, json={"detail": "temporary"})
        return httpx.Response(
            201,
            json={
                "evidence_id": "evd-checkpoint",
                "artifact_kind": "before_read",
                "immutable": True,
            },
        )

    client = ControlPlaneExecutorClient(
        base_url="http://control-plane.test",
        api_key="executor-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.checkpoint_response(
            "lxc-1",
            artifact_kind="before_read",
            content=b'{"responses":[]}',
            sequence_number=None,
            trace_id="trace-execution",
        )
    finally:
        client.close()
    assert result["evidence_id"] == "evd-checkpoint"
    assert calls["count"] == 3


@pytest.mark.parametrize("operation", ["checkpoint", "receipt"])
def test_execution_bookkeeping_exhausts_bounded_retries(operation):
    calls = {"count": 0}

    def handler(request: httpx.Request):
        calls["count"] += 1
        return httpx.Response(503, json={"detail": "temporary"})

    client = ControlPlaneExecutorClient(
        base_url="http://control-plane.test",
        api_key="executor-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        if operation == "checkpoint":
            with pytest.raises(ExecutionCheckpointError, match="durably checkpoint"):
                client.checkpoint_response(
                    "lxc-1",
                    artifact_kind="product_import_response",
                    content=b'{"responses":[]}',
                    sequence_number=None,
                    trace_id="trace-execution",
                )
        else:
            with pytest.raises(RuntimeError, match="execution receipt returned HTTP 503"):
                client.receipt(
                    "lxc-1",
                    {
                        "outcome": "uncertain",
                        "remote_operation_id": "42",
                        "resulting_state_hash": None,
                        "mutation_applied": False,
                        "error_code": "CHECKPOINT_FAILED",
                        "error_detail": "reconciliation required",
                        "evidence_ids": ["evd-before"],
                    },
                    trace_id="trace-execution",
                )
    finally:
        client.close()
    assert calls["count"] == 3


def test_execution_receipt_retries_with_one_stable_request_id():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.headers["X-Request-ID"])
        if len(calls) < 3:
            return httpx.Response(503, json={"detail": "temporary"})
        return httpx.Response(201, json={"id": "lxr-1", "outcome": "uncertain"})

    client = ControlPlaneExecutorClient(
        base_url="http://control-plane.test",
        api_key="executor-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.receipt(
            "lxc-1",
            {
                "outcome": "uncertain",
                "remote_operation_id": "42",
                "resulting_state_hash": None,
                "mutation_applied": False,
                "error_code": "CHECKPOINT_FAILED",
                "error_detail": "reconciliation required",
                "evidence_ids": ["evd-before"],
            },
            trace_id="trace-execution",
        )
    finally:
        client.close()
    assert result["id"] == "lxr-1"
    assert len(calls) == 3
    assert len(set(calls)) == 1


def test_ozon_schema_drift_fails_closed_without_leaking_response_body():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"unexpected": [{"secret": "upstream-private"}]})

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OzonApiError, match="schema drift") as caught:
            client.offer_state("offer-1")
    finally:
        client.close()
    assert caught.value.code == "OZON_SCHEMA_DRIFT"
    assert caught.value.retryable is False
    assert "upstream-private" not in str(caught.value)


def test_ozon_circuit_opens_after_bounded_5xx_failures_and_recovers(monkeypatch):
    calls = {"count": 0}
    now = {"value": 0.0}
    monkeypatch.setattr("apps.control_plane.ozon_worker.time.sleep", lambda _: None)

    def handler(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] <= 6:
            return httpx.Response(503, json={"message": "private upstream failure"})
        return httpx.Response(200, json={"result": {"items": []}})

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=10,
        clock=lambda: now["value"],
    )
    try:
        for _ in range(2):
            with pytest.raises(OzonApiError) as caught:
                client.import_status("42")
            assert caught.value.code == "OZON_HTTP_503"
        assert calls["count"] == 6
        assert client.circuit_status()["state"] == "open"
        with pytest.raises(OzonApiError) as opened:
            client.import_status("42")
        assert opened.value.code == "OZON_CIRCUIT_OPEN"
        assert calls["count"] == 6
        now["value"] = 11
        assert client.import_status("42")["response"] == {"result": {"items": []}}
        assert client.circuit_status()["state"] == "closed"
    finally:
        client.close()


class _BeforeWriteReadClient:
    def offer_state(self, offer_id):
        state = {
            "contract_version": "ozon-product-read-v1",
            "offer_id": offer_id,
            "info": {"items": [{"offer_id": offer_id, "version": 1}]},
            "attributes": {"result": [{"offer_id": offer_id, "name": "Name"}]},
        }
        return {
            "state": state,
            "state_hash": OzonSellerClient.state_hash(state),
            "response_evidence_bytes": b"before-response",
        }


class _WriteClientOpened(RuntimeError):
    pass


class _WriteOrderFactory(_GrantBoundClientFactory):
    def open(self, *, grant, as_of):
        capability = grant["required_capability"]
        self.events.append(("client_open", capability))
        self.opens.append((grant, as_of))
        if capability == "catalog.write":
            raise _WriteClientOpened("write client opened after authorization")
        return _ClientLease(self.clients[capability], self.events, capability)


def _grant(capability):
    return {
        "grant_id": f"grant-{capability}",
        "required_capability": capability,
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
    }


def test_write_worker_opens_catalog_write_only_after_claim_and_begin_attempt():
    events = []
    queued = {**command(), "credential_grant": _grant("catalog.read")}

    class GrantControl(FakeControlPlane):
        def get_command(self, command_id, *, trace_id):
            events.append(("get_command", command_id))
            return super().get_command(command_id, trace_id=trace_id)

        def claim(self, command_id, state_hash, *, trace_id):
            events.append(("claim", command_id))
            return super().claim(command_id, state_hash, trace_id=trace_id)

        def begin_write_attempt(self, command_id, *, trace_id):
            events.append(("begin_write_attempt", command_id))
            result = super().begin_write_attempt(command_id, trace_id=trace_id)
            events.append(("write_attempt_consumed", True))
            return {**result, "credential_grant": _grant("catalog.write")}

    factory = _WriteOrderFactory(
        {"catalog.read": _BeforeWriteReadClient()},
        events,
    )
    worker = OzonExecutionWorker(
        control_plane=GrantControl([queued]),
        ozon_client_factory=factory,
    )

    with pytest.raises(_WriteClientOpened):
        worker.run_once(
            command_id=queued["id"],
            offer_id="offer-1",
            evidence_ids=["evidence-1"],
        )

    write_open = events.index(("client_open", "catalog.write"))
    assert events.index(("claim", queued["id"])) < write_open
    assert events.index(("begin_write_attempt", queued["id"])) < write_open
    assert events.index(("write_attempt_consumed", True)) < write_open


def test_write_worker_missing_catalog_write_grant_fails_before_write_client():
    events = []
    queued = {**command(), "credential_grant": _grant("catalog.read")}

    class MissingWriteGrantControl(FakeControlPlane):
        def begin_write_attempt(self, command_id, *, trace_id):
            events.append(("begin_write_attempt", command_id))
            return super().begin_write_attempt(command_id, trace_id=trace_id)

    factory = _GrantBoundClientFactory(
        {"catalog.read": _BeforeWriteReadClient()},
        events,
    )
    worker = OzonExecutionWorker(
        control_plane=MissingWriteGrantControl([queued]),
        ozon_client_factory=factory,
    )

    with pytest.raises(PermissionError, match="credential grant"):
        worker.run_once(
            command_id=queued["id"],
            offer_id="offer-1",
            evidence_ids=["evidence-1"],
        )

    assert [grant["required_capability"] for grant, _as_of in factory.opens] == [
        "catalog.read"
    ]


class _LifecycleWriteClient:
    def __init__(self, events, outcome):
        self.events = events
        self.outcome = outcome

    def import_product(self, _item):
        self.events.append(("write_call", "import_product"))
        if self.outcome == "exception":
            raise RuntimeError("synthetic write client failure")
        return {
            "task_id": "42",
            "response_evidence_bytes": b"import-response",
        }

    def wait_for_import(self, task_id, *, on_response=None):
        assert task_id == "42"
        self.events.append(("write_call", "wait_for_import"))
        if on_response is not None:
            on_response(b"status-response", 0)
        return {
            "status": "uncertain" if self.outcome == "uncertain" else "succeeded"
        }

    def offer_state(self, offer_id):
        self.events.append(("write_call", "after_offer_state"))
        state = {
            "contract_version": "ozon-product-read-v1",
            "offer_id": offer_id,
            "info": {"items": [{"offer_id": offer_id, "version": 2}]},
            "attributes": {
                "result": [{"offer_id": offer_id, "name": "Updated name"}]
            },
        }
        return {
            "state": state,
            "state_hash": OzonSellerClient.state_hash(state),
            "response_evidence_bytes": b"after-response",
        }


class _LifecycleGrantControl(FakeControlPlane):
    def begin_write_attempt(self, command_id, *, trace_id):
        return {
            **super().begin_write_attempt(command_id, trace_id=trace_id),
            "credential_grant": _grant("catalog.write"),
        }


@pytest.mark.parametrize(
    ("outcome", "expected_calls", "expected_receipt"),
    [
        (
            "normal",
            ["import_product", "wait_for_import", "after_offer_state"],
            "succeeded",
        ),
        (
            "uncertain",
            ["import_product", "wait_for_import"],
            "uncertain",
        ),
    ],
)
def test_write_client_lease_exits_once_only_after_all_provider_calls(
    outcome,
    expected_calls,
    expected_receipt,
):
    events = []
    queued = {**command(), "credential_grant": _grant("catalog.read")}
    factory = _GrantBoundClientFactory(
        {
            "catalog.read": _BeforeWriteReadClient(),
            "catalog.write": _LifecycleWriteClient(events, outcome),
        },
        events,
    )

    receipt = OzonExecutionWorker(
        control_plane=_LifecycleGrantControl([queued]),
        ozon_client_factory=factory,
    ).run_once(
        command_id=queued["id"],
        offer_id="offer-1",
        evidence_ids=["evidence-1"],
    )

    assert receipt["outcome"] == expected_receipt
    assert [value for kind, value in events if kind == "write_call"] == expected_calls
    write_exit = events.index(("client_exit", "catalog.write"))
    assert all(
        events.index(("write_call", call)) < write_exit for call in expected_calls
    )
    assert events.count(("client_enter", "catalog.write")) == 1
    assert events.count(("client_exit", "catalog.write")) == 1


def test_write_client_lease_exception_path_exits_exactly_once_after_failure():
    events = []
    queued = {**command(), "credential_grant": _grant("catalog.read")}
    factory = _GrantBoundClientFactory(
        {
            "catalog.read": _BeforeWriteReadClient(),
            "catalog.write": _LifecycleWriteClient(events, "exception"),
        },
        events,
    )

    with pytest.raises(RuntimeError, match="synthetic write client failure"):
        OzonExecutionWorker(
            control_plane=_LifecycleGrantControl([queued]),
            ozon_client_factory=factory,
        ).run_once(
            command_id=queued["id"],
            offer_id="offer-1",
            evidence_ids=["evidence-1"],
        )

    failure_call = events.index(("write_call", "import_product"))
    write_exit = events.index(("client_exit", "catalog.write"))
    assert failure_call < write_exit
    assert events.count(("client_enter", "catalog.write")) == 1
    assert events.count(("client_exit", "catalog.write")) == 1


@pytest.mark.parametrize(
    "grant",
    [
        None,
        {},
        {"required_capability": "finance.read"},
        {"required_capability": "catalog.write"},
    ],
)
def test_read_worker_rejects_forged_or_capability_drifted_grant_before_factory(
    grant,
):
    events = []

    class DriftedGrantControl(FakePilotControlPlane):
        def start(self, pilot_id, *, trace_id, **body):
            return {
                **super().start(pilot_id, trace_id=trace_id, **body),
                "credential_grant": grant,
            }

    factory = _GrantBoundClientFactory(
        {"catalog.read": _ReadGrantClient()},
        events,
    )
    with pytest.raises(PermissionError, match="credential grant"):
        OzonReadOnlyWorker(
            control_plane=DriftedGrantControl(),
            ozon_client_factory=factory,
        ).run_once(
            pilot_id="pilot-1",
            offer_id="offer-1",
            idempotency_key="forged-read-grant",
        )

    assert factory.opens == []
    assert not [event for event in events if event[0].startswith("client_")]


def test_scope_drift_rejected_by_factory_never_enters_or_closes_provider_client():
    events = []
    drifted = {
        "grant_id": "read-grant-drifted",
        "required_capability": "catalog.read",
        "tenant_ref": "other-tenant",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
    }

    class DriftedGrantControl(FakePilotControlPlane):
        def start(self, pilot_id, *, trace_id, **body):
            return {
                **super().start(pilot_id, trace_id=trace_id, **body),
                "credential_grant": drifted,
            }

    class ExactScopeFactory:
        def __init__(self):
            self.opens = []

        def open(self, *, grant, as_of):
            self.opens.append((grant, as_of))
            if (
                grant.get("tenant_ref"),
                grant.get("entity_ref"),
                grant.get("store_ref"),
            ) != ("tenant-1", "entity-1", "store-1"):
                raise PermissionError("credential grant exact-scope drift")
            raise AssertionError("drifted grant must not create a client lease")

    factory = ExactScopeFactory()
    with pytest.raises(PermissionError, match="exact-scope drift"):
        OzonReadOnlyWorker(
            control_plane=DriftedGrantControl(),
            ozon_client_factory=factory,
        ).run_once(
            pilot_id="pilot-1",
            offer_id="offer-1",
            idempotency_key="scope-drift-read-grant",
        )

    assert len(factory.opens) == 1
    assert events == []


def test_category_tree_reads_official_contract_and_captures_raw_evidence():
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, json.loads(request.read())))
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "description_category_id": 17028634,
                        "category_name": "Кабели и переходники",
                        "children": [
                            {"type_name": "Органайзер для хранения проводов", "type_id": 97946, "children": []}
                        ],
                    }
                ]
            },
        )

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.category_tree(language="RU")
    finally:
        client.close()

    assert calls == [("/v1/description-category/tree", {"language": "RU"})]
    assert result["contract_version"] == "ozon-category-read-v1"
    assert len(result["state_hash"]) == 64
    assert result["state"]["result"][0]["category_name"] == "Кабели и переходники"
    bundle = json.loads(result["response_evidence_bytes"])
    assert bundle["contract_version"] == "ozon-category-read-v1"
    assert bundle["request_context"] == {"language": "RU"}
    assert "Кабели и переходники" in base64.b64decode(
        bundle["responses"][0]["body_base64"]
    ).decode("utf-8")


def test_category_attributes_reads_official_contract_and_captures_raw_evidence():
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.read())
        calls.append((request.url.path, body))
        return httpx.Response(
            200,
            json={
                "result": [
                    {"id": 85, "name": "Бренд", "type": "String", "is_required": True},
                    {"id": 9048, "name": "Название модели", "type": "String", "is_required": True},
                ]
            },
        )

    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.category_attributes(
            type_id=97946,
            description_category_id=17028634,
            language="RU",
        )
    finally:
        client.close()

    assert calls == [
        (
            "/v1/description-category/attribute",
            {"description_category_id": 17028634, "language": "RU", "type_id": 97946},
        )
    ]
    assert result["contract_version"] == "ozon-category-read-v1"
    assert len(result["state_hash"]) == 64
    assert result["state"]["result"][0]["id"] == 85
    bundle = json.loads(result["response_evidence_bytes"])
    assert bundle["request_context"] == {
        "description_category_id": 17028634,
        "type_id": 97946,
        "language": "RU",
    }
    assert "Название модели" in base64.b64decode(
        bundle["responses"][0]["body_base64"]
    ).decode("utf-8")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"type_id": 0, "description_category_id": 17028634}, "type_id"),
        ({"type_id": -1, "description_category_id": 17028634}, "type_id"),
        ({"type_id": 97946, "description_category_id": 0}, "description_category_id"),
        ({"type_id": True, "description_category_id": 17028634}, "type_id"),
        ({"type_id": 97946, "description_category_id": True}, "description_category_id"),
    ],
)
def test_category_attributes_reject_unsafe_shapes_before_network(kwargs, message):
    client = OzonSellerClient(
        OzonCredentials.for_test_fixture(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(lambda request: pytest.fail("network must not be reached")),
    )
    try:
        with pytest.raises(ValueError, match=message):
            client.category_attributes(**kwargs)
    finally:
        client.close()


def test_offline_preflight_rejects_empty_evidence_ids():
    with pytest.raises(ValueError, match="At least one Evidence id"):
        offline_execution_preflight(
            command_id="command-private-id",
            offer_id="offer-private-id",
            evidence_ids=[],
            environment=execution_environment(),
        )


def test_offline_preflight_rejects_control_char_identifiers():
    with pytest.raises(ValueError):
        offline_execution_preflight(
            command_id="command\nid",
            offer_id="offer-private-id",
            evidence_ids=["evidence-private-id"],
            environment=execution_environment(),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com",
        "http://api-seller.ozon.ru",
        "https://api-seller.ozon.ru/v4",
        "https://user:pass@api-seller.ozon.ru",
        "https://api-seller.ozon.ru?x=1",
        "https://api-seller.ozon.ru#frag",
    ],
)
def test_execution_environment_rejects_non_official_ozon_origin(url):
    env = execution_environment()
    env["OZON_API_URL"] = url
    with pytest.raises(ValueError):
        ozon_worker.validate_execution_environment(env)


def test_execution_environment_rejects_tampered_attributes_path():
    env = execution_environment()
    env["OZON_PRODUCT_ATTRIBUTES_PATH"] = "/v4/product/info/other"
    with pytest.raises(ValueError):
        ozon_worker.validate_execution_environment(env)


def test_execution_environment_rejects_external_control_plane_url():
    env = execution_environment()
    env["KJDS_CONTROL_PLANE_URL"] = "http://evil.example.com"
    with pytest.raises(ValueError):
        ozon_worker.validate_execution_environment(env)


def test_execution_environment_rejects_missing_identity_ref():
    env = execution_environment()
    del env["KJDS_OZON_EXECUTION_IDENTITY_REF"]
    with pytest.raises(ValueError):
        ozon_worker.validate_execution_environment(env)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#frag",
        "ftp://example.com",
    ],
)
def test_safe_url_rejects_credentials_query_fragment_path_and_bad_scheme(url):
    with pytest.raises(ValueError):
        ozon_worker._safe_url(url, name="URL", allowed_hosts={"example.com"}, require_https=True)


def test_safe_url_rejects_disallowed_host():
    with pytest.raises(ValueError):
        ozon_worker._safe_url(
            "https://evil.example.com",
            name="URL",
            allowed_hosts={"example.com"},
            require_https=True,
        )


def test_bounded_required_rejects_empty_oversized_and_control_chars():
    with pytest.raises(ValueError):
        ozon_worker._bounded_required("", "Name", 10)
    with pytest.raises(ValueError):
        ozon_worker._bounded_required("x" * 11, "Name", 10)
    with pytest.raises(ValueError):
        ozon_worker._bounded_required("x\ny", "Name", 10)
    assert ozon_worker._bounded_required("x" * 10, "Name", 10) == "x" * 10
