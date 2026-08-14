from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import apps.control_plane.commander_tool_gateway as gateway_module
from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalContractRow,
    GoalTaskRow,
    GraphProjectRow,
    _sha,
)
from apps.control_plane.commander_tool_gateway import (
    GATEWAY_CONTRACT_VERSION,
    MEDIA_AGENT_REGISTRY_CONTENT_SHA256,
    CommanderToolGateway,
    CommanderToolGatewayError,
)
from apps.control_plane.evidence import EvidenceBlobRow, EvidenceRecordRow, EvidenceService
from apps.control_plane.media_connectors import MediaConnectorContract
from apps.control_plane.media_jobs import (
    FFMPEG_RENDER_PROFILE,
    GovernedMediaJobWorkspace,
    MediaJobBindingProjection,
    MediaJobEventRow,
    MediaJobEvidenceLinkRow,
    MediaJobProjection,
    MediaJobRow,
    MediaJobScope,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

FFMPEG_PROVIDER_DESCRIPTOR = MediaConnectorContract().internal_runtime_provider("ffmpeg")

REGISTRY = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "media_agent_contracts.json"
)
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
PRINCIPAL = Principal(
    actor_id="operator-1",
    roles=frozenset({"operator"}),
    tenant_ref="tenant-1",
    store_refs=frozenset({"store-1"}),
)


class HarnessStub:
    def __init__(self, *, status: str = "ready") -> None:
        self.status = status
        self.workspace_calls = []
        self.compile_calls = []

    def workspace(self, project_ref, **kwargs):
        self.workspace_calls.append((project_ref, kwargs))
        return {"status": self.status, "snapshot_sha256": "1" * 64}

    def compile_campaign_brief(self, **kwargs):
        self.compile_calls.append(kwargs)
        if self.status != "ready":
            raise ValueError(f"campaign_brief_graph_{self.status}")
        campaign = kwargs["campaign"]
        content = {
            "contract_id": "kjds-campaign-brief-v1",
            "contract_version": "1.0.0",
            "project_ref": kwargs["project_id"],
            "graph_snapshot_sha256": "1" * 64,
            **kwargs["current_scope"],
            "scope_binding_sha256": _sha(kwargs["current_scope"]),
            **campaign,
        }
        content_sha256 = _sha(content)
        return {
            **content,
            "brief_ref": "campaign_brief_" + content_sha256[:32],
            "content_sha256": content_sha256,
            "external_write_allowed": False,
        }


class JobsStub:
    def __init__(self) -> None:
        self.submit_calls = []
        self.read_calls = []
        self.state = "QUEUED"
        self.safe_reason_code = None
        self.tool_name = "media.image_generate"
        self.submit_error = None
        self.scope = MediaJobScope(
            tenant_ref="tenant-1",
            entity_ref="entity-1",
            store_ref="store-1",
            authority_sha256="f" * 64,
            subject_actor_id="operator-1",
        )
        self.last_descriptor = None
        self.last_request = None

    def _projection(self):
        return MediaJobProjection(
            job_ref="media_job_1",
            state=self.state,
            tool_name=self.tool_name,
            connector_ref="private-connector",
            created_at=NOW.isoformat(),
            last_event_ordinal=1,
            safe_reason_code=self.safe_reason_code,
        )

    def submit(self, **kwargs):
        self.submit_calls.append(kwargs)
        self.last_request = kwargs["request"]
        self.last_descriptor = kwargs["tool_descriptor"]
        if self.submit_error is not None:
            raise self.submit_error
        return self._projection()

    def current_scope(self, **kwargs):
        return self.scope

    def read_bound(self, **kwargs):
        self.read_calls.append(kwargs)
        descriptor = self.last_descriptor
        if descriptor is None:
            descriptor_content = {
                "contract_id": "kjds-media-tool-descriptor-seal-v1",
                "registry_sha256": MEDIA_AGENT_REGISTRY_CONTENT_SHA256,
                "tool_name": "media.image_generate",
                "tool_version": "1.0.0",
                "capabilities": ["image_generation"],
                "cost_upper_bound": {
                    "amount_minor": 250,
                    "currency": "USD",
                    "basis": "engineering_dispatch_ceiling_not_invoice",
                },
                "output_contract": "image_artifact_evidence",
                "provider": "codex_oauth",
                "connector_ref": "connector-1",
                "connector_binding_sha256": "a" * 64,
            }
            descriptor = {
                **descriptor_content,
                "descriptor_sha256": _sha(descriptor_content),
            }
        request = self.last_request or {"campaign_brief_sha256": "e" * 64}
        return self._projection(), MediaJobBindingProjection(
            job_ref="media_job_1",
            tool_name=self.tool_name,
            tool_version="1.0.0",
            provider="codex_oauth",
            connector_ref="connector-1",
            connector_binding_sha256="a" * 64,
            tool_descriptor_sha256=descriptor["descriptor_sha256"],
            campaign_brief_sha256=request["campaign_brief_sha256"],
            request_sha256="c" * 64,
        )


