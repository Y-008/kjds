from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import ApprovalRow, Base, ProductRow
from apps.control_plane.warehouse_fulfillment import (
    WarehouseExecutionAuthorityService,
)

SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "warehouse_ref": "warehouse-cn-1",
    "scope_grant_authority_sha256": "a" * 64,
}
NOW = datetime.now(UTC) - timedelta(minutes=10)


@dataclass
class Evidence:
    id: str
    sha256: str
    metadata: dict


class EvidenceStore:
    def __init__(self, records):
        self.records = {record.id: record for record in records}

    def require_current(self, evidence_ids, *, as_of):
        for evidence_id in evidence_ids:
            record = self.records[evidence_id]
            if record.metadata.get("revoked") is True:
                raise ValueError("revoked")

    def get(self, evidence_id):
        return self.records[evidence_id]


class ScopedEvidence:
    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": "ready",
            "records": [
                {"evidence_id": evidence_id, "status": "ready"}
                for evidence_id in evidence_ids
            ],
        }


def principal():
    return Principal(
        actor_id="warehouse-operator",
        roles=frozenset({"operator"}),
        tenant_ref=SCOPE["tenant_ref"],
        store_refs=frozenset({SCOPE["store_ref"]}),
    )


def entity_scope():
    return {
        "status": "ready",
        "entity_ref": SCOPE["entity_ref"],
        "authority_sha256": SCOPE["scope_grant_authority_sha256"],
    }


def records(*, source_kind="authorized_warehouse_system", revoked=False):
    authorization = Evidence(
        id="evd-auth",
        sha256="1" * 64,
        metadata={
            "contract_id": "kjds-authorized-warehouse-adapter-v1",
            "status": "authorized",
            "revoked": revoked,
            "source_kind": source_kind,
            "adapter_id": "wms-export",
            "adapter_version": "1",
            **{
                key: SCOPE[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "warehouse_ref",
                )
            },
        },
    )
    source = Evidence(
        id="evd-event",
        sha256="2" * 64,
        metadata={
            "contract_id": "kjds-formal-warehouse-event-evidence-v1",
            "source_kind": source_kind,
            "adapter_id": "wms-export",
            "adapter_version": "1",
            "authorization_evidence_id": authorization.id,
            "immutable": True,
            "revoked": False,
            "source_event_ref": "source-1",
            "aggregate_ref": "aggregate-1",
            "event_type": "wave_created",
            "order_external_id": "order-1",
            "product_id": "prd-1",
            "sku": "SKU-1",
            "event_payload_sha256": "3" * 64,
            **{
                key: SCOPE[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                    "warehouse_ref",
                )
            },
        },
    )
    return [authorization, source]


def service(*, source_kind="authorized_warehouse_system", revoked=False):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id="prd-1",
                sku="SKU-1",
                name="Product",
                market="RU",
                channel="OZON",
                status="active",
                created_at=NOW,
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
                scope_grant_authority_sha256=SCOPE[
                    "scope_grant_authority_sha256"
                ],
                scope_as_of=NOW,
                created_by="operator",
            )
        )
    evidence = EvidenceStore(
        records(source_kind=source_kind, revoked=revoked)
    )
    return (
        WarehouseExecutionAuthorityService(
            engine=engine,
            evidence=evidence,
            scoped_evidence=ScopedEvidence(),
        ),
        engine,
    )


