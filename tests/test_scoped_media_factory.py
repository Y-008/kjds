from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import (
    ContentAsset,
    ContentStatus,
    ContentType,
    Product,
)
from apps.control_plane.media_workbench import (
    MediaDeliveryManifestRow,
    MediaExecutionEventRow,
    MediaExecutionRow,
    MediaWorkbenchService,
)
from apps.control_plane.scoped_media_factory import (
    ScopedContentMediaFactoryWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import (
    Base,
    SqlAlchemyRepository,
)

AT = datetime(2026, 7, 29, 8, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": "a" * 64,
}
SCOPE_VALUE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}


def principal(
    stores: frozenset[str] = frozenset({"ozon-primary"}),
) -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


def hashed(value: dict) -> dict:
    result = dict(value)
    result["snapshot_sha256"] = (
        ScopedContentMediaFactoryWorkspace._hash(value)
    )
    return result


def projected_asset(
    *,
    asset_id: str = "asset-1",
    status: str = "brief",
    evidence_ready: bool = True,
    evidence_ids: list[str] | None = None,
    qa_count: int = 0,
) -> dict:
    return {
        "id": asset_id,
        "content_type": "image",
        "locale": "ru-RU",
        "channel": "OZON",
        "status": status,
        "artifact_ref": (
            f"evd-artifact-{asset_id}"
            if status in {"generated", "approved"}
            else None
        ),
        "evidence_ids": (
            evidence_ids
            if evidence_ids is not None
            else [f"evd-rights-{asset_id}"]
        ),
        "evidence_ready": evidence_ready,
        "qa_check_count": qa_count,
        "created_at": (AT - timedelta(hours=2)).isoformat(),
    }


def product_item(
    *,
    product_id: str = "product-1",
    sku: str = "SKU-1",
    assets: list[dict] | None = None,
) -> dict:
    core = {
        "product": {
            "id": product_id,
            "sku": sku,
            "name": f"Product {sku}",
            "market": "RU",
            "channel": "OZON",
            "status": "candidate",
            "created_at": (AT - timedelta(days=2)).isoformat(),
        },
        "scope_authority": "native_product_scope",
        "passports": [],
        "content_assets": (
            [projected_asset()] if assets is None else assets
        ),
        "evidence_ids": [],
        "evidence_authority_sha256": "e" * 64,
        "readiness": {
            "product_identity_ready": True,
            "passport_approved": True,
            "content_draft_allowed": True,
            "media_qa_ready": False,
            "listing_draft_allowed": False,
            "approval_plan_allowed": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        },
        "source_gaps": [],
        "blockers": [],
    }
    return hashed(core)


def product_projection(
    products: list[dict] | None = None,
    *,
    status: str = "ready",
) -> dict:
    core = {
        "contract_id": "kjds-scoped-product-content-v1",
        "status": status,
        "as_of": AT.isoformat(),
        "scope": SCOPE_VALUE,
        "products": (
            [product_item()] if products is None else products
        ),
        "counts": {},
        "excluded": {
            "count": 0,
            "by_reason": {},
            "details_disclosed": False,
        },
        "source_gaps": [],
        "blockers": [],
        "control_envelope": {
            "read_only": True,
            "raw_product_content_read": True,
            "external_write_allowed": False,
        },
    }
    return hashed(core)


def raw_asset(
    *,
    asset_id: str = "asset-1",
    product_id: str = "product-1",
    status: str = "brief",
    role: str = "hero",
    qa_results: list[dict] | None = None,
    generation: dict | None = None,
) -> dict:
    return {
        "id": asset_id,
        "product_id": product_id,
        "content_type": "image",
        "locale": "ru-RU",
        "channel": "OZON",
        "status": status,
        "artifact_ref": (
            f"evd-artifact-{asset_id}"
            if status in {"generated", "approved"}
            else None
        ),
        "brief": {
            "template_id": "ozon-retouch-v1",
            "role": role,
            "rights_evidence_ids": [f"evd-rights-{asset_id}"],
        },
        "source_facts": {},
        "qa_results": qa_results or [],
        "generation": generation or {},
        "created_at": (AT - timedelta(hours=2)).isoformat(),
    }


