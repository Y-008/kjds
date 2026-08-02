import base64
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    ScopedChannelCredentialClientFactory,
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrantAuthority,
    _ManagedCredentialLeaseRecord,
)
from apps.control_plane.channel_credential_grants import (
    SqlWorkerCredentialGrantStore,
    WorkerCredentialGrantRow,
)
from apps.control_plane.domain import Product
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.execution_plans import ExecutionPlanService
from apps.control_plane.limited_executor import LimitedExecutorService
from apps.control_plane.pilot_readiness import (
    PILOT_CONTROLS,
    PilotReadinessService,
    ReadOnlyPilotRow,
)
from apps.control_plane.pilot_runs import PilotRunService, ReadOnlyPilotRunRow
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.read_only_claims import ReadOnlyClaimRow
from apps.control_plane.readiness import LISTING_EXECUTION_READINESS_KEYS
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.runtime import _build_worker_grant_issuer
from apps.control_plane.scoped_worker_credential_grants import (
    ADAPTER_BY_CAPABILITY,
    CanonicalLeaseBinding,
    CanonicalWorkerCredentialGrantIssuer,
    UnboundCanonicalLeaseBindingSource,
)
from apps.control_plane.security import KillSwitchService
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import ListingDraft, listing_approval_payload
from apps.control_plane.sql_repository import ApprovalRow, Base

NOW = datetime(2026, 8, 1, 8, tzinfo=UTC)
SCOPE_AUTHORITY_SHA256 = "e" * 64
assert CausalPolicyRow.__tablename__ == "causal_policies"
assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"


def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def lease_record(*, capability="catalog.read", adapter_id="ozon-seller-api-read"):
    now = datetime.now(UTC)
    return _ManagedCredentialLeaseRecord(
        lease_id="lease-1",
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        platform="ozon",
        account_ref="account-1",
        adapter_id=adapter_id,
        adapter_version="v1",
        capabilities=frozenset({capability}),
        secret_reference_sha256="c" * 64,
        credential_fingerprint_sha256="d" * 64,
        issued_at=now - timedelta(minutes=30),
        expires_at=now + timedelta(hours=2),
        revoked_at=None,
        client_id="client-1",
        api_key="api-key-1",
        provider_readback_sha256="f" * 64,
        provider_readback_verified_at=now - timedelta(seconds=30),
        external_verifier_observation_sha256="9" * 64,
        external_verifier_verified_at=now - timedelta(seconds=30),
    )


class MemoryLeaseStore:
    def __init__(self, record):
        self.record = record

    def get(self, lease_id):
        return self.record if self.record and self.record.lease_id == lease_id else None


class BindingSource:
    def __init__(self, binding, *, drift=None, error=None):
        self.binding = binding
        self.drift = drift
        self.error = error
        self.calls = []

    def resolve(self, **values):
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return replace(self.binding, **self.drift) if self.drift else self.binding


def binding(
    *,
    tenant_ref="tenant-1",
    entity_ref="entity-1",
    store_ref="store-1",
    account_ref="account-1",
    adapter_id="ozon-seller-api-read",
    adapter_version="v1",
    capability="catalog.read",
    epoch=1,
    handle=None,
    expires_at=None,
    secret_reference_sha256="c" * 64,
    credential_fingerprint_sha256="d" * 64,
) -> CanonicalLeaseBinding:
    return CanonicalLeaseBinding(
        tenant_ref=tenant_ref,
        entity_ref=entity_ref,
        store_ref=store_ref,
        platform="ozon",
        account_ref=account_ref,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        required_capability=capability,
        authorization_epoch=epoch,
        lease_handle=handle
        or ManagedCredentialLeaseHandle(
            issuer="kjds-managed-store",
            key_id="lease-kid-1",
            lease_id="lease-1",
            envelope_sha256="a" * 64,
            signature="b" * 64,
        ),
        secret_reference_sha256=secret_reference_sha256,
        credential_fingerprint_sha256=credential_fingerprint_sha256,
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=2),
    )


def authority_and_issuer(engine, *, lease_source):
    issuer = CanonicalWorkerCredentialGrantIssuer(
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_source=lease_source,
    )
    return issuer


