"""Persist governed Agent run envelopes, events, and immutable Evidence.

Revision ID: 20260803_0090
Revises: 20260802_0089
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260803_0090"
down_revision = "20260802_0089"
branch_labels = None
depends_on = None

ENVELOPES = "agent_runtime_run_envelopes"
EVENTS = "agent_runtime_run_events"
EVIDENCE_SOURCE = "governed-agent-run-evidence"
EXACT_SCOPE = (
    "run_id",
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "authority_sha256",
)


def upgrade() -> None:
    op.create_table(
        ENVELOPES,
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("root_span_id", sa.String(length=16), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("scope_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_type", sa.String(length=160), nullable=False),
        sa.Column("registry_sha256", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=160), nullable=False),
        sa.Column("schema_version", sa.String(length=160), nullable=False),
        sa.Column("routing_policy_version", sa.String(length=160), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("tool_contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_field_names_json", sa.JSON(), nullable=False),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("scoped_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("required_capabilities_json", sa.JSON(), nullable=False),
        sa.Column("allowed_tools_json", sa.JSON(), nullable=False),
        sa.Column("max_cost_usd", sa.Numeric(30, 18), nullable=False),
        sa.Column("max_latency_ms", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            *EXACT_SCOPE,
            name="uq_agent_runtime_run_exact_scope",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "idempotency_sha256",
            name="uq_agent_runtime_scope_idempotency",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) > 0 AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 AND length(actor_id) > 0 "
            "AND length(task_type) > 0",
            name="ck_agent_runtime_run_required_scope",
        ),
        sa.CheckConstraint(
            "authority_sha256 ~ '^[0-9a-f]{64}$' "
            "AND registry_sha256 ~ '^[0-9a-f]{64}$' "
            "AND prompt_sha256 ~ '^[0-9a-f]{64}$' "
            "AND output_schema_sha256 ~ '^[0-9a-f]{64}$' "
            "AND tool_contract_sha256 ~ '^[0-9a-f]{64}$' "
            "AND idempotency_sha256 ~ '^[0-9a-f]{64}$' "
            "AND request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND input_sha256 ~ '^[0-9a-f]{64}$' "
            "AND evidence_snapshot_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_agent_runtime_run_hashes",
        ),
        sa.CheckConstraint("input_bytes >= 0", name="ck_agent_runtime_input_bytes"),
        sa.CheckConstraint(
            "max_cost_usd >= 0 "
            "AND max_cost_usd::text NOT IN ('NaN','Infinity','-Infinity')",
            name="ck_agent_runtime_max_cost",
        ),
        sa.CheckConstraint(
            "max_latency_ms > 0", name="ck_agent_runtime_max_latency"
        ),
        sa.CheckConstraint(
            "max_attempts > 0 AND max_attempts <= 8",
            name="ck_agent_runtime_max_attempts",
        ),
    )
    op.create_index(
        "ix_agent_runtime_run_scope_started",
        ENVELOPES,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "started_at",
        ],
    )

    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=160), nullable=True),
        sa.Column("adapter_sha256", sa.String(length=64), nullable=True),
        sa.Column("provider_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_sha256", sa.String(length=64), nullable=True),
        sa.Column("adapter_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("eval_sha256", sa.String(length=64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(30, 18), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("safe_payload_json", sa.JSON(), nullable=False),
        sa.Column("previous_event_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            EXACT_SCOPE,
            tuple(f"{ENVELOPES}.{item}" for item in EXACT_SCOPE),
            name="fk_agent_runtime_event_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            *EXACT_SCOPE,
            "event_index",
            name="uq_agent_runtime_event_ordinal",
        ),
        sa.UniqueConstraint(
            "run_id",
            "event_sha256",
            name="uq_agent_runtime_event_hash",
        ),
        sa.UniqueConstraint(
            "evidence_id",
            name="uq_agent_runtime_event_evidence",
        ),
        sa.CheckConstraint("event_index > 0", name="ck_agent_runtime_event_index"),
        sa.CheckConstraint(
            "event_type IN ('run_started','route_selected','attempt_started',"
            "'attempt_completed','attempt_denied','attempt_failed','eval_completed',"
            "'run_succeeded','run_failed','run_denied','unknown_outcome')",
            name="ck_agent_runtime_event_type",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[a-zA-Z0-9_.:\\-\\[\\]]{1,160}$'",
            name="ck_agent_runtime_reason_code",
        ),
        sa.CheckConstraint(
            "authority_sha256 ~ '^[0-9a-f]{64}$' "
            "AND previous_event_sha256 ~ '^[0-9a-f]{64}$' "
            "AND event_sha256 ~ '^[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^[0-9a-f]{64}$' "
            "AND (adapter_sha256 IS NULL OR adapter_sha256 ~ '^[0-9a-f]{64}$') "
            "AND (provider_sha256 IS NULL OR provider_sha256 ~ '^[0-9a-f]{64}$') "
            "AND (model_sha256 IS NULL OR model_sha256 ~ '^[0-9a-f]{64}$') "
            "AND (adapter_config_sha256 IS NULL OR adapter_config_sha256 ~ '^[0-9a-f]{64}$') "
            "AND (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$') "
            "AND (eval_sha256 IS NULL OR eval_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_agent_runtime_event_hashes",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0",
            name="ck_agent_runtime_event_metrics",
        ),
        sa.CheckConstraint(
            "cost_usd >= 0 "
            "AND cost_usd::text NOT IN ('NaN','Infinity','-Infinity')",
            name="ck_agent_runtime_event_cost",
        ),
    )
    op.create_index(
        "ix_agent_runtime_event_run",
        EVENTS,
        ["run_id", "event_index"],
    )
    op.create_index(
        "uq_governed_agent_run_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(
            f"source = '{EVIDENCE_SOURCE}'"
        ),
    )
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION kjds_validate_agent_runtime_event_append()
            RETURNS trigger AS $$
            DECLARE
                previous_index integer;
                previous_type text;
                previous_sha256 text;
                previous_occurred_at timestamptz;
            BEGIN
                PERFORM 1
                FROM {ENVELOPES}
                WHERE run_id = NEW.run_id
                  AND tenant_ref = NEW.tenant_ref
                  AND entity_ref = NEW.entity_ref
                  AND store_ref = NEW.store_ref
                  AND authority_sha256 = NEW.authority_sha256
                FOR UPDATE;

                SELECT event_index, event_type, event_sha256, occurred_at
                INTO previous_index, previous_type, previous_sha256,
                     previous_occurred_at
                FROM {EVENTS}
                WHERE run_id = NEW.run_id
                ORDER BY event_index DESC
                LIMIT 1;

                IF previous_index IS NULL THEN
                    IF NEW.event_index <> 1
                       OR NEW.event_type <> 'run_started'
                       OR NEW.previous_event_sha256 <> repeat('0', 64) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid governed Agent run start event';
                    END IF;
                ELSE
                    IF NEW.event_index <> previous_index + 1
                       OR NEW.previous_event_sha256 <> previous_sha256
                       OR NEW.occurred_at < previous_occurred_at THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid governed Agent run event chain';
                    END IF;
                    IF NOT (
                        (previous_type = 'run_started' AND NEW.event_type IN
                            ('route_selected', 'run_denied')) OR
                        (previous_type = 'route_selected' AND NEW.event_type IN
                            ('attempt_started', 'run_failed', 'unknown_outcome')) OR
                        (previous_type = 'attempt_started' AND NEW.event_type IN
                            ('attempt_completed', 'attempt_denied', 'attempt_failed',
                             'unknown_outcome')) OR
                        (previous_type = 'attempt_completed' AND NEW.event_type IN
                            ('eval_completed', 'unknown_outcome')) OR
                        (previous_type = 'attempt_denied' AND NEW.event_type IN
                            ('run_denied', 'unknown_outcome')) OR
                        (previous_type = 'attempt_failed' AND NEW.event_type IN
                            ('attempt_started', 'run_failed', 'unknown_outcome')) OR
                        (previous_type = 'eval_completed' AND NEW.event_type IN
                            ('run_succeeded', 'unknown_outcome'))
                    ) THEN
                        RAISE EXCEPTION USING
                            ERRCODE = '23514',
                            MESSAGE = 'invalid governed Agent run event transition';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            f'CREATE TRIGGER "trg_{EVENTS}_append_contract" '
            f'BEFORE INSERT ON "{EVENTS}" FOR EACH ROW '
            "EXECUTE FUNCTION kjds_validate_agent_runtime_event_append()"
        )
    )
    for table in (ENVELOPES, EVENTS):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" '
                f'BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    run_count = connection.execute(
        sa.text(
            f"SELECT (SELECT count(*) FROM {ENVELOPES}) + "
            f"(SELECT count(*) FROM {EVENTS})"
        )
    ).scalar_one()
    evidence_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM evidence_records WHERE source = :source"
        ),
        {"source": EVIDENCE_SOURCE},
    ).scalar_one()
    if run_count or evidence_count:
        raise RuntimeError(
            "Cannot downgrade 0090 while governed Agent run rows or Evidence exist; "
            "export and explicitly retire the immutable audit domain first"
        )

    for table in (EVENTS, ENVELOPES):
        op.execute(
            f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"'
        )
    op.execute(
        f'DROP TRIGGER IF EXISTS "trg_{EVENTS}_append_contract" ON "{EVENTS}"'
    )
    op.execute("DROP FUNCTION IF EXISTS kjds_validate_agent_runtime_event_append()")
    op.drop_index(
        "uq_governed_agent_run_evidence_source_ref",
        table_name="evidence_records",
    )
    op.drop_index("ix_agent_runtime_event_run", table_name=EVENTS)
    op.drop_table(EVENTS)
    op.drop_index("ix_agent_runtime_run_scope_started", table_name=ENVELOPES)
    op.drop_table(ENVELOPES)
