from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.automation import AutomationService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.sql_repository import Base


class FakeOllama:
    def list_models(self):
        return [
            {"name": "qwen2.5:3b", "size": 10, "digest": "abc", "modified_at": "now"},
            {"name": "unknown:latest", "size": 20, "digest": "def", "modified_at": "now"},
        ]


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return AutomationService(engine, InMemoryRepository())


def test_model_discovery_is_idempotent_and_license_gated():
    service = make_service()
    service.sync_ollama_models(FakeOllama())
    second = service.sync_ollama_models(FakeOllama())

    assert len(second) == 2
    assert {model.model_name: model.enabled for model in second} == {"qwen2.5:3b": True, "unknown:latest": False}


def test_shadow_recommendation_requires_evidence():
    service = make_service()
    with pytest.raises(ValueError, match="requires evidence"):
        service.create_recommendation(
            product_id=None,
            agent="finance",
            action="hold price",
            rationale="CM3",
            evidence=[],
            expected_cm3_delta=Decimal("10"),
            risk="low",
        )

    recommendation = service.create_recommendation(
        product_id=None,
        agent="finance",
        action="hold price",
        rationale="CM3 improved",
        evidence=["import://1"],
        expected_cm3_delta=Decimal("10"),
        risk="low",
    )
    assert recommendation.shadow_mode is True
    assert recommendation.status == "observing"
