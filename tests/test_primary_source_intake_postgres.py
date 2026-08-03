from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from apps.control_plane.evidence import EvidenceService
from apps.control_plane.primary_source_intake import (
    EVIDENCE_SOURCE,
    PrimarySourceIntake,
)
from apps.control_plane.security import Principal

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)
NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)


class FakeScopeGrants:
    def current(self, *, principal, store_ref, as_of):
        entity_ref = f"entity-{principal.tenant_ref}"
        authority_sha256 = hashlib.sha256(
            f"{principal.tenant_ref}|{entity_ref}|{store_ref}|v1".encode()
        ).hexdigest()
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority_sha256,
        }


@pytest.fixture(scope="module")
def engine():
    target = create_engine(DATABASE_URL, pool_pre_ping=True)
    yield target
    target.dispose()


@pytest.fixture
def intake(engine):
    return PrimarySourceIntake(
        engine=engine,
        evidence=EvidenceService(engine),
        scope_grants=FakeScopeGrants(),
        clock=lambda: NOW,
    )


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def principal(tenant: str) -> Principal:
    return Principal(
        actor_id="postgres-operator",
        roles=frozenset({"operator"}),
        tenant_ref=tenant,
        store_refs=frozenset({"store-a"}),
    )


def envelope() -> dict:
    return {
        "source_pack_id": "global_trade_lead_intelligence",
        "source_contract_id": "owner-export-v1",
        "source_contract_version": "2026-08-03",
        "subject_ref": "subject://postgres-batch",
        "source_locator_ref": "customer-vault://exports/postgres-batch",
        "blob_sha256": "a" * 64,
        "byte_count": 512,
        "mime_type": "application/json",
        "captured_at": NOW - timedelta(hours=3),
        "effective_at": NOW - timedelta(hours=3),
        "acquisition_mode": "account_owner_export",
        "license_or_terms_basis": "account owner export terms v1",
        "allowed_purpose": "B2B market research",
        "jurisdiction": "US",
        "retention_class": "operational",
        "data_classification": "business_public",
        "cross_border_transfer_classification": "domestic_only",
        "parser_version": "lead-normalizer-1",
        "field_count": 16,
        "pagination": {
            "expected_pages": 1,
            "received_pages": 1,
            "failed_page_refs": [],
            "checkpoint_ref": None,
        },
        "integrity": {
            "raw_blob_reverified": True,
            "verifier_id": "sha256-byte-verifier",
            "verifier_version": "1",
            "verified_at": NOW - timedelta(hours=1),
        },
        "conservation": {
            "source_total": 1,
            "quarantined_count": 0,
            "duplicate_count": 0,
        },
        "review_due_at": NOW + timedelta(days=30),
    }


def record() -> dict:
    return {
        "source_family": "amazon",
        "marketplace_or_site": "amazon.com",
        "business_entity_name": "Postgres Contract Seller LLC",
        "country_or_region": "US",
        "category": "home-and-kitchen",
        "public_business_url": "https://seller.example/store/postgres-contract",
        "entity_type": "seller_account",
        "signal_type": "seller_presence",
        "signal_observed_at": NOW - timedelta(hours=2),
        "license_or_terms_basis": "public business page terms v1",
        "contact_ref": None,
        "contact_purpose_basis": "not_applicable",
        "jurisdiction": "US",
        "do_not_contact_status": "unknown",
        "confidence_bps": 8500,
        "evidence_refs": [],
    }


def admit(intake: PrimarySourceIntake, tenant: str, key: str):
    return intake.admit(
        principal=principal(tenant),
        store_ref="store-a",
        as_of=NOW,
        idempotency_key=key,
        envelope=envelope(),
        records=[record()],
    )


