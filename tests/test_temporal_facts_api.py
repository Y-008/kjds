import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.control_plane.api import registered_routes
from apps.control_plane.routers.temporal_facts import RestateFactInput, _timestamp


def test_as_of_rejects_future_timestamp():
    with pytest.raises(HTTPException, match="future"):
        _timestamp("2999-01-01T00:00:00Z")


def test_temporal_fact_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/facts/as-of" in paths
    assert "/v1/facts/{fact_id}/versions" in paths
    assert "/v1/facts/{fact_id}/restate" in paths


def test_restatement_requires_idempotency_key():
    with pytest.raises(ValidationError):
        RestateFactInput(
            entity_ref="entity-a",
            payload={"value": 1},
            correction_reason="late settlement",
        )
