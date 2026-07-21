import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.control_plane.ozon_read_worker import (
    ControlPlanePilotReaderClient,
    OzonFinanceReadOnlyWorker,
    OzonReadOnlyWorker,
)
from apps.control_plane.ozon_worker import (
    OzonApiError,
    OzonCredentials,
    OzonExecutionWorker,
    OzonSellerClient,
)


class FakeControlPlane:
    def __init__(self, commands):
        self.commands = commands
        self.claims = []
        self.receipts = []
        self.trace_ids = []

    def list_commands(self, *, trace_id):
        self.trace_ids.append(trace_id)
        return self.commands

    def claim(self, command_id, state_hash, *, trace_id):
        self.trace_ids.append(trace_id)
        self.claims.append((command_id, state_hash))
        original = next(item for item in self.commands if item["id"] == command_id)
        return {**original, "status": "claimed"}

    def receipt(self, command_id, body, *, trace_id):
        self.trace_ids.append(trace_id)
        self.receipts.append((command_id, body))
        return {"command_id": command_id, "trace_id": trace_id, **body}


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
    value["portfolio_risk"]["snapshot_hash"] = OzonExecutionWorker._hash(
        value["portfolio_risk"]
    )
    value["authorization_hash"] = OzonExecutionWorker._authorization_hash(value)
    return value


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
            return httpx.Response(200, json={"result": [{"offer_id": "offer-1", "name": "Name"}]})
        if request.url.path == "/v3/product/import":
            state_version["value"] = 2
            return httpx.Response(200, json={"result": {"task_id": 42}})
        if request.url.path == "/v1/product/import/info":
            return httpx.Response(
                200,
                json={"result": {"items": [{"offer_id": "offer-1", "status": "imported", "errors": []}]}},
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    credentials = OzonCredentials(client_id="client-1", api_key="secret-key")
    assert "secret-key" not in repr(credentials)
    ozon = OzonSellerClient(credentials, transport=httpx.MockTransport(handler))
    control = FakeControlPlane([command()])
    worker = OzonExecutionWorker(control_plane=control, ozon=ozon)
    try:
        receipt = worker.run_once(evidence_ids=["evd-1"])
    finally:
        ozon.close()

    assert receipt["outcome"] == "succeeded"
    assert receipt["mutation_applied"] is True
    assert receipt["remote_operation_id"] == "42"
    assert control.claims[0][0] == "lxc-1"
    assert control.claims[0][1] != receipt["resulting_state_hash"]
    assert [path for path, _, _ in calls].count("/v3/product/import") == 1
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
    internally_tampered["authorization_hash"] = OzonExecutionWorker._authorization_hash(
        internally_tampered
    )
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OzonApiError, match="outcome is uncertain") as caught:
            client.import_product({"offer_id": "offer-1", "name": "Name"})
    finally:
        client.close()
    assert caught.value.retryable is False
    assert calls["writes"] == 1


def test_ozon_read_retries_rate_limit_without_leaking_response_body(monkeypatch):
    calls = {"count": 0}
    monkeypatch.setattr("apps.control_plane.ozon_worker.time.sleep", lambda _: None)

    def handler(request: httpx.Request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "secret upstream detail"})
        return httpx.Response(200, json={"result": {"items": []}})

    client = OzonSellerClient(
        OzonCredentials(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.import_status("42")
    finally:
        client.close()
    assert result == {"result": {"items": []}}
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
                    "operations": [
                        {"operation_id": 123, "amount": 42.5, "posting": "private-order"}
                    ],
                    "page_count": 4,
                }
            },
        )

    client = OzonSellerClient(
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"result": {"transactions": []}})
        ),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
                    "operations": [
                        {"operation_id": "private-transaction", "amount": "999.99"}
                    ],
                    "page_count": 1,
                }
            },
        )

    ozon = OzonSellerClient(
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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


def test_ozon_schema_drift_fails_closed_without_leaking_response_body():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"unexpected": [{"secret": "upstream-private"}]})

    client = OzonSellerClient(
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        OzonCredentials(client_id="client-1", api_key="secret-key"),
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
        assert client.import_status("42") == {"result": {"items": []}}
        assert client.circuit_status()["state"] == "closed"
    finally:
        client.close()
