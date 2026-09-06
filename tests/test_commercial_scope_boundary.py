from __future__ import annotations

import pytest
from fastapi import HTTPException

from apps.control_plane.api_contracts import CommercialScopeInput
from apps.control_plane.routers.commercial_lifecycle import _ensure_tenant_scope
from apps.control_plane.security import Principal


def test_commercial_scope_cannot_cross_authenticated_tenant():
    principal = Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    scope = CommercialScopeInput(
        customer_ref="customer-1",
        deployment_ref="deployment-1",
        tenant_ref="tenant-b",
        entity_ref="entity-1",
        store_ref="store-a",
    )
    with pytest.raises(HTTPException) as caught:
        _ensure_tenant_scope(scope, principal)
    assert caught.value.status_code == 403

