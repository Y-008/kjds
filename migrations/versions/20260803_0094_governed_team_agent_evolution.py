"""Add governed team-agent evolution candidates and transition Evidence.

Revision ID: 20260803_0094
Revises: 20260803_0093
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260803_0094"
down_revision = "20260803_0093"
branch_labels = None
depends_on = None

CANDIDATES = "team_agent_evolution_candidates"
EVENTS = "team_agent_evolution_events"
EVIDENCE_LINKS = "team_agent_evolution_evidence_links"
TABLES = (CANDIDATES, EVENTS, EVIDENCE_LINKS)
EVIDENCE_SOURCE = "governed-team-agent-evolution"
AUTHORITY_EVIDENCE_SOURCES = (
    "team-agent-baseline-authority",
    "team-agent-deidentification-authority",
    "team-agent-eval-set-authority",
    "team-agent-license-authority",
    "team-agent-retirement-authority",
    "team-agent-review-authority",
    "team-agent-revocation-authority",
    "team-agent-risk-authority",
    "team-agent-rollback-authority",
    "team-agent-shadow-authority",
)
AUTHORITY_EVIDENCE_SOURCES_SQL = ",".join(
    f"'{source}'" for source in AUTHORITY_EVIDENCE_SOURCES
)
RESERVED_EVIDENCE_SOURCES_SQL = (
    f"'{EVIDENCE_SOURCE}',{AUTHORITY_EVIDENCE_SOURCES_SQL}"
)

HEX64 = "^[0-9a-f]{64}$"
ZERO_SHA256 = "0" * 64

STATES_SQL = (
    "'observation','skill_candidate','evaluation','shadow',"
    "'independent_review','promoted','active','rolled_back','retired'"
)
LEARNING_INPUTS_SQL = (
    "'human_correction','verified_failure','evidence_backed_outcome',"
    "'policy_violation','cost_or_latency_regression','official_source_change'"
)
PURPOSES_SQL = (
    "'event_audit','agent_run','eval_set','baseline','shadow','review',"
    "'risk_authority','rollback','license','deidentification',"
    "'revocation','retirement','graph_observation'"
)


def upgrade() -> None:
    op.create_index(
        "uq_team_agent_evolution_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(f"source = '{EVIDENCE_SOURCE}'"),
    )
    op.create_index(
        "uq_team_agent_authority_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(
            f"source IN ({AUTHORITY_EVIDENCE_SOURCES_SQL})"
        ),
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_prevent_team_agent_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.source IN ({RESERVED_EVIDENCE_SOURCES_SQL}) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = 'governed team-agent Evidence is append-only';
            END IF;
            IF TG_OP = 'UPDATE'
               AND NEW.source IN ({RESERVED_EVIDENCE_SOURCES_SQL}) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '55000',
                    MESSAGE = 'governed team-agent Evidence is append-only';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_gta_evidence_immutable "
        "BEFORE UPDATE OR DELETE ON evidence_records FOR EACH ROW "
        "EXECUTE FUNCTION kjds_prevent_team_agent_evidence_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION kjds_lock_scope_authority_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    concat_ws(
                        chr(31),
                        NEW.tenant_ref,
                        NEW.store_ref,
                        NEW.subject_actor_id
                    ),
                    0
                )
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_gta_scope_authority_write_lock "
        "BEFORE INSERT ON scope_grant_events FOR EACH ROW "
        "EXECUTE FUNCTION kjds_lock_scope_authority_write()"
    )
    op.execute(
        """
        CREATE FUNCTION kjds_lock_team_agent_authority_subject_write()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.source IN (
                'team-agent-license-authority',
                'team-agent-deidentification-authority',
                'team-agent-revocation-authority'
            ) THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        concat_ws(
                            chr(31),
                            'team-agent-authority',
                            NEW.metadata_json ->> 'tenant_ref',
                            NEW.metadata_json ->> 'entity_ref',
                            NEW.metadata_json ->> 'store_ref',
                            NEW.metadata_json ->> 'scope_authority_sha256',
                            NEW.metadata_json ->> 'authority_subject_sha256'
                        ),
                        0
                    )
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_gta_authority_subject_write_lock "
        "BEFORE INSERT ON evidence_records FOR EACH ROW "
        "EXECUTE FUNCTION kjds_lock_team_agent_authority_subject_write()"
    )

    op.create_table(
        CANDIDATES,
        sa.Column("candidate_ref", sa.String(64), primary_key=True),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("candidate_author_actor_id", sa.String(160), nullable=False),
        sa.Column("human_owner_actor_id", sa.String(160), nullable=False),
        sa.Column("skill_id", sa.String(160), nullable=False),
        sa.Column("skill_version", sa.String(100), nullable=False),
        sa.Column("predecessor_candidate_ref", sa.String(64), nullable=True),
        sa.Column("predecessor_skill_version", sa.String(100), nullable=True),
        sa.Column("supersedes_candidate_ref", sa.String(64), nullable=True),
        sa.Column("supersedes_sha256", sa.String(64), nullable=False),
        sa.Column("learning_input_type", sa.String(40), nullable=False),
        sa.Column("agent_role_version_sha256", sa.String(64), nullable=False),
        sa.Column("skill_contract_sha256", sa.String(64), nullable=False),
        sa.Column("eval_set_sha256", sa.String(64), nullable=False),
        sa.Column("model_profile_sha256", sa.String(64), nullable=False),
        sa.Column("tool_contract_sha256", sa.String(64), nullable=False),
        sa.Column("policy_version_sha256", sa.String(64), nullable=False),
        sa.Column("rollback_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("cross_tenant_mode", sa.String(48), nullable=False),
        sa.Column("license_sha256", sa.String(64), nullable=False),
        sa.Column("deidentification_sha256", sa.String(64), nullable=False),
        sa.Column("revocation_contract_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_gta_candidate_exact_scope",
        ),
        sa.UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "skill_version",
            name="uq_gta_candidate_exact_version",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "idempotency_sha256",
            name="uq_gta_candidate_scope_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "skill_id",
            "skill_version",
            name="uq_gta_candidate_skill_version_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "predecessor_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "predecessor_skill_version",
            ],
            [
                f"{CANDIDATES}.candidate_ref",
                f"{CANDIDATES}.tenant_ref",
                f"{CANDIDATES}.entity_ref",
                f"{CANDIDATES}.store_ref",
                f"{CANDIDATES}.scope_authority_sha256",
                f"{CANDIDATES}.skill_version",
            ],
            name="fk_gta_candidate_predecessor_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "supersedes_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                f"{CANDIDATES}.candidate_ref",
                f"{CANDIDATES}.tenant_ref",
                f"{CANDIDATES}.entity_ref",
                f"{CANDIDATES}.store_ref",
                f"{CANDIDATES}.scope_authority_sha256",
            ],
            name="fk_gta_candidate_supersedes_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "candidate_ref ~ '^gtac_[0-9a-f]{32}$'",
            name="ck_gta_candidate_ref",
        ),
        sa.CheckConstraint(
            "length(btrim(tenant_ref)) > 0 "
            "AND length(btrim(entity_ref)) > 0 "
            "AND length(btrim(store_ref)) > 0 "
            "AND length(btrim(candidate_author_actor_id)) > 0 "
            "AND length(btrim(human_owner_actor_id)) > 0 "
            "AND length(btrim(skill_id)) > 0 "
            "AND length(btrim(skill_version)) > 0",
            name="ck_gta_candidate_required_text",
        ),
        sa.CheckConstraint(
            "candidate_author_actor_id <> human_owner_actor_id",
            name="ck_gta_candidate_owner_sod",
        ),
        sa.CheckConstraint(
            "skill_version ~ '^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$' "
            "AND (predecessor_skill_version IS NULL OR "
            "predecessor_skill_version ~ "
            "'^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$')",
            name="ck_gta_candidate_canonical_skill_version",
        ),
        sa.CheckConstraint(
            f"learning_input_type IN ({LEARNING_INPUTS_SQL})",
            name="ck_gta_candidate_learning_input",
        ),
        sa.CheckConstraint(
            "cross_tenant_mode IN ('same_tenant','licensed_deidentified_nonreversible')",
            name="ck_gta_candidate_cross_tenant_mode",
        ),
        sa.CheckConstraint(
            "(cross_tenant_mode = 'same_tenant' "
            f"AND license_sha256 = '{ZERO_SHA256}' "
            f"AND deidentification_sha256 = '{ZERO_SHA256}' "
            f"AND revocation_contract_sha256 = '{ZERO_SHA256}') OR "
            "(cross_tenant_mode = 'licensed_deidentified_nonreversible' "
            f"AND license_sha256 <> '{ZERO_SHA256}' "
            f"AND deidentification_sha256 <> '{ZERO_SHA256}' "
            f"AND revocation_contract_sha256 <> '{ZERO_SHA256}')",
            name="ck_gta_candidate_cross_tenant_hashes",
        ),
        sa.CheckConstraint(
            "(predecessor_candidate_ref IS NULL "
            "AND predecessor_skill_version IS NULL "
            "AND supersedes_candidate_ref IS NULL "
            f"AND supersedes_sha256 = '{ZERO_SHA256}') OR "
            "(predecessor_candidate_ref IS NOT NULL "
            "AND predecessor_skill_version IS NOT NULL "
            "AND supersedes_candidate_ref = predecessor_candidate_ref "
            f"AND supersedes_sha256 <> '{ZERO_SHA256}' "
            "AND predecessor_candidate_ref <> candidate_ref "
            "AND predecessor_skill_version <> skill_version)",
            name="ck_gta_candidate_version_chain",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND supersedes_sha256 ~ '{HEX64}' "
            f"AND agent_role_version_sha256 ~ '{HEX64}' "
            f"AND skill_contract_sha256 ~ '{HEX64}' "
            f"AND eval_set_sha256 ~ '{HEX64}' "
            f"AND model_profile_sha256 ~ '{HEX64}' "
            f"AND tool_contract_sha256 ~ '{HEX64}' "
            f"AND policy_version_sha256 ~ '{HEX64}' "
            f"AND rollback_artifact_sha256 ~ '{HEX64}' "
            f"AND license_sha256 ~ '{HEX64}' "
            f"AND deidentification_sha256 ~ '{HEX64}' "
            f"AND revocation_contract_sha256 ~ '{HEX64}' "
            f"AND request_sha256 ~ '{HEX64}' "
            f"AND idempotency_sha256 ~ '{HEX64}' "
            f"AND content_sha256 ~ '{HEX64}'",
            name="ck_gta_candidate_hashes",
        ),
    )
    op.create_index(
        "uq_gta_candidate_single_successor",
        CANDIDATES,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "supersedes_candidate_ref",
        ],
        unique=True,
        postgresql_where=sa.text("supersedes_candidate_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_gta_candidate_scope_created",
        CANDIDATES,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "created_at",
            "candidate_ref",
        ],
    )

    op.create_table(
        EVENTS,
        sa.Column("event_ref", sa.String(64), primary_key=True),
        sa.Column("candidate_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(40), nullable=False),
        sa.Column("to_state", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("actor_role", sa.String(40), nullable=False),
        sa.Column("risk_actor_id", sa.String(160), nullable=True),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("eval_baseline_passed", sa.Boolean(), nullable=False),
        sa.Column("negative_tests_passed", sa.Boolean(), nullable=False),
        sa.Column("scope_tests_passed", sa.Boolean(), nullable=False),
        sa.Column("shadow_passed", sa.Boolean(), nullable=False),
        sa.Column("external_write_observed", sa.Boolean(), nullable=False),
        sa.Column("zero_external_writes", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(38, 12), nullable=False),
        sa.Column("latency_ms", sa.Numeric(20, 6), nullable=False),
        sa.Column("token_count", sa.BigInteger(), nullable=False),
        sa.Column("risk_authority_sha256", sa.String(64), nullable=False),
        sa.Column("eval_set_id", sa.String(160), nullable=False),
        sa.Column("eval_set_version", sa.String(100), nullable=False),
        sa.Column("eval_set_sha256", sa.String(64), nullable=False),
        sa.Column("baseline_runtime_ref", sa.String(160), nullable=False),
        sa.Column("baseline_runtime_sha256", sa.String(64), nullable=False),
        sa.Column("candidate_runtime_ref", sa.String(160), nullable=False),
        sa.Column("candidate_runtime_sha256", sa.String(64), nullable=False),
        sa.Column("agent_run_ref", sa.String(160), nullable=True),
        sa.Column("agent_run_sha256", sa.String(64), nullable=False),
        sa.Column("eval_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("result_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("review_verdict", sa.String(32), nullable=False),
        sa.Column("rollback_target_candidate_ref", sa.String(64), nullable=True),
        sa.Column("rollback_target_skill_version", sa.String(100), nullable=True),
        sa.Column("rollback_target_content_sha256", sa.String(64), nullable=False),
        sa.Column("rollback_target_runtime_sha256", sa.String(64), nullable=False),
        sa.Column("rollback_target_sha256", sa.String(64), nullable=False),
        sa.Column("graph_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("graph_observation_type", sa.String(80), nullable=False),
        sa.Column("graph_observation_version", sa.String(100), nullable=False),
        sa.Column("graph_effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graph_effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graph_observation_only", sa.Boolean(), nullable=False),
        sa.Column("graph_gate_eligible", sa.Boolean(), nullable=False),
        sa.Column("prev_event_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "insert_xid",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("txid_current()"),
        ),
        sa.ForeignKeyConstraint(
            [
                "candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                f"{CANDIDATES}.candidate_ref",
                f"{CANDIDATES}.tenant_ref",
                f"{CANDIDATES}.entity_ref",
                f"{CANDIDATES}.store_ref",
                f"{CANDIDATES}.scope_authority_sha256",
            ],
            name="fk_gta_event_candidate_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "rollback_target_candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "rollback_target_skill_version",
            ],
            [
                f"{CANDIDATES}.candidate_ref",
                f"{CANDIDATES}.tenant_ref",
                f"{CANDIDATES}.entity_ref",
                f"{CANDIDATES}.store_ref",
                f"{CANDIDATES}.scope_authority_sha256",
                f"{CANDIDATES}.skill_version",
            ],
            name="fk_gta_event_rollback_target",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_ref",
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_gta_event_exact_scope",
        ),
        sa.UniqueConstraint(
            "event_ref",
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "insert_xid",
            name="uq_gta_event_exact_insert",
        ),
        sa.UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "ordinal",
            name="uq_gta_event_candidate_ordinal",
        ),
        sa.UniqueConstraint(
            "candidate_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "idempotency_sha256",
            name="uq_gta_event_candidate_idempotency",
        ),
        sa.UniqueConstraint(
            "candidate_ref",
            "event_sha256",
            name="uq_gta_event_hash_per_candidate",
        ),
        sa.CheckConstraint(
            "event_ref ~ '^gtae_[0-9a-f]{32}$' AND ordinal > 0",
            name="ck_gta_event_identity",
        ),
        sa.CheckConstraint(
            f"from_state IN ({STATES_SQL}) AND to_state IN ({STATES_SQL})",
            name="ck_gta_event_states",
        ),
        sa.CheckConstraint(
            "length(btrim(actor_id)) > 0 "
            "AND length(btrim(actor_role)) > 0 "
            "AND length(btrim(eval_set_id)) > 0 "
            "AND length(btrim(eval_set_version)) > 0 "
            "AND length(btrim(baseline_runtime_ref)) > 0 "
            "AND length(btrim(candidate_runtime_ref)) > 0 "
            "AND length(btrim(graph_observation_type)) > 0 "
            "AND length(btrim(graph_observation_version)) > 0 "
            "AND reason_code ~ '^[a-z0-9_]{1,80}$'",
            name="ck_gta_event_required_text",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND risk_authority_sha256 ~ '{HEX64}' "
            f"AND eval_set_sha256 ~ '{HEX64}' "
            f"AND baseline_runtime_sha256 ~ '{HEX64}' "
            f"AND candidate_runtime_sha256 ~ '{HEX64}' "
            f"AND agent_run_sha256 ~ '{HEX64}' "
            f"AND eval_snapshot_sha256 ~ '{HEX64}' "
            f"AND result_snapshot_sha256 ~ '{HEX64}' "
            f"AND rollback_target_content_sha256 ~ '{HEX64}' "
            f"AND rollback_target_runtime_sha256 ~ '{HEX64}' "
            f"AND rollback_target_sha256 ~ '{HEX64}' "
            f"AND graph_snapshot_sha256 ~ '{HEX64}' "
            f"AND prev_event_sha256 ~ '{HEX64}' "
            f"AND event_sha256 ~ '{HEX64}' "
            f"AND request_sha256 ~ '{HEX64}' "
            f"AND idempotency_sha256 ~ '{HEX64}'",
            name="ck_gta_event_hashes",
        ),
        sa.CheckConstraint(
            "NOT external_write_observed AND zero_external_writes",
            name="ck_gta_event_zero_external_write",
        ),
        sa.CheckConstraint(
            "data_as_of <= occurred_at",
            name="ck_gta_event_data_as_of",
        ),
        sa.CheckConstraint(
            "cost_usd >= 0 "
            "AND cost_usd::text NOT IN ('NaN','Infinity','-Infinity') "
            "AND latency_ms >= 0 "
            "AND latency_ms::text NOT IN ('NaN','Infinity','-Infinity') "
            "AND token_count >= 0",
            name="ck_gta_event_finite_usage",
        ),
        sa.CheckConstraint(
            "graph_observation_only AND NOT graph_gate_eligible "
            "AND graph_effective_from <= occurred_at "
            "AND (graph_effective_until IS NULL "
            "OR graph_effective_from < graph_effective_until)",
            name="ck_gta_event_graph_observation",
        ),
        sa.CheckConstraint(
            "(to_state IN ('skill_candidate','evaluation') "
            "AND NOT eval_baseline_passed AND NOT negative_tests_passed "
            "AND NOT scope_tests_passed AND NOT shadow_passed) OR "
            "(to_state = 'shadow' "
            "AND eval_baseline_passed AND negative_tests_passed "
            "AND scope_tests_passed AND NOT shadow_passed) OR "
            "(to_state IN ('independent_review','promoted','active') "
            "AND eval_baseline_passed AND negative_tests_passed "
            "AND scope_tests_passed AND shadow_passed) OR "
            "to_state IN ('rolled_back','retired')",
            name="ck_gta_event_gate_projection",
        ),
        sa.CheckConstraint(
            "(to_state IN ('skill_candidate','evaluation','shadow') "
            "AND review_verdict = 'not_reviewed') OR "
            "(to_state = 'independent_review' "
            "AND review_verdict = 'approved') OR "
            "(to_state IN ('promoted','active') "
            "AND review_verdict = 'approved') OR "
            "(to_state = 'rolled_back' AND review_verdict = 'rolled_back') OR "
            "(to_state = 'retired' AND review_verdict = 'retired')",
            name="ck_gta_event_review_verdict",
        ),
        sa.CheckConstraint(
            "(to_state = 'rolled_back' "
            "AND rollback_target_candidate_ref IS NOT NULL "
            "AND rollback_target_skill_version IS NOT NULL "
            f"AND rollback_target_content_sha256 <> '{ZERO_SHA256}' "
            f"AND rollback_target_runtime_sha256 <> '{ZERO_SHA256}' "
            f"AND rollback_target_sha256 <> '{ZERO_SHA256}') OR "
            "(to_state <> 'rolled_back' "
            "AND rollback_target_candidate_ref IS NULL "
            "AND rollback_target_skill_version IS NULL "
            f"AND rollback_target_content_sha256 = '{ZERO_SHA256}' "
            f"AND rollback_target_runtime_sha256 = '{ZERO_SHA256}' "
            f"AND rollback_target_sha256 = '{ZERO_SHA256}')",
            name="ck_gta_event_rollback_target",
        ),
        sa.CheckConstraint(
            "(to_state IN ('shadow','independent_review','promoted','active') "
            f"AND (agent_run_ref IS NOT NULL OR agent_run_sha256 <> '{ZERO_SHA256}')) "
            "OR to_state NOT IN ('shadow','independent_review','promoted','active')",
            name="ck_gta_event_agent_run",
        ),
    )
    op.create_index(
        "ix_gta_event_scope_time",
        EVENTS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "occurred_at",
            "event_ref",
        ],
    )
    op.create_index(
        "ix_gta_event_candidate_ordinal",
        EVENTS,
        ["candidate_ref", "ordinal"],
    )

    op.create_table(
        EVIDENCE_LINKS,
        sa.Column("link_ref", sa.String(64), primary_key=True),
        sa.Column("event_ref", sa.String(64), nullable=False),
        sa.Column("candidate_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("event_insert_xid", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(60), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(160), nullable=False),
        sa.Column("evidence_source_ref", sa.String(240), nullable=False),
        sa.Column("evidence_grade", sa.String(8), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "event_ref",
                "candidate_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "event_insert_xid",
            ],
            [
                f"{EVENTS}.event_ref",
                f"{EVENTS}.candidate_ref",
                f"{EVENTS}.tenant_ref",
                f"{EVENTS}.entity_ref",
                f"{EVENTS}.store_ref",
                f"{EVENTS}.scope_authority_sha256",
                f"{EVENTS}.insert_xid",
            ],
            name="fk_gta_link_event_exact_insert",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "evidence_id",
                "evidence_sha256",
                "evidence_source",
                "evidence_source_ref",
                "evidence_grade",
                "evidence_effective_at",
            ],
            [
                "evidence_records.id",
                "evidence_records.blob_sha256",
                "evidence_records.source",
                "evidence_records.source_ref",
                "evidence_records.grade",
                "evidence_records.effective_at",
            ],
            name="fk_gta_link_exact_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "event_ref",
            "ordinal",
            name="uq_gta_link_event_ordinal",
        ),
        sa.UniqueConstraint(
            "event_ref",
            "evidence_id",
            name="uq_gta_link_event_evidence",
        ),
        sa.CheckConstraint(
            "link_ref ~ '^gtal_[0-9a-f]{32}$' AND ordinal > 0",
            name="ck_gta_link_identity",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' AND evidence_sha256 ~ '{HEX64}'",
            name="ck_gta_link_hashes",
        ),
        sa.CheckConstraint(
            f"purpose IN ({PURPOSES_SQL})",
            name="ck_gta_link_purpose",
        ),
        sa.CheckConstraint(
            "evidence_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_gta_link_grade",
        ),
    )
    op.create_index(
        "ix_gta_link_evidence_id",
        EVIDENCE_LINKS,
        ["evidence_id"],
    )

    _create_event_hash_function()
    _create_transition_trigger()
    _create_evidence_link_trigger()
    _create_conservation_trigger()

    for table, trigger in (
        (CANDIDATES, "trg_gta_candidate_immutable"),
        (EVENTS, "trg_gta_event_immutable"),
        (EVIDENCE_LINKS, "trg_gta_link_immutable"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )


def _create_event_hash_function() -> None:
    op.execute(
        f"""
        CREATE FUNCTION kjds_team_agent_event_sha256(event_row {EVENTS})
        RETURNS text
        LANGUAGE SQL
        IMMUTABLE
        STRICT
        AS $$
        SELECT encode(
            sha256(
                convert_to(
                    concat_ws(
                        chr(31),
                        event_row.candidate_ref,
                        event_row.tenant_ref,
                        event_row.entity_ref,
                        event_row.store_ref,
                        event_row.scope_authority_sha256,
                        event_row.ordinal::text,
                        event_row.from_state,
                        event_row.to_state,
                        event_row.actor_id,
                        event_row.actor_role,
                        coalesce(event_row.risk_actor_id, ''),
                        event_row.reason_code,
                        CASE WHEN event_row.eval_baseline_passed
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.negative_tests_passed
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.scope_tests_passed
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.shadow_passed
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.external_write_observed
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.zero_external_writes
                            THEN 'true' ELSE 'false' END,
                        trim_scale(event_row.cost_usd)::text,
                        trim_scale(event_row.latency_ms)::text,
                        event_row.token_count::text,
                        event_row.risk_authority_sha256,
                        event_row.eval_set_id,
                        event_row.eval_set_version,
                        event_row.eval_set_sha256,
                        event_row.baseline_runtime_ref,
                        event_row.baseline_runtime_sha256,
                        event_row.candidate_runtime_ref,
                        event_row.candidate_runtime_sha256,
                        coalesce(event_row.agent_run_ref, ''),
                        event_row.agent_run_sha256,
                        event_row.eval_snapshot_sha256,
                        event_row.result_snapshot_sha256,
                        event_row.review_verdict,
                        coalesce(event_row.rollback_target_candidate_ref, ''),
                        coalesce(event_row.rollback_target_skill_version, ''),
                        event_row.rollback_target_content_sha256,
                        event_row.rollback_target_runtime_sha256,
                        event_row.rollback_target_sha256,
                        event_row.graph_snapshot_sha256,
                        event_row.graph_observation_type,
                        event_row.graph_observation_version,
                        to_char(
                            event_row.graph_effective_from AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US'
                        ) || '+00:00',
                        coalesce(
                            to_char(
                                event_row.graph_effective_until
                                    AT TIME ZONE 'UTC',
                                'YYYY-MM-DD"T"HH24:MI:SS.US'
                            ) || '+00:00',
                            ''
                        ),
                        CASE WHEN event_row.graph_observation_only
                            THEN 'true' ELSE 'false' END,
                        CASE WHEN event_row.graph_gate_eligible
                            THEN 'true' ELSE 'false' END,
                        event_row.prev_event_sha256,
                        event_row.request_sha256,
                        event_row.idempotency_sha256,
                        to_char(
                            event_row.data_as_of AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US'
                        ) || '+00:00',
                        to_char(
                            event_row.occurred_at AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US'
                        ) || '+00:00'
                    ),
                    'UTF8'
                )
            ),
            'hex'
        )
        $$
        """
    )


def _create_transition_trigger() -> None:
    op.execute(
        f"""
        CREATE FUNCTION kjds_validate_team_agent_transition_append()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            candidate_row {CANDIDATES}%ROWTYPE;
            previous_row {EVENTS}%ROWTYPE;
            rollback_target_row {CANDIDATES}%ROWTYPE;
            evaluator_id text;
            shadow_actor_id text;
            reviewer_id text;
            promoter_id text;
        BEGIN
            SELECT * INTO candidate_row
            FROM {CANDIDATES}
            WHERE candidate_ref = NEW.candidate_ref
              AND tenant_ref = NEW.tenant_ref
              AND entity_ref = NEW.entity_ref
              AND store_ref = NEW.store_ref
              AND scope_authority_sha256 = NEW.scope_authority_sha256
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23503',
                    MESSAGE = 'team-agent event exact candidate scope is missing';
            END IF;
            IF NEW.eval_set_sha256 <> candidate_row.eval_set_sha256 THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'event eval set differs from candidate contract';
            END IF;

            IF NEW.event_sha256 <> kjds_team_agent_event_sha256(NEW) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'team-agent event content hash is inconsistent';
            END IF;

            SELECT * INTO previous_row
            FROM {EVENTS}
            WHERE candidate_ref = NEW.candidate_ref
            ORDER BY ordinal DESC
            LIMIT 1;

            IF previous_row.event_ref IS NULL THEN
                IF NEW.ordinal <> 1
                   OR NEW.from_state <> 'observation'
                   OR NEW.to_state <> 'skill_candidate'
                   OR NEW.prev_event_sha256 <> repeat('0', 64)
                   OR NEW.actor_id <> candidate_row.candidate_author_actor_id
                   OR NEW.actor_role <> 'candidate_author'
                   OR NEW.occurred_at <> candidate_row.created_at THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid initial team-agent candidate event';
                END IF;
            ELSE
                IF NEW.ordinal <> previous_row.ordinal + 1
                   OR NEW.from_state <> previous_row.to_state
                   OR NEW.prev_event_sha256 <> previous_row.event_sha256
                   OR NEW.occurred_at < previous_row.occurred_at THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid team-agent event hash/state chain';
                END IF;
                IF NEW.eval_set_id <> previous_row.eval_set_id
                   OR NEW.eval_set_version <> previous_row.eval_set_version
                   OR NEW.eval_set_sha256 <> previous_row.eval_set_sha256 THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'immutable event contract snapshot drift';
                END IF;
                IF previous_row.to_state <> 'skill_candidate'
                   AND (
                       NEW.baseline_runtime_ref <> previous_row.baseline_runtime_ref
                       OR NEW.baseline_runtime_sha256
                            <> previous_row.baseline_runtime_sha256
                       OR NEW.candidate_runtime_ref
                            <> previous_row.candidate_runtime_ref
                       OR NEW.candidate_runtime_sha256
                            <> previous_row.candidate_runtime_sha256
                   ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'frozen baseline/candidate runtime snapshot drift';
                END IF;
                IF NOT (
                    (previous_row.to_state = 'skill_candidate'
                     AND NEW.to_state = 'evaluation') OR
                    (previous_row.to_state = 'evaluation'
                     AND NEW.to_state IN ('shadow','rolled_back')) OR
                    (previous_row.to_state = 'shadow'
                     AND NEW.to_state IN ('independent_review','rolled_back')) OR
                    (previous_row.to_state = 'independent_review'
                     AND NEW.to_state IN ('promoted','rolled_back')) OR
                    (previous_row.to_state = 'promoted'
                     AND NEW.to_state IN ('active','rolled_back')) OR
                    (previous_row.to_state = 'active'
                     AND NEW.to_state IN ('rolled_back','retired')) OR
                    (previous_row.to_state = 'rolled_back'
                     AND NEW.to_state = 'retired')
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'invalid team-agent lifecycle transition';
                END IF;
                IF NEW.to_state IN ('rolled_back','retired')
                   AND (
                       NEW.eval_baseline_passed
                            <> previous_row.eval_baseline_passed
                       OR NEW.negative_tests_passed
                            <> previous_row.negative_tests_passed
                       OR NEW.scope_tests_passed
                            <> previous_row.scope_tests_passed
                       OR NEW.shadow_passed <> previous_row.shadow_passed
                   ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'terminal event may not rewrite Gate history';
                END IF;
            END IF;

            SELECT actor_id INTO evaluator_id FROM {EVENTS}
            WHERE candidate_ref = NEW.candidate_ref AND to_state = 'evaluation'
            ORDER BY ordinal DESC LIMIT 1;
            SELECT actor_id INTO shadow_actor_id FROM {EVENTS}
            WHERE candidate_ref = NEW.candidate_ref AND to_state = 'shadow'
            ORDER BY ordinal DESC LIMIT 1;
            SELECT actor_id INTO reviewer_id FROM {EVENTS}
            WHERE candidate_ref = NEW.candidate_ref
              AND to_state = 'independent_review'
            ORDER BY ordinal DESC LIMIT 1;
            SELECT actor_id INTO promoter_id FROM {EVENTS}
            WHERE candidate_ref = NEW.candidate_ref AND to_state = 'promoted'
            ORDER BY ordinal DESC LIMIT 1;

            IF NEW.to_state = 'evaluation'
               AND (
                   NEW.actor_role <> 'evaluator'
                   OR NEW.actor_id IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'evaluator separation of duties failed';
            END IF;
            IF NEW.to_state = 'shadow'
               AND (
                   NEW.actor_role <> 'shadow_operator'
                   OR NEW.actor_id IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id,
                       evaluator_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'shadow operator separation of duties failed';
            END IF;
            IF NEW.to_state = 'independent_review'
               AND (
                   NEW.actor_role <> 'independent_reviewer'
                   OR NEW.actor_id IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id,
                       evaluator_id,
                       shadow_actor_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'independent reviewer separation of duties failed';
            END IF;
            IF NEW.to_state = 'promoted'
               AND (
                   NEW.actor_role <> 'promoter'
                   OR NEW.actor_id IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id,
                       evaluator_id,
                       shadow_actor_id,
                       reviewer_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'promoter separation of duties failed';
            END IF;
            IF NEW.to_state = 'active'
               AND (
                   NEW.actor_role <> 'human_owner'
                   OR NEW.actor_id <> candidate_row.human_owner_actor_id
                   OR NEW.risk_actor_id IS NULL
                   OR NEW.risk_actor_id IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id,
                       evaluator_id,
                       shadow_actor_id,
                       reviewer_id,
                       promoter_id
                   )
                   OR NEW.risk_authority_sha256 = repeat('0', 64)
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'active state owner/risk authority Gate failed';
            END IF;
            IF NEW.to_state = 'rolled_back'
               AND NOT (
                   NEW.actor_id = candidate_row.human_owner_actor_id
                   AND NEW.actor_role = 'human_owner'
                   OR NEW.actor_role IN ('risk','compliance')
                   AND NEW.actor_id NOT IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'rollback actor is not owner or independent risk/compliance';
            END IF;
            IF NEW.to_state = 'rolled_back' THEN
                SELECT * INTO rollback_target_row FROM {CANDIDATES}
                WHERE candidate_ref = NEW.rollback_target_candidate_ref
                  AND tenant_ref = NEW.tenant_ref
                  AND entity_ref = NEW.entity_ref
                  AND store_ref = NEW.store_ref
                  AND scope_authority_sha256 = NEW.scope_authority_sha256;
                IF NOT FOUND
                   OR rollback_target_row.candidate_ref = NEW.candidate_ref
                   OR rollback_target_row.skill_id <> candidate_row.skill_id
                   OR rollback_target_row.skill_version <>
                        NEW.rollback_target_skill_version
                   OR rollback_target_row.content_sha256 <>
                        NEW.rollback_target_content_sha256
                   OR NOT EXISTS (
                        SELECT 1 FROM {EVENTS} approved
                        WHERE approved.candidate_ref = rollback_target_row.candidate_ref
                          AND approved.to_state IN ('promoted','active')
                          AND approved.review_verdict = 'approved'
                          AND approved.candidate_runtime_sha256 =
                                NEW.rollback_target_runtime_sha256
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'rollback target approved snapshot binding failed';
                END IF;
            END IF;
            IF NEW.to_state = 'retired'
               AND NOT (
                   NEW.actor_id = candidate_row.human_owner_actor_id
                   AND NEW.actor_role = 'human_owner'
                   OR NEW.actor_role IN ('risk','compliance')
                   AND NEW.actor_id NOT IN (
                       candidate_row.candidate_author_actor_id,
                       candidate_row.human_owner_actor_id
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'retirement actor is not owner or independent risk/compliance';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_gta_event_append BEFORE INSERT ON {EVENTS} "
        "FOR EACH ROW EXECUTE FUNCTION "
        "kjds_validate_team_agent_transition_append()"
    )


def _create_evidence_link_trigger() -> None:
    op.execute(
        f"""
        CREATE FUNCTION kjds_validate_team_agent_evidence_link()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            event_row {EVENTS}%ROWTYPE;
            candidate_row {CANDIDATES}%ROWTYPE;
            evidence_row evidence_records%ROWTYPE;
            evidence_payload jsonb;
            expected_payload_hash text;
            expected_support_snapshot jsonb;
            expected_support_sha256 text;
            expected_predecessor jsonb;
        BEGIN
            SELECT * INTO event_row FROM {EVENTS}
            WHERE event_ref = NEW.event_ref
              AND candidate_ref = NEW.candidate_ref
              AND tenant_ref = NEW.tenant_ref
              AND entity_ref = NEW.entity_ref
              AND store_ref = NEW.store_ref
              AND scope_authority_sha256 = NEW.scope_authority_sha256;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE = '23503',
                    MESSAGE = 'team-agent Evidence link exact event scope is missing';
            END IF;
            SELECT * INTO candidate_row FROM {CANDIDATES}
            WHERE candidate_ref = NEW.candidate_ref;
            SELECT * INTO evidence_row FROM evidence_records
            WHERE id = NEW.evidence_id
              AND blob_sha256 = NEW.evidence_sha256
              AND source = NEW.evidence_source
              AND source_ref = NEW.evidence_source_ref
              AND grade = NEW.evidence_grade
              AND effective_at = NEW.evidence_effective_at;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE = '23503',
                    MESSAGE = 'team-agent Evidence exact binding is missing';
            END IF;
            SELECT convert_from(content_bytes, 'UTF8')::jsonb
            INTO STRICT evidence_payload
            FROM evidence_blobs
            WHERE sha256 = evidence_row.blob_sha256;

            IF NEW.event_insert_xid <> event_row.insert_xid
               OR NEW.event_insert_xid <> txid_current() THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'late team-agent Evidence link append is prohibited';
            END IF;
            NEW.created_at := event_row.occurred_at;
            IF (NEW.purpose <> 'event_audit'
                AND evidence_row.recorded_at > event_row.occurred_at)
               OR evidence_row.effective_at > event_row.occurred_at
               OR (
                   evidence_row.effective_until IS NOT NULL
                   AND evidence_row.effective_until <= event_row.occurred_at
               )
               OR evidence_row.metadata_json ->> 'tenant_ref'
                    IS DISTINCT FROM NEW.tenant_ref
               OR evidence_row.metadata_json ->> 'entity_ref'
                    IS DISTINCT FROM NEW.entity_ref
               OR evidence_row.metadata_json ->> 'store_ref'
                    IS DISTINCT FROM NEW.store_ref
               OR evidence_row.metadata_json ->> 'scope_authority_sha256'
                    IS DISTINCT FROM NEW.scope_authority_sha256 THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'team-agent Evidence exact scope/time is inconsistent';
            END IF;

            IF NEW.purpose = 'event_audit' THEN
                SELECT coalesce(
                    jsonb_agg(
                        jsonb_build_object(
                            'sha256', link.evidence_sha256,
                            'source', link.evidence_source,
                            'source_ref', link.evidence_source_ref,
                            'grade', link.evidence_grade,
                            'purpose', link.purpose,
                            'claims_sha256', support.metadata_json
                                ->> 'claims_sha256'
                        ) ORDER BY link.evidence_sha256
                    ),
                    '[]'::jsonb
                ), encode(
                    sha256(
                        convert_to(
                            '[' || coalesce(
                                string_agg(
                                    '{{"claims_sha256":'
                                    || to_jsonb(
                                        support.metadata_json
                                            ->> 'claims_sha256'
                                    )::text
                                    || ',"grade":'
                                    || to_jsonb(link.evidence_grade)::text
                                    || ',"purpose":'
                                    || to_jsonb(link.purpose)::text
                                    || ',"sha256":'
                                    || to_jsonb(link.evidence_sha256)::text
                                    || ',"source":'
                                    || to_jsonb(link.evidence_source)::text
                                    || ',"source_ref":'
                                    || to_jsonb(link.evidence_source_ref)::text
                                    || '}}',
                                    ',' ORDER BY link.evidence_sha256
                                ),
                                ''
                            ) || ']',
                            'UTF8'
                        )
                    ),
                    'hex'
                ) INTO expected_support_snapshot, expected_support_sha256
                FROM {EVIDENCE_LINKS} link
                JOIN evidence_records support
                  ON support.id = link.evidence_id
                 AND support.blob_sha256 = link.evidence_sha256
                 AND support.source = link.evidence_source
                 AND support.source_ref = link.evidence_source_ref
                 AND support.grade = link.evidence_grade
                 AND support.effective_at = link.evidence_effective_at
                WHERE link.event_ref = NEW.event_ref
                  AND link.purpose <> 'event_audit';
                expected_predecessor := CASE
                    WHEN candidate_row.predecessor_candidate_ref IS NULL
                    THEN 'null'::jsonb
                    ELSE jsonb_build_object(
                        'predecessor_candidate_ref',
                            candidate_row.predecessor_candidate_ref,
                        'predecessor_skill_version',
                            candidate_row.predecessor_skill_version,
                        'supersedes_sha256', candidate_row.supersedes_sha256
                    )
                END;
                IF NEW.evidence_source <> '{EVIDENCE_SOURCE}'
                   OR NEW.evidence_source_ref <> 'team-agent-evolution://'
                        || NEW.candidate_ref || '/' || NEW.event_ref
                   OR NEW.evidence_grade <> 'D'
                   OR evidence_row.metadata_json ->> 'candidate_ref'
                        IS DISTINCT FROM NEW.candidate_ref
                   OR evidence_row.metadata_json ->> 'event_ref'
                        IS DISTINCT FROM NEW.event_ref
                   OR evidence_row.metadata_json ->> 'event_sha256'
                        IS DISTINCT FROM event_row.event_sha256
                   OR evidence_row.metadata_json ->> 'evolution_purpose'
                        IS DISTINCT FROM 'event_audit'
                   OR evidence_row.metadata_json ->> 'contract_id'
                        IS DISTINCT FROM
                        'kjds-governed-team-agent-evolution-evidence-v1'
                   OR (evidence_payload ->> 'data_as_of')::timestamptz
                        IS DISTINCT FROM event_row.data_as_of
                   OR evidence_payload - 'data_as_of' IS DISTINCT FROM
                        jsonb_build_object(
                            'contract_id',
                                'kjds-governed-team-agent-evolution-evidence-v1',
                            'candidate_ref', event_row.candidate_ref,
                            'event_ref', event_row.event_ref,
                            'event_sha256', event_row.event_sha256,
                            'from_state', event_row.from_state,
                            'to_state', event_row.to_state,
                            'supporting_evidence', expected_support_snapshot,
                            'supporting_evidence_sha256',
                                expected_support_sha256,
                            'payload_status', 'hash_and_code_only',
                            'observation_only', true,
                            'runtime_activation_performed', false,
                            'formal_fact_created', false,
                            'external_write_performed', false,
                            'predecessor', expected_predecessor
                        ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'team-agent event audit Evidence is inconsistent';
                END IF;
            ELSE
                IF evidence_payload ->> 'contract_id'
                        IS DISTINCT FROM
                        'kjds-governed-team-agent-evolution-evidence-v1'
                   OR evidence_payload ->> 'source_contract_id'
                        IS DISTINCT FROM
                        evidence_row.metadata_json ->> 'source_contract_id'
                   OR evidence_payload ->> 'purpose'
                        IS DISTINCT FROM NEW.purpose
                   OR evidence_payload ->> 'source'
                        IS DISTINCT FROM evidence_row.source
                   OR evidence_payload ->> 'source_ref'
                        IS DISTINCT FROM evidence_row.source_ref
                   OR evidence_payload ->> 'grade'
                        IS DISTINCT FROM evidence_row.grade
                   OR evidence_payload -> 'scope' IS DISTINCT FROM
                        jsonb_build_object(
                            'tenant_ref', NEW.tenant_ref,
                            'entity_ref', NEW.entity_ref,
                            'store_ref', NEW.store_ref,
                            'scope_authority_sha256', NEW.scope_authority_sha256
                        )
                   OR evidence_payload ->> 'payload_sha256'
                        IS DISTINCT FROM
                        evidence_row.metadata_json ->> 'payload_sha256'
                   OR jsonb_typeof(evidence_payload -> 'claims')
                        IS DISTINCT FROM 'object'
                   OR NOT (
                        evidence_row.metadata_json::jsonb
                        @> (evidence_payload -> 'claims')
                   )
                   OR evidence_row.metadata_json ->> 'evolution_purpose'
                        IS DISTINCT FROM NEW.purpose
                   OR NEW.evidence_source IS DISTINCT FROM (CASE NEW.purpose
                        WHEN 'agent_run' THEN 'governed-agent-run-evidence'
                        WHEN 'eval_set' THEN 'team-agent-eval-set-authority'
                        WHEN 'baseline' THEN 'team-agent-baseline-authority'
                        WHEN 'shadow' THEN 'team-agent-shadow-authority'
                        WHEN 'review' THEN 'team-agent-review-authority'
                        WHEN 'risk_authority' THEN 'team-agent-risk-authority'
                        WHEN 'rollback' THEN 'team-agent-rollback-authority'
                        WHEN 'license' THEN 'team-agent-license-authority'
                        WHEN 'deidentification'
                            THEN 'team-agent-deidentification-authority'
                        WHEN 'revocation' THEN 'team-agent-revocation-authority'
                        WHEN 'retirement' THEN 'team-agent-retirement-authority'
                        WHEN 'graph_observation'
                            THEN 'strategic-benchmark-observation'
                        ELSE NULL
                   END)
                   OR NEW.evidence_grade IS DISTINCT FROM (CASE NEW.purpose
                        WHEN 'agent_run' THEN 'B'
                        WHEN 'baseline' THEN 'B'
                        WHEN 'shadow' THEN 'B'
                        WHEN 'graph_observation' THEN 'B'
                        ELSE 'A'
                   END)
                   OR evidence_row.metadata_json ->> 'source_contract_id'
                        IS DISTINCT FROM (CASE NEW.purpose
                        WHEN 'agent_run'
                            THEN 'kjds-governed-agent-run-evidence-v1'
                        WHEN 'eval_set'
                            THEN 'kjds-team-agent-eval-set-authority-v1'
                        WHEN 'baseline'
                            THEN 'kjds-team-agent-baseline-authority-v1'
                        WHEN 'shadow'
                            THEN 'kjds-team-agent-shadow-authority-v1'
                        WHEN 'review'
                            THEN 'kjds-team-agent-review-authority-v1'
                        WHEN 'risk_authority'
                            THEN 'kjds-team-agent-risk-authority-v1'
                        WHEN 'rollback'
                            THEN 'kjds-team-agent-rollback-authority-v1'
                        WHEN 'license'
                            THEN 'kjds-team-agent-license-authority-v1'
                        WHEN 'deidentification'
                            THEN 'kjds-team-agent-deidentification-authority-v1'
                        WHEN 'revocation'
                            THEN 'kjds-team-agent-revocation-authority-v1'
                        WHEN 'retirement'
                            THEN 'kjds-team-agent-retirement-authority-v1'
                        WHEN 'graph_observation'
                            THEN 'kjds-team-agent-graph-observation-v1'
                        ELSE NULL
                   END) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'team-agent supporting Evidence authority contract is inconsistent';
                END IF;
                expected_payload_hash := CASE NEW.purpose
                    WHEN 'license' THEN candidate_row.license_sha256
                    WHEN 'deidentification'
                        THEN candidate_row.deidentification_sha256
                    WHEN 'revocation'
                        THEN candidate_row.revocation_contract_sha256
                    WHEN 'graph_observation' THEN event_row.graph_snapshot_sha256
                    WHEN 'eval_set' THEN event_row.eval_set_sha256
                    WHEN 'agent_run' THEN event_row.agent_run_sha256
                    ELSE NULL
                END;
                IF expected_payload_hash IS NOT NULL
                   AND evidence_row.metadata_json ->> 'payload_sha256'
                        IS DISTINCT FROM expected_payload_hash THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'team-agent supporting Evidence payload hash drift';
                END IF;
                IF NEW.purpose IN (
                    'eval_set','baseline','shadow','review','risk_authority',
                    'rollback','license','deidentification','revocation','retirement'
                )
                   AND evidence_row.created_by IN (
                        candidate_row.candidate_author_actor_id,
                        candidate_row.human_owner_actor_id
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'team-agent authority signer separation of duties failed';
                END IF;
                IF NEW.purpose = 'agent_run'
                   AND (
                        evidence_row.metadata_json ->> 'agent_run_ref'
                            IS DISTINCT FROM event_row.agent_run_ref
                        OR evidence_row.metadata_json ->> 'runtime_sha256'
                            IS DISTINCT FROM event_row.candidate_runtime_sha256
                        OR evidence_row.metadata_json ->> 'snapshot_sha256'
                            IS DISTINCT FROM event_row.agent_run_sha256
                        OR evidence_row.metadata_json ->> 'zero_external_writes'
                            IS DISTINCT FROM 'true'
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'AgentRun Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'eval_set'
                   AND (
                        evidence_row.metadata_json ->> 'eval_set_sha256'
                            IS DISTINCT FROM event_row.eval_set_sha256
                        OR evidence_row.metadata_json ->> 'eval_set_sha256'
                            IS DISTINCT FROM candidate_row.eval_set_sha256
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'eval-set Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'baseline'
                   AND (
                        evidence_row.metadata_json ->> 'baseline_runtime_ref'
                            IS DISTINCT FROM event_row.baseline_runtime_ref
                        OR evidence_row.metadata_json
                            ->> 'baseline_runtime_sha256'
                            IS DISTINCT FROM event_row.baseline_runtime_sha256
                        OR evidence_row.metadata_json ->> 'candidate_runtime_ref'
                            IS DISTINCT FROM event_row.candidate_runtime_ref
                        OR evidence_row.metadata_json
                            ->> 'candidate_runtime_sha256'
                            IS DISTINCT FROM event_row.candidate_runtime_sha256
                        OR evidence_row.metadata_json
                            ->> 'candidate_agent_run_ref'
                            IS DISTINCT FROM event_row.agent_run_ref
                        OR evidence_row.metadata_json
                            ->> 'candidate_agent_run_sha256'
                            IS DISTINCT FROM event_row.agent_run_sha256
                        OR evidence_row.metadata_json ->> 'eval_baseline_passed'
                            IS DISTINCT FROM 'true'
                        OR evidence_row.metadata_json ->> 'negative_tests_passed'
                            IS DISTINCT FROM 'true'
                        OR evidence_row.metadata_json ->> 'scope_tests_passed'
                            IS DISTINCT FROM 'true'
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'baseline Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'shadow'
                   AND (
                        evidence_row.metadata_json ->> 'agent_run_ref'
                            IS DISTINCT FROM event_row.agent_run_ref
                        OR evidence_row.metadata_json ->> 'runtime_sha256'
                            IS DISTINCT FROM event_row.candidate_runtime_sha256
                        OR evidence_row.metadata_json ->> 'snapshot_sha256'
                            IS DISTINCT FROM event_row.agent_run_sha256
                        OR evidence_row.metadata_json ->> 'shadow_passed'
                            IS DISTINCT FROM 'true'
                        OR evidence_row.metadata_json ->> 'zero_external_writes'
                            IS DISTINCT FROM 'true'
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'shadow Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'review'
                   AND (
                        evidence_row.metadata_json ->> 'review_verdict'
                            IS DISTINCT FROM event_row.review_verdict
                        OR event_row.to_state = 'independent_review'
                        AND evidence_row.created_by
                            IS DISTINCT FROM event_row.actor_id
                        OR event_row.to_state IN ('promoted','active')
                        AND NOT EXISTS (
                            SELECT 1 FROM {EVENTS} reviewed
                            WHERE reviewed.candidate_ref = event_row.candidate_ref
                              AND reviewed.to_state = 'independent_review'
                              AND reviewed.actor_id = evidence_row.created_by
                              AND reviewed.ordinal < event_row.ordinal
                        )
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'review Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'risk_authority'
                   AND (
                        evidence_row.metadata_json ->> 'current'
                            IS DISTINCT FROM 'true'
                        OR evidence_row.created_by IN (
                            candidate_row.candidate_author_actor_id,
                            candidate_row.human_owner_actor_id
                        )
                        OR event_row.to_state = 'promoted'
                        AND (
                            evidence_row.created_by = event_row.actor_id
                            OR EXISTS (
                                SELECT 1 FROM {EVENTS} gate_actor
                                WHERE gate_actor.candidate_ref = event_row.candidate_ref
                                  AND gate_actor.ordinal < event_row.ordinal
                                  AND gate_actor.to_state IN (
                                    'evaluation','shadow','independent_review'
                                  )
                                  AND gate_actor.actor_id = evidence_row.created_by
                            )
                        )
                        OR event_row.to_state = 'active'
                        AND (
                            evidence_row.metadata_json
                                ->> 'risk_authority_sha256'
                                IS DISTINCT FROM event_row.risk_authority_sha256
                            OR evidence_row.created_by
                                IS DISTINCT FROM event_row.risk_actor_id
                        )
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'risk authority Evidence event binding failed';
                END IF;
                IF NEW.purpose = 'deidentification'
                   AND evidence_row.metadata_json ->> 'nonreversible'
                        IS DISTINCT FROM 'true' THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'cross-tenant projection is not nonreversible';
                END IF;
                IF NEW.purpose IN ('license','deidentification','revocation') THEN
                    IF evidence_row.metadata_json ->> 'current'
                            IS DISTINCT FROM 'true'
                       OR coalesce(
                            evidence_row.metadata_json
                                ->> 'authority_subject_sha256',
                            ''
                       ) !~ '{HEX64}'
                       OR coalesce(
                            evidence_row.metadata_json ->> 'authority_epoch',
                            ''
                       ) !~ '^[1-9][0-9]*$'
                       OR (
                            NEW.purpose = 'revocation'
                            AND evidence_row.metadata_json ->> 'revoked'
                                IS DISTINCT FROM 'false'
                       ) THEN
                        RAISE EXCEPTION USING ERRCODE = '23514',
                            MESSAGE = 'cross-tenant authority state is invalid';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM evidence_records newer
                        WHERE newer.id <> evidence_row.id
                          AND newer.source = evidence_row.source
                          AND newer.metadata_json
                                ->> 'authority_subject_sha256'
                                = evidence_row.metadata_json
                                ->> 'authority_subject_sha256'
                          AND newer.metadata_json ->> 'tenant_ref'
                                = NEW.tenant_ref
                          AND newer.metadata_json ->> 'entity_ref'
                                = NEW.entity_ref
                          AND newer.metadata_json ->> 'store_ref'
                                = NEW.store_ref
                          AND newer.metadata_json
                                ->> 'scope_authority_sha256'
                                = NEW.scope_authority_sha256
                          AND newer.effective_at <= event_row.occurred_at
                          AND newer.recorded_at <= event_row.occurred_at
                          AND coalesce(
                                newer.metadata_json ->> 'authority_epoch',
                                ''
                          ) ~ '^[1-9][0-9]*$'
                          AND (
                            (newer.metadata_json ->> 'authority_epoch')::numeric
                                > (evidence_row.metadata_json
                                    ->> 'authority_epoch')::numeric
                            OR (
                                (newer.metadata_json
                                    ->> 'authority_epoch')::numeric
                                    = (evidence_row.metadata_json
                                        ->> 'authority_epoch')::numeric
                                AND (
                                    newer.effective_at > evidence_row.effective_at
                                    OR newer.effective_at = evidence_row.effective_at
                                    AND newer.recorded_at > evidence_row.recorded_at
                                    OR newer.effective_at = evidence_row.effective_at
                                    AND newer.recorded_at = evidence_row.recorded_at
                                    AND newer.id > evidence_row.id
                                )
                            )
                          )
                    ) THEN
                        RAISE EXCEPTION USING ERRCODE = '23514',
                            MESSAGE = 'cross-tenant authority Evidence is not latest';
                    END IF;
                END IF;
                IF NEW.purpose = 'rollback'
                   AND event_row.to_state = 'rolled_back'
                   AND (
                       evidence_row.metadata_json ->> 'rollback_target_ref'
                            IS DISTINCT FROM
                            event_row.rollback_target_candidate_ref
                       OR evidence_row.metadata_json ->> 'rollback_version'
                            IS DISTINCT FROM
                            event_row.rollback_target_skill_version
                       OR evidence_row.metadata_json
                            ->> 'rollback_target_content_sha256'
                            IS DISTINCT FROM
                            event_row.rollback_target_content_sha256
                       OR evidence_row.metadata_json
                            ->> 'rollback_target_runtime_sha256'
                            IS DISTINCT FROM
                            event_row.rollback_target_runtime_sha256
                       OR evidence_row.metadata_json
                            ->> 'rollback_artifact_sha256'
                            IS DISTINCT FROM candidate_row.rollback_artifact_sha256
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'rollback Evidence target snapshot binding failed';
                END IF;
                IF NEW.purpose = 'graph_observation'
                   AND (
                       evidence_row.metadata_json ->> 'graph_type'
                            IS DISTINCT FROM event_row.graph_observation_type
                       OR evidence_row.metadata_json ->> 'graph_version'
                            IS DISTINCT FROM event_row.graph_observation_version
                       OR evidence_row.metadata_json ->> 'observation_only'
                            IS DISTINCT FROM 'true'
                       OR evidence_row.metadata_json ->> 'gate_eligible'
                            IS DISTINCT FROM 'false'
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Graph Evidence is not observation-only';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_gta_link_exact_evidence "
        f"BEFORE INSERT ON {EVIDENCE_LINKS} FOR EACH ROW "
        "EXECUTE FUNCTION kjds_validate_team_agent_evidence_link()"
    )


def _create_conservation_trigger() -> None:
    op.execute(
        f"""
        CREATE FUNCTION kjds_check_team_agent_evolution_conservation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_candidate text;
            candidate_row {CANDIDATES}%ROWTYPE;
            event_row {EVENTS}%ROWTYPE;
            predecessor_state text;
            predecessor_row {CANDIDATES}%ROWTYPE;
            audit_count bigint;
            support_count bigint;
            required_count bigint;
            invalid_count bigint;
            unexpected_count bigint;
            authority_subject_count bigint;
            authority_epoch_count bigint;
            required_purposes text[];
        BEGIN
            target_candidate := NEW.candidate_ref;
            SELECT * INTO candidate_row FROM {CANDIDATES}
            WHERE candidate_ref = target_candidate;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM {EVENTS}
                WHERE candidate_ref = target_candidate
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'candidate requires initial skill_candidate event';
            END IF;

            IF candidate_row.predecessor_candidate_ref IS NOT NULL THEN
                SELECT * INTO predecessor_row FROM {CANDIDATES}
                WHERE candidate_ref = candidate_row.predecessor_candidate_ref
                  AND tenant_ref = candidate_row.tenant_ref
                  AND entity_ref = candidate_row.entity_ref
                  AND store_ref = candidate_row.store_ref
                  AND scope_authority_sha256 =
                        candidate_row.scope_authority_sha256;
                IF NOT FOUND
                   OR predecessor_row.skill_id <> candidate_row.skill_id
                   OR predecessor_row.skill_version <>
                        candidate_row.predecessor_skill_version
                   OR predecessor_row.skill_version = candidate_row.skill_version
                   OR ARRAY[
                        split_part(candidate_row.skill_version, '.', 1)::numeric,
                        split_part(candidate_row.skill_version, '.', 2)::numeric,
                        split_part(candidate_row.skill_version, '.', 3)::numeric
                   ] <= ARRAY[
                        split_part(predecessor_row.skill_version, '.', 1)::numeric,
                        split_part(predecessor_row.skill_version, '.', 2)::numeric,
                        split_part(predecessor_row.skill_version, '.', 3)::numeric
                   ]
                   OR predecessor_row.content_sha256 <>
                        candidate_row.supersedes_sha256 THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'successor predecessor skill/content binding failed';
                END IF;
                SELECT to_state INTO predecessor_state FROM {EVENTS}
                WHERE candidate_ref = predecessor_row.candidate_ref
                ORDER BY ordinal DESC LIMIT 1;
                IF predecessor_state NOT IN ('rolled_back','retired') THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'successor requires terminal predecessor candidate';
                END IF;
            END IF;

            FOR event_row IN
                SELECT * FROM {EVENTS}
                WHERE candidate_ref = target_candidate
                ORDER BY ordinal
            LOOP
                required_purposes := CASE event_row.to_state
                    WHEN 'skill_candidate' THEN ARRAY['agent_run','eval_set','rollback']
                    WHEN 'evaluation' THEN ARRAY['agent_run','eval_set','baseline']
                    WHEN 'shadow' THEN ARRAY['agent_run','baseline','shadow']
                    WHEN 'independent_review' THEN ARRAY['review','shadow']
                    WHEN 'promoted' THEN ARRAY[
                        'baseline','shadow','review','risk_authority'
                    ]
                    WHEN 'active' THEN ARRAY[
                        'baseline','shadow','review','risk_authority'
                    ]
                    WHEN 'rolled_back' THEN ARRAY['rollback']
                    WHEN 'retired' THEN ARRAY['retirement']
                    ELSE ARRAY[]::text[]
                END;
                IF candidate_row.cross_tenant_mode =
                   'licensed_deidentified_nonreversible' THEN
                    required_purposes := required_purposes || ARRAY[
                        'license','deidentification','revocation'
                    ];
                END IF;

                SELECT count(*) FILTER (WHERE purpose = 'event_audit'),
                       count(*) FILTER (WHERE purpose <> 'event_audit')
                INTO audit_count, support_count
                FROM {EVIDENCE_LINKS}
                WHERE event_ref = event_row.event_ref;
                SELECT count(*) INTO invalid_count
                FROM unnest(required_purposes) required_purpose
                WHERE (
                    SELECT count(*) FROM {EVIDENCE_LINKS} link
                    WHERE link.event_ref = event_row.event_ref
                      AND link.purpose = required_purpose
                      AND link.evidence_grade = CASE required_purpose
                            WHEN 'agent_run' THEN 'B'
                            WHEN 'baseline' THEN 'B'
                            WHEN 'shadow' THEN 'B'
                            WHEN 'graph_observation' THEN 'B'
                            ELSE 'A'
                      END
                ) <> 1;
                SELECT count(*) INTO unexpected_count
                FROM {EVIDENCE_LINKS} link
                WHERE link.event_ref = event_row.event_ref
                  AND link.purpose NOT IN ('event_audit','graph_observation')
                  AND NOT (link.purpose = ANY(required_purposes));
                IF audit_count <> 1
                   OR support_count < cardinality(required_purposes)
                   OR invalid_count <> 0
                   OR unexpected_count <> 0 THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'team-agent event Evidence purpose conservation failed';
                END IF;

                IF candidate_row.cross_tenant_mode =
                   'licensed_deidentified_nonreversible' THEN
                    SELECT count(DISTINCT link.purpose) INTO required_count
                    FROM {EVIDENCE_LINKS} link
                    JOIN {EVENTS} prior ON prior.event_ref = link.event_ref
                    WHERE prior.candidate_ref = target_candidate
                      AND prior.ordinal <= event_row.ordinal
                      AND link.evidence_grade = 'A'
                      AND link.purpose IN ('license','deidentification','revocation');
                    IF required_count <> 3 THEN
                        RAISE EXCEPTION USING ERRCODE = '23514',
                            MESSAGE = 'licensed cross-tenant Evidence Gate is incomplete';
                    END IF;
                    SELECT
                        count(DISTINCT evidence.metadata_json
                            ->> 'authority_subject_sha256'),
                        count(DISTINCT evidence.metadata_json
                            ->> 'authority_epoch')
                    INTO authority_subject_count, authority_epoch_count
                    FROM {EVIDENCE_LINKS} link
                    JOIN evidence_records evidence
                      ON evidence.id = link.evidence_id
                     AND evidence.blob_sha256 = link.evidence_sha256
                     AND evidence.source = link.evidence_source
                     AND evidence.source_ref = link.evidence_source_ref
                     AND evidence.grade = link.evidence_grade
                     AND evidence.effective_at = link.evidence_effective_at
                    WHERE link.event_ref = event_row.event_ref
                      AND link.purpose IN (
                        'license','deidentification','revocation'
                      );
                    IF authority_subject_count <> 1
                       OR authority_epoch_count <> 1 THEN
                        RAISE EXCEPTION USING ERRCODE = '23514',
                            MESSAGE = 'cross-tenant authority epoch/subject drift';
                    END IF;
                ELSIF candidate_row.cross_tenant_mode = 'same_tenant' THEN
                    SELECT count(*) INTO invalid_count
                    FROM {EVIDENCE_LINKS}
                    WHERE event_ref = event_row.event_ref
                      AND purpose IN ('license','deidentification','revocation');
                    IF invalid_count <> 0 THEN
                        RAISE EXCEPTION USING ERRCODE = '23514',
                            MESSAGE = 'same-tenant candidate claims cross-tenant Evidence';
                    END IF;
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$
        """
    )
    for table, suffix in (
        (CANDIDATES, "candidate"),
        (EVENTS, "event"),
        (EVIDENCE_LINKS, "link"),
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_gta_{suffix}_conservation "
            f"AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION "
            "kjds_check_team_agent_evolution_conservation()"
        )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE evidence_records, lineage_edges, "
        "team_agent_evolution_candidates, team_agent_evolution_events, "
        "team_agent_evolution_evidence_links IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {CANDIDATES})
               OR EXISTS (SELECT 1 FROM {EVENTS})
               OR EXISTS (SELECT 1 FROM {EVIDENCE_LINKS})
                OR EXISTS (
                    SELECT 1 FROM evidence_records
                    WHERE source IN ({RESERVED_EVIDENCE_SOURCES_SQL})
                )
               OR EXISTS (
                   SELECT 1 FROM lineage_edges lineage
                   WHERE lineage.from_id IN (
                        SELECT id FROM evidence_records
                        WHERE source IN ({RESERVED_EVIDENCE_SOURCES_SQL})
                    )
                   OR lineage.to_id IN (
                        SELECT id FROM evidence_records
                        WHERE source IN ({RESERVED_EVIDENCE_SOURCES_SQL})
                   )
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0094 downgrade blocked: team-agent evolution Evidence exists';
            END IF;
        END;
        $$
        """
    )

    for table, suffix in reversed(
        (
            (CANDIDATES, "candidate"),
            (EVENTS, "event"),
            (EVIDENCE_LINKS, "link"),
        )
    ):
        op.execute(f"DROP TRIGGER trg_gta_{suffix}_conservation ON {table}")
    op.execute("DROP FUNCTION kjds_check_team_agent_evolution_conservation()")

    for table, trigger in reversed(
        (
            (CANDIDATES, "trg_gta_candidate_immutable"),
            (EVENTS, "trg_gta_event_immutable"),
            (EVIDENCE_LINKS, "trg_gta_link_immutable"),
        )
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute(f"DROP TRIGGER trg_gta_link_exact_evidence ON {EVIDENCE_LINKS}")
    op.execute(f"DROP TRIGGER trg_gta_event_append ON {EVENTS}")
    op.execute("DROP FUNCTION kjds_validate_team_agent_evidence_link()")
    op.execute("DROP FUNCTION kjds_validate_team_agent_transition_append()")
    op.execute(f"DROP FUNCTION kjds_team_agent_event_sha256({EVENTS})")
    op.execute(
        "DROP TRIGGER trg_gta_scope_authority_write_lock ON scope_grant_events"
    )
    op.execute("DROP FUNCTION kjds_lock_scope_authority_write()")
    op.execute(
        "DROP TRIGGER trg_gta_authority_subject_write_lock ON evidence_records"
    )
    op.execute("DROP FUNCTION kjds_lock_team_agent_authority_subject_write()")

    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP TRIGGER trg_gta_evidence_immutable ON evidence_records")
    op.execute("DROP FUNCTION kjds_prevent_team_agent_evidence_mutation()")
    op.drop_index(
        "uq_team_agent_evolution_evidence_source_ref",
        table_name="evidence_records",
    )
    op.drop_index(
        "uq_team_agent_authority_evidence_source_ref",
        table_name="evidence_records",
    )