def test_00_migration_replays_0091_to_0092_to_0091_to_0092(engine):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

    command.upgrade(config, "20260803_0092")
    command.downgrade(config, "20260803_0091")
    assert "primary_source_intake_envelopes" not in inspect(engine).get_table_names()
    command.upgrade(config, "20260803_0092")
    assert {
        "primary_source_intake_envelopes",
        "primary_source_intake_records",
    }.issubset(inspect(engine).get_table_names())
    command.downgrade(config, "20260803_0091")
    command.upgrade(config, "20260803_0092")

    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == "20260803_0092"
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                    "AND tgname LIKE 'trg_primary_source_%'"
                )
            )
        )
    assert triggers == {
        "trg_primary_source_envelopes_immutable",
        "trg_primary_source_records_immutable",
    }
    indexes = {item["name"] for item in inspect(engine).get_indexes("evidence_records")}
    assert "uq_primary_source_intake_evidence_source_ref" in indexes


def test_concurrent_idempotency_creates_one_intake_record_and_evidence(engine, intake):
    tenant = unique("tenant-primary-source-concurrent")
    key = unique("owner-export")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: admit(intake, tenant, key), range(8)))

    intake_refs = {result["intake"]["intake_ref"] for result in results}
    assert len(intake_refs) == 1
    intake_ref = intake_refs.pop()
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM primary_source_intake_envelopes "
                "WHERE tenant_ref=:tenant AND intake_ref=:intake_ref"
            ),
            {"tenant": tenant, "intake_ref": intake_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM primary_source_intake_records "
                "WHERE tenant_ref=:tenant AND intake_ref=:intake_ref"
            ),
            {"tenant": tenant, "intake_ref": intake_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM evidence_records "
                "WHERE source=:source AND source_ref=:source_ref"
            ),
            {
                "source": EVIDENCE_SOURCE,
                "source_ref": f"primary-source-intake://{intake_ref}",
            },
        ) == 1


def test_database_rejects_cross_scope_record_update_and_delete(engine, intake):
    tenant = unique("tenant-primary-source-exact")
    result = admit(intake, tenant, unique("owner-export"))
    intake_ref = result["intake"]["intake_ref"]
    with engine.connect() as connection:
        source = connection.execute(
            text(
                "SELECT * FROM primary_source_intake_records "
                "WHERE intake_ref=:intake_ref"
            ),
            {"intake_ref": intake_ref},
        ).mappings().one()

    forged = dict(source)
    forged.update(
        record_ref=f"psr_{uuid4().hex}",
        tenant_ref=unique("tenant-forged"),
        source_record_sha256="f" * 64,
    )
    columns = ",".join(forged)
    parameters = ",".join(f":{name}" for name in forged)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO primary_source_intake_records ({columns}) "
                f"VALUES ({parameters})"
            ),
            forged,
        )
    with pytest.raises(DBAPIError, match="immutable ledger"), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE primary_source_intake_envelopes "
                "SET parser_version='drift-2' WHERE intake_ref=:intake_ref"
            ),
            {"intake_ref": intake_ref},
        )
    with pytest.raises(DBAPIError, match="immutable ledger"), engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM primary_source_intake_records "
                "WHERE intake_ref=:intake_ref"
            ),
            {"intake_ref": intake_ref},
        )


def test_database_schema_has_no_raw_contact_or_credential_columns(engine):
    banned_markers = {
        "email",
        "phone",
        "cookie",
        "password",
        "token",
        "credential",
    }
    banned_raw_columns = {"source_locator_ref", "subject_ref"}
    inspector = inspect(engine)
    for table in (
        "primary_source_intake_envelopes",
        "primary_source_intake_records",
    ):
        names = {column["name"].lower() for column in inspector.get_columns(table)}
        assert not any(
            marker in name for name in names for marker in banned_markers
        )
        assert names.isdisjoint(banned_raw_columns)


def test_99_data_bearing_downgrade_fails_closed(engine):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    with pytest.raises(DBAPIError, match="BAS-198 downgrade blocked"):
        command.downgrade(config, "20260803_0091")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == "20260803_0092"
