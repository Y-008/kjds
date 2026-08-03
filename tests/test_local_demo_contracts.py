import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
ADR_PATH = ROOT / "docs" / "adr" / "ADR-0093-local-demo-client-boundary.md"
REGISTRY_PATH = (
    ROOT / "docs" / "project" / "registries" / "local_demo_contracts.json"
)


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_contract_freezes_one_deep_module_chain_and_gateway_surface():
    registry = _registry()

    assert registry["schema_version"] == "kjds-local-demo-contracts-v1"
    assert registry["task_id"] == "BAS-190"
    assert registry["owner_lane"] == "K"
    assert registry["owner_thread_id"] == "019fc654-03dc-7c71-a520-8f85918f3e44"
    assert registry["lease_commit"] == "10a07abb6575bf733110d49f0209b1172bfb4908"
    assert registry["contract_version"] == "local-demo-gateway/1.0.0"
    assert registry["decision_state"] == "contract_frozen"
    assert registry["module_chain"] == [
        "ScenarioPack",
        "DemoSession",
        "LocalDemoGateway",
    ]
    gateway = registry["domain_objects"]["LocalDemoGateway"]
    assert gateway["only_public_application_interface"] is True
    assert gateway["methods"] == ["open_session", "query", "apply", "reset"]
    assert gateway["action_output_type"] == "DemoTransition"
    assert gateway["production_authority_output_types"] == []


def test_every_response_is_visibly_synthetic_non_billable_and_non_authoritative():
    envelope = _registry()["response_envelope"]

    assert set(envelope["applies_to"]) == {
        "success",
        "error",
        "not_found",
        "conflict",
        "idempotent_replay",
        "export",
    }
    assert envelope["constant_top_level_fields"] == {
        "demo": True,
        "synthetic": True,
        "non_billable": True,
        "external_side_effect_allowed": False,
        "real_principal_ref": None,
        "real_entitlement_ref": None,
        "real_quota_ledger_ref": None,
        "real_approval_ref": None,
        "real_permit_ref": None,
    }
    assert envelope["caller_override_allowed"] is False
    assert {"sequence", "state_sha256", "network_invoked"} <= set(
        envelope["required_dynamic_fields"]
    )


def test_scope_is_session_only_and_foreign_sessions_are_non_enumerable():
    scope = _registry()["scope_and_errors"]

    assert scope["scope_source"] == "session_id_only"
    hidden = scope["foreign_or_missing_session"]
    assert hidden == {
        "http_status": 404,
        "error_code": "demo_session_not_found",
        "same_envelope": True,
        "foreign_identifiers_disclosed": False,
        "foreign_counts_disclosed": False,
        "foreign_data_disclosed": False,
    }
    override = scope["forbidden_scope_override"]
    assert override["error_code"] == "demo_scope_override_rejected"
    assert override["state_changed"] is False
    assert {"tenant_ref", "store_ref", "principal_ref", "api_key", "cookie"} <= set(
        override["forbidden_inputs"]
    )


def test_idempotent_replay_and_payload_drift_cannot_repeat_or_mutate():
    idempotency = _registry()["idempotency"]

    assert idempotency["method"] == "apply"
    assert idempotency["required_input"] == "idempotency_key"
    assert idempotency["fingerprint"] == "canonical_payload_sha256"
    replay = idempotency["same_key_same_fingerprint"]
    assert replay["result"] == "original_response"
    assert replay["sequence_changed"] is False
    assert replay["state_changed"] is False
    assert replay["network_invoked"] is False
    drift = idempotency["same_key_different_fingerprint"]
    assert drift["http_status"] == 409
    assert drift["error_code"] == "demo_idempotency_payload_drift"
    assert drift["sequence_changed"] is False
    assert drift["state_changed"] is False
    assert drift["network_invoked"] is False


def test_scenario_identity_is_content_addressed_and_hash_drift_fails_closed():
    scenario = _registry()["domain_objects"]["ScenarioPack"]

    assert scenario["immutable"] is True
    assert scenario["identity_prefix"] == "demo-"
    assert {"scenario_ref", "scenario_version", "scenario_sha256"} <= set(
        scenario["required_fields"]
    )
    assert scenario["same_ref_version_hash_drift"] == {
        "http_status": 409,
        "error_code": "demo_scenario_hash_drift",
        "state_changed": False,
    }
    session = _registry()["domain_objects"]["DemoSession"]
    assert session["storage"] == "local_memory_only"
    assert session["bound_for_lifetime"] == [
        "scenario_ref",
        "scenario_version",
        "scenario_sha256",
    ]


def test_production_dependencies_credentials_authority_and_writes_are_all_closed():
    registry = _registry()
    isolation = registry["isolation"]
    boolean_controls = {
        key: value
        for key, value in isolation.items()
        if key.endswith("_allowed")
    }
    assert boolean_controls
    assert all(value is False for value in boolean_controls.values())
    assert isolation["allowed_storage"] == "local_memory_only"
    assert {"Principal", "CommercialEntitlement", "UsageLedger", "Evidence"} <= set(
        isolation["forbidden_production_objects"]
    )
    assert {"Approval", "Permit", "Command", "CampaignGrant"} <= set(
        isolation["forbidden_production_objects"]
    )
    assert isolation["forbidden_import_prefixes"] == [
        "apps.control_plane",
        "web.app.backend",
    ]
    assert ".env" in isolation["forbidden_runtime_inputs"]
    assert "KJDS_API_KEY" in isolation["forbidden_runtime_inputs"]
    assert all(value is False for value in registry["control_boundary"].values())


def test_ui_vocabulary_never_claims_real_package_quota_authority_or_cash():
    vocabulary = _registry()["ui_vocabulary"]

    assert vocabulary["package"] == "企业演示包 · DEMO"
    assert vocabulary["capacity"] == "演示容量"
    assert vocabulary["connected_account"] == "场景店铺已连接"
    assert vocabulary["completed_action"] == "本地模拟完成"
    assert vocabulary["listing_action"] == "生成预览"
    assert vocabulary["profit"] == "合成利润场景"
    assert vocabulary["persistent_markers"] == ["LOCAL DEMO", "合成数据", "不计费"]


def test_adr_and_machine_registry_share_the_same_contract_and_boundaries():
    adr = ADR_PATH.read_text(encoding="utf-8")
    registry = _registry()

    for term in (
        "ScenarioPack",
        "DemoSession",
        "LocalDemoGateway",
        "open_session",
        "demo_idempotency_payload_drift",
        "demo_scenario_hash_drift",
        "external_side_effect_allowed",
        "clients/local-demo",
    ):
        assert term in adr
    assert "BAS-190 freezes documentation and machine contracts only" in adr
    assert registry["write_contract"]["shared_leases_required"] == []


def test_bas190_write_contract_is_exact_and_excludes_implementation_roots():
    write_contract = _registry()["write_contract"]

    assert write_contract["allowed_files"] == [
        "docs/adr/ADR-0093-local-demo-client-boundary.md",
        "docs/project/registries/local_demo_contracts.json",
        "tests/test_local_demo_contracts.py",
    ]
    assert {
        "docs/project/MASTER_SPEC.md",
        "clients/local-demo",
        "apps/control_plane",
        "web",
        "migrations",
        "docs/project/contracts/openapi-v1.json",
    } <= set(write_contract["forbidden_paths"])
