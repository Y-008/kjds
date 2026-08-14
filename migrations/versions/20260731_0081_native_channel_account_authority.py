"""Add native exact-scope append-only channel account authority.

Revision ID: 20260731_0081
Revises: 20260730_0080
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260731_0081"
down_revision = "20260730_0080"
branch_labels = None
depends_on = None

SCOPE_REQUIRED = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND platform IS NOT NULL AND length(platform) > 0 "
    "AND account_ref IS NOT NULL AND length(account_ref) > 0 "
    "AND adapter_id IS NOT NULL AND length(adapter_id) > 0 "
    "AND adapter_version IS NOT NULL AND length(adapter_version) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND adapter_contract_sha256 IS NOT NULL "
    "AND length(adapter_contract_sha256) = 64 "
    "AND consent_evidence_sha256 IS NOT NULL "
    "AND length(consent_evidence_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND source_payload_sha256 IS NOT NULL "
    "AND length(source_payload_sha256) = 64 "
    "AND payload_sha256 IS NOT NULL AND length(payload_sha256) = 64 "
    "AND secret_reference_sha256 IS NOT NULL "
    "AND length(secret_reference_sha256) = 64 "
    "AND credential_fingerprint_sha256 IS NOT NULL "
    "AND length(credential_fingerprint_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
GOVERNED_EVENTS = (
    "'authorization_granted',"
    "'authorization_refreshed',"
    "'credential_rotated',"
    "'authorization_revoked',"
    "'external_verification_readback'"
)
GOVERNANCE_BINDING = (
    "("
    f"event_type NOT IN ({GOVERNED_EVENTS}) "
    "AND approval_id IS NULL AND command_id IS NULL "
    "AND receipt_id IS NULL AND permit_evidence_id IS NULL "
    "AND readback_evidence_id IS NULL AND kill_switch_sequence IS NULL "
    "AND kill_switch_state_id IS NULL "
    "AND kill_switch_evidence_id IS NULL "
    "AND compensation_plan_id IS NULL "
    "AND compensation_evidence_id IS NULL"
    ") OR ("
    f"event_type IN ({GOVERNED_EVENTS}) "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND receipt_id IS NOT NULL "
    "AND permit_evidence_id IS NOT NULL AND readback_evidence_id IS NOT NULL "
    "AND kill_switch_sequence IS NOT NULL "
    "AND kill_switch_state_id IS NOT NULL "
    "AND kill_switch_evidence_id IS NOT NULL "
    "AND compensation_plan_id IS NOT NULL "
    "AND compensation_evidence_id IS NOT NULL"
    ")"
)
EXECUTION_PLAN_SOURCE_VARIANT = (
    "(source_kind = 'causal_policy_handoff' "
    "AND source_id = handoff_id "
    "AND handoff_id IS NOT NULL "
    "AND policy_id IS NOT NULL "
    "AND release_id IS NOT NULL) "
    "OR (source_kind = 'approved_listing_draft' "
    "AND handoff_id IS NULL AND policy_id IS NULL "
    "AND release_id IS NULL) "
    "OR (source_kind = 'approved_customer_service_reply' "
    "AND handoff_id IS NULL AND policy_id IS NULL "
    "AND release_id IS NULL) "
    "OR (source_kind IN ("
    "'approved_channel_account_change', "
    "'approved_channel_account_compensation'"
    ") "
    "AND handoff_id IS NULL AND policy_id IS NULL "
    "AND release_id IS NULL)"
)
LEGACY_EXECUTION_PLAN_SOURCE_VARIANT = (
    "(source_kind = 'causal_policy_handoff' "
    "AND source_id = handoff_id "
    "AND handoff_id IS NOT NULL "
    "AND policy_id IS NOT NULL "
    "AND release_id IS NOT NULL) "
    "OR (source_kind = 'approved_listing_draft' "
    "AND handoff_id IS NULL AND policy_id IS NULL "
    "AND release_id IS NULL) "
    "OR (source_kind = 'approved_customer_service_reply' "
    "AND handoff_id IS NULL AND policy_id IS NULL "
    "AND release_id IS NULL)"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION channel_account_capabilities_valid(value jsonb)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
            SELECT jsonb_typeof(value) = 'array'
               AND jsonb_array_length(value) > 0
               AND NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(value) AS item
                    WHERE jsonb_typeof(item) <> 'string'
                       OR btrim(item #>> '{}') = ''
                       OR (item #>> '{}') !~ '^[a-z][a-z0-9_.:-]{0,159}$'
               )
               AND jsonb_array_length(value) = (
                    SELECT count(DISTINCT item #>> '{}')
                    FROM jsonb_array_elements(value) AS item
               )
        $$
        """
    )
    op.drop_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        EXECUTION_PLAN_SOURCE_VARIANT,
    )
    op.create_table(
        "channel_account_review_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "submission_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "decision_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=240), nullable=False),
        sa.Column("decision_sha256", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.UniqueConstraint(
            "submission_evidence_id",
            "sequence",
            name="uq_channel_account_review_decision_sequence",
        ),
        sa.UniqueConstraint(
            "submission_evidence_id",
            "decision_sha256",
            name="uq_channel_account_review_decision_hash",
        ),
        sa.CheckConstraint(
            "sequence > 0 AND decision_sha256 ~ '^[0-9a-f]{64}$' AND decided_at <= recorded_at",
            name="ck_channel_account_review_decision",
        ),
    )
    op.create_index(
        "ix_channel_account_review_decision_latest",
        "channel_account_review_decisions",
        ["submission_evidence_id", "sequence", "id"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_channel_account_review_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'channel_account_review_decisions is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_review_no_update
        BEFORE UPDATE ON channel_account_review_decisions
        FOR EACH ROW EXECUTE FUNCTION reject_channel_account_review_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_review_no_delete
        BEFORE DELETE ON channel_account_review_decisions
        FOR EACH ROW EXECUTE FUNCTION reject_channel_account_review_mutation()
        """
    )
    op.create_table(
        "channel_account_kill_switch_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "source_event_ref",
            sa.String(length=240),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "kill_switch_sequence",
            sa.Integer(),
            sa.ForeignKey("kill_switch_events.sequence"),
            nullable=False,
        ),
        sa.Column("writes_enabled", sa.Boolean(), nullable=False),
        sa.Column("action_id", sa.String(length=160), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("account_ref", sa.String(length=240), nullable=False),
        sa.Column("adapter_id", sa.String(length=160), nullable=False),
        sa.Column(
            "adapter_version",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "evidence_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "payload_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_event_ref",
            name="uq_channel_account_kill_switch_source",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "action_id",
            "sequence",
            name="uq_channel_account_kill_switch_sequence",
        ),
        sa.CheckConstraint(
            "sequence > 0 "
            "AND action_id IN ("
            "'channel_authorization_grant',"
            "'channel_authorization_refresh',"
            "'channel_credential_rotate',"
            "'channel_authorization_revoke',"
            "'channel_authorization_external_verify') "
            "AND scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^[0-9a-f]{64}$' "
            "AND effective_at <= scope_as_of "
            "AND scope_as_of <= recorded_at",
            name="ck_channel_account_kill_switch_authority",
        ),
    )
    op.create_index(
        "ix_channel_account_kill_switch_current",
        "channel_account_kill_switch_states",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "action_id",
            "effective_at",
            "sequence",
        ],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_channel_account_kill_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'channel_account_kill_switch_states is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_kill_no_update
        BEFORE UPDATE ON channel_account_kill_switch_states
        FOR EACH ROW
        EXECUTE FUNCTION reject_channel_account_kill_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_kill_no_delete
        BEFORE DELETE ON channel_account_kill_switch_states
        FOR EACH ROW
        EXECUTE FUNCTION reject_channel_account_kill_mutation()
        """
    )
    op.create_table(
        "channel_account_authorization_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_event_ref", sa.String(length=240), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column(
            "authorization_source",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("account_ref", sa.String(length=240), nullable=False),
        sa.Column("adapter_id", sa.String(length=160), nullable=False),
        sa.Column("adapter_version", sa.String(length=80), nullable=False),
        sa.Column("role_ref", sa.String(length=160), nullable=True),
        sa.Column("subaccount_ref", sa.String(length=240), nullable=True),
        sa.Column("credential_kind", sa.String(length=80), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("secret_reference", sa.String(length=256), nullable=False),
        sa.Column(
            "secret_reference_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "credential_fingerprint_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("health_status", sa.String(length=80), nullable=False),
        sa.Column("readback_outcome", sa.String(length=80), nullable=False),
        sa.Column("rate_limit_state", sa.String(length=80), nullable=False),
        sa.Column(
            "external_schema_version",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "consent_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "adapter_contract_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "consent_evidence_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_evidence_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_payload_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
        sa.Column(
            "command_id",
            sa.String(),
            sa.ForeignKey("limited_execution_commands.id"),
            nullable=True,
        ),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("limited_execution_receipts.id"),
            nullable=True,
        ),
        sa.Column(
            "permit_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "readback_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "kill_switch_sequence",
            sa.Integer(),
            sa.ForeignKey("kill_switch_events.sequence"),
            nullable=True,
        ),
        sa.Column(
            "kill_switch_state_id",
            sa.String(),
            sa.ForeignKey("channel_account_kill_switch_states.id"),
            nullable=True,
        ),
        sa.Column(
            "kill_switch_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "compensation_plan_id",
            sa.String(),
            sa.ForeignKey("governed_execution_plans.id"),
            nullable=True,
        ),
        sa.Column(
            "compensation_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_event_ref",
            name="uq_channel_account_authority_source_event",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "sequence",
            name="uq_channel_account_authority_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "command_id",
            name="uq_channel_account_authority_command",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "receipt_id",
            name="uq_channel_account_authority_receipt",
        ),
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_channel_account_authority_scope_required",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_channel_account_authority_sequence",
        ),
        sa.CheckConstraint(
            "authorization_source IN ('official', 'explicit_written_authorization')",
            name="ck_channel_account_authority_source",
        ),
        sa.CheckConstraint(
            GOVERNANCE_BINDING,
            name="ck_channel_account_authority_governance",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'authorization_granted','authorization_refreshed',"
            "'credential_rotated','authorization_revoked',"
            "'authorization_expired','external_verification_readback',"
            "'health_observed','rate_limit_observed',"
            "'schema_drift_observed','unknown_outcome_observed') "
            "AND credential_kind IN ("
            "'api_key_ref','oauth_client_ref','service_account_ref') "
            "AND health_status IN ("
            "'healthy','degraded','unreachable','unknown') "
            "AND readback_outcome IN ("
            "'succeeded','failed','unknown','not_applicable') "
            "AND rate_limit_state IN ("
            "'available','limited','exhausted','unknown')",
            name="ck_channel_account_authority_enums",
        ),
        sa.CheckConstraint(
            "effective_at <= verified_at "
            "AND effective_at < expires_at "
            "AND verified_at <= scope_as_of "
            "AND scope_as_of <= recorded_at "
            "AND secret_reference ~ '^msl_[A-Za-z0-9]{24,96}$'",
            name="ck_channel_account_authority_time_locator",
        ),
        sa.CheckConstraint(
            "channel_account_capabilities_valid(capabilities_json::jsonb) "
            "AND adapter_contract_sha256 ~ '^[0-9a-f]{64}$' "
            "AND consent_evidence_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_evidence_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_payload_sha256 ~ '^[0-9a-f]{64}$' "
            "AND payload_sha256 ~ '^[0-9a-f]{64}$' "
            "AND secret_reference_sha256 ~ '^[0-9a-f]{64}$' "
            "AND credential_fingerprint_sha256 ~ '^[0-9a-f]{64}$' "
            "AND scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_channel_account_authority_payload_shape",
        ),
    )
    op.create_index(
        "ix_channel_account_authority_scope_account",
        "channel_account_authorization_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "platform",
            "account_ref",
            "adapter_id",
            "effective_at",
            "id",
        ],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_channel_account_authority_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'channel_account_authorization_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_authority_no_update
        BEFORE UPDATE ON channel_account_authorization_events
        FOR EACH ROW
        EXECUTE FUNCTION reject_channel_account_authority_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_account_authority_no_delete
        BEFORE DELETE ON channel_account_authorization_events
        FOR EACH ROW
        EXECUTE FUNCTION reject_channel_account_authority_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_authority_no_delete ON channel_account_authorization_events")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_authority_no_update ON channel_account_authorization_events")
    op.execute("DROP FUNCTION IF EXISTS reject_channel_account_authority_mutation()")
    op.drop_index(
        "ix_channel_account_authority_scope_account",
        table_name="channel_account_authorization_events",
    )
    op.drop_table("channel_account_authorization_events")
    op.execute("DROP FUNCTION IF EXISTS channel_account_capabilities_valid(jsonb)")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_kill_no_delete ON channel_account_kill_switch_states")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_kill_no_update ON channel_account_kill_switch_states")
    op.execute("DROP FUNCTION IF EXISTS reject_channel_account_kill_mutation()")
    op.drop_index(
        "ix_channel_account_kill_switch_current",
        table_name="channel_account_kill_switch_states",
    )
    op.drop_table("channel_account_kill_switch_states")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_review_no_delete ON channel_account_review_decisions")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_account_review_no_update ON channel_account_review_decisions")
    op.execute("DROP FUNCTION IF EXISTS reject_channel_account_review_mutation()")
    # Early 0081 worktrees predated the review-decision table while carrying
    # the same uncommitted revision id. Keep downgrade replayable for that
    # known local shape; current upgrades still create the full authority.
    op.execute(
        "DROP INDEX IF EXISTS ix_channel_account_review_decision_latest"
    )
    op.execute("DROP TABLE IF EXISTS channel_account_review_decisions")
    op.drop_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        LEGACY_EXECUTION_PLAN_SOURCE_VARIANT,
    )
