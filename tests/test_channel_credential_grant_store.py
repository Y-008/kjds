from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.control_plane.channel_account_runtime_identity import (
    SignedWorkerCredentialGrantAuthority,
    _WorkerCredentialGrantRecord,
)
from apps.control_plane.channel_credential_grants import (
    SqlWorkerCredentialGrantStore,
    WorkerCredentialGrantRow,
)
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 1, 8, tzinfo=UTC)


def row() -> WorkerCredentialGrantRow:
    return WorkerCredentialGrantRow(
        grant_id="grant-db-1",
        issuer="kjds-control-plane",
        key_id="grant-kid-1",
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        platform="ozon",
        account_ref="account-1",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        required_capability="catalog.read",
        purpose="pilot-read",
        authorization_epoch=1,
        lease_issuer="kjds-managed-store",
        lease_key_id="lease-kid-1",
        lease_id="lease-1",
        lease_envelope_sha256="a" * 64,
        lease_signature="b" * 64,
        secret_reference_sha256="c" * 64,
        credential_fingerprint_sha256="d" * 64,
        issued_at=NOW - timedelta(seconds=10),
        expires_at=NOW + timedelta(seconds=10),
        revoked_at=None,
        consumed_at=None,
    )


def test_sql_store_atomically_consumes_once_and_persists_receipt_time():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(row())
        session.commit()
        store = SqlWorkerCredentialGrantStore(session)
        record = store.get("grant-db-1")
        assert isinstance(record, _WorkerCredentialGrantRecord)
        authority = SignedWorkerCredentialGrantAuthority(
            issuer="kjds-control-plane",
            key_id="grant-kid-1",
            signing_key=b"g" * 32,
            store=store,
        )
        grant = authority.issue(record)

        consumed = store.consume_once(
            grant_id=record.grant_id,
            consumed_at=NOW,
            expected_envelope_sha256=grant.envelope_sha256,
        )
        session.commit()

        assert consumed.consumed_at == NOW
        assert store.get(record.grant_id).consumed_at == NOW
        with pytest.raises(PermissionError, match="replay"):
            store.consume_once(
                grant_id=record.grant_id,
                consumed_at=NOW,
                expected_envelope_sha256=grant.envelope_sha256,
            )


def test_sql_store_rejects_wrong_envelope_before_consumption():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(row())
        session.commit()
        store = SqlWorkerCredentialGrantStore(session)

        with pytest.raises(PermissionError, match="envelope drift"):
            store.consume_once(
                grant_id="grant-db-1",
                consumed_at=NOW,
                expected_envelope_sha256="0" * 64,
            )

        assert store.get("grant-db-1").consumed_at is None