def media_projection(
    *,
    assets: list[dict] | None = None,
    executions: list[dict] | None = None,
    events: list[dict] | None = None,
    manifests: list[dict] | None = None,
    authorized_asset_ids: list[str] | None = None,
    truncated: bool = False,
) -> dict:
    asset_rows = [raw_asset()] if assets is None else assets
    authorized = (
        sorted(item["id"] for item in asset_rows)
        if authorized_asset_ids is None
        else authorized_asset_ids
    )
    core = {
        "contract_id": "kjds-scoped-media-read-source-v1",
        "as_of": AT.isoformat(),
        "authorized_asset_ids": authorized,
        "assets": asset_rows,
        "executions": executions or [],
        "events": events or [],
        "manifests": manifests or [],
        "truncated": {
            "assets": truncated,
            "executions": False,
            "events": False,
            "manifests": False,
        },
        "raw_read": bool(authorized),
    }
    return hashed(core)


class ProductContent:
    def __init__(self, value: dict | None = None) -> None:
        self.value = value or product_projection()
        self.calls = 0

    def project(self, **_kwargs):
        self.calls += 1
        return self.value


class MediaSource:
    def __init__(self, value: dict | None = None) -> None:
        self.value = value or media_projection()
        self.calls = 0

    def read_sources(self, **_kwargs):
        self.calls += 1
        return self.value


def workspace(
    *,
    content: ProductContent | None = None,
    media: MediaSource | None = None,
) -> tuple[
    ScopedContentMediaFactoryWorkspace,
    ProductContent,
    MediaSource,
]:
    content = content or ProductContent()
    media = media or MediaSource()
    return (
        ScopedContentMediaFactoryWorkspace(
            product_content=content,
            media_workbench=media,
        ),
        content,
        media,
    )


def valid_execution(
    *,
    asset: dict | None = None,
    status: str = "queued",
) -> tuple[dict, list[dict]]:
    asset = asset or raw_asset()
    template_id = "ozon-retouch-v1"
    input_sha = ScopedContentMediaFactoryWorkspace._hash(
        {
            "asset_id": asset["id"],
            "product_id": asset["product_id"],
            "content_type": asset["content_type"],
            "brief": asset["brief"],
            "template_id": template_id,
        }
    )
    queued_at = AT - timedelta(hours=1)
    execution = {
        "id": "execution-1",
        "asset_id": asset["id"],
        "media_kind": "image",
        "template_id": template_id,
        "input_sha256": input_sha,
        "status": status,
        "attempt": 1,
        "queued_by": "operator-a",
        "queued_at": queued_at.isoformat(),
        "lease_owner": None,
        "lease_expires_at": None,
        "started_at": None,
        "completed_at": None,
        "latency_ms": None,
        "cost": {"amount": "0", "currency": "CNY"},
        "outputs": {},
        "error_code": None,
        "error_detail": None,
        "external_side_effect": False,
    }
    events = [
        {
            "id": "event-1",
            "execution_id": execution["id"],
            "sequence": 1,
            "event_type": status,
            "from_status": None,
            "to_status": status,
            "payload": {},
            "actor_id": "operator-a",
            "occurred_at": queued_at.isoformat(),
        }
    ]
    return execution, events


def test_missing_or_invalid_entity_reads_no_upstream_sources():
    service, content, media = workspace()

    missing = service.project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    invalid = service.project(
        principal=principal(),
        entity_scope={
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": "bad",
        },
        store_ref="ozon-primary",
        as_of=AT,
    )

    assert missing["status"] == "no_data"
    assert invalid["status"] == "blocked"
    assert content.calls == 0
    assert media.calls == 0
    assert missing["control_envelope"]["scoped_input_read"] is False


def test_exact_scope_projection_is_deterministic_and_suggestion_only():
    service, _, _ = workspace()

    first = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    replay = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )

    assert first == replay
    assert first["status"] == "partial"
    assert first["product_groups"][0]["assets"][0]["stage"] == (
        "source_rights_ready"
    )
    assert first["agent_artifact"][
        "asset_or_job_creation_allowed"
    ] is False
    assert first["agent_artifact"][
        "qa_or_manifest_creation_allowed"
    ] is False
    assert first["control_envelope"]["external_write_allowed"] is False
    assert len(first["snapshot_sha256"]) == 64