def configure_governed(
    authority,
    engine,
    *,
    decided_by="warehouse-approver",
    outcome="succeeded",
    expires_at=None,
    source_event_ref="source-1",
):
    action_id = "warehouse_carrier_handoff"
    approval_id = "apr-warehouse-1"
    permit_id = "evd-permit-1"
    readback_id = "evd-readback-1"
    kill_id = "evd-kill-1"
    compensation_id = "evd-compensation-1"
    scope_metadata = {
        key: SCOPE[key]
        for key in (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
        )
    }
    authority.evidence.records["evd-event"].metadata.update(
        {
            "event_type": "carrier_handoff_readback",
            "source_event_ref": source_event_ref,
            "governed_action_id": action_id,
            "approval_id": approval_id,
            "permit_evidence_id": permit_id,
            "readback_evidence_id": readback_id,
            "kill_switch_evidence_id": kill_id,
            "compensation_evidence_id": compensation_id,
        }
    )
    authority.evidence.records.update(
        {
            permit_id: Evidence(
                id=permit_id,
                sha256="4" * 64,
                metadata={
                    "contract_id": "kjds-warehouse-one-time-permit-v1",
                    "status": "issued",
                    "revoked": False,
                    "single_use": True,
                    "approval_id": approval_id,
                    "action_id": action_id,
                    "event_type": "carrier_handoff_readback",
                    "source_event_ref": source_event_ref,
                    "order_external_id": "order-1",
                    "issued_at": (NOW - timedelta(minutes=1)).isoformat(),
                    "expires_at": (
                        expires_at
                        or NOW + timedelta(minutes=2)
                    ).isoformat(),
                    **scope_metadata,
                },
            ),
            readback_id: Evidence(
                id=readback_id,
                sha256="5" * 64,
                metadata={
                    "contract_id": (
                        "kjds-warehouse-execution-readback-v1"
                    ),
                    "outcome": outcome,
                    "mutation_applied": True,
                    "approval_id": approval_id,
                    "permit_evidence_id": permit_id,
                    "action_id": action_id,
                    "event_type": "carrier_handoff_readback",
                    "source_event_ref": source_event_ref,
                    "order_external_id": "order-1",
                    "adapter_id": "wms-export",
                    "adapter_version": "1",
                    "remote_operation_id": "handoff-remote-1",
                    "resulting_state_sha256": "6" * 64,
                    "readback_at": NOW.isoformat(),
                    **scope_metadata,
                },
            ),
            kill_id: Evidence(
                id=kill_id,
                sha256="7" * 64,
                metadata={
                    "purpose": "kill_switch_release",
                    "status": "released",
                    "event_type": "carrier_handoff_readback",
                    "action_id": action_id,
                    "approval_id": approval_id,
                    "permit_evidence_id": permit_id,
                    "readback_evidence_id": readback_id,
                    "source_event_ref": source_event_ref,
                    "order_external_id": "order-1",
                    "owner": "risk-owner",
                    **scope_metadata,
                },
            ),
            compensation_id: Evidence(
                id=compensation_id,
                sha256="8" * 64,
                metadata={
                    "purpose": "warehouse_compensation_plan",
                    "status": "ready",
                    "event_type": "carrier_handoff_readback",
                    "action_id": action_id,
                    "approval_id": approval_id,
                    "permit_evidence_id": permit_id,
                    "readback_evidence_id": readback_id,
                    "source_event_ref": source_event_ref,
                    "order_external_id": "order-1",
                    "owner": "warehouse-owner",
                    **scope_metadata,
                },
            ),
        }
    )
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRow(
                id=approval_id,
                action=action_id,
                resource_type="warehouse_order",
                resource_id="order-1",
                requested_by="warehouse-requester",
                payload_json={
                    **scope_metadata,
                    "scope_grant_authority_sha256": SCOPE[
                        "scope_grant_authority_sha256"
                    ],
                    "order_external_id": "order-1",
                    "event_type": "carrier_handoff_readback",
                    "source_event_ref": source_event_ref,
                },
                status="approved",
                decided_by=decided_by,
                decision_reason="independent warehouse approval",
                created_at=NOW - timedelta(minutes=2),
            )
        )
    return {
        "approval_id": approval_id,
        "command_id": permit_id,
        "receipt_id": readback_id,
        "kill_switch_evidence_id": kill_id,
        "compensation_evidence_id": compensation_id,
    }


