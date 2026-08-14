from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    ROOT / "docs" / "project" / "registries" / "media_agent_source_adoption.json"
)
CONTRACT_PATH = (
    ROOT / "docs" / "project" / "registries" / "media_agent_contracts.json"
)
ADR_PATH = ROOT / "docs" / "adr" / "ADR-0092-commander-media-subagent-contracts.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bas_180_files_are_versioned_contract_only_authorities() -> None:
    source = _load(SOURCE_PATH)
    contract = _load(CONTRACT_PATH)
    adr = " ".join(ADR_PATH.read_text(encoding="utf-8").split())

    assert source["schema_version"] == "kjds-media-agent-source-adoption-v1"
    assert contract["schema_version"] == "kjds-media-agent-contracts-v1"
    assert source["status"] == contract["status"] == "contract_only"
    assert source["work_item"] == contract["work_item"] == "BAS-180"
    assert "introduces no database table, API route, Worker, Provider" in adr
    assert contract["future_public_surface"]["implemented_by_bas_180"] is False


def test_source_adoption_is_complete_unique_and_never_auto_installs() -> None:
    registry = _load(SOURCE_PATH)
    allowed_decisions = set(registry["decision_vocabulary"])
    candidates = registry["candidates"]
    ids = [item["id"] for item in candidates]

    assert len(ids) == len(set(ids))
    assert registry["policy"]["new_runtime_execution_in_bas_180"] is False
    assert registry["policy"]["automatic_install"] is False
    assert registry["policy"]["pinned_version_and_hash_required_before_runtime"] is True
    assert registry["policy"]["commercial_sale_readiness_granted"] is False
    for item in candidates:
        assert item["decision"] in allowed_decisions
        assert item["version"]
        assert item["license"]
        assert item["evidence_urls"]
        assert item["entry_gate"]
        assert item["exit_gate"]
        assert isinstance(item["borrowed_patterns"], list)
        assert isinstance(item["allowed_kjds_use"], list)
        assert isinstance(item["prohibited_kjds_use"], list)


def test_source_selection_prefers_codex_protocol_and_preserves_existing_media_seams() -> None:
    registry = _load(SOURCE_PATH)
    candidates = {item["id"]: item for item in registry["candidates"]}

    assert candidates["openai_codex_app_server"]["decision"] == "preferred_protocol"
    assert candidates["comfyui"]["decision"] == "existing_runtime"
    assert candidates["ffmpeg"]["decision"] == "existing_runtime"
    assert candidates["agent_cli_to_api"]["decision"] == "adopt_pattern"
    assert candidates["ima2_gen"]["decision"] == "adopt_pattern"
    assert candidates["catgpt_gateway"]["decision"] == "adopt_pattern"
    assert candidates["browser_fingerprint_mutation_stacks"]["decision"] == "reject_runtime"
    assert registry["policy"]["chatgpt_web_dom_is_production_transport"] is False
    assert registry["policy"]["explicit_provider_selection_required"] is True


def test_exactly_five_tools_return_only_a_durable_job_reference() -> None:
    contract = _load(CONTRACT_PATH)
    gateway = contract["tool_gateway"]
    tools = gateway["tools"]

    assert {item["name"] for item in tools} == {
        "media.image_generate",
        "media.image_edit",
        "media.video_blueprint",
        "media.video_render",
        "tutorial.build",
    }
    assert len(tools) == 5
    assert gateway["immediate_result_required_fields"] == [
        "contract_version",
        "job_ref",
        "status",
    ]
    assert gateway["immediate_result_additional_fields_allowed"] is False
    assert gateway["immediate_result_status"] == "QUEUED"
    assert all(item["version"] == "1.0.0" for item in tools)
    assert all(item["required_capabilities"] for item in tools)
    assert all(item["accepted_providers"] for item in tools)


def test_tool_inputs_do_not_accept_caller_scope_or_sensitive_material() -> None:
    contract = _load(CONTRACT_PATH)
    gateway = contract["tool_gateway"]
    allowed = set(gateway["common_allowed_inputs"])
    for tool in gateway["tools"]:
        allowed.update(tool["additional_allowed_inputs"])

    forbidden_scope = set(contract["scope_contract"]["caller_forbidden_scope_fields"])
    forbidden_sensitive = {
        value.lower()
        for value in contract["sensitive_field_policy"]["forbidden_payload_keys"]
    }
    assert contract["scope_contract"]["caller_supplied_authority_fields_allowed"] is False
    assert not allowed.intersection(forbidden_scope)
    assert not {value.lower() for value in allowed}.intersection(forbidden_sensitive)
    assert contract["control_envelope"]["credential_material_visible_to_commander"] is False
    assert contract["control_envelope"]["blob_bytes_visible_to_commander"] is False


