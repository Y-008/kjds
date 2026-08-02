"""Add single-use channel worker credential grant ledger.

Revision ID: 20260801_0082
Revises: 20260731_0081
Create Date: 2026-08-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260801_0082"
down_revision = "20260731_0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_worker_credential_grants",
        sa.Column("grant_id", sa.String(length=240), primary_key=True),
        sa.Column("issuer", sa.String(length=160), nullable=False),
        sa.Column("key_id", sa.String(length=160), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("account_ref", sa.String(length=240), nullable=False),
        sa.Column("adapter_id", sa.String(length=160), nullable=False),
        sa.Column("adapter_version", sa.String(length=80), nullable=False),
        sa.Column("required_capability", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.String(length=160), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_issuer", sa.String(length=160), nullable=False),
        sa.Column("lease_key_id", sa.String(length=160), nullable=False),
        sa.Column("lease_id", sa.String(length=240), nullable=False),
        sa.Column("lease_envelope_sha256", sa.String(length=64), nullable=False),
        sa.Column("lease_signature", sa.String(length=64), nullable=False),
        sa.Column("secret_reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("credential_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "authorization_epoch > 0 AND issued_at < expires_at "
            "AND (revoked_at IS NULL OR revoked_at >= issued_at) "
            "AND (consumed_at IS NULL OR (consumed_at >= issued_at AND consumed_at < expires_at)) "
            "AND length(secret_reference_sha256) = 64 "
            "AND length(credential_fingerprint_sha256) = 64 "
            "AND length(lease_envelope_sha256) = 64 "
            "AND length(lease_signature) = 64",
            name="ck_channel_worker_credential_grant_authority",
        ),
    )
    op.create_index(
        "ix_channel_worker_credential_grant_scope",
        "channel_worker_credential_grants",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "required_capability",
            "expires_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_worker_credential_grant_scope",
        table_name="channel_worker_credential_grants",
    )
    op.drop_table("channel_worker_credential_grants")