def test_server_filter_cursor_counts_and_store_authorization():
    products = [
        product_item(
            product_id="product-2",
            sku="SKU-2",
            assets=[
                projected_asset(
                    asset_id="asset-2",
                    evidence_ids=[],
                    evidence_ready=False,
                )
            ],
        ),
        product_item(
            product_id="product-1",
            sku="SKU-1",
        ),
    ]
    raws = [
        raw_asset(asset_id="asset-2", product_id="product-2"),
        raw_asset(),
    ]
    service, _, _ = workspace(
        content=ProductContent(product_projection(products)),
        media=MediaSource(media_projection(assets=raws)),
    )

    first = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
    )
    second = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
        cursor=first["query"]["next_cursor"],
    )
    searched = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        query="asset-2",
        stage="brief",
    )

    assert first["counts"]["total_product_groups"] == 2
    assert first["product_groups"][0]["product"]["id"] == "product-1"
    assert second["product_groups"][0]["product"]["id"] == "product-2"
    assert searched["counts"]["total_product_groups"] == 1
    with pytest.raises(PermissionError):
        service.project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="other-store",
            as_of=AT,
        )
    with pytest.raises(ValueError, match="cursor"):
        service.project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=AT,
            cursor="not-a-cursor",
        )


def test_bad_latest_evidence_hides_asset_payload():
    projected = projected_asset(evidence_ready=False)
    service, _, _ = workspace(
        content=ProductContent(
            product_projection([product_item(assets=[projected])])
        )
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    asset = result["product_groups"][0]["assets"][0]

    assert result["status"] == "blocked"
    assert asset["stage"] == "blocked"
    assert asset["brief"] == {}
    assert asset["artifact_ref"] is None
    assert "content_asset_evidence_invalid" in asset["source_gaps"]


def test_future_mutable_asset_state_fails_closed():
    generation = {
        "completed_at": (AT + timedelta(seconds=1)).isoformat()
    }
    raw = raw_asset(status="generated", generation=generation)
    projected = projected_asset(status="generated")
    service, _, _ = workspace(
        content=ProductContent(
            product_projection([product_item(assets=[projected])])
        ),
        media=MediaSource(media_projection(assets=[raw])),
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )

    assert result["status"] == "blocked"
    assert "content_asset_future_state_unprovable" in (
        result["product_groups"][0]["assets"][0]["source_gaps"]
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda execution, events: execution.update(
                input_sha256="0" * 64
            ),
            "media_execution_input_hash_drift",
        ),
        (
            lambda execution, events: events[0].update(sequence=2),
            "media_execution_event_sequence_invalid",
        ),
        (
            lambda execution, events: execution.update(status="generated"),
            "media_execution_latest_state_mismatch",
        ),
    ],
)
def test_execution_integrity_drift_fails_closed(mutate, expected):
    raw = raw_asset()
    execution, events = valid_execution(asset=raw)
    mutate(execution, events)
    service, _, _ = workspace(
        media=MediaSource(
            media_projection(
                assets=[raw],
                executions=[execution],
                events=events,
            )
        )
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )

    asset = result["product_groups"][0]["assets"][0]
    assert asset["stage"] == "blocked"
    assert expected in asset["source_gaps"]
    assert asset["execution_timeline"] == []