def grant_rows(engine):
    with Session(engine) as session:
        return list(session.scalars(select(WorkerCredentialGrantRow)))


class Incidents:
    def list(self):
        return [
            {
                "id": "drill-1",
                "mode": "drill",
                "status": "closed",
                "updated_at": "2026-07-17T00:00:00+00:00",
            }
        ]


class Switch:
    def current(self):
        return SimpleNamespace(engaged=False)


def native_pilot(engine, *, operation="ozon.product.read"):
    evidence = EvidenceService(engine)
    source = evidence.capture(
        content=b"native pilot evidence",
        filename="pilot.txt",
        content_type="text/plain",
        source="test",
        source_ref="scoped-worker-grant",
        grade=EvidenceGrade.A,
        effective_at="2026-08-01T00:00:00+00:00",
        effective_until=None,
        created_by="owner",
    )
    pilots = PilotReadinessService(
        engine=engine,
        evidence=evidence,
        incidents=Incidents(),
        kill_switch=Switch(),
    )
    pilot = pilots.create(
        idempotency_key="scoped-pilot",
        platform="ozon",
        account_alias="ozon-main",
        allowed_operations=[operation],
        max_daily_requests=5,
        max_targets=2,
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-03T00:00:00+00:00",
        evidence_ids=[source.id],
        requested_by="owner",
        scope_authority={
            "tenant_ref": "tenant-1",
            "entity_ref": "entity-1",
            "store_ref": "store-1",
            "scope_grant_authority_sha256": SCOPE_AUTHORITY_SHA256,
            "scope_evidence_authority_sha256": "9" * 64,
            "scope_as_of": "2026-08-01T00:00:00+00:00",
        },
    )
    for control in PILOT_CONTROLS:
        pilots.attest(
            pilot["id"],
            control=control,
            passed=True,
            notes="verified",
            evidence_ids=[source.id],
            attested_by="owner",
        )
    pilots.submit_review(pilot["id"], actor_id="owner", as_of="2026-08-01T01:00:00+00:00")
    pilots.review(pilot["id"], accepted=True, rationale="independent", actor_id="reviewer")
    pilots.activate(pilot["id"], actor_id="admin", as_of="2026-08-01T01:00:00+00:00")
    return pilots, pilot


def test_pilot_run_issuer_derives_and_signs_read_grant_from_canonical_scope():
    engine = database()
    issuer = authority_and_issuer(
        engine,
        lease_source=BindingSource(binding()),
    )
    pilots, pilot = native_pilot(engine)
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=EvidenceService(engine),
        credential_grant_issuer=issuer,
    )

    started = runs.start(
        pilot["id"],
        idempotency_key="granted-run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-08-01T02:00:00+00:00",
    )

    grant = started["credential_grant"]
    assert started["credential_grant_bound"] is True
    assert grant["contract_id"] == "kjds-channel-account-worker-credential-grant-v1"
    assert grant["required_capability"] == "catalog.read"
    assert grant["issuer"] == "kjds-control-plane"
    assert grant["key_id"] == "grant-kid-1"
    assert set(grant) == {
        "contract_id",
        "issuer",
        "key_id",
        "grant_id",
        "required_capability",
        "envelope_sha256",
        "signature",
    }
    rows = grant_rows(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row.grant_id == grant["grant_id"]
    assert (row.tenant_ref, row.entity_ref, row.store_ref) == (
        "tenant-1",
        "entity-1",
        "store-1",
    )
    assert row.adapter_id == "ozon-seller-api-read"
    assert row.required_capability == "catalog.read"
    assert row.purpose == "pilot-read"
    assert row.authorization_epoch == 1
    assert row.secret_reference_sha256 == "c" * 64
    assert row.credential_fingerprint_sha256 == "d" * 64
    assert row.consumed_at is None

    replay = runs.start(
        pilot["id"],
        idempotency_key="granted-run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of="2026-08-01T02:00:00+00:00",
    )
    assert replay["idempotency_replay"] is True
    assert replay["credential_grant"] is None
    assert len(grant_rows(engine)) == 1


def test_pilot_run_issuer_derives_finance_read_grant():
    engine = database()
    issuer = authority_and_issuer(
        engine,
        lease_source=BindingSource(
            binding(capability="finance.read", adapter_id="ozon-seller-api-read")
        ),
    )
    pilots, pilot = native_pilot(engine, operation="ozon.finance.read")
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=EvidenceService(engine),
        credential_grant_issuer=issuer,
    )

    started = runs.start(
        pilot["id"],
        idempotency_key="finance-grant-run-1",
        operation="ozon.finance.read",
        target_ref="c" * 64,
        worker_id="reader-1",
        as_of="2026-08-01T02:00:00+00:00",
    )
    assert started["credential_grant"]["required_capability"] == "finance.read"
    assert grant_rows(engine)[0].purpose == "pilot-finance-read"


