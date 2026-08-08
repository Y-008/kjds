import json
import sys
from pathlib import Path

import pytest

from apps.control_plane import ozon_read_worker
from apps.control_plane.ozon_read_worker import offline_finance_preflight, offline_preflight


def valid_environment() -> dict[str, str]:
    return {
        "KJDS_PILOT_READER_API_KEY": "pilot-reader-private-value",
        "OZON_CLIENT_ID": "seller-private-id",
        "OZON_API_KEY": "ozon-private-value",
        "OZON_API_URL": "https://api-seller.ozon.ru",
        "OZON_PRODUCT_ATTRIBUTES_PATH": "/v4/product/info/attributes",
        "KJDS_CONTROL_PLANE_URL": "http://127.0.0.1:8000",
    }


def run_preflight(environment=None, **overrides):
    values = {
        "pilot_id": "pilot-private-id",
        "offer_ids": ["offer-private-id"],
        "idempotency_key": "idempotency-private-key",
        "environment": valid_environment() if environment is None else environment,
    }
    values.update(overrides)
    return offline_preflight(**values)


def test_offline_preflight_returns_only_safe_hashed_configuration():
    environment = valid_environment()
    report = run_preflight(environment)

    assert report["status"] == "ready_for_explicit_execution"
    assert report["mode"] == "offline_preflight"
    assert report["network_calls_performed"] is False
    assert report["contract_version"] == "ozon-product-read-v1"
    assert report["target_count"] == 1
    assert report["required_credentials_present"] == 3
    assert report["credential_values_distinct"] is True
    assert report["explicit_execution_required"] is True
    serialized = json.dumps(report)
    for private_value in (
        "pilot-private-id",
        "offer-private-id",
        "idempotency-private-key",
        *environment.values(),
    ):
        assert private_value not in serialized


def test_finance_preflight_is_offline_bounded_and_does_not_expose_dates_or_secrets():
    environment = valid_environment()
    report = offline_finance_preflight(
        pilot_id="pilot-private-id",
        date_from="2026-07-01T08:00:00+08:00",
        date_to="2026-07-02T08:00:00+08:00",
        idempotency_key="idempotency-private-key",
        page=2,
        page_size=500,
        environment=environment,
    )
    assert report["operation"] == "ozon.finance.read"
    assert report["contract_version"] == "ozon-finance-transactions-v1"
    assert report["network_calls_performed"] is False
    assert report["page"] == 2
    assert report["page_size"] == 500
    assert len(report["query_window_sha256"]) == 64
    serialized = json.dumps(report)
    assert "2026-07" not in serialized
    for private_value in environment.values():
        assert private_value not in serialized


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"date_from": "2026-07-01T00:00:00"}, "timezone"),
        ({"date_to": "2026-08-02T00:00:00Z"}, "31 days"),
        ({"page": 0}, "positive integer"),
        ({"page_size": 0}, "between 1 and 1000"),
    ],
)
def test_finance_preflight_rejects_unsafe_query_shapes(overrides, message):
    values = {
        "pilot_id": "pilot-private-id",
        "date_from": "2026-07-01T00:00:00Z",
        "date_to": "2026-07-02T00:00:00Z",
        "idempotency_key": "idempotency-private-key",
        "page": 1,
        "page_size": 1000,
        "environment": valid_environment(),
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        offline_finance_preflight(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"offer_ids": []}, "exactly one"),
        ({"offer_ids": ["one", "two"]}, "exactly one"),
        ({"batch": True}, "non-batch"),
        ({"cursor": "1"}, "non-batch"),
        ({"page_size": 1}, "default page size"),
        ({"pilot_id": "missing"}, "Pilot id"),
        ({"idempotency_key": "missing"}, "Idempotency key"),
    ],
)
def test_offline_preflight_rejects_non_initial_pilot_shapes(overrides, message):
    with pytest.raises(ValueError, match=message):
        run_preflight(**overrides)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"OZON_API_URL": "http://api-seller.ozon.ru"}, "safe origin"),
        ({"OZON_API_URL": "https://example.com"}, "host is not allowed"),
        (
            {"OZON_API_URL": "https://api-seller.ozon.ru/path?secret=value"},
            "safe origin",
        ),
        ({"OZON_PRODUCT_ATTRIBUTES_PATH": "/v3/unknown"}, "fixed v4"),
        ({"KJDS_CONTROL_PLANE_URL": "file:///private"}, "safe origin"),
        ({"KJDS_CONTROL_PLANE_URL": "http://control.example.com"}, "requires HTTPS"),
        ({"KJDS_PILOT_READER_API_KEY": ""}, "must be configured"),
        ({"OZON_API_KEY": "replace-me"}, "must be configured"),
    ],
)
def test_offline_preflight_rejects_unsafe_environment(change, message):
    environment = valid_environment()
    environment.update(change)
    with pytest.raises(ValueError, match=message):
        run_preflight(environment)