class ScopeAuthority:
    def __init__(self) -> None:
        self.authority_sha256 = "f" * 64

    def current(self, *, principal, store_ref, as_of):
        return {
            "status": "ready" if self.authority_sha256 else "revoked",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": "entity-1",
            "store_ref": store_ref,
            "authority_sha256": self.authority_sha256,
        }


def gateway(*, harness=None, jobs=None, registry=REGISTRY):
    harness = harness or HarnessStub()
    jobs = jobs or JobsStub()
    return (
        CommanderToolGateway(
            harness=harness,
            jobs=jobs,
            registry_path=registry,
        ),
        harness,
        jobs,
    )


def campaign():
    return {
        "objective": "Create a product image proposal.",
        "audiences": ["buyer-a"],
        "channel": "listing-draft",
        "constraints": ["proposal only"],
        "content_asset_refs": ["content_asset_1"],
    }


def arguments(**changes):
    value = {
        "project_ref": "project-1",
        "campaign": campaign(),
        "provider": "codex_oauth",
        "connector_ref": "connector-1",
        "connector_binding_sha256": "a" * 64,
        "idempotency_key": "command-1",
        "output_contract": "image_artifact_evidence",
        "prompt": "draw a rights-approved product",
        "size": "1024x1024",
        "count": 1,
        "reference_asset_refs": ["content_asset_1"],
    }
    value.update(changes)
    return value


def video_arguments(**changes):
    value = {
        "project_ref": "project-1",
        "campaign": campaign(),
        "provider": "ffmpeg",
        "connector_ref": FFMPEG_PROVIDER_DESCRIPTOR.connector_ref,
        "connector_binding_sha256": FFMPEG_PROVIDER_DESCRIPTOR.binding_sha256,
        "idempotency_key": "command-video-1",
        "output_contract": "video_artifact_evidence",
        "editing_blueprint_ref": "editing_blueprint_1",
        "source_asset_refs": ["content_asset_1"],
        "audio_asset_refs": ["content_asset_audio_1"],
        "render_profile": FFMPEG_RENDER_PROFILE,
    }
    value.update(changes)
    return value


def test_inventory_exposes_only_five_safe_tool_projections():
    service, harness, _ = gateway()

    result = service.inventory(
        project_ref="project-1",
        principal=PRINCIPAL,
        store_ref="store-1",
        as_of=NOW,
    )

    assert result["registry_sha256"] == MEDIA_AGENT_REGISTRY_CONTENT_SHA256
    assert result["live_provider_admission"] == "not_admitted"
    assert result["external_write_allowed"] is False
    assert len(result["tools"]) == 5

    blueprint = next(
        item for item in result["tools"] if item["name"] == "media.video_blueprint"
    )
    assert blueprint["cost_upper_bound"] == {
        "amount_minor": 0,
        "currency": "USD",
        "basis": "internal_deterministic_compiler_no_provider_charge",
    }
    assert {item["state"] for item in result["tools"]} == {"job_intake_only"}
    assert set(result["tools"][0]) == {
        "name",
        "version",
        "capabilities",
        "state",
        "cost_upper_bound",
        "result_kind",
    }
    serialized = repr(result).lower()
    for forbidden in (
        "accepted_providers",
        "connector_ref",
        "prompt",
        "credential",
        "description",
    ):
        assert forbidden not in serialized
    assert len(harness.workspace_calls) == 1