def append(authority, **values):
    return authority.append_event(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref=SCOPE["store_ref"],
        warehouse_ref=SCOPE["warehouse_ref"],
        source_event_ref="source-1",
        aggregate_ref="aggregate-1",
        sequence=1,
        event_type="wave_created",
        order_external_id="order-1",
        product_id="prd-1",
        sku="SKU-1",
        evidence_id="evd-event",
        effective_at=NOW.isoformat(),
        as_of=(NOW + timedelta(minutes=1)).isoformat(),
        **values,
    )


def test_authorized_event_is_append_only_idempotent_and_exact_scope():
    authority, _engine = service()
    first = append(authority)
    second = append(authority)
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    source = authority.read_scoped_sources(
        tenant_ref=SCOPE["tenant_ref"],
        entity_ref=SCOPE["entity_ref"],
        store_ref=SCOPE["store_ref"],
        warehouse_ref=SCOPE["warehouse_ref"],
        scope_grant_authority_sha256=SCOPE[
            "scope_grant_authority_sha256"
        ],
        as_of=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )
    assert source["status"] == "ready"
    assert len(source["events"]) == 1
    assert source["control_envelope"]["legacy_warehouse_rows_read"] == 0


@pytest.mark.parametrize(
    "source_kind",
    ["private_erp_endpoint", "cookie_session", "internal_token"],
)
def test_private_or_fictional_source_authority_is_rejected(source_kind):
    authority, _engine = service(source_kind=source_kind)
    with pytest.raises(
        ValueError,
        match="Evidence authority binding is invalid",
    ):
        append(authority)


def test_revoked_authorization_fails_closed():
    authority, _engine = service(revoked=True)
    with pytest.raises(ValueError, match="revoked"):
        append(authority)


def test_sequence_conflict_and_payload_drift_do_not_fallback():
    authority, _engine = service()
    append(authority)
    with pytest.raises(ValueError, match="conflicts with immutable"):
        append(authority, location_ref="different-zone")


def test_governed_event_cannot_self_report_without_all_controls():
    authority, _engine = service()
    authority.evidence.records["evd-event"].metadata.update(
        {
            "event_type": "carrier_handoff_readback",
        }
    )
    with pytest.raises(
        ValueError,
        match="requires Approval, one-time Permit",
    ):
        authority.append_event(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref=SCOPE["store_ref"],
            warehouse_ref=SCOPE["warehouse_ref"],
            source_event_ref="source-1",
            aggregate_ref="aggregate-1",
            sequence=1,
            event_type="carrier_handoff_readback",
            order_external_id="order-1",
            product_id="prd-1",
            sku="SKU-1",
            evidence_id="evd-event",
            effective_at=NOW.isoformat(),
            as_of=(NOW + timedelta(minutes=1)).isoformat(),
        )


def test_governed_readback_requires_independent_authorities_and_is_idempotent():
    authority, engine = service()
    governance = configure_governed(authority, engine)
    first = authority.append_event(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref=SCOPE["store_ref"],
        warehouse_ref=SCOPE["warehouse_ref"],
        source_event_ref="source-1",
        aggregate_ref="aggregate-1",
        sequence=1,
        event_type="carrier_handoff_readback",
        order_external_id="order-1",
        product_id="prd-1",
        sku="SKU-1",
        evidence_id="evd-event",
        effective_at=NOW.isoformat(),
        as_of=(NOW + timedelta(minutes=1)).isoformat(),
        **governance,
    )
    second = authority.append_event(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref=SCOPE["store_ref"],
        warehouse_ref=SCOPE["warehouse_ref"],
        source_event_ref="source-1",
        aggregate_ref="aggregate-1",
        sequence=1,
        event_type="carrier_handoff_readback",
        order_external_id="order-1",
        product_id="prd-1",
        sku="SKU-1",
        evidence_id="evd-event",
        effective_at=NOW.isoformat(),
        as_of=(NOW + timedelta(minutes=1)).isoformat(),
        **governance,
    )
    assert first["idempotent"] is False
    assert second["idempotent"] is True


