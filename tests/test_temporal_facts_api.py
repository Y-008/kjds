from apps.control_plane.api import registered_routes


def test_temporal_fact_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/facts/as-of" in paths
    assert "/v1/facts/{fact_id}/versions" in paths
    assert "/v1/facts/{fact_id}/restate" in paths