def test_legacy_pilot_run_never_derives_grant():
    engine = database()
    issuer = authority_and_issuer(
        engine,
        lease_source=BindingSource(binding()),
    )
    evidence = EvidenceService(engine)
    source = evidence.capture(
        content=b"legacy pilot evidence",
        filename="pilot.txt",
        content_type="text/plain",
        source="test",
        source_ref="legacy-pilot",
        grade=EvidenceGrade.A,
        effective_at="2026-08-01T00:00:00+00:00",
        effective_until=None,
        created_by="owner",
    )
    pilots = PilotReadinessService(
        engine=engine,
        evidence=evidence,
        incidents=Incidents(),
        kill_switch=Switch(),
    )
    pilot = pilots.create(
        idempotency_key="legacy-pilot",
        platform="ozon",
        account_alias="ozon-legacy",
        allowed_operations=["ozon.product.read"],
        max_daily_requests=5,
        max_targets=2,
        starts_at="2026-08-01T00:00:00+00:00",
        ends_at="2026-08-03T00:00:00+00:00",
        evidence_ids=[source.id],
        requested_by="owner",
    )
    for control in PILOT_CONTROLS:
        pilots.attest(
            pilot["id"],
            control=control,
            passed=True,
            notes="verified",
            evidence_ids=[source.id],
            attested_by="owner",
        )
    pilots.submit_review(pilot["id"], actor_id="owner", as_of="2026-08-01T01:00:00+00:00")
    pilots.review(pilot["id"], accepted=True, rationale="independent", actor_id="reviewer")
    pilots.activate(pilot["id"], actor_id="admin", as_of="2026-08-01T01:00:00+00:00")
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=evidence,
        credential_grant_issuer=issuer,
    )

    started = runs.start(
        pilot["id"],
        idempotency_key="legacy-run-1",
        operation="ozon.product.read",
        target_ref="offer-legacy",
        worker_id="reader-1",
        as_of="2026-08-01T02:00:00+00:00",
    )
    assert started["execution_granted"] is True
    assert started["credential_grant"] is None
    assert started["credential_grant_bound"] is False
    assert grant_rows(engine) == []


def test_unbound_lease_source_fails_closed_with_zero_grant_rows():
    engine = database()
    issuer = authority_and_issuer(
        engine,
        lease_source=UnboundCanonicalLeaseBindingSource(),
    )
    pilots, pilot = native_pilot(engine)
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=EvidenceService(engine),
        credential_grant_issuer=issuer,
    )

    with pytest.raises(PermissionError, match="not bound"):
        runs.start(
            pilot["id"],
            idempotency_key="unbound-run-1",
            operation="ozon.product.read",
            target_ref="offer-1",
            worker_id="reader-1",
            as_of="2026-08-01T02:00:00+00:00",
        )
    assert grant_rows(engine) == []


def test_drifted_lease_binding_never_signs_grant():
    engine = database()
    issuer = authority_and_issuer(
        engine,
        lease_source=BindingSource(
            binding(),
            drift={"store_ref": "other-store"},
        ),
    )
    pilots, pilot = native_pilot(engine)
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=EvidenceService(engine),
        credential_grant_issuer=issuer,
    )

    with pytest.raises(PermissionError, match="exact-scope binding"):
        runs.start(
            pilot["id"],
            idempotency_key="drifted-run-1",
            operation="ozon.product.read",
            target_ref="offer-1",
            worker_id="reader-1",
            as_of="2026-08-01T02:00:00+00:00",
        )
    assert grant_rows(engine) == []