def test_governed_readback_rejects_self_approval():
    authority, engine = service()
    governance = configure_governed(
        authority,
        engine,
        decided_by="warehouse-requester",
    )
    with pytest.raises(ValueError, match="independent Approval"):
        authority.append_event(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref=SCOPE["store_ref"],
            warehouse_ref=SCOPE["warehouse_ref"],
            source_event_ref="source-1",
            aggregate_ref="aggregate-1",
            sequence=1,
            event_type="carrier_handoff_readback",
            order_external_id="order-1",
            product_id="prd-1",
            sku="SKU-1",
            evidence_id="evd-event",
            effective_at=NOW.isoformat(),
            as_of=(NOW + timedelta(minutes=1)).isoformat(),
            **governance,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("permit", "expired"), "one-time Permit"),
        (("readback", "uncertain"), "successful Readback"),
        (("readback", "fictional-adapter"), "successful Readback"),
    ],
)
def test_governed_readback_rejects_expiry_unknown_or_fictional_authority(
    mutation,
    message,
):
    authority, engine = service()
    governance = configure_governed(authority, engine)
    kind, value = mutation
    if kind == "permit":
        authority.evidence.records["evd-permit-1"].metadata[
            "expires_at"
        ] = (NOW - timedelta(seconds=1)).isoformat()
    elif value == "fictional-adapter":
        authority.evidence.records["evd-readback-1"].metadata[
            "adapter_id"
        ] = value
    else:
        authority.evidence.records["evd-readback-1"].metadata[
            "outcome"
        ] = value
    with pytest.raises(ValueError, match=message):
        authority.append_event(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref=SCOPE["store_ref"],
            warehouse_ref=SCOPE["warehouse_ref"],
            source_event_ref="source-1",
            aggregate_ref="aggregate-1",
            sequence=1,
            event_type="carrier_handoff_readback",
            order_external_id="order-1",
            product_id="prd-1",
            sku="SKU-1",
            evidence_id="evd-event",
            effective_at=NOW.isoformat(),
            as_of=(NOW + timedelta(minutes=1)).isoformat(),
            **governance,
        )


def test_governed_readback_rejects_permit_or_receipt_reuse():
    authority, engine = service()
    governance = configure_governed(authority, engine)
    authority.append_event(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref=SCOPE["store_ref"],
        warehouse_ref=SCOPE["warehouse_ref"],
        source_event_ref="source-1",
        aggregate_ref="aggregate-1",
        sequence=1,
        event_type="carrier_handoff_readback",
        order_external_id="order-1",
        product_id="prd-1",
        sku="SKU-1",
        evidence_id="evd-event",
        effective_at=NOW.isoformat(),
        as_of=(NOW + timedelta(minutes=1)).isoformat(),
        **governance,
    )
    authority.evidence.records["evd-event"].metadata[
        "source_event_ref"
    ] = "source-2"
    authority.evidence.records["evd-event"].metadata[
        "aggregate_ref"
    ] = "aggregate-2"
    for evidence_id in (
        "evd-permit-1",
        "evd-readback-1",
        "evd-kill-1",
        "evd-compensation-1",
    ):
        authority.evidence.records[evidence_id].metadata[
            "source_event_ref"
        ] = "source-2"
    with Session(engine) as session, session.begin():
        approval = session.get(ApprovalRow, "apr-warehouse-1")
        approval.payload_json = {
            **approval.payload_json,
            "source_event_ref": "source-2",
        }
    with pytest.raises(ValueError, match="already consumed"):
        authority.append_event(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref=SCOPE["store_ref"],
            warehouse_ref=SCOPE["warehouse_ref"],
            source_event_ref="source-2",
            aggregate_ref="aggregate-2",
            sequence=1,
            event_type="carrier_handoff_readback",
            order_external_id="order-1",
            product_id="prd-1",
            sku="SKU-1",
            evidence_id="evd-event",
            effective_at=NOW.isoformat(),
            as_of=(NOW + timedelta(minutes=1)).isoformat(),
            **governance,
        )
