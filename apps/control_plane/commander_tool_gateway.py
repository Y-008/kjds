from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent_harness import AgentHarnessService
from .media_connectors import (
    INTERNAL_BLUEPRINT_PROVIDER,
    RUNTIME_FFMPEG_PROVIDER,
    MediaConnectorContract,
)
from .media_jobs import (
    EDITING_TARGET_CHANNELS,
    FFMPEG_RENDER_PROFILE,
    FFMPEG_RENDER_PROFILE_SHA256,
    MEDIA_JOB_SAFE_REASON_BY_STATE,
    MEDIA_JOB_STATES,
    GovernedMediaJobWorkspace,
    MediaJobProjection,
)
from .security import Principal

MEDIA_AGENT_REGISTRY_CONTENT_SHA256 = (
    "a14e57cc61ba2840aa94a1747cff6da82b2b9b6421c0c5a2bb4bf12bbdffe075"
)
GATEWAY_CONTRACT_ID = "kjds-commander-tool-gateway-v1"
GATEWAY_CONTRACT_VERSION = "1.0.0"
TOOL_NAMES = (
    "media.image_generate",
    "media.image_edit",
    "media.video_blueprint",
    "media.video_render",
    "tutorial.build",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_OPAQUE_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,299}$")
_REGISTRY_FORBIDDEN_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "oauthtoken",
        "clientsecret",
        "password",
        "cookie",
        "cookies",
        "localstorage",
        "browserprofile",
        "browserprofilearchive",
        "codexhomecontents",
    }
)
_SENSITIVE_FRAGMENTS = frozenset(
    {
        "authorization",
        "accesstoken",
        "apikey",
        "bearertoken",
        "browserprofile",
        "clientsecret",
        "cookie",
        "credential",
        "localstorage",
        "oauthtoken",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "sessiontoken",
    }
)
_SENSITIVE_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "api_key=",
    "api-key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "set-cookie:",
    "-----begin private key-----",
)
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"\bsk-(?:proj-|svcacct-)?[a-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|github_pat|xox[baprs])[_-][a-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_PRIVATE_BODY_KEYS = frozenset(
    {
        "blobbody",
        "providerraw",
        "providerresponse",
        "rawfields",
        "rawpayload",
        "responsebody",
        "responsepayload",
    }
)


class CommanderToolGatewayError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CommanderToolGatewayError("gateway_payload_not_canonical") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise CommanderToolGatewayError(f"{name}_invalid")
    return value.strip()


def _hex64(value: Any, name: str) -> str:
    value = _text(value, name, maximum=64).lower()
    if not _HEX64.fullmatch(value):
        raise CommanderToolGatewayError(f"{name}_invalid")
    return value


def _safe_tree(value: Any, *, depth: int = 0, field: str | None = None) -> None:
    if depth > 12:
        raise CommanderToolGatewayError("gateway_payload_depth_exceeded")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CommanderToolGatewayError("gateway_payload_key_invalid")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS) or any(
                fragment in normalized for fragment in _PRIVATE_BODY_KEYS
            ):
                raise CommanderToolGatewayError("gateway_sensitive_input_forbidden")
            _safe_tree(item, depth=depth + 1, field=normalized)
    elif isinstance(value, list):
        if len(value) > 200:
            raise CommanderToolGatewayError("gateway_payload_collection_too_large")
        for item in value:
            _safe_tree(item, depth=depth + 1, field=field)
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if (
            any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS)
            or any(pattern.search(value) for pattern in _CREDENTIAL_VALUE_PATTERNS)
            or lowered.startswith("data:")
            or "\x00" in value
        ):
            raise CommanderToolGatewayError("gateway_sensitive_input_forbidden")
        if lowered.startswith(("{", "[")):
            try:
                embedded = json.loads(value)
            except json.JSONDecodeError:
                embedded = None
            if isinstance(embedded, (dict, list)):
                raise CommanderToolGatewayError("gateway_embedded_raw_payload_forbidden")
        compact = value.strip()
        is_reference = bool(
            field and (field.endswith("ref") or field.endswith("refs"))
        )
        if is_reference and not _OPAQUE_REF.fullmatch(compact):
            raise CommanderToolGatewayError("gateway_sensitive_input_forbidden")
        safe_digest_or_idempotency = bool(
            field and (field.endswith("sha256") or field == "idempotencykey")
        )
        if (
            not safe_digest_or_idempotency
            and len(compact) >= 64
            and len(set(compact)) >= 8
            and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact)
        ):
            raise CommanderToolGatewayError("gateway_sensitive_input_forbidden")
    elif value is None or isinstance(value, (bool, int)) or (
        isinstance(value, float) and math.isfinite(value)
    ):
        return
    else:
        raise CommanderToolGatewayError("gateway_payload_type_invalid")


