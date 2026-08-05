from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from apps.control_plane.api_contracts import current_principal
from apps.control_plane.routers import evidence_governance as evidence_router
from apps.control_plane.routers import strategic_benchmark as benchmark_router
from apps.control_plane.security import Principal

NOW = datetime.now(UTC)
NOW_QUERY = NOW.isoformat().replace("+00:00", "Z")


def principal(tenant: str = "tenant-a", *roles: str) -> Principal:
    return Principal(
        actor_id=f"actor-{tenant}",
        roles=frozenset(roles or ("admin",)),
        tenant_ref=tenant,
        store_refs=frozenset({"store-a"}),
    )


def snapshot(snapshot_ref: str, *, store_ref: str = "store-a") -> dict:
    return {
        "snapshot_ref": snapshot_ref,
        "store_ref": store_ref,
        "registry_schema": "kjds-strategic-benchmark-contracts-v1",
        "registry_sha256": "a" * 64,
        "as_of": NOW.isoformat(),
        "group_count": 1,
        "observation_count": 1,
        "snapshot_citation": {
            "token": "sbc_token",
            "sha256": "b" * 64,
            "grade": "D",
        },
        "request_sha256": "c" * 64,
        "idempotent_replay": False,
        "global_top1_claim": False,
        "formal_fact_created": False,
        "finance_entry_created": False,
        "approval_created": False,
        "permit_created": False,
        "external_write_allowed": False,
        "created_at": NOW.isoformat(),
    }


class FakeStrategicBenchmark:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.owners: dict[str, str] = {}
        self.extra_response = False

    def build_snapshot(self, **kwargs):
        self.calls.append(("build_snapshot", kwargs))
        if kwargs["idempotency_key"] == "conflict-key":
            raise benchmark_router.StrategicBenchmarkConflictError("idempotency conflict")
        snapshot_ref = f"sbs_{len(self.owners) + 1:032x}"
        self.owners[snapshot_ref] = kwargs["principal"].tenant_ref
        value = snapshot(snapshot_ref)
        if self.extra_response:
            value["raw_evidence_ids"] = ["evd-secret"]
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "snapshot": value,
            "groups": [],
        }

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        tenant = kwargs["principal"].tenant_ref
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "items": [
                snapshot(snapshot_ref)
                for snapshot_ref, owner in self.owners.items()
                if owner == tenant
            ],
            "next_cursor": "sbcursor_next" if self.owners else None,
        }

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        self._require_owner(kwargs["snapshot_ref"], kwargs["principal"])
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "snapshot": snapshot(kwargs["snapshot_ref"]),
            "groups": [],
        }

    def compare(self, **kwargs):
        self.calls.append(("compare", kwargs))
        self._require_owner(kwargs["snapshot_ref"], kwargs["principal"])
        self._require_owner(kwargs["baseline_snapshot_ref"], kwargs["principal"])
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "snapshot_ref": kwargs["snapshot_ref"],
            "baseline_snapshot_ref": kwargs["baseline_snapshot_ref"],
            "as_of": kwargs["as_of"],
            "comparisons": [],
            "global_top1_claim": False,
            "formal_fact_created": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        }

    def _require_owner(self, snapshot_ref: str, active: Principal) -> None:
        if self.owners.get(snapshot_ref) != active.tenant_ref:
            raise KeyError("not found")


@pytest.fixture
def api_client(monkeypatch):
    service = FakeStrategicBenchmark()
    active = {"principal": principal()}
    app = FastAPI()
    app.include_router(benchmark_router.router)
    app.dependency_overrides[current_principal] = lambda: active["principal"]
    monkeypatch.setattr(
        benchmark_router,
        "_runtime_services",
        lambda: SimpleNamespace(strategic_benchmark=service),
    )
    return TestClient(app, raise_server_exceptions=False), service, active


def body() -> dict:
    return {
        "store_ref": "store-a",
        "as_of": NOW.isoformat(),
        "evidence_refs": ["evd_one", "evd_two"],
    }


def post(client: TestClient, *, key: str = "benchmark-key", payload=None):
    return client.post(
        "/v1/strategic-benchmark-snapshots",
        headers={"Idempotency-Key": key},
        json=payload or body(),
    )


def query(**extra) -> str:
    parts = {"store_ref": "store-a", "as_of": NOW_QUERY, **extra}
    return "&".join(f"{key}={value}" for key, value in parts.items())


def test_post_accepts_only_evidence_refs_and_dispatches_server_scope(api_client):
    client, service, _active = api_client
    response = post(client)
    assert response.status_code == 201
    method, call = service.calls[-1]
    assert method == "build_snapshot"
    assert call["evidence_refs"] == ["evd_one", "evd_two"]
    assert call["principal"].tenant_ref == "tenant-a"
    assert "groups" not in call


@pytest.mark.parametrize(
    "field",
    [
        "tenant_ref",
        "entity_ref",
        "scope_authority_sha256",
        "groups",
        "value",
        "confidence_bps",
        "sample_size",
        "methodology_id",
        "source_kind",
        "subject_class",
    ],
)
def test_post_forbids_client_claim_and_scope_fields(api_client, field):
    client, _service, _active = api_client
    payload = body()
    payload[field] = "forged"
    assert post(client, payload=payload).status_code == 422