def test_offline_preflight_rejects_credential_reuse_without_exposing_value():
    environment = valid_environment()
    environment["KJDS_EXECUTOR_API_KEY"] = environment["KJDS_PILOT_READER_API_KEY"]
    with pytest.raises(ValueError, match="must be distinct") as caught:
        run_preflight(environment)
    assert environment["KJDS_PILOT_READER_API_KEY"] not in str(caught.value)


@pytest.mark.parametrize(
    "control_plane_url",
    ["http://localhost:8000", "http://api:8000", "https://control.example.com"],
)
def test_offline_preflight_accepts_local_compose_or_https_control_plane(control_plane_url):
    environment = valid_environment()
    environment["KJDS_CONTROL_PLANE_URL"] = control_plane_url

    assert run_preflight(environment)["network_calls_performed"] is False


def test_preflight_cli_returns_before_any_http_client_is_constructed(monkeypatch, capsys):
    for name, value in valid_environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_read_worker",
            "--preflight",
            "--pilot-id",
            "pilot-private-id",
            "--offer-id",
            "offer-private-id",
            "--idempotency-key",
            "idempotency-private-key",
        ],
    )

    def fail_client(*args, **kwargs):
        raise AssertionError("offline preflight must not construct an HTTP client")

    monkeypatch.setattr(ozon_read_worker.httpx, "Client", fail_client)
    ozon_read_worker.main()

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["network_calls_performed"] is False
    assert "private" not in output


@pytest.mark.parametrize("mode_args", [[], ["--preflight", "--execute"]])
def test_worker_cli_requires_exactly_one_explicit_mode_before_constructing_clients(
    monkeypatch, mode_args
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_read_worker",
            *mode_args,
            "--pilot-id",
            "pilot-private-id",
            "--offer-id",
            "offer-private-id",
            "--idempotency-key",
            "idempotency-private-key",
        ],
    )

    def fail_client(*args, **kwargs):
        raise AssertionError("missing execution intent must fail before constructing a client")

    monkeypatch.setattr(ozon_read_worker.httpx, "Client", fail_client)
    with pytest.raises(SystemExit) as caught:
        ozon_read_worker.main()
    assert caught.value.code == 2


def test_execute_mode_revalidates_current_environment_before_constructing_clients(monkeypatch):
    environment = valid_environment()
    environment["KJDS_CONTROL_PLANE_URL"] = "http://control.example.com"
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ozon_read_worker",
            "--execute",
            "--pilot-id",
            "pilot-private-id",
            "--offer-id",
            "offer-private-id",
            "--idempotency-key",
            "idempotency-private-key",
        ],
    )

    def fail_client(*args, **kwargs):
        raise AssertionError("execution-time validation must run before constructing a client")

    monkeypatch.setattr(ozon_read_worker.httpx, "Client", fail_client)
    with pytest.raises(ValueError, match="requires HTTPS"):
        ozon_read_worker.main()


def test_operator_script_defaults_to_no_deps_preflight_before_explicit_execute():
    script = Path("scripts/run-ozon-read-worker.ps1").read_text(encoding="utf-8")
    preflight = script.index("--preflight")
    execution_gate = script.index("if (-not $Execute)")
    live_run = script.rindex("docker compose --profile read-only-pilot run --rm ozon-read-worker")

    assert "[switch]$Execute" in script
    assert "--rm --no-deps ozon-read-worker" in script
    assert "--pilot-id $PilotId" in script
    assert "--idempotency-key $IdempotencyKey" in script
    assert '"--offer-id=$OfferId"' in script
    assert '"--offer-id=$targetOfferId"' in script
    assert preflight < execution_gate < live_run


def test_compose_worker_command_carries_explicit_execution_intent():
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    read_worker = compose.split("  ozon-read-worker:", maxsplit=1)[1]

    assert "      - --execute" in read_worker
