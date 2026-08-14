"""Add authoritative managed credential lease store.

Revision ID: 20260801_0084
Revises: 20260801_0083
Create Date: 2026-08-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260801_0084"
down_revision = "20260801_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_managed_credential_leases",
        sa.Column("lease_id", sa.String(length=240), primary_key=True),
        sa.Column("issuer", sa.String(length=160), nullable=False),
        sa.Column("key_id", sa.String(length=160), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("account_ref", sa.String(length=240), nullable=False),
        sa.Column("adapter_id", sa.String(length=160), nullable=False),
        sa.Column("adapter_version", sa.String(length=80), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("secret_reference", sa.String(length=256), nullable=False),
        sa.Column("secret_reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("credential_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=240), nullable=False),
        sa.Column("api_key", sa.String(length=500), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_readback_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_readback_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "external_verifier_observation_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("external_verifier_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "adapter_version",
            "authorization_epoch",
            name="uq_channel_managed_lease_authority",
        ),
        sa.CheckConstraint(
            "length(issuer) > 0 AND length(key_id) > 0 "
            "AND length(tenant_ref) > 0 AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 AND length(platform) > 0 "
            "AND length(account_ref) > 0 AND length(adapter_id) > 0 "
            "AND length(adapter_version) > 0 "
            "AND length(secret_reference) > 0 "
            "AND secret_reference LIKE 'msl_%' "
            "AND length(secret_reference_sha256) = 64 "
            "AND length(credential_fingerprint_sha256) = 64 "
            "AND length(provider_readback_sha256) = 64 "
            "AND length(external_verifier_observation_sha256) = 64 "
            "AND authorization_epoch > 0 "
            "AND issued_at < expires_at "
            "AND (revoked_at IS NULL OR revoked_at >= issued_at) "
            "AND length(client_id) > 0 AND length(api_key) > 0 "
            "AND provider_readback_verified_at IS NOT NULL "
            "AND external_verifier_verified_at IS NOT NULL "
            "AND provider_readback_verified_at <= expires_at "
            "AND external_verifier_verified_at <= expires_at",
            name="ck_channel_managed_lease_authority",
        ),
    )
    op.create_index(
        "ix_channel_managed_lease_scope",
        "channel_managed_credential_leases",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "adapter_version",
            "expires_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_managed_lease_scope",
        table_name="channel_managed_credential_leases",
    )
    op.drop_table("channel_managed_credential_leases")