def test_job_state_machine_is_closed_and_unknown_outcome_is_readback_only() -> None:
    job = _load(CONTRACT_PATH)["job_contract"]
    states = set(job["states"])
    transitions = job["transitions"]

    assert job["start_state"] == "QUEUED"
    assert set(transitions) == states
    assert set(job["terminal_states"]) == {
        "SUCCEEDED",
        "FAILED",
        "UNKNOWN_OUTCOME",
    }
    assert set(job["paused_states"]) == {"LOGIN_REQUIRED", "LIMITED"}
    assert all(set(targets).issubset(states) for targets in transitions.values())
    assert all(not transitions[state] for state in job["terminal_states"])
    assert transitions["UNKNOWN_OUTCOME"] == []
    assert "no_new_dispatch" in job["resume_requirements"]["UNKNOWN_OUTCOME"]
    assert job["defaults"]["automatic_retry_after_unknown_outcome"] is False


def test_bas_186_render_is_ffmpeg_only_and_result_readback_is_frozen() -> None:
    contract = _load(CONTRACT_PATH)
    tools = {item["name"]: item for item in contract["tool_gateway"]["tools"]}
    assert tools["media.video_render"]["accepted_providers"] == ["ffmpeg"]
    assert tools["media.video_render"]["state"] == "job_intake_only"
    assert tools["media.image_generate"]["state"] == "job_intake_only"
    result = contract["job_contract"]["result_receipt_contract"]
    assert result == {
        "contract_id": "kjds-governed-media-job-result-v1",
        "allowed_states": ["SUCCEEDED"],
        "non_success_terminal_authority": "not_admitted",
        "typed_provider_receipt_authority_connected": False,
        "unknown_outcome_mode": "contract_only_not_admitted",
        "terminal_asset_and_receipt_atomic_transaction": True,
        "terminal_receipt_deferred_conservation": True,
        "scope_authority_lock_key": [
            "tenant_ref",
            "store_ref",
            "subject_actor_id",
        ],
        "active_dispatched_attempt_grace_seconds": 1500,
        "automatic_retry": False,
        "automatic_failover": False,
        "cancellation_result_receipt": False,
    }
    worker_input = contract["job_contract"]["worker_input_contract"]
    assert worker_input["reserved_evidence_source"] == (
        "governed-media-job-worker-input"
    )
    assert worker_input["safe_refs_hashes_versions_counts_only"] is True
    assert worker_input["raw_prompt_blob_or_command_allowed"] is False


def test_runtime_owned_tool_and_provider_descriptors_have_exact_parity() -> None:
    contract = _load(CONTRACT_PATH)
    tools = {item["name"]: item for item in contract["tool_gateway"]["tools"]}
    descriptors = contract["connector_contract"][
        "runtime_owned_provider_descriptors"
    ]

    expected = {
        "kjds_internal_blueprint_compiler": {
            "tool": "media.video_blueprint",
            "connector_ref": "internal://editing-blueprint-compiler-v1",
            "binding_sha256": (
                "9efaed15669de37606902e0473e798323f3b2018655bf3a7d51058c15fa1a4c8"
            ),
            "protocol_version": "kjds-internal-blueprint-compiler/1",
            "external_side_effect": "internal_deterministic_compile_only",
        },
        "kjds_internal_tutorial_compiler": {
            "tool": "tutorial.build",
            "connector_ref": "internal://tutorial-graph-compiler-v1",
            "binding_sha256": (
                "d0a0eb549be5a81cadb249bac37efce7a71768d49898c0c690dd7fd745f01a79"
            ),
            "protocol_version": "kjds-internal-tutorial-compiler/1",
            "external_side_effect": "internal_deterministic_compile_only",
        },
        "ffmpeg": {
            "tool": "media.video_render",
            "connector_ref": "internal://local-ffmpeg-renderer-v1",
            "binding_sha256": (
                "d39f725911da61e70ab388cf2a42fbd2941ebbcc196cdf4b390e5d0f4c468493"
            ),
            "protocol_version": "kjds-local-ffmpeg/1",
            "external_side_effect": "local_media_render_only",
        },
    }
    assert set(descriptors) == set(expected)
    for provider, frozen in expected.items():
        descriptor = descriptors[provider]
        tool = tools[frozen["tool"]]
        assert descriptor["provider"] == provider
        assert descriptor["connector_ref"] == frozen["connector_ref"]
        assert descriptor["binding_sha256"] == frozen["binding_sha256"]
        assert descriptor["protocol_version"] == frozen["protocol_version"]
        assert tool["accepted_providers"] == [provider]
        assert set(tool["required_capabilities"]) == set(
            descriptor["capabilities"]
        )
        assert tool["cost_upper_bound"] == descriptor["cost_upper_bound"]
        assert tool["external_side_effect"] == frozen["external_side_effect"]
        assert descriptor["connector_ref"].startswith("internal://")
        assert descriptor["deterministic"] is True
        assert descriptor["external_call"] is False
        assert descriptor["credential_required"] is False
        assert descriptor["enrollment_allowed"] is False
        assert descriptor["automatic_retry"] is False
        assert descriptor["automatic_failover"] is False

    assert descriptors["kjds_internal_blueprint_compiler"]["provider"] != (
        "codex_oauth"
    )


