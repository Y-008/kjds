import httpx
import pytest

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

    def list_commands(self):
        return self.commands

    def claim(self, command_id, state_hash):
        self.claims.append((command_id, state_hash))
        return {"id": command_id, "status": "claimed"}

    def receipt(self, command_id, body):
        self.receipts.append((command_id, body))
        return {"command_id": command_id, **body}


def command():
    return {
        "id": "lxc-1",
        "status": "queued",
        "adapter_id": "ozon.product.import.v3",
        "target": {"offer_id": "offer-1"},
        "patch": {"item": {"offer_id": "offer-1", "name": "Updated name"}},
    }


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
    assert paths[-2:] == ["/v4/product/info/attributes", "/v3/products/info/attributes"]