def test_list_get_compare_dispatch_filters_cursor_and_scope(api_client):
    client, service, _active = api_client
    baseline = post(client, key="baseline").json()["snapshot"]["snapshot_ref"]
    current = post(client, key="current").json()["snapshot"]["snapshot_ref"]
    listed = client.get(
        "/v1/strategic-benchmark-snapshots?"
        + query(
            domain="product_experience",
            metric_id="activation_rate",
            comparison_state="comparable",
            limit=20,
            cursor="sbcursor_bound",
        )
    )
    assert listed.status_code == 200
    _, call = service.calls[-1]
    assert call["cursor"] == "sbcursor_bound"
    assert call["domain"] == "product_experience"
    fetched = client.get(
        f"/v1/strategic-benchmark-snapshots/{current}?" + query()
    )
    assert fetched.status_code == 200
    assert "scope_authority_sha256" not in fetched.text
    compared = client.get(
        f"/v1/strategic-benchmark-snapshots/{current}/compare?"
        + query(baseline_snapshot_ref=baseline)
    )
    assert compared.status_code == 200


def test_conflict_and_all_scope_misses_are_non_enumerable(api_client):
    client, _service, active = api_client
    assert post(client, key="conflict-key").status_code == 409
    owned = post(client, key="owned").json()["snapshot"]["snapshot_ref"]
    active["principal"] = principal("tenant-b")
    get_response = client.get(
        f"/v1/strategic-benchmark-snapshots/{owned}?" + query()
    )
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "Strategic benchmark resource not found"


def test_post_role_and_response_extra_fields_are_fail_closed(api_client):
    client, service, active = api_client
    active["principal"] = principal("tenant-a", "reviewer")
    assert post(client).status_code == 403
    active["principal"] = principal()
    service.extra_response = True
    assert post(client, key="extra").status_code == 500


@pytest.mark.parametrize(
    "projection",
    [
        {"mode": "withheld", "value": "1"},
        {"mode": "withheld", "lower": "0", "upper": "1"},
        {"mode": "internal_band", "value": "1", "lower": "0", "upper": "2"},
        {"mode": "internal_band", "lower": "0"},
        {"mode": "public_exact", "lower": "0", "upper": "2"},
        {"mode": "public_exact", "value": "1", "lower": "0"},
    ],
)
def test_value_projection_discriminator_fails_closed(projection):
    adapter = TypeAdapter(benchmark_router.ValueProjectionResponse)
    with pytest.raises(ValidationError):
        adapter.validate_python(projection)


def test_value_projection_discriminator_accepts_only_mode_contracts():
    adapter = TypeAdapter(benchmark_router.ValueProjectionResponse)
    assert adapter.validate_python({"mode": "withheld"}).mode == "withheld"
    assert (
        adapter.validate_python(
            {"mode": "internal_band", "lower": "0", "upper": "2"}
        ).mode
        == "internal_band"
    )
    assert (
        adapter.validate_python(
            {"mode": "public_exact", "value": "1", "lower": "0", "upper": "2"}
        ).mode
        == "public_exact"
    )


def test_main_openapi_has_explicit_whitelists_and_api_key_security():
    from apps.control_plane.api import app

    app.openapi_schema = None
    schema = app.openapi()
    paths = schema["paths"]
    operations = [
        paths["/v1/strategic-benchmark-snapshots"]["post"],
        paths["/v1/strategic-benchmark-snapshots"]["get"],
        paths["/v1/strategic-benchmark-snapshots/{snapshot_ref}"]["get"],
        paths["/v1/strategic-benchmark-snapshots/{snapshot_ref}/compare"]["get"],
    ]
    assert all(operation["security"] == [{"KjdsApiKey": []}] for operation in operations)
    request_schema = operations[0]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    request_ref = request_schema["$ref"].rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][request_ref]["properties"]
    assert set(properties) == {"store_ref", "as_of", "evidence_refs"}
    serialized = str(operations)
    assert "dict[str, Any]" not in serialized
    assert "raw_evidence_ids" not in serialized
    assert "expected_scope_authority_sha256" not in serialized
    assert "scope_authority_sha256" not in schema["components"]["schemas"][
        "SnapshotResponse"
    ]["properties"]
    projection_schemas = {
        name: value
        for name, value in schema["components"]["schemas"].items()
        if name.endswith("ValueProjectionResponse")
    }
    assert set(projection_schemas) == {
        "WithheldValueProjectionResponse",
        "InternalBandValueProjectionResponse",
        "PublicExactValueProjectionResponse",
    }
    assert set(projection_schemas["WithheldValueProjectionResponse"]["properties"]) == {
        "mode"
    }
    assert set(
        projection_schemas["InternalBandValueProjectionResponse"]["properties"]
    ) == {"mode", "lower", "upper"}
    assert set(
        projection_schemas["PublicExactValueProjectionResponse"]["properties"]
    ) == {"mode", "value", "lower", "upper"}


def test_strategic_evidence_content_access_is_exact_scope_and_authority(
    monkeypatch,
):
    authority = {"sha": "a" * 64}

    class ScopeGrants:
        @staticmethod
        def current(*, principal, store_ref, as_of):
            return {
                "status": "ready",
                "tenant_ref": principal.tenant_ref,
                "entity_ref": f"entity-{principal.tenant_ref}",
                "store_ref": store_ref,
                "authority_sha256": authority["sha"],
            }

    monkeypatch.setattr(
        evidence_router,
        "runtime",
        SimpleNamespace(scope_grants=ScopeGrants()),
    )
    record = SimpleNamespace(
        source="strategic-benchmark-observation",
        metadata={
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-tenant-a",
            "store_ref": "store-a",
            "scope_authority_sha256": "a" * 64,
        },
    )
    evidence_router._ensure_channel_evidence_access(record, principal(), content=True)
    with pytest.raises(HTTPException) as cross_tenant:
        evidence_router._ensure_channel_evidence_access(
            record,
            principal("tenant-b"),
            content=True,
        )
    assert cross_tenant.value.status_code == 404
    authority["sha"] = "b" * 64
    with pytest.raises(HTTPException) as rotated:
        evidence_router._ensure_channel_evidence_access(
            record,
            principal(),
            content=True,
        )
    assert rotated.value.status_code == 404