def test_dispatch_compiles_brief_and_submits_one_exact_job_with_safe_result():
    service, harness, jobs = gateway()

    result = service.dispatch(
        principal=PRINCIPAL,
        store_ref="store-1",
        as_of=NOW,
        tool_name="media.image_generate",
        tool_version="1.0.0",
        arguments=arguments(),
    )

    assert len(harness.compile_calls) == 1
    assert len(jobs.submit_calls) == 1
    request = jobs.submit_calls[0]["request"]
    assert request["brief_ref"].startswith("campaign_brief_")
    assert request["idempotency_sha256"] != "command-1"
    assert request["contract_id"] == "kjds-commander-media-job-request-v1"
    assert request["tool_input_ref_count"] == 1
    assert set(request) == {
        "contract_id",
        "tool_name",
        "tool_version",
        "project_ref",
        "brief_ref",
        "campaign_brief_sha256",
        "provider",
        "connector_ref",
        "connector_binding_sha256",
        "idempotency_sha256",
        "output_contract",
        "tool_descriptor_sha256",
        "tool_inputs_sha256",
        "tool_input_ref_count",
        "safe_reason_codes",
    }
    assert "campaign_brief" not in request
    assert "tool_inputs" not in request
    assert jobs.submit_calls[0]["campaign_brief"]["entity_ref"] == "entity-1"
    assert jobs.submit_calls[0]["tool_descriptor"]["tool_version"] == "1.0.0"
    assert set(result) == {"contract_version", "job_ref", "status"}
    assert result["contract_version"] == GATEWAY_CONTRACT_VERSION
    assert result["status"] == "QUEUED"
    serialized = repr(result).lower()
    for forbidden in ("provider", "connector", "prompt", "campaign"):
        assert forbidden not in serialized


def test_unknown_outcome_read_never_dispatches_or_retries():
    jobs = JobsStub()
    jobs.state = "UNKNOWN_OUTCOME"
    jobs.safe_reason_code = "provider_outcome_unknown"
    service, _, _ = gateway(jobs=jobs)

    result = service.read(
        principal=PRINCIPAL,
        store_ref="store-1",
        job_ref="media_job_1",
    )

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] == "provider_outcome_unknown"
    assert jobs.submit_calls == []
    assert len(jobs.read_calls) == 1