def test_latest_manifest_hash_drift_fails_closed():
    qa = [
        {
            "check": "all",
            "passed": True,
            "reviewed_at": (AT - timedelta(minutes=10)).isoformat(),
        }
    ]
    generation = {"encoder_version": None}
    raw = raw_asset(
        status="approved",
        qa_results=qa,
        generation=generation,
    )
    projected = projected_asset(
        status="approved",
        qa_count=1,
        evidence_ids=[
            "evd-rights-asset-1",
            "evd-artifact-asset-1",
        ],
    )
    execution, events = valid_execution(asset=raw)
    state = {
        "asset_id": raw["id"],
        "product_id": raw["product_id"],
        "content_type": raw["content_type"],
        "status": raw["status"],
        "artifact_evidence_ids": ["evd-artifact-asset-1"],
        "qa_results": qa,
        "generation": generation,
    }
    payload = {
        "contract_id": "kjds-media-delivery-manifest-v1",
        "manifest_id": "manifest-1",
        "asset_id": raw["id"],
        "product_id": raw["product_id"],
        "content_type": raw["content_type"],
        "qa_status": "passed",
        "listing_eligible": True,
        "artifact_evidence_ids": ["evd-artifact-asset-1"],
        "input_sha256": execution["input_sha256"],
        "template_id": execution["template_id"],
        "encoder_version": None,
        "latency_ms": None,
        "cost": execution["cost"],
        "created_at": (AT - timedelta(minutes=5)).isoformat(),
        "external_marketplace_write": False,
    }
    payload["manifest_sha256"] = "0" * 64
    manifest = {
        "id": "manifest-1",
        "asset_id": raw["id"],
        "execution_id": execution["id"],
        "asset_state_sha256": (
            ScopedContentMediaFactoryWorkspace._hash(state)
        ),
        "manifest_sha256": "0" * 64,
        "payload": payload,
        "created_by": "reviewer-a",
        "created_at": payload["created_at"],
    }
    service, _, _ = workspace(
        content=ProductContent(
            product_projection([product_item(assets=[projected])])
        ),
        media=MediaSource(
            media_projection(
                assets=[raw],
                executions=[execution],
                events=events,
                manifests=[manifest],
            )
        ),
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )

    assert "media_manifest_hash_invalid" in (
        result["product_groups"][0]["assets"][0]["source_gaps"]
    )


def test_valid_approved_asset_projects_delivery_manifest_without_writes():
    qa = [
        {
            "check": "all",
            "passed": True,
            "reviewed_at": (AT - timedelta(minutes=10)).isoformat(),
        }
    ]
    generation = {"encoder_version": None}
    raw = raw_asset(
        status="approved",
        qa_results=qa,
        generation=generation,
    )
    projected = projected_asset(
        status="approved",
        qa_count=1,
        evidence_ids=[
            "evd-rights-asset-1",
            "evd-artifact-asset-1",
        ],
    )
    execution, events = valid_execution(
        asset=raw,
        status="generated",
    )
    state = {
        "asset_id": raw["id"],
        "product_id": raw["product_id"],
        "content_type": raw["content_type"],
        "status": raw["status"],
        "artifact_evidence_ids": ["evd-artifact-asset-1"],
        "qa_results": qa,
        "generation": generation,
    }
    payload = {
        "contract_id": "kjds-media-delivery-manifest-v1",
        "manifest_id": "manifest-1",
        "asset_id": raw["id"],
        "product_id": raw["product_id"],
        "content_type": raw["content_type"],
        "qa_status": "passed",
        "listing_eligible": True,
        "artifact_evidence_ids": ["evd-artifact-asset-1"],
        "input_sha256": execution["input_sha256"],
        "template_id": execution["template_id"],
        "encoder_version": None,
        "latency_ms": None,
        "cost": execution["cost"],
        "created_at": (AT - timedelta(minutes=5)).isoformat(),
        "external_marketplace_write": False,
    }
    manifest_sha = ScopedContentMediaFactoryWorkspace._hash(payload)
    payload["manifest_sha256"] = manifest_sha
    manifest = {
        "id": "manifest-1",
        "asset_id": raw["id"],
        "execution_id": execution["id"],
        "asset_state_sha256": (
            ScopedContentMediaFactoryWorkspace._hash(state)
        ),
        "manifest_sha256": manifest_sha,
        "payload": payload,
        "created_by": "reviewer-a",
        "created_at": payload["created_at"],
    }
    service, _, _ = workspace(
        content=ProductContent(
            product_projection([product_item(assets=[projected])])
        ),
        media=MediaSource(
            media_projection(
                assets=[raw],
                executions=[execution],
                events=events,
                manifests=[manifest],
            )
        ),
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    asset = result["product_groups"][0]["assets"][0]

    assert asset["stage"] == "delivery_ready"
    assert asset["readiness"]["qa_passed"] is True
    assert asset["readiness"]["delivery_manifest_ready"] is True
    assert asset["delivery_manifest"]["manifest_sha256"] == manifest_sha
    assert result["control_envelope"]["manifest_created"] is False
    assert result["external_write_allowed"] is False


def test_truncated_source_projection_blocks_without_payload():
    service, _, _ = workspace(
        media=MediaSource(media_projection(truncated=True))
    )

    result = service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )

    assert result["status"] == "blocked"
    assert result["product_groups"] == []
    assert "media_source_projection_truncated" in result["source_gaps"]