def test_provider_and_connector_routing_never_rotate_or_fail_over_implicitly() -> None:
    contract = _load(CONTRACT_PATH)
    envelope = contract["control_envelope"]
    connector = contract["connector_contract"]
    defaults = contract["job_contract"]["defaults"]

    assert envelope["provider_selection"] == "explicit"
    assert envelope["automatic_cross_provider_failover"] is False
    assert envelope["automatic_connector_identity_rotation"] is False
    assert connector["shared_pool"] is False
    assert connector["cross_tenant_reuse"] is False
    assert connector["automatic_rotation"] is False
    assert connector["raw_credential_readback"] is False
    assert defaults == {
        "connector_concurrency": 1,
        "tenant_queue_cap": 100,
        "raw_artifact_retention_days": 30,
        "automatic_retry_after_unknown_outcome": False,
        "automatic_cross_provider_retry": False,
        "automatic_identity_rotation": False,
    }


def test_connector_descriptor_has_no_secret_or_browser_archive_fields() -> None:
    contract = _load(CONTRACT_PATH)
    connector = contract["connector_contract"]
    allowed = {value.lower() for value in connector["allowed_record_fields"]}
    forbidden = {
        value.lower()
        for value in contract["sensitive_field_policy"]["forbidden_payload_keys"]
    }

    assert set(connector["deployment_modes"]) == {
        "customer_local",
        "hosted_isolated",
    }
    assert not allowed.intersection(forbidden)
    assert connector["credential_storage"] == (
        "provider_or_codex_owned_local_store_outside_kjds_database"
    )
    assert "connector_derived_tenant_matches_job_derived_tenant" in connector[
        "job_assignment_requirements"
    ]


def test_success_references_existing_asset_and_evidence_authority() -> None:
    contract = _load(CONTRACT_PATH)
    artifact = contract["artifact_contract"]
    job = contract["job_contract"]

    assert artifact["evidence_owner"] == "ContentAsset/Evidence"
    assert job["success_required_references"] == ["artifact_evidence_refs"]
    assert job["governed_commerce_success_references"] == [
        "content_asset_ref",
        "artifact_evidence_refs",
    ]
    assert artifact["standalone_proposal_listing_eligible"] is False
    assert artifact["content_asset_attachment_requires_existing_scope_and_media_qa"] is True
    assert artifact["job_owns_blob_bytes"] is False
    assert artifact["job_owns_qa_or_approval"] is False


def test_existing_authority_owners_are_not_reassigned() -> None:
    owners = _load(CONTRACT_PATH)["authority_owners"]

    assert owners == {
        "commander_goal_graph_and_verifiers": "AgentHarness",
        "media_blob_hash_lineage_qa_and_manifest": "ContentAsset/Evidence",
        "connector_descriptor_and_tenant_binding": "BAS-181",
        "codex_protocol_worker": "BAS-182",
        "job_api_sse_idempotency_and_usage_adapter": "BAS-183",
        "access_token_plan_balance_refund_sla_dpa_export_delete": "COM-002",
        "social_campaign_grant_publish_readback_revoke_kill": "BAS-178",
    }


def test_bas_180_contract_contains_no_runtime_or_api_claim() -> None:
    contract = _load(CONTRACT_PATH)
    source = _load(SOURCE_PATH)

    assert contract["status"] == "contract_only"
    assert contract["future_public_surface"]["implemented_by_bas_180"] is False
    assert source["current_selection"]["runtime_installation_status"] == (
        "no_new_runtime_from_bas_180"
    )
    assert source["current_selection"]["commercial_status"] == "not_for_sale"