@pytest.mark.parametrize(
    ("tool_name", "tool_version", "changes", "reason"),
    [
        ("media.unknown", "1.0.0", {}, "tool_not_registered"),
        ("media.image_generate", "2.0.0", {}, "tool_version_not_registered"),
        ("media.image_generate", "1.0.0", {"provider": "ffmpeg"}, "provider_not_registered"),
        ("media.image_generate", "1.0.0", {"output_contract": "raw_blob"}, "output_contract"),
        ("media.image_generate", "1.0.0", {"unexpected": True}, "arguments_shape"),
        (
            "media.image_generate",
            "1.0.0",
            {"campaign": {**campaign(), "metadata": {"client_secret": "leak"}}},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"prompt": "Authorization: Bearer never-persist-this"},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"prompt": "sk-proj-abcdefghijklmnopqrstuvwx"},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"prompt": "data:image/png;base64,AAAA"},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"prompt": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789+/" * 3},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"campaign": {**campaign(), "provider_raw": {"response": "private"}}},
            "sensitive_input",
        ),
        (
            "media.image_generate",
            "1.0.0",
            {"prompt": "x" * 262_144},
            "arguments_budget_exceeded",
        ),
    ],
)
def test_dispatch_contract_drift_fails_before_brief_or_job(
    tool_name, tool_version, changes, reason
):
    service, harness, jobs = gateway()

    with pytest.raises(CommanderToolGatewayError, match=reason):
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name=tool_name,
            tool_version=tool_version,
            arguments=arguments(**changes),
        )

    assert harness.compile_calls == []
    assert jobs.submit_calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"render_profile": {"oauth_token": "opaque-credential-value"}},
        {"render_profile": {"provider_response": "private-body"}},
        {"render_profile": {"raw_fields": {"result": "private-body"}}},
        {
            "source_asset_refs": [
                "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789+/" * 3
            ]
        },
    ],
)
def test_video_render_rejects_nested_private_or_encoded_values_before_submit(changes):
    service, harness, jobs = gateway()

    with pytest.raises(
        CommanderToolGatewayError,
        match="gateway_sensitive_input_forbidden",
    ) as exc:
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.video_render",
            tool_version="1.0.0",
            arguments=video_arguments(**changes),
        )

    assert "opaque-credential-value" not in str(exc.value)
    assert "private-body" not in str(exc.value)
    assert harness.compile_calls == []
    assert jobs.submit_calls == []


def test_video_render_remotion_is_rejected_before_brief_or_job():
    service, harness, jobs = gateway()

    with pytest.raises(CommanderToolGatewayError, match="provider_not_registered"):
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.video_render",
            tool_version="1.0.0",
            arguments=video_arguments(provider="remotion"),
        )

    assert harness.compile_calls == []
    assert jobs.submit_calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"connector_ref": "mcn_00000000000000000000000000000000"},
        {"connector_binding_sha256": "0" * 64},
    ],
)
def test_video_render_runtime_connector_drift_is_rejected_before_job(changes):
    service, _, jobs = gateway()

    with pytest.raises(
        CommanderToolGatewayError,
        match="video_render_runtime_binding_not_admitted",
    ):
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.video_render",
            tool_version="1.0.0",
            arguments=video_arguments(**changes),
        )

    assert jobs.submit_calls == []


def test_sensitive_value_is_never_reflected_in_gateway_error():
    service, _, jobs = gateway()
    secret = "sk-proj-abcdefghijklmnopqrstuvwx"

    with pytest.raises(CommanderToolGatewayError) as exc:
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.image_generate",
            tool_version="1.0.0",
            arguments=arguments(prompt=secret),
        )

    assert str(exc.value) == "gateway_sensitive_input_forbidden"
    assert secret not in str(exc.value)
    assert jobs.submit_calls == []


def test_registry_byte_drift_fails_before_harness_or_job(monkeypatch):
    original_read_bytes = Path.read_bytes

    def drifted_read_bytes(path):
        raw = original_read_bytes(path)
        return (
            raw.replace(b'"job_intake_only"', b'"review_required"', 1)
            if path == REGISTRY
            else raw
        )

    monkeypatch.setattr(Path, "read_bytes", drifted_read_bytes)
    service, harness, jobs = gateway()

    with pytest.raises(CommanderToolGatewayError, match="registry_hash_drift"):
        service.inventory(
            project_ref="project-1",
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
        )

    assert harness.workspace_calls == []
    assert jobs.submit_calls == []


def test_job_tool_binding_drift_is_not_projected():
    jobs = JobsStub()
    jobs.tool_name = "media.video_render"
    service, _, _ = gateway(jobs=jobs)

    with pytest.raises(CommanderToolGatewayError, match="job_tool_binding_invalid"):
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.image_generate",
            tool_version="1.0.0",
            arguments=arguments(),
        )

    assert len(jobs.submit_calls) == 1