class FakeEvidence:
    def require_valid(self, _evidence_ids) -> None:
        return None


class FakeImageExecution:
    def queue(self, _asset_id: str, *, requested_by: str):
        return SimpleNamespace(status=ContentStatus.QUEUED)


def test_real_media_read_source_filters_asset_and_as_of():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRepository(engine)
    first_product = repository.add_product(
        Product("SKU-1", "Product one")
    )
    second_product = repository.add_product(
        Product("SKU-2", "Product two")
    )
    first_asset = repository.add_content_asset(
        ContentAsset(
            first_product.id,
            ContentType.IMAGE,
            "ru-RU",
            "OZON",
            {"template_id": "ozon-retouch-v1"},
            {},
            created_at=(AT - timedelta(days=1)).isoformat(),
        )
    )
    second_asset = repository.add_content_asset(
        ContentAsset(
            second_product.id,
            ContentType.IMAGE,
            "ru-RU",
            "OZON",
            {"template_id": "ozon-retouch-v1"},
            {},
            created_at=(AT - timedelta(days=1)).isoformat(),
        )
    )
    before = AT - timedelta(minutes=10)
    after = AT + timedelta(minutes=10)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                MediaExecutionRow(
                    id="execution-before",
                    asset_id=first_asset.id,
                    idempotency_key="before",
                    media_kind="image",
                    template_id="ozon-retouch-v1",
                    input_sha256="1" * 64,
                    status="queued",
                    attempt=1,
                    queued_by="operator-a",
                    queued_at=before,
                    lease_owner=None,
                    lease_expires_at=None,
                    started_at=None,
                    completed_at=None,
                    latency_ms=None,
                    cost_amount=Decimal("0"),
                    cost_currency="CNY",
                    outputs_json={},
                    error_code=None,
                    error_detail=None,
                ),
                MediaExecutionRow(
                    id="execution-after",
                    asset_id=first_asset.id,
                    idempotency_key="after",
                    media_kind="image",
                    template_id="ozon-retouch-v1",
                    input_sha256="2" * 64,
                    status="queued",
                    attempt=2,
                    queued_by="operator-a",
                    queued_at=after,
                    lease_owner=None,
                    lease_expires_at=None,
                    started_at=None,
                    completed_at=None,
                    latency_ms=None,
                    cost_amount=Decimal("0"),
                    cost_currency="CNY",
                    outputs_json={},
                    error_code=None,
                    error_detail=None,
                ),
                MediaExecutionRow(
                    id="execution-other",
                    asset_id=second_asset.id,
                    idempotency_key="other",
                    media_kind="image",
                    template_id="ozon-retouch-v1",
                    input_sha256="3" * 64,
                    status="queued",
                    attempt=1,
                    queued_by="operator-a",
                    queued_at=before,
                    lease_owner=None,
                    lease_expires_at=None,
                    started_at=None,
                    completed_at=None,
                    latency_ms=None,
                    cost_amount=Decimal("0"),
                    cost_currency="CNY",
                    outputs_json={},
                    error_code=None,
                    error_detail=None,
                ),
            ]
        )
        session.add(
            MediaExecutionEventRow(
                id="event-before",
                execution_id="execution-before",
                sequence=1,
                event_type="queued",
                from_status=None,
                to_status="queued",
                payload_json={},
                actor_id="operator-a",
                occurred_at=before,
            )
        )
        session.add(
            MediaDeliveryManifestRow(
                id="manifest-other",
                asset_id=second_asset.id,
                execution_id="execution-other",
                asset_state_sha256="4" * 64,
                manifest_sha256="5" * 64,
                payload_json={},
                created_by="reviewer-a",
                created_at=before,
            )
        )
    service = MediaWorkbenchService(
        engine=engine,
        repository=repository,
        evidence=FakeEvidence(),
        image_execution=FakeImageExecution(),
    )

    result = service.read_sources(
        asset_ids=[first_asset.id],
        as_of=AT,
    )

    assert [item["id"] for item in result["assets"]] == [
        first_asset.id
    ]
    assert [item["id"] for item in result["executions"]] == [
        "execution-before"
    ]
    assert [item["id"] for item in result["events"]] == [
        "event-before"
    ]
    assert result["manifests"] == []
    assert result["authorized_asset_ids"] == [first_asset.id]
    assert result["raw_read"] is True
