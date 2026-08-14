from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from apps.control_plane.commerce_mcp import (
    MCP_CONTRACT_VERSION,
    CommerceMcpFacade,
    create_mcp_server,
)
from apps.control_plane.security import (
    AuthenticationFailure,
    Principal,
)


class AuthStub:
    def __init__(self, principal: Principal | None):
        self.principal = principal
        self.keys: list[str | None] = []

    def authenticate(self, key):
        self.keys.append(key)
        if self.principal is None:
            raise AuthenticationFailure("missing", 401)
        return self.principal


class CommerceStub:
    def __init__(self):
        self.calls = []

    def workspace(self, **values):
        self.calls.append(values)
        return {
            "contract_version": "commerce-operating-system/1.0.0",
            "scope": {"store_ref": values["store_ref"]},
            "control_envelope": {"external_writes": False},
            "snapshot_sha256": "workspace-hash",
        }


def services(principal):
    auth = AuthStub(principal)
    commerce = CommerceStub()
    return SimpleNamespace(authenticator=auth, commerce_os=commerce)


def operator(stores=frozenset({"ozon-primary"})):
    return Principal(
        "mcp-operator",
        frozenset({"operator"}),
        "tenant-a",
        stores,
    )


def test_mcp_facade_uses_bound_identity_and_existing_deep_module():
    runtime = services(operator())
    facade = CommerceMcpFacade(
        services=runtime,
        api_key_provider=lambda: "bound-mcp-key",
    )

    result = facade.workspace(
        store_ref="ozon-primary",
        as_of="2026-07-28T00:00:00Z",
    )

    assert runtime.authenticator.keys == ["bound-mcp-key"]
    assert runtime.commerce_os.calls == [
        {
            "principal": operator(),
            "store_ref": "ozon-primary",
            "as_of": "2026-07-28T00:00:00Z",
        }
    ]
    assert result["mcp_contract_version"] == MCP_CONTRACT_VERSION
    assert result["mode"] == "read_only"
    assert result["control_envelope"] == {
        "external_write_tools_exposed": False,
        "agent_self_approval": False,
        "agent_permit_issuance": False,
        "direct_database_access": False,
    }


def test_mcp_facade_rejects_missing_wrong_role_and_cross_store():
    missing = CommerceMcpFacade(
        services=services(None),
        api_key_provider=lambda: None,
    )
    with pytest.raises(AuthenticationFailure):
        missing.workspace(store_ref="ozon-primary")

    executor = CommerceMcpFacade(
        services=services(
            Principal(
                "executor",
                frozenset({"executor"}),
                "tenant-a",
                frozenset({"ozon-primary"}),
            )
        ),
        api_key_provider=lambda: "executor-key",
    )
    with pytest.raises(PermissionError, match="read role"):
        executor.workspace(store_ref="ozon-primary")

    cross_store = CommerceMcpFacade(
        services=services(operator()),
        api_key_provider=lambda: "operator-key",
    )
    with pytest.raises(PermissionError, match="not authorized"):
        cross_store.workspace(store_ref="other-store")


def test_mcp_server_exposes_one_read_only_tool_and_no_write_tool():
    facade = CommerceMcpFacade(
        services=services(operator()),
        api_key_provider=lambda: "operator-key",
    )
    server = create_mcp_server(facade)

    tools = asyncio.run(server.list_tools())
    assert [item.name for item in tools] == [
        "get_commerce_os_workspace"
    ]
    tool = tools[0]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert not any(
        token in tool.name
        for token in ("publish", "purchase", "payment", "permit", "approve")
    )