def test_submit_failure_never_triggers_provider_failover():
    jobs = JobsStub()
    jobs.submit_error = RuntimeError("provider_private_failure_body")
    service, _, _ = gateway(jobs=jobs)

    with pytest.raises(CommanderToolGatewayError, match="media_job_submit_failed") as exc:
        service.dispatch(
            principal=PRINCIPAL,
            store_ref="store-1",
            as_of=NOW,
            tool_name="media.image_generate",
            tool_version="1.0.0",
            arguments=arguments(),
        )

    assert len(jobs.submit_calls) == 1
    assert "provider_private_failure_body" not in str(exc.value)


def test_persisted_unknown_outcome_restarts_as_exact_replay_without_retry():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    authority = ScopeAuthority()
    first_workspace = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=authority,
        clock=lambda: NOW,
    )
    provider_attempts = []

    class PersistThenThrowJobs:
        def __init__(self, workspace, *, persist_then_throw):
            self.workspace = workspace
            self.persist_then_throw = persist_then_throw

        def current_scope(self, **kwargs):
            return self.workspace.current_scope(**kwargs)

        def read_bound(self, **kwargs):
            return self.workspace.read_bound(**kwargs)

        def submit(self, **kwargs):
            projection = self.workspace.submit(**kwargs)
            projection, claimed = self.workspace.claim_provider_attempt(
                principal=kwargs["principal"],
                store_ref=kwargs["store_ref"],
                job_ref=projection.job_ref,
            )
            if not claimed:
                return projection
            provider_attempts.append(projection.job_ref)
            if not self.persist_then_throw:
                return projection
            job_scope = self.workspace.current_scope(
                principal=kwargs["principal"], store_ref=kwargs["store_ref"]
            )
            with Session(engine, expire_on_commit=False) as session, session.begin():
                row = session.get(MediaJobRow, projection.job_ref)
                assert row is not None
                self.workspace._append_event(
                    session=session,
                    job=row,
                    scope=job_scope,
                    state="UNKNOWN_OUTCOME",
                    reason="provider_outcome_unknown",
                    now=NOW,
                    command_idempotency_sha256=row.idempotency_sha256,
                    command_request_sha256=row.request_sha256,
                )
            raise RuntimeError("provider_response_lost_after_persist")

    first_jobs = PersistThenThrowJobs(first_workspace, persist_then_throw=True)
    first_gateway, _, _ = gateway(jobs=first_jobs)
    dispatch_kwargs = {
        "principal": PRINCIPAL,
        "store_ref": "store-1",
        "as_of": NOW,
        "tool_name": "media.image_generate",
        "tool_version": "1.0.0",
        "arguments": arguments(),
    }

    with pytest.raises(CommanderToolGatewayError, match="media_job_submit_failed"):
        first_gateway.dispatch(**dispatch_kwargs)
    with Session(engine) as session:
        baseline = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                MediaJobRow,
                MediaJobEventRow,
                MediaJobEvidenceLinkRow,
                EvidenceRecordRow,
                EvidenceBlobRow,
            )
        )

    restarted_workspace = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=authority,
        clock=lambda: NOW,
    )
    restarted_jobs = PersistThenThrowJobs(
        restarted_workspace,
        persist_then_throw=False,
    )
    restarted_gateway, _, _ = gateway(jobs=restarted_jobs)
    replay = restarted_gateway.dispatch(**dispatch_kwargs)
    assert replay["status"] == "UNKNOWN_OUTCOME"
    assert provider_attempts == [replay["job_ref"]]

    with pytest.raises(CommanderToolGatewayError, match="media_job_submit_failed"):
        restarted_gateway.dispatch(
            **{**dispatch_kwargs, "arguments": arguments(prompt="drifted")}
        )
    authority.authority_sha256 = "d" * 64
    with pytest.raises(CommanderToolGatewayError, match="media_job_submit_failed"):
        restarted_gateway.dispatch(**dispatch_kwargs)
    assert provider_attempts == [replay["job_ref"]]
    with Session(engine) as session:
        assert baseline == tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                MediaJobRow,
                MediaJobEventRow,
                MediaJobEvidenceLinkRow,
                EvidenceRecordRow,
                EvidenceBlobRow,
            )
        )