@dataclass(frozen=True, slots=True)
class CommanderToolProjection:
    name: str
    version: str
    capabilities: tuple[str, ...]
    state: str
    cost_upper_bound: Mapping[str, Any]
    result_kind: str


@dataclass(frozen=True, slots=True)
class CommanderDispatchProjection:
    contract_version: str
    tool_name: str
    tool_version: str
    capabilities: tuple[str, ...]
    state: str
    cost_upper_bound: Mapping[str, Any]
    job_ref: str
    content_asset_ref: str | None
    safe_reason_code: str | None


class CommanderToolGateway:
    """Internal model seam over the existing harness and durable media Job."""

    def __init__(
        self,
        *,
        harness: AgentHarnessService,
        jobs: GovernedMediaJobWorkspace,
        registry_path: str | Path,
        media_connector_contract: MediaConnectorContract | None = None,
    ) -> None:
        self.harness = harness
        self.jobs = jobs
        self.registry_path = Path(registry_path)
        self.media_connector_contract = (
            media_connector_contract
            or MediaConnectorContract(path=self.registry_path)
        )
        if type(self.media_connector_contract) is not MediaConnectorContract:
            raise CommanderToolGatewayError(
                "media_connector_contract_invalid"
            )
        self.blueprint_provider = (
            self.media_connector_contract.internal_runtime_provider(
                INTERNAL_BLUEPRINT_PROVIDER
            )
        )
        self.ffmpeg_provider = self.media_connector_contract.internal_runtime_provider(
            RUNTIME_FFMPEG_PROVIDER
        )

    def _registry(self) -> dict[str, Any]:
        try:
            raw = self.registry_path.read_bytes()
            root = json.loads(raw)
        except CommanderToolGatewayError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise CommanderToolGatewayError("media_agent_registry_unavailable") from exc
        if not isinstance(root, dict):
            raise CommanderToolGatewayError("media_agent_registry_shape_invalid")
        if _sha(root) != MEDIA_AGENT_REGISTRY_CONTENT_SHA256:
            raise CommanderToolGatewayError("media_agent_registry_hash_drift")
        gateway = root.get("tool_gateway")
        sensitive_policy = root.get("sensitive_field_policy")
        if not isinstance(sensitive_policy, dict):
            raise CommanderToolGatewayError("sensitive_field_policy_invalid")
        forbidden_keys = sensitive_policy.get("forbidden_payload_keys")
        if not isinstance(forbidden_keys, list) or {
            re.sub(r"[^a-z0-9]", "", value.lower())
            for value in forbidden_keys
            if isinstance(value, str)
        } != _REGISTRY_FORBIDDEN_SENSITIVE_KEYS:
            raise CommanderToolGatewayError("sensitive_field_policy_drift")
        expected_gateway = {
            "contract_id",
            "contract_version",
            "commander_owner",
            "campaign_brief_contract",
            "common_allowed_inputs",
            "model_projection_fields",
            "immediate_result_required_fields",
            "immediate_result_additional_fields_allowed",
            "immediate_result_status",
            "tools",
        }
        if not isinstance(gateway, dict) or set(gateway) != expected_gateway:
            raise CommanderToolGatewayError("tool_gateway_contract_shape_invalid")
        if (
            gateway["contract_id"] != GATEWAY_CONTRACT_ID
            or gateway["contract_version"] != GATEWAY_CONTRACT_VERSION
            or gateway["commander_owner"] != "AgentHarness"
            or gateway["campaign_brief_contract"]
            != {
                "contract_id": AgentHarnessService.CAMPAIGN_BRIEF_CONTRACT_ID,
                "contract_version": AgentHarnessService.CAMPAIGN_BRIEF_CONTRACT_VERSION,
            }
            or gateway["immediate_result_status"] != "QUEUED"
            or gateway["immediate_result_additional_fields_allowed"] is not False
        ):
            raise CommanderToolGatewayError("tool_gateway_contract_drift")
        expected_projection = [
            "contract_version",
            "tool_name",
            "tool_version",
            "capabilities",
            "state",
            "cost_upper_bound",
            "job_ref",
            "content_asset_ref",
            "safe_reason_code",
        ]
        expected_common = [
            "project_ref",
            "campaign",
            "provider",
            "connector_ref",
            "connector_binding_sha256",
            "idempotency_key",
            "output_contract",
        ]
        if gateway["common_allowed_inputs"] != expected_common:
            raise CommanderToolGatewayError("tool_gateway_input_contract_drift")
        if (
            gateway["model_projection_fields"] != expected_projection
            or gateway["immediate_result_required_fields"]
            != ["contract_version", "job_ref", "status"]
        ):
            raise CommanderToolGatewayError("tool_gateway_projection_drift")
        tools = gateway["tools"]
        if not isinstance(tools, list) or [item.get("name") for item in tools if isinstance(item, dict)] != list(TOOL_NAMES):
            raise CommanderToolGatewayError("tool_gateway_inventory_drift")
        expected_tool = {
            "name",
            "version",
            "owner_task",
            "purpose",
            "required_capabilities",
            "additional_allowed_inputs",
            "accepted_providers",
            "result_kind",
            "external_side_effect",
            "state",
            "cost_upper_bound",
        }
        for item in tools:
            if not isinstance(item, dict) or set(item) != expected_tool:
                raise CommanderToolGatewayError("tool_gateway_tool_shape_invalid")
            if not _SEMVER.fullmatch(str(item["version"])):
                raise CommanderToolGatewayError("tool_gateway_version_invalid")
            if item["state"] != "job_intake_only":
                raise CommanderToolGatewayError("tool_gateway_state_invalid")
            cost = item["cost_upper_bound"]
            runtime_owned = {
                "media.video_blueprint": self.blueprint_provider,
                "media.video_render": self.ffmpeg_provider,
            }.get(item["name"])
            runtime_owned_admitted = (
                runtime_owned is not None
                and item["accepted_providers"] == [runtime_owned.provider]
            )
            expected_basis = (
                runtime_owned.cost_basis
                if runtime_owned_admitted
                else "engineering_dispatch_ceiling_not_invoice"
            )
            if (
                not isinstance(cost, dict)
                or set(cost) != {"amount_minor", "currency", "basis"}
                or not isinstance(cost["amount_minor"], int)
                or isinstance(cost["amount_minor"], bool)
                or not 0 <= cost["amount_minor"] <= 1_000_000
                or cost["currency"] != "USD"
                or cost["basis"] != expected_basis
                or (
                    runtime_owned_admitted
                    and cost["amount_minor"] != runtime_owned.cost_amount_minor
                )
            ):
                raise CommanderToolGatewayError("tool_gateway_cost_contract_invalid")
            for field in ("required_capabilities", "additional_allowed_inputs", "accepted_providers"):
                values = item[field]
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise CommanderToolGatewayError("tool_gateway_tool_contract_invalid")
        return gateway

    @staticmethod
    def _tool(gateway: Mapping[str, Any], name: str, version: str | None = None) -> dict[str, Any]:
        for item in gateway["tools"]:
            if item["name"] == name:
                if version is not None and item["version"] != version:
                    raise CommanderToolGatewayError("tool_version_not_registered")
                return item
        raise CommanderToolGatewayError("tool_not_registered")

    @staticmethod
    def _descriptor(
        *,
        tool: Mapping[str, Any],
        provider: str,
        connector_ref: str,
        connector_binding_sha256: str,
    ) -> dict[str, Any]:
        content = {
            "contract_id": "kjds-media-tool-descriptor-seal-v1",
            "registry_sha256": MEDIA_AGENT_REGISTRY_CONTENT_SHA256,
            "tool_name": tool["name"],
            "tool_version": tool["version"],
            "capabilities": list(tool["required_capabilities"]),
            "cost_upper_bound": dict(tool["cost_upper_bound"]),
            "output_contract": tool["result_kind"],
            "provider": provider,
            "connector_ref": connector_ref,
            "connector_binding_sha256": connector_binding_sha256,
        }
        return {**content, "descriptor_sha256": _sha(content)}

    @staticmethod
    def _projection(
        tool: Mapping[str, Any],
        job: MediaJobProjection,
        *,
        descriptor_sha256: str,
        historical_descriptor_sha256: str | None = None,
    ) -> CommanderDispatchProjection:
        if job.tool_name != tool["name"]:
            raise CommanderToolGatewayError("media_job_tool_binding_invalid")
        if (
            historical_descriptor_sha256 is not None
            and historical_descriptor_sha256 != descriptor_sha256
        ):
            raise CommanderToolGatewayError("media_job_tool_descriptor_drifted")
        if (
            job.state not in MEDIA_JOB_STATES
            or job.safe_reason_code != MEDIA_JOB_SAFE_REASON_BY_STATE[job.state]
        ):
            raise CommanderToolGatewayError("media_job_state_projection_invalid")
        return CommanderDispatchProjection(
            contract_version=GATEWAY_CONTRACT_VERSION,
            tool_name=tool["name"],
            tool_version=tool["version"],
            capabilities=tuple(tool["required_capabilities"]),
            state=job.state,
            cost_upper_bound=dict(tool["cost_upper_bound"]),
            job_ref=_text(job.job_ref, "job_ref"),
            content_asset_ref=None,
            safe_reason_code=job.safe_reason_code,
        )

    def inventory(
        self,
        *,
        project_ref: str,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        gateway = self._registry()
        if as_of.tzinfo is None:
            raise CommanderToolGatewayError("gateway_as_of_timezone_required")
        snapshot = self.harness.workspace(
            _text(project_ref, "project_ref"),
            principal=principal,
            store_ref=_text(store_ref, "store_ref"),
            as_of=as_of,
        )
        tools = [
            CommanderToolProjection(
                name=item["name"],
                version=item["version"],
                capabilities=tuple(item["required_capabilities"]),
                state=item["state"],
                cost_upper_bound=dict(item["cost_upper_bound"]),
                result_kind=item["result_kind"],
            )
            for item in gateway["tools"]
        ]
        return {
            "contract_id": GATEWAY_CONTRACT_ID,
            "contract_version": GATEWAY_CONTRACT_VERSION,
            "registry_sha256": MEDIA_AGENT_REGISTRY_CONTENT_SHA256,
            "graph_status": snapshot["status"],
            "tools": [asdict(tool) for tool in tools],
            "live_provider_admission": "not_admitted",
            "external_write_allowed": False,
        }

    def dispatch(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        tool_name: str,
        tool_version: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        gateway = self._registry()
        tool = self._tool(gateway, _text(tool_name, "tool_name"), _text(tool_version, "tool_version"))
        if not isinstance(arguments, Mapping):
            raise CommanderToolGatewayError("tool_arguments_invalid")
        _safe_tree(arguments)
        if len(_canonical(arguments)) > 262_144:
            raise CommanderToolGatewayError("tool_arguments_budget_exceeded")
        common = set(gateway["common_allowed_inputs"])
        allowed = common | set(tool["additional_allowed_inputs"])
        required = {
            "project_ref",
            "campaign",
            "provider",
            "connector_ref",
            "connector_binding_sha256",
            "idempotency_key",
            "output_contract",
        }
        if not required <= set(arguments) or not set(arguments) <= allowed:
            raise CommanderToolGatewayError("tool_arguments_shape_invalid")
        provider = _text(arguments["provider"], "provider")
        if provider not in tool["accepted_providers"]:
            raise CommanderToolGatewayError("provider_not_registered_for_tool")
        if tool["name"] == "media.video_render" and provider != self.ffmpeg_provider.provider:
            raise CommanderToolGatewayError("video_render_provider_not_admitted")
        if (
            tool["name"] == "media.video_blueprint"
            and provider != self.blueprint_provider.provider
        ):
            raise CommanderToolGatewayError("video_blueprint_provider_not_admitted")
        if arguments["output_contract"] != tool["result_kind"]:
            raise CommanderToolGatewayError("tool_output_contract_invalid")
        if as_of.tzinfo is None:
            raise CommanderToolGatewayError("gateway_as_of_timezone_required")
        try:
            current_scope = self.jobs.current_scope(
                principal=principal,
                store_ref=_text(store_ref, "store_ref"),
            )
            brief = self.harness.compile_campaign_brief(
                project_id=_text(arguments["project_ref"], "project_ref"),
                principal=principal,
                store_ref=_text(store_ref, "store_ref"),
                as_of=as_of.astimezone(UTC),
                campaign=arguments["campaign"],
                current_scope={
                    "tenant_ref": current_scope.tenant_ref,
                    "entity_ref": current_scope.entity_ref,
                    "store_ref": current_scope.store_ref,
                    "authority_sha256": current_scope.authority_sha256,
                    "subject_actor_id": current_scope.subject_actor_id,
                },
            )
        except Exception:
            raise CommanderToolGatewayError("campaign_brief_not_admitted") from None
        idempotency_key = _text(arguments["idempotency_key"], "idempotency_key", maximum=500)
        tool_inputs = {
            key: arguments[key]
            for key in tool["additional_allowed_inputs"]
            if key in arguments
        }
        if (
            tool["name"] == "media.video_blueprint"
            and tool_inputs.get("target_channels")
            != list(EDITING_TARGET_CHANNELS)
        ):
            raise CommanderToolGatewayError(
                "video_blueprint_target_channel_not_admitted"
            )
        if tool["name"] == "media.video_blueprint" and (
            not isinstance(tool_inputs.get("audio_asset_refs"), list)
            or len(tool_inputs["audio_asset_refs"]) != 1
        ):
            raise CommanderToolGatewayError(
                "video_blueprint_audio_input_not_admitted"
            )
        if (
            tool["name"] == "media.video_render"
            and tool_inputs.get("render_profile") != FFMPEG_RENDER_PROFILE
        ):
            raise CommanderToolGatewayError("video_render_profile_not_admitted")
        connector_ref = _text(arguments["connector_ref"], "connector_ref")
        connector_binding_sha256 = _hex64(
            arguments["connector_binding_sha256"],
            "connector_binding_sha256",
        )
        if tool["name"] == "media.video_blueprint" and (
            connector_ref != self.blueprint_provider.connector_ref
            or connector_binding_sha256
            != self.blueprint_provider.binding_sha256
            or not isinstance(tool_inputs.get("analysis_evidence_ref"), str)
        ):
            raise CommanderToolGatewayError(
                "video_blueprint_internal_binding_not_admitted"
            )
        if tool["name"] == "media.video_render" and (
            connector_ref != self.ffmpeg_provider.connector_ref
            or connector_binding_sha256 != self.ffmpeg_provider.binding_sha256
        ):
            raise CommanderToolGatewayError(
                "video_render_runtime_binding_not_admitted"
            )
        descriptor = self._descriptor(
            tool=tool,
            provider=provider,
            connector_ref=connector_ref,
            connector_binding_sha256=connector_binding_sha256,
        )
        input_ref_count = sum(
            len(value) if isinstance(value, list) else 1
            for key, value in tool_inputs.items()
            if key.endswith("_ref") or key.endswith("_refs")
        )
        request = {
            "contract_id": "kjds-commander-media-job-request-v1",
            "tool_name": tool["name"],
            "tool_version": tool["version"],
            "project_ref": brief["project_ref"],
            "brief_ref": brief["brief_ref"],
            "campaign_brief_sha256": brief["content_sha256"],
            "provider": provider,
            "connector_ref": connector_ref,
            "connector_binding_sha256": connector_binding_sha256,
            "idempotency_sha256": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
            "output_contract": tool["result_kind"],
            "tool_descriptor_sha256": descriptor["descriptor_sha256"],
            "tool_inputs_sha256": _sha(tool_inputs),
            "tool_input_ref_count": input_ref_count,
            "safe_reason_codes": [],
        }
        worker_input = None
        if tool["name"] in {"media.video_blueprint", "media.video_render"}:
            worker_input = {
                "contract_id": "kjds-governed-media-job-worker-input-v1",
                "tool_name": tool["name"],
                "tool_version": tool["version"],
                "project_ref": brief["project_ref"],
                "brief_ref": brief["brief_ref"],
                "campaign_content_asset_refs": list(
                    brief["content_asset_refs"]
                ),
                "editing_blueprint_ref": tool_inputs.get(
                    "editing_blueprint_ref"
                ),
                "reference_asset_refs": list(
                    tool_inputs.get("reference_asset_refs", [])
                ),
                "source_asset_refs": list(
                    tool_inputs.get("source_asset_refs", [])
                ),
                "audio_asset_refs": list(
                    tool_inputs.get("audio_asset_refs", [])
                ),
                "target_channels": list(
                    EDITING_TARGET_CHANNELS
                ),
                "analysis_contract_sha256": (
                    _sha(tool_inputs["analysis_contract"])
                    if "analysis_contract" in tool_inputs
                    else None
                ),
                "analysis_evidence_ref": tool_inputs.get(
                    "analysis_evidence_ref"
                ),
                "render_profile_sha256": (
                    FFMPEG_RENDER_PROFILE_SHA256
                    if tool["name"] in {
                        "media.video_blueprint",
                        "media.video_render",
                    }
                    else None
                ),
            }
        try:
            job = self.jobs.submit(
                principal=principal,
                store_ref=store_ref,
                request=request,
                campaign_brief=brief,
                tool_descriptor=descriptor,
                worker_input=worker_input,
            )
        except Exception:
            raise CommanderToolGatewayError("media_job_submit_failed") from None
        projection = self._projection(
            tool,
            job,
            descriptor_sha256=descriptor["descriptor_sha256"],
        )
        return {
            "contract_version": projection.contract_version,
            "job_ref": projection.job_ref,
            "status": projection.state,
        }

    def read(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> dict[str, Any]:
        gateway = self._registry()
        try:
            job, binding = self.jobs.read_bound(
                principal=principal,
                store_ref=_text(store_ref, "store_ref"),
                job_ref=_text(job_ref, "job_ref"),
            )
        except Exception:
            raise CommanderToolGatewayError("media_job_read_failed") from None
        tool = self._tool(gateway, binding.tool_name, binding.tool_version)
        descriptor = self._descriptor(
            tool=tool,
            provider=binding.provider,
            connector_ref=binding.connector_ref,
            connector_binding_sha256=binding.connector_binding_sha256,
        )
        return asdict(
            self._projection(
                tool,
                job,
                descriptor_sha256=descriptor["descriptor_sha256"],
                historical_descriptor_sha256=binding.tool_descriptor_sha256,
            )
        )
