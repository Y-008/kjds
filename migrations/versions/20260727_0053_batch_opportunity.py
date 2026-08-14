"""Add batch opportunity mining and observed checkout semantics."""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0053"
down_revision = "20260726_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_observation_items",
        sa.Column("candidate_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "product_identity_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.drop_constraint(
        "ck_marketplace_observation_source_profile",
        "marketplace_observation_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_source_profile",
        "marketplace_observation_snapshots",
        "source_profile IN "
        "('browser_observation','seller_tool_export',"
        "'manual_verified_public_page',"
        "'public_search_index_observation')",
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column("observed_quantity", sa.Integer(), nullable=True),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "checkout_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column("tax_included", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "domestic_freight_included",
            sa.Boolean(),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "purchase_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "confidence_decimal",
            sa.Numeric(8, 6),
            nullable=False,
            server_default="0.5",
        ),
    )
    for name in (
        "market_signals_json",
        "supply_signals_json",
        "experiment_readbacks_json",
    ):
        op.add_column(
            "marketplace_observation_items",
            sa.Column(
                name,
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "media_rights_status",
            sa.String(),
            nullable=False,
            server_default="unverified_external_reference",
        ),
    )
    op.drop_constraint(
        "ck_marketplace_observation_price_kind",
        "marketplace_observation_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_price_kind",
        "marketplace_observation_items",
        "price_kind IN "
        "('public_display_price','new_customer_price','member_price',"
        "'range_minimum','marketplace_listing_price',"
        "'observed_checkout_price')",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_quantity_positive",
        "marketplace_observation_items",
        "observed_quantity IS NULL OR observed_quantity > 0",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_confidence",
        "marketplace_observation_items",
        "confidence_decimal > 0 AND confidence_decimal <= 1",
    )
    op.create_index(
        "ix_marketplace_observation_candidate_latest",
        "marketplace_observation_items",
        ["candidate_key", "price_kind", "observed_at"],
    )

    op.create_table(
        "batch_opportunity_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("store_ref", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("contract_version", sa.String(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.UniqueConstraint(
            "store_ref",
            "idempotency_key",
            name="uq_batch_opportunity_run_idempotency",
        ),
    )
    op.create_index(
        "ix_batch_opportunity_run_latest",
        "batch_opportunity_runs",
        ["store_ref", "as_of"],
    )
    op.create_table(
        "batch_opportunity_candidates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("batch_opportunity_runs.id"),
            nullable=False,
        ),
        sa.Column("candidate_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("pilot_ready", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_batch_opportunity_candidate_fingerprint",
        ),
        sa.CheckConstraint(
            "rank > 0",
            name="ck_batch_opportunity_candidate_rank",
        ),
        sa.CheckConstraint(
            "state IN "
            "('observe','match','evaluate','content_ready','pilot',"
            "'scale','stop','reconcile')",
            name="ck_batch_opportunity_candidate_state",
        ),
    )
    op.create_index(
        "ix_batch_opportunity_candidate_rank",
        "batch_opportunity_candidates",
        ["run_id", "rank"],
    )
    for table in (
        "batch_opportunity_runs",
        "batch_opportunity_candidates",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" '
                f'BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION "
                "kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_batch_opportunity_candidate_rank",
        table_name="batch_opportunity_candidates",
    )
    op.drop_table("batch_opportunity_candidates")
    op.drop_index(
        "ix_batch_opportunity_run_latest",
        table_name="batch_opportunity_runs",
    )
    op.drop_table("batch_opportunity_runs")
    op.drop_constraint(
        "ck_marketplace_observation_source_profile",
        "marketplace_observation_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_source_profile",
        "marketplace_observation_snapshots",
        "source_profile IN "
        "('browser_observation','seller_tool_export',"
        "'manual_verified_public_page')",
    )
    op.drop_index(
        "ix_marketplace_observation_candidate_latest",
        table_name="marketplace_observation_items",
    )
    op.drop_constraint(
        "ck_marketplace_observation_confidence",
        "marketplace_observation_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_observation_quantity_positive",
        "marketplace_observation_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_observation_price_kind",
        "marketplace_observation_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_price_kind",
        "marketplace_observation_items",
        "price_kind IN "
        "('public_display_price','new_customer_price','member_price',"
        "'range_minimum','marketplace_listing_price')",
    )
    for name in (
        "media_rights_status",
        "experiment_readbacks_json",
        "supply_signals_json",
        "market_signals_json",
        "confidence_decimal",
        "purchase_available",
        "domestic_freight_included",
        "tax_included",
        "checkout_verified",
        "observed_quantity",
        "product_identity_json",
        "candidate_key",
    ):
        op.drop_column("marketplace_observation_items", name)
