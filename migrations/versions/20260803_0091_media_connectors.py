"""Add exact-tenant, descriptor-only media connector registry.

Revision ID: 20260803_0091
Revises: 20260803_0090
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260803_0091"
down_revision = "20260803_0090"
branch_labels = None
depends_on = None

CONNECTORS = "media_connectors"
EVENTS = "media_connector_events"


def upgrade() -> None:
    op.create_table(
        CONNECTORS,
        sa.Column("connector_ref", sa.String(length=64), primary_key=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("deployment_mode", sa.String(length=32), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.String(length=80), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("registration_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("registration_idempotency_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_ref",
            "registration_idempotency_sha256",
            name="uq_media_connector_tenant_idempotency",
        ),
        sa.UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "provider",
            name="uq_media_connector_exact_binding",
        ),
        sa.CheckConstraint(
            "provider IN ('codex_oauth','comfyui','ffmpeg','remotion','windows_agent')",
            name="ck_media_connector_provider",
        ),
        sa.CheckConstraint(
            "deployment_mode IN ('customer_local','hosted_isolated')",
            name="ck_media_connector_deployment_mode",
        ),
        sa.CheckConstraint(
            "connector_ref ~ '^mcn_[0-9a-f]{32}$' "
            "AND length(tenant_ref) > 0 "
            "AND binding_sha256 ~ '^[0-9a-f]{64}$' "
            "AND length(protocol_version) > 0 "
            "AND registration_request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND registration_idempotency_sha256 ~ '^[0-9a-f]{64}$' "
            "AND length(created_by) > 0",
            name="ck_media_connector_required_fields",
        ),
        sa.CheckConstraint(
            "concurrency_limit = 1",
            name="ck_media_connector_v1_concurrency",
        ),
    )
    op.create_index(
        "ix_media_connector_tenant_provider",
        CONNECTORS,
        ["tenant_ref", "provider", "connector_ref"],
    )

    op.create_table(
        EVENTS,
        sa.Column("event_ref", sa.String(length=64), primary_key=True),
        sa.Column("connector_ref", sa.String(length=64), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("health", sa.String(length=32), nullable=False),
        sa.Column("rate_limit_status", sa.String(length=16), nullable=True),
        sa.Column("rate_limit_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(length=64), nullable=False),
        sa.Column("previous_event_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_ref", "tenant_ref", "provider"],
            [
                f"{CONNECTORS}.connector_ref",
                f"{CONNECTORS}.tenant_ref",
                f"{CONNECTORS}.provider",
            ],
            name="fk_media_connector_event_exact_binding",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "sequence",
            name="uq_media_connector_event_sequence",
        ),
        sa.UniqueConstraint(
            "connector_ref",
            "tenant_ref",
            "idempotency_sha256",
            name="uq_media_connector_event_idempotency",
        ),
        sa.CheckConstraint(
            "event_type IN ('registered','health_observed','revoked')",
            name="ck_media_connector_event_type",
        ),
        sa.CheckConstraint(
            "health IN ('ENROLLING','READY','BUSY','LOGIN_REQUIRED','LIMITED',"
            "'OFFLINE','ERROR','REVOKED')",
            name="ck_media_connector_event_health",
        ),
        sa.CheckConstraint(
            "(event_type = 'registered' AND health = 'ENROLLING') "
            "OR (event_type = 'revoked' AND health = 'REVOKED') "
            "OR (event_type = 'health_observed' "
            "AND health NOT IN ('ENROLLING','REVOKED'))",
            name="ck_media_connector_event_semantics",
        ),
        sa.CheckConstraint(
            "event_ref ~ '^mce_[0-9a-f]{32}$' AND sequence > 0 "
            "AND observation_request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND idempotency_sha256 ~ '^[0-9a-f]{64}$' "
            "AND previous_event_sha256 ~ '^[0-9a-f]{64}$' "
            "AND event_sha256 ~ '^[0-9a-f]{64}$' "
            "AND length(created_by) > 0",
            name="ck_media_connector_event_required_fields",
        ),
        sa.CheckConstraint(
            "(rate_limit_status IS NULL AND rate_limit_observed_at IS NULL "
            "AND retry_after_at IS NULL) OR "
            "(rate_limit_status IN ('ok','limited','unknown') "
            "AND rate_limit_observed_at IS NOT NULL "
            "AND (retry_after_at IS NULL OR retry_after_at >= rate_limit_observed_at))",
            name="ck_media_connector_rate_limit_summary",
        ),
        sa.CheckConstraint(
            "(health = 'LIMITED' AND rate_limit_status = 'limited') "
            "OR (health <> 'LIMITED' AND "
            "(rate_limit_status IS NULL OR rate_limit_status <> 'limited'))",
            name="ck_media_connector_limited_state",
        ),
        sa.CheckConstraint(
            "recorded_at >= observed_at",
            name="ck_media_connector_event_time_order",
        ),
    )
    op.create_index(
        "ix_media_connector_event_latest",
        EVENTS,
        ["tenant_ref", "connector_ref", "sequence"],
    )

    op.execute(
        """
        CREATE FUNCTION kjds_media_connector_event_append_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            bound_provider text;
            prior_sequence integer;
            prior_sha256 text;
            prior_health text;
            prior_observed_at timestamptz;
        BEGIN
            SELECT provider INTO bound_provider
              FROM media_connectors
             WHERE connector_ref = NEW.connector_ref
               AND tenant_ref = NEW.tenant_ref
               AND provider = NEW.provider
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'media connector exact binding missing';
            END IF;

            SELECT sequence, event_sha256, health, observed_at
              INTO prior_sequence, prior_sha256, prior_health, prior_observed_at
              FROM media_connector_events
             WHERE connector_ref = NEW.connector_ref
               AND tenant_ref = NEW.tenant_ref
             ORDER BY sequence DESC
             LIMIT 1
             FOR UPDATE;

            IF NOT FOUND THEN
                IF NEW.sequence <> 1 OR NEW.event_type <> 'registered'
                   OR NEW.health <> 'ENROLLING'
                   OR NEW.previous_event_sha256 <> repeat('0', 64) THEN
                    RAISE EXCEPTION 'invalid media connector registration event';
                END IF;
            ELSE
                IF prior_health = 'REVOKED' THEN
                    RAISE EXCEPTION 'revoked media connector is terminal';
                END IF;
                IF NEW.event_type = 'registered' THEN
                    RAISE EXCEPTION 'media connector registration event must be first';
                END IF;
                IF NEW.sequence <> prior_sequence + 1
                   OR NEW.previous_event_sha256 <> prior_sha256 THEN
                    RAISE EXCEPTION 'media connector event hash chain drift';
                END IF;
                IF NEW.observed_at < prior_observed_at THEN
                    RAISE EXCEPTION 'media connector observation moved backwards';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_media_connector_event_append_guard
        BEFORE INSERT ON media_connector_events
        FOR EACH ROW EXECUTE FUNCTION kjds_media_connector_event_append_guard();

        CREATE FUNCTION kjds_media_connector_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$;

        CREATE TRIGGER trg_media_connectors_immutable
        BEFORE UPDATE OR DELETE ON media_connectors
        FOR EACH ROW EXECUTE FUNCTION kjds_media_connector_immutable();

        CREATE TRIGGER trg_media_connector_events_immutable
        BEFORE UPDATE OR DELETE ON media_connector_events
        FOR EACH ROW EXECUTE FUNCTION kjds_media_connector_immutable();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_media_connector_events_immutable
          ON media_connector_events;
        DROP TRIGGER IF EXISTS trg_media_connector_event_append_guard
          ON media_connector_events;
        DROP TRIGGER IF EXISTS trg_media_connectors_immutable
          ON media_connectors;
        DROP FUNCTION IF EXISTS kjds_media_connector_event_append_guard();
        DROP FUNCTION IF EXISTS kjds_media_connector_immutable();
        """
    )
    op.drop_index("ix_media_connector_event_latest", table_name=EVENTS)
    op.drop_table(EVENTS)
    op.drop_index("ix_media_connector_tenant_provider", table_name=CONNECTORS)
    op.drop_table(CONNECTORS)