def test_issued_grant_round_trips_through_scoped_factory_and_consumes_once():
    engine = database()
    record = lease_record()
    record = replace(
        record,
        credential_fingerprint_sha256=(
            SignedManagedCredentialLeaseResolver.credential_fingerprint(
                client_id=record.client_id,
                api_key=record.api_key,
                platform=record.platform,
                account_ref=record.account_ref,
            )
        ),
    )
    resolver = SignedManagedCredentialLeaseResolver(
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
        signing_key=b"h" * 32,
        store=MemoryLeaseStore(record),
    )
    handle = resolver.sign_authoritative_record(record)
    binding_value = binding(
        handle=handle,
        secret_reference_sha256=record.secret_reference_sha256,
        credential_fingerprint_sha256=record.credential_fingerprint_sha256,
    )
    issuer = CanonicalWorkerCredentialGrantIssuer(
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_source=BindingSource(binding_value),
    )
    pilots, pilot = native_pilot(engine)
    runs = PilotRunService(
        engine=engine,
        pilots=pilots,
        evidence=EvidenceService(engine),
        credential_grant_issuer=issuer,
    )
    started = runs.start(
        pilot["id"],
        idempotency_key="roundtrip-run-1",
        operation="ozon.product.read",
        target_ref="offer-1",
        worker_id="reader-1",
        as_of=datetime.now(UTC).isoformat(),
    )
    grant = started["credential_grant"]

    opens = []

    @contextmanager
    def builder(material):
        opens.append(material)
        try:
            yield object()
        finally:
            pass

    with Session(engine) as session:
        authority = SignedWorkerCredentialGrantAuthority(
            issuer="kjds-control-plane",
            key_id="grant-kid-1",
            signing_key=b"g" * 32,
            store=SqlWorkerCredentialGrantStore(session),
        )
        factory = ScopedChannelCredentialClientFactory(
            grant_authority=authority,
            grant_store=SqlWorkerCredentialGrantStore(session),
            lease_resolver=resolver,
            client_builder=builder,
        )
        with factory.open(grant=grant, as_of=datetime.now(UTC)):
            assert len(opens) == 1
        session.commit()
        assert opens[0].client_id == "client-1"
        assert opens[0].api_key == "api-key-1"

    with Session(engine) as session:
        consumed = session.get(WorkerCredentialGrantRow, grant["grant_id"])
        assert consumed is not None and consumed.consumed_at is not None
    with Session(engine) as session:
        authority = SignedWorkerCredentialGrantAuthority(
            issuer="kjds-control-plane",
            key_id="grant-kid-1",
            signing_key=b"g" * 32,
            store=SqlWorkerCredentialGrantStore(session),
        )
        factory = ScopedChannelCredentialClientFactory(
            grant_authority=authority,
            grant_store=SqlWorkerCredentialGrantStore(session),
            lease_resolver=resolver,
            client_builder=builder,
        )
        with pytest.raises(PermissionError, match="consumed"):
            factory.open(grant=grant, as_of=datetime.now(UTC))
        assert len(opens) == 1


class ListingStore:
    def __init__(self, draft):
        self.draft = draft

    def get_listing_draft(self, draft_id):
        if draft_id != self.draft.id:
            raise KeyError(draft_id)
        return self.draft


class ListingSourcing:
    def __init__(self, draft):
        self.store = ListingStore(draft)

    def verify_listing_approval(self, *, draft_id, approval_id, approval_payload):
        draft = self.store.get_listing_draft(draft_id)
        if draft.approval_id != approval_id or approval_payload["draft_id"] != draft.id:
            raise ValueError("Listing approval does not match the stored draft")
        return draft


class NoCausalSource:
    def get_handoff(self, _handoff_id):
        raise AssertionError("Listing execution must not resolve a causal handoff")


