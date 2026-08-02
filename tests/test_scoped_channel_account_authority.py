from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.scoped_channel_account_authority import (
    AuthenticatedStoreMatrixAuthority,
    ChannelAccountMutationScopeAuthority,
    ScopedChannelAccountAuthorityWorkspace,
)
from apps.control_plane.security import Principal

AS_OF = datetime.now(UTC) - timedelta(minutes=5)
AUTHORITY = "a" * 64
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": AUTHORITY,
}
ENTITY_SCOPE = {
    "status": "ready",
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "authority_sha256": AUTHORITY,
}


class FakeScopeGrants:
    def __init__(self, value=None):
        self.value = deepcopy(value or ENTITY_SCOPE)
        self.calls = 0

    def current(self, **_kwargs):
        self.calls += 1
        return deepcopy(self.value)


class FakeStoreMatrix:
    def __init__(self, *, status="ready", values=None):
        self.status = status
        self.values = deepcopy(values or {})
        self.calls = 0

    def current(self, *, principal, entity_ref, store_ref, **_kwargs):
        self.calls += 1
        return {
            "contract_id": "kjds-authenticated-store-matrix-v1",
            "status": self.status,
            "actor_id": principal.actor_id,
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "roles": sorted(principal.roles),
            "source_gaps": ([] if self.status == "ready" else [f"channel_account_store_matrix_{self.status}"]),
            **deepcopy(self.values),
        }


class FakeAuthority:
    SOURCE_CONTRACT_ID = "kjds-channel-account-authority-source-v1"

    def __init__(self, events=None):
        self.events = deepcopy(events or [])
        self.calls = 0

    def read_scoped_sources(self, **kwargs):
        self.calls += 1
        payload = {
            "contract_id": self.SOURCE_CONTRACT_ID,
            "status": "ready" if self.events else "no_data",
            "as_of": kwargs["as_of"],
            "scope": {
                key: kwargs[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "scope_grant_authority_sha256",
                )
            },
            "events": deepcopy(self.events),
            "truncated": False,
            "source_gaps": ([] if self.events else ["channel_account_binding_missing"]),
            "control_envelope": {
                "secret_reference_returned": False,
            },
        }
        payload["snapshot_sha256"] = ScopedChannelAccountAuthorityWorkspace._hash(payload)
        return payload

    def validate_event(self, *, event, **_kwargs):
        if event.get("_raise"):
            raise ValueError("bad evidence")
        return list(event.get("_issues") or [])


class FakeAdapters:
    def resolve(self, **_kwargs):
        return {
            "verification_ttl_hours": 24,
            "contract_sha256": "b" * 64,
        }

    def snapshot(self, *, as_of):
        result = {
            "registry_id": "kjds-channel-account-adapters",
            "as_of": as_of.isoformat(),
        }
        result["snapshot_sha256"] = ScopedChannelAccountAuthorityWorkspace._hash(result)
        return result


class FakeRuntimeIdentity:
    def __init__(self, *, status="fresh_passed"):
        self.status = status

    def verify(self, **_kwargs):
        passed = self.status == "fresh_passed"
        return {
            "contract_id": ("kjds-channel-account-runtime-binding-probe-v1"),
            "status": self.status,
            "managed_store_bound": passed,
            "lease_fresh": passed,
            "fingerprint_match": passed,
            "scope_match": passed,
            "capabilities_match": passed,
            "provider_readback_fresh_passed": passed,
            "external_verifier_fresh_passed": passed,
            "source_gaps": ([] if passed else ["channel_account_runtime_identity_unbound"]),
        }


