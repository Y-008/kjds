from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .runtime import RuntimeServices, runtime
from .security import Principal

MCP_CONTRACT_VERSION = "kjds-commerce-mcp/1.0.0"
ALLOWED_READ_ROLES = frozenset(
    {"operator", "reviewer", "compliance", "admin"}
)


class CommerceMcpFacade:
    """Expose governed read models without creating another business seam."""

    def __init__(
        self,
        *,
        services: RuntimeServices,
        api_key_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.services = services
        self.api_key_provider = api_key_provider or (
            lambda: os.getenv("KJDS_MCP_API_KEY")
        )

    def workspace(
        self,
        *,
        store_ref: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        principal = self._principal()
        store = store_ref.strip()
        if not store:
            raise ValueError("store_ref is required")
        if not principal.can_access_store(store):
            raise PermissionError(
                "MCP identity is not authorized for store_ref"
            )
        workspace = self.services.commerce_os.workspace(
            principal=principal,
            store_ref=store,
            as_of=as_of,
        )
        return {
            "mcp_contract_version": MCP_CONTRACT_VERSION,
            "mode": "read_only",
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "store_ref": store,
                "actor_id": principal.actor_id,
                "roles": sorted(principal.roles),
            },
            "workspace": workspace,
            "control_envelope": {
                "external_write_tools_exposed": False,
                "agent_self_approval": False,
                "agent_permit_issuance": False,
                "direct_database_access": False,
            },
        }

    def _principal(self) -> Principal:
        principal = self.services.authenticator.authenticate(
            self.api_key_provider()
        )
        if not principal.roles.intersection(ALLOWED_READ_ROLES):
            raise PermissionError(
                "MCP identity lacks a Commerce OS read role"
            )
        return principal


def create_mcp_server(
    facade: CommerceMcpFacade | None = None,
) -> FastMCP:
    read_model = facade or CommerceMcpFacade(services=runtime)
    server = FastMCP(
        "KJDS Commerce OS",
        instructions=(
            "Read-only KJDS operating facts. No tool can approve, issue a "
            "Permit, publish, contact a supplier, purchase, pay, or run ads."
        ),
    )
    read_only = ToolAnnotations(
        title="Read Commerce OS workspace",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        name="get_commerce_os_workspace",
        description=(
            "Read one authorized store's server-owned ERP lifecycle, "
            "business outcomes, evidence gaps, native modules, and Agent "
            "handoffs. Readiness is not recalculated by the MCP client."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def get_commerce_os_workspace(
        store_ref: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        return read_model.workspace(store_ref=store_ref, as_of=as_of)

    @server.resource(
        "kjds://commerce-os/{store_ref}",
        name="commerce_os_workspace",
        description=(
            "Authenticated read-only Commerce OS snapshot for an authorized "
            "store."
        ),
        mime_type="application/json",
    )
    def commerce_os_resource(store_ref: str) -> str:
        return json.dumps(
            read_model.workspace(store_ref=store_ref),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    return server


def main() -> None:
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