def bundle(info, attributes):
    responses = []
    for path, body in (
        ("/v3/product/info/list", info),
        ("/v4/product/info/attributes", attributes),
    ):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        responses.append(
            {
                "path": path,
                "status_code": 200,
                "headers": {},
                "body_sha256": hashlib.sha256(encoded).hexdigest(),
                "body_base64": base64.b64encode(encoded).decode(),
            }
        )
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-product-read-v1",
            "responses": responses,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def scoped_listing_fixture(engine):
    evidence = EvidenceService(engine)
    repo = InMemoryRepository()
    product = Product(sku="ozon-offer-001", name="Storage box")
    repo.add_product(product)
    commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
    draft = ListingDraft(
        product_id=product.id,
        offer_id="off_internal_supplier_key",
        scenario_id="scenario-1",
        target_platform="OZON",
        listing_data={
            "title": "Контейнер для хранения",
            "description": "Verified facts only",
            "category_id": "123",
            "attributes": [{"complex_id": 0, "id": 1, "values": [{"value": "white"}]}],
            "images": ["https://cdn.example.test/approved.jpg"],
            "content_asset_ids": ["asset-1"],
        },
        requested_by="listing-requester",
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        scope_grant_authority_sha256=SCOPE_AUTHORITY_SHA256,
        scoped_product_content_sha256="7" * 64,
        scope_as_of="2026-08-01T00:00:00+00:00",
    )
    scenario = type(
        "Scenario",
        (),
        {
            "cm3_cny": Decimal("10"),
            "cm3_rate": Decimal("0.1"),
            "cost_complete": True,
            "cost_breakdown": lambda self: {},
            "cost_evidence": {},
            "cost_states": {},
            "template_id": "profit-v1",
            "missing_cost_evidence": [],
            "unknown_costs": [],
            "evidence": [],
        },
    )()
    source_approval = commerce.request_approval(
        action="listing.publish",
        resource_type="listing_draft",
        resource_id=draft.id,
        requested_by=draft.requested_by,
        payload=listing_approval_payload(draft, scenario),
    )
    commerce.decide_approval(
        source_approval.id,
        approved=True,
        decided_by="independent-listing-reviewer",
        reason="Snapshot independently reviewed",
    )
    draft.approval_id = source_approval.id
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRow(
                id=source_approval.id,
                action=source_approval.action,
                resource_type=source_approval.resource_type,
                resource_id=source_approval.resource_id,
                requested_by=source_approval.requested_by,
                payload_json=source_approval.payload,
                status=source_approval.status.value,
                decided_by=source_approval.decided_by,
                decision_reason=source_approval.decision_reason,
                created_at=NOW,
            )
        )
    before_info = {"items": [{"offer_id": product.sku, "version": 1}]}
    rollback_item = {
        "offer_id": product.sku,
        "name": "Prior title",
        "description": "Prior description",
        "description_category_id": 123,
        "attributes": [{"complex_id": 0, "id": 1, "values": [{"value": "prior"}]}],
        "images": ["https://cdn.example.test/prior.jpg"],
    }
    before_attributes = {"result": [rollback_item]}
    before_state = {
        "contract_version": "ozon-product-read-v1",
        "offer_id": product.sku,
        "info": before_info,
        "attributes": before_attributes,
    }
    state_hash = ExecutionPlanService._hash(before_state)
    raw = bundle(before_info, before_attributes)
    raw_record = evidence.capture(
        content=raw,
        filename="before.json",
        content_type="application/json",
        source="ozon-isolated-read-worker",
        source_ref="run-write-grant",
        grade=EvidenceGrade.A,
        effective_at="2026-08-01T00:00:00+00:00",
        effective_until=None,
        created_by="ozon-read-worker",
        metadata={
            "raw_response_stored": True,
            "response_sha256": hashlib.sha256(raw).hexdigest(),
        },
    )
    evidence.link(
        evidence_id=raw_record.id,
        target_type="read_only_pilot_run",
        target_id="run-write-grant",
        relationship="raw_response",
        created_by="ozon-read-worker",
    )
    summary_record = evidence.capture(
        content=b'{"outcome":"succeeded","raw_response_stored":true}',
        filename="summary.json",
        content_type="application/json",
        source="ozon-isolated-read-worker",
        source_ref="run-write-grant",
        grade=EvidenceGrade.B,
        effective_at="2026-08-01T00:00:00+00:00",
        effective_until=None,
        created_by="ozon-read-worker",
        metadata={"raw_response_evidence_id": raw_record.id},
    )
    with Session(engine) as session, session.begin():
        session.add(
            ReadOnlyPilotRow(
                id="pilot-write-grant",
                idempotency_key="pilot-write-grant",
                platform="ozon",
                account_alias="ozon-main",
                allowed_operations_json=["ozon.product.read"],
                max_daily_requests=1,
                max_targets=1,
                starts_at=NOW,
                ends_at=NOW,
                evidence_json=[raw_record.id],
                status="active",
                requested_by="owner",
                reviewed_by="reviewer",
                review_rationale="approved",
                activated_by="admin",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ReadOnlyPilotRunRow(
                id="run-write-grant",
                idempotency_key="run-write-grant",
                request_hash="a" * 64,
                pilot_id="pilot-write-grant",
                operation="ozon.product.read",
                target_hash=hashlib.sha256(product.sku.encode()).hexdigest(),
                worker_id="ozon-read-worker",
                request_id="req-1",
                trace_id="trace-1",
                status="completed",
                outcome="succeeded",
                response_sha256=raw_record.sha256,
                response_byte_size=len(raw),
                record_count=2,
                summary_json={
                    "contract_version": "ozon-product-read-v1",
                    "state_sha256": state_hash,
                    "info_item_count": 1,
                    "attribute_item_count": 1,
                },
                error_code=None,
                evidence_id=summary_record.id,
                started_at=NOW,
                lease_expires_at=NOW,
                completed_at=NOW,
            )
        )
        session.add(
            ReadOnlyClaimRow(
                id="claim-write-grant",
                idempotency_key="claim-write-grant",
                request_hash="b" * 64,
                run_id="run-write-grant",
                claim_type="product_attribute",
                payload_json={"target_verified": True},
                payload_hash="c" * 64,
                source_state_sha256=state_hash,
                effective_at=NOW,
                evidence_id=summary_record.id,
                status="accepted",
                proposed_by="reader",
                reviewed_by="claim-reviewer",
                decision="accepted",
                rationale="Target and state accepted",
                created_at=NOW,
                reviewed_at=NOW,
            )
        )

    def listing_readiness(context):
        identity_matches = context.executor_identity_ref in {None, "ozon-worker"}
        return {
            key: {
                "ready": identity_matches if key == "ozon.execution_identity" else True,
                "evidence_ids": [raw_record.id],
                "blocking_reasons": (
                    []
                    if key != "ozon.execution_identity" or identity_matches
                    else ["OZON_EXECUTION_IDENTITY_MISMATCH"]
                ),
            }
            for key in LISTING_EXECUTION_READINESS_KEYS
        }

    service = ExecutionPlanService(
        engine=engine,
        policy_shadow=NoCausalSource(),
        policies=None,
        evidence=evidence,
        commerce=commerce,
        sourcing=ListingSourcing(draft),
        repository=repo,
        readiness_provider=listing_readiness,
    )
    return (
        evidence,
        draft,
        product,
        state_hash,
        raw_record,
        summary_record,
        service,
    )


def test_begin_write_attempt_derives_catalog_write_grant_in_same_transaction():
    engine = database()
    (
        evidence,
        draft,
        product,
        state_hash,
        _raw_record,
        summary_record,
        service,
    ) = scoped_listing_fixture(engine)
    plan = service.create_from_approved_listing(
        draft.id,
        idempotency_key="write-grant-plan-1",
        precondition_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        created_by="execution-planner",
        risk_limits={
            "max_quantity": "1",
            "max_daily_runs": "1",
            "max_expected_loss": "500",
        },
        risk_values={"quantity": "1", "expected_loss": "100"},
        risk_currency="CNY",
    )
    dry_run = service.dry_run(
        plan["id"],
        current_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        performed_by="dry-run-operator",
    )
    assert dry_run["passed"] is True
    service.commerce.decide_approval(
        plan["approval_id"],
        approved=True,
        decided_by="execution-approver",
        reason="Execution snapshot independently approved",
    )
    assert service.get(plan["id"])["ready_for_executor"] is True

    lease_source = BindingSource(
        binding(
            adapter_id=ADAPTER_BY_CAPABILITY["catalog.write"][0],
            capability="catalog.write",
        )
    )
    issuer = authority_and_issuer(engine, lease_source=lease_source)
    executor = LimitedExecutorService(
        engine=engine,
        execution_plans=service,
        evidence=evidence,
        kill_switch=KillSwitchService(engine),
        enabled=True,
        credential_grant_issuer=issuer,
    )
    command = executor.queue(plan["id"], queued_by="execution-operator")
    claimed = executor.claim(
        command["id"],
        current_state_hash=state_hash,
        worker_id="ozon-worker",
    )
    assert claimed["status"] == "claimed"

    started = executor.begin_write_attempt(
        command["id"],
        worker_id="ozon-worker",
    )
    grant = started["credential_grant"]
    assert started["credential_grant_bound"] is True
    assert grant["required_capability"] == "catalog.write"
    rows = grant_rows(engine)
    assert len(rows) == 1
    row = rows[0]
    assert (row.tenant_ref, row.entity_ref, row.store_ref) == (
        "tenant-1",
        "entity-1",
        "store-1",
    )
    assert row.adapter_id == "ozon-product-import-v3"
    assert row.purpose == "listing-write"
    assert row.consumed_at is None

    with pytest.raises(ValueError, match="not available"):
        executor.begin_write_attempt(command["id"], worker_id="ozon-worker")
    assert len(grant_rows(engine)) == 1


def test_begin_write_attempt_without_issuer_stays_unbound():
    engine = database()
    (
        evidence,
        draft,
        _product,
        state_hash,
        _raw_record,
        summary_record,
        service,
    ) = scoped_listing_fixture(engine)
    plan = service.create_from_approved_listing(
        draft.id,
        idempotency_key="write-grant-plan-2",
        precondition_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        created_by="execution-planner",
        risk_limits={
            "max_quantity": "1",
            "max_daily_runs": "1",
            "max_expected_loss": "500",
        },
        risk_values={"quantity": "1", "expected_loss": "100"},
        risk_currency="CNY",
    )
    service.dry_run(
        plan["id"],
        current_state_hash=state_hash,
        evidence_ids=[summary_record.id],
        performed_by="dry-run-operator",
    )
    service.commerce.decide_approval(
        plan["approval_id"],
        approved=True,
        decided_by="execution-approver",
        reason="Execution snapshot independently approved",
    )
    executor = LimitedExecutorService(
        engine=engine,
        execution_plans=service,
        evidence=evidence,
        kill_switch=KillSwitchService(engine),
        enabled=True,
    )
    command = executor.queue(plan["id"], queued_by="execution-operator")
    executor.claim(command["id"], current_state_hash=state_hash, worker_id="ozon-worker")
    started = executor.begin_write_attempt(command["id"], worker_id="ozon-worker")
    assert started["credential_grant"] is None
    assert started["credential_grant_bound"] is False
    assert grant_rows(engine) == []


def test_runtime_worker_grant_issuer_fails_closed_without_signing_key(monkeypatch):
    engine = database()
    monkeypatch.delenv("KJDS_CHANNEL_LEASE_SIGNING_KEY", raising=False)
    assert _build_worker_grant_issuer(engine) is None
    monkeypatch.setenv("KJDS_CHANNEL_LEASE_SIGNING_KEY", "short")
    assert _build_worker_grant_issuer(engine) is None


def test_runtime_worker_grant_issuer_composes_managed_binding(monkeypatch):
    engine = database()
    monkeypatch.setenv("KJDS_CHANNEL_LEASE_SIGNING_KEY", "s" * 32)
    monkeypatch.setenv("KJDS_CHANNEL_LEASE_ISSUER", "kjds-managed-store")
    monkeypatch.setenv("KJDS_CHANNEL_LEASE_KEY_ID", "lease-kid-1")
    issuer = _build_worker_grant_issuer(engine)
    assert isinstance(issuer, CanonicalWorkerCredentialGrantIssuer)
    assert issuer._grant_issuer == "kjds-managed-store"
    assert issuer._grant_key_id == "lease-kid-1"
    assert len(issuer._signing_key) >= 32
    from apps.control_plane.managed_credential_leases import (
        SqlManagedCredentialLeaseBindingSource,
    )

    assert isinstance(issuer._lease_source, SqlManagedCredentialLeaseBindingSource)