def principal(*, stores=frozenset({"ozon-primary"})):
    return Principal(
        actor_id="channel-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


def event(
    *,
    account_ref="account-a",
    adapter_id="adapter-a",
    sequence=1,
    event_type="authorization_granted",
    **values,
):
    return {
        "id": f"caev-{account_ref}-{adapter_id}-{sequence}",
        "source_event_ref": (f"source-{account_ref}-{adapter_id}-{sequence}"),
        "sequence": sequence,
        "event_type": event_type,
        "authorization_source": "official",
        "platform": "ozon",
        "account_ref": account_ref,
        "adapter_id": adapter_id,
        "adapter_version": "v1",
        "adapter_contract_sha256": "b" * 64,
        "role_ref": "seller",
        "subaccount_ref": None,
        "credential_kind": "api_key_ref",
        "capabilities": ["orders.read"],
        "secret_reference_present": True,
        "secret_reference_sha256": "c" * 64,
        "credential_fingerprint_sha256": "d" * 64,
        "health_status": "healthy",
        "readback_outcome": "succeeded",
        "rate_limit_state": "available",
        "external_schema_version": "v1",
        "consent_evidence_id": "consent-a",
        "consent_evidence_sha256": "e" * 64,
        "evidence_id": "event-a",
        "source_evidence_sha256": "f" * 64,
        "source_payload_sha256": "1" * 64,
        "payload_sha256": f"{sequence:x}".rjust(64, "0"),
        "approval_id": "approval-a",
        "command_id": "command-a",
        "receipt_id": "receipt-a",
        "permit_evidence_id": "permit-a",
        "readback_evidence_id": "readback-a",
        "kill_switch_sequence": 1,
        "kill_switch_evidence_id": "kill-a",
        "compensation_plan_id": "comp-plan-a",
        "compensation_evidence_id": "comp-a",
        "effective_at": (AS_OF - timedelta(hours=2) + timedelta(seconds=sequence)).isoformat(),
        "expires_at": (AS_OF + timedelta(days=1)).isoformat(),
        "verified_at": (AS_OF - timedelta(hours=1)).isoformat(),
        "recorded_at": (AS_OF - timedelta(hours=2) + timedelta(seconds=sequence)).isoformat(),
        "scope_as_of": (AS_OF - timedelta(hours=2)).isoformat(),
        "scope": SCOPE,
        **values,
    }


def workspace(
    *,
    events=None,
    canonical_scope=None,
    runtime_identity=None,
    store_matrix=None,
):
    authority = FakeAuthority(events)
    grants = FakeScopeGrants(canonical_scope)
    return (
        ScopedChannelAccountAuthorityWorkspace(
            authority=authority,
            adapters=FakeAdapters(),
            scope_grants=grants,
            store_matrix=(store_matrix or FakeStoreMatrix()),
            runtime_identity=(runtime_identity or FakeRuntimeIdentity()),
        ),
        authority,
        grants,
    )


def project(module, **values):
    return module.project(
        principal=values.pop("principal_value", principal()),
        entity_scope=values.pop("entity_scope", ENTITY_SCOPE),
        store_ref=values.pop("store_ref", "ozon-primary"),
        as_of=values.pop("as_of", AS_OF),
        **values,
    )


def test_missing_canonical_entity_reads_no_raw_authority():
    module, authority, grants = workspace(
        canonical_scope={
            "status": "no_data",
            "tenant_ref": "tenant-a",
            "store_ref": "ozon-primary",
        }
    )
    result = project(
        module,
        entity_scope={
            "status": "no_data",
            "tenant_ref": "tenant-a",
            "store_ref": "ozon-primary",
        },
    )
    assert result["status"] == "no_data"
    assert result["verified_native"] is False
    assert authority.calls == 0
    assert grants.calls == 1
    assert result["control_envelope"]["upstream_reads"] == [
        "canonical_scope_grant"
    ]


@pytest.mark.parametrize("status", ["blocked", "denied", "stale", "revoked"])
def test_canonical_scope_failure_blocks_before_matrix_or_raw_authority(status):
    matrix = FakeStoreMatrix()
    module, authority, grants = workspace(
        canonical_scope={
            **ENTITY_SCOPE,
            "status": status,
        },
        store_matrix=matrix,
    )
    result = project(
        module,
        entity_scope={
            **ENTITY_SCOPE,
            "status": status,
        },
    )
    assert result["status"] == "blocked"
    assert result["control_envelope"]["upstream_reads"] == [
        "canonical_scope_grant"
    ]
    assert authority.calls == 0
    assert grants.calls == 1
    assert matrix.calls == 0


@pytest.mark.parametrize("status", ["blocked", "denied", "stale", "revoked"])
def test_store_matrix_failure_blocks_after_scope_before_raw_authority(status):
    matrix = FakeStoreMatrix(status=status)
    module, authority, grants = workspace(store_matrix=matrix)
    result = project(module)
    assert result["status"] == "blocked"
    assert result["control_envelope"]["upstream_reads"] == [
        "canonical_scope_grant",
        "canonical_store_matrix",
    ]
    assert authority.calls == 0
    assert grants.calls == 1
    assert matrix.calls == 1


def test_store_matrix_binding_conflict_fails_before_scope_or_authority():
    matrix = FakeStoreMatrix(values={"actor_id": "attacker"})
    module, authority, grants = workspace(store_matrix=matrix)
    with pytest.raises(PermissionError, match="Store Matrix"):
        project(module)
    assert authority.calls == 0
    assert grants.calls == 1


def test_store_matrix_roles_must_intersect_principal_and_workspace_roles():
    matrix = FakeStoreMatrix(values={"roles": ["reviewer"]})
    module, authority, grants = workspace(store_matrix=matrix)
    with pytest.raises(PermissionError, match="Store Matrix"):
        project(module)
    assert authority.calls == 0
    assert grants.calls == 1
    assert matrix.calls == 1


def test_authenticated_store_matrix_hash_binds_as_of():
    canonical_principal = principal()
    authority = AuthenticatedStoreMatrixAuthority(
        identity_resolver=lambda _actor_id: canonical_principal
    )
    first = authority.current(
        principal=canonical_principal,
        entity_ref="entity-a",
        store_ref="ozon-primary",
        as_of=AS_OF,
    )
    second = authority.current(
        principal=canonical_principal,
        entity_ref="entity-a",
        store_ref="ozon-primary",
        as_of=AS_OF + timedelta(seconds=1),
    )
    assert first["status"] == "ready"
    assert first["as_of"] == AS_OF.isoformat()
    assert first["authority_sha256"] != second["authority_sha256"]


def test_mutation_scope_resolves_canonical_grant_and_store_matrix():
    grants = FakeScopeGrants()
    matrix = FakeStoreMatrix()
    authority = ChannelAccountMutationScopeAuthority(
        scope_grants=grants,
        store_matrix=matrix,
    )
    resolved = authority.resolve(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="ozon-primary",
        as_of=AS_OF,
    )
    assert resolved == SCOPE
    assert grants.calls == 1
    assert matrix.calls == 1


@pytest.mark.parametrize("boundary", ["scope", "matrix", "supplied"])
def test_mutation_scope_fails_before_service_authority(boundary):
    canonical = ENTITY_SCOPE
    matrix = FakeStoreMatrix()
    supplied = ENTITY_SCOPE
    if boundary == "scope":
        canonical = {**ENTITY_SCOPE, "status": "revoked"}
    elif boundary == "matrix":
        matrix = FakeStoreMatrix(status="revoked")
    else:
        supplied = {**ENTITY_SCOPE, "entity_ref": "forged-entity"}
    authority = ChannelAccountMutationScopeAuthority(
        scope_grants=FakeScopeGrants(canonical),
        store_matrix=matrix,
    )
    with pytest.raises(PermissionError):
        authority.resolve(
            principal=principal(),
            entity_scope=supplied,
            store_ref="ozon-primary",
            as_of=AS_OF,
        )


def test_direct_workspace_call_cannot_forge_scope_or_store():
    module, authority, _grants = workspace()
    forged = {**ENTITY_SCOPE, "entity_ref": "entity-other"}
    with pytest.raises(
        PermissionError,
        match="canonical Scope Grant",
    ):
        project(module, entity_scope=forged)
    with pytest.raises(PermissionError, match="store scope"):
        project(
            module,
            store_ref="store-other",
            principal_value=principal(),
        )
    assert authority.calls == 0


def test_empty_real_authority_is_honest_no_data():
    module, _, _ = workspace()
    result = project(module)
    assert result["status"] == "no_data"
    assert result["counts"]["total"] == 0
    assert result["verified_native"] is False
    assert result["native_implementation_status"] == "implemented_unverified"
    assert result["governed_action_contract"]["production_workflow_status"] == "mutation_gated"
    assert result["governed_action_contract"]["internal_governance_api_exposed"] is True
    assert result["governed_action_contract"]["provider_mutation_api_exposed"] is False
    assert result["governed_action_contract"]["provider_mutation_enabled"] is False
    assert result["native_implementation_status"] == ("implemented_unverified")


def test_dual_active_adapter_identity_blocks_whole_account():
    module, _, _ = workspace(
        events=[
            event(adapter_id="adapter-a"),
            event(adapter_id="adapter-b"),
        ]
    )
    result = project(module)
    assert result["status"] == "blocked"
    assert result["verified_native"] is False
    assert result["counts"]["evidence_blocked"] == 2
    assert all(
        "channel_account_dual_runtime_identity_conflict" in item["source_gaps"] for item in result["channel_accounts"]
    )


def test_dual_lifecycle_active_conflict_blocks_ready_and_degraded_identity():
    module, _, _ = workspace(
        events=[
            event(adapter_id="adapter-a"),
            event(adapter_id="adapter-b", health_status="degraded"),
        ]
    )
    result = project(module)
    assert result["status"] == "blocked"
    assert result["counts"]["evidence_blocked"] == 2
    assert all(
        "channel_account_dual_runtime_identity_conflict" in item["source_gaps"] for item in result["channel_accounts"]
    )


def test_invalid_latest_revoke_remains_possibly_active_for_dual_identity():
    module, _, _ = workspace(
        events=[
            event(adapter_id="adapter-a"),
            event(adapter_id="adapter-b"),
            event(
                adapter_id="adapter-b",
                sequence=2,
                event_type="authorization_revoked",
                _issues=["observation_hash_drift"],
            ),
        ]
    )
    result = project(module)
    assert result["status"] == "blocked"
    assert result["counts"]["evidence_blocked"] == 2
    assert all(
        "channel_account_dual_runtime_identity_conflict" in item["source_gaps"]
        for item in result["channel_accounts"]
    )


def test_collection_status_and_counts_do_not_follow_page_or_filter():
    module, _, _ = workspace(
        events=[
            event(account_ref="account-a"),
            event(
                account_ref="account-z",
                event_type="authorization_revoked",
            ),
        ]
    )
    first_page = project(module, page_size=1)
    filtered = project(module, state="ready", page_size=1)
    assert first_page["channel_accounts"][0]["state"] == "ready"
    assert first_page["status"] == "blocked"
    assert first_page["verified_native"] is False
    assert first_page["counts"]["total"] == 2
    assert first_page["counts"]["revoked"] == 1
    assert filtered["channel_accounts"][0]["state"] == "ready"
    assert filtered["status"] == "blocked"
    assert filtered["counts"] == first_page["counts"]
    assert filtered["pagination"]["filtered_total"] == 1


def test_latest_bad_event_blocks_without_older_ready_fallback():
    first = event()
    second = event(
        sequence=2,
        event_type="unknown_outcome_observed",
        readback_outcome="unknown",
        approval_id=None,
        command_id=None,
        receipt_id=None,
        permit_evidence_id=None,
        readback_evidence_id=None,
        kill_switch_sequence=None,
        kill_switch_evidence_id=None,
        compensation_plan_id=None,
        compensation_evidence_id=None,
    )
    module, _, _ = workspace(events=[first, second])
    result = project(module)
    assert result["status"] == "blocked"
    assert result["channel_accounts"][0]["state"] == ("unknown_outcome")
    assert result["channel_accounts"][0]["lifecycle"]["latest_sequence"] == 2


def test_new_authorization_epoch_may_begin_at_global_sequence_after_scope_filter():
    # Earlier-epoch rows are intentionally outside the current Scope Grant.
    # The first visible row therefore retains the global append-only sequence.
    module, _, _ = workspace(events=[event(sequence=7)])
    result = project(module)
    assert result["status"] == "ready"
    assert result["channel_accounts"][0]["state"] == "ready"
    assert result["channel_accounts"][0]["lifecycle"]["latest_sequence"] == 7
    assert "channel_account_sequence_drift" not in result["source_gaps"]
    assert result["verified_native"] is False


def test_degraded_health_never_enters_runtime_ready_or_native_verified():
    module, _, _ = workspace(events=[event(health_status="degraded")])
    result = project(module)
    assert result["status"] == "blocked"
    assert result["channel_accounts"][0]["state"] == "health_blocked"
    assert result["verified_native"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("health_status", "unknown"),
        ("rate_limit_state", "unknown"),
        ("external_schema_version", "drifted"),
        ("verified_at", "2020-01-01T00:00:00+00:00"),
    ],
)
def test_single_observation_field_drift_fails_closed(field, value):
    row = event(**{field: value}, _issues=["observation_hash_drift"])
    module, _, _ = workspace(events=[row])
    result = project(module)
    assert result["status"] == "blocked"
    assert result["verified_native"] is False
    assert result["channel_accounts"][0]["state"] == ("evidence_blocked")


def test_agent_artifact_never_grants_authority():
    module, _, _ = workspace(events=[event()])
    result = project(module)
    artifact = result["agent_artifact"]
    forbidden = [
        "reauthorization_allowed",
        "credential_rotation_allowed",
        "secret_read_allowed",
        "scope_expansion_allowed",
        "authorization_change_allowed",
        "self_approval_allowed",
        "permit_issue_allowed",
        "external_verification_allowed",
        "customer_contact_allowed",
        "platform_contact_allowed",
        "fictional_authority_allowed",
        "external_write_allowed",
    ]
    assert all(artifact[field] is False for field in forbidden)
    assert result["control_envelope"]["private_endpoint_allowed"] is False
    assert result["control_envelope"]["captcha_bypass_allowed"] is False