def test_gateway_integrates_with_harness_and_exact_scope_media_job(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            GraphProjectRow(
                id="project-1",
                tenant_ref="tenant-1",
                entity_ref="entity-1",
                store_ref="store-1",
                title="Campaign project",
                lifecycle="active",
                baseline_sha256="a" * 64,
                goal_contract_sha256="b" * 64,
                created_at=NOW,
            )
        )
        session.add(
            GoalContractRow(
                id="goal-1",
                project_id="project-1",
                objective="Compile governed media proposal.",
                constraints_json=["no external write"],
                content_sha256="b" * 64,
                created_at=NOW,
            )
        )
        session.add(
            GoalTaskRow(
                id="task-1",
                project_id="project-1",
                title="Campaign inputs verified",
                owner="engineering",
                verifier_id="pytest",
                verifier_version="1",
                dependency_ids_json=[],
                verification_condition="focused tests pass",
                next_safe_action="inspect failure",
                workspace="/campaign",
                sla_seconds=3600,
                fingerprint=_sha(["campaign", "task-1"]),
                created_at=NOW,
            )
        )
    harness = AgentHarnessService(engine)
    harness.register_verifier(
        {
            "id": "pytest",
            "version": "1",
            "source_type": "process_log",
            "authority": "external_verifier",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    harness.record_observation(
        {
            "project_id": "project-1",
            "task_id": "task-1",
            "verifier_id": "pytest",
            "verifier_version": "1",
            "source": "pytest process log",
            "scope": {"tenant_ref": "tenant-1", "store_ref": "store-1"},
            "state": "passed",
            "summary": "focused pass",
            "input_sha256": "c" * 64,
            "artifact_ref": "test.log",
            "observed_at": NOW.isoformat(),
            "store_ref": "store-1",
        },
        principal=Principal(
            actor_id="monitor-1",
            roles=frozenset({"monitor"}),
            tenant_ref="tenant-1",
            store_refs=frozenset({"store-1"}),
        ),
    )
    jobs = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=ScopeAuthority(),
        clock=lambda: NOW,
    )
    service = CommanderToolGateway(
        harness=harness,
        jobs=jobs,
        registry_path=REGISTRY,
    )
    kwargs = {
        "principal": PRINCIPAL,
        "store_ref": "store-1",
        "as_of": NOW,
        "tool_name": "media.image_generate",
        "tool_version": "1.0.0",
        "arguments": arguments(),
    }

    first = service.dispatch(**kwargs)
    replay = service.dispatch(**kwargs)

    assert replay == first
    assert first["status"] == "QUEUED"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaJobRow)) == 1

    cross_scope = Principal(
        actor_id="operator-2",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-2",
        store_refs=frozenset({"store-1"}),
    )
    with pytest.raises(CommanderToolGatewayError, match="campaign_brief_not_admitted"):
        service.dispatch(**{**kwargs, "principal": cross_scope})
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaJobRow)) == 1

    changed_registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    image_tool = changed_registry["tool_gateway"]["tools"][0]
    assert image_tool["name"] == "media.image_generate"
    image_tool["version"] = "1.1.0"
    image_tool["required_capabilities"] = ["image_generation", "registry_v2"]
    image_tool["cost_upper_bound"]["amount_minor"] += 1
    changed_path = tmp_path / "media_agent_contracts_v2.json"
    changed_path.write_text(
        json.dumps(changed_registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gateway_module,
        "MEDIA_AGENT_REGISTRY_CONTENT_SHA256",
        _sha(changed_registry),
    )
    service.registry_path = changed_path
    with pytest.raises(CommanderToolGatewayError, match="tool_version_not_registered"):
        service.read(
            principal=PRINCIPAL,
            store_ref="store-1",
            job_ref=first["job_ref"],
        )
