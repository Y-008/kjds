"""Add governed exact-scope strategic benchmark snapshots.

Revision ID: 20260803_0093
Revises: 20260803_0092
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260803_0093"
down_revision = "20260803_0092"
branch_labels = None
depends_on = None

SNAPSHOTS = "strategic_benchmark_snapshots"
GROUPS = "strategic_benchmark_groups"
OBSERVATIONS = "strategic_benchmark_observations"
LEADERS = "strategic_benchmark_leaders"
EVIDENCE_LINKS = "strategic_benchmark_evidence_links"
TABLES = (SNAPSHOTS, GROUPS, OBSERVATIONS, LEADERS, EVIDENCE_LINKS)

HEX64 = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_evidence_record_strategic_binding",
        "evidence_records",
        ["id", "blob_sha256", "source", "source_ref", "grade", "effective_at"],
    )
    op.create_index(
        "uq_strategic_benchmark_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'strategic-benchmark-snapshot'"),
    )
    op.create_index(
        "uq_strategic_benchmark_observation_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'strategic-benchmark-observation'"),
    )

    op.create_table(
        SNAPSHOTS,
        sa.Column("snapshot_ref", sa.String(64), primary_key=True),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("registry_schema", sa.String(100), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("group_count", sa.Integer(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(80), nullable=False),
        sa.Column("evidence_source_ref", sa.String(240), nullable=False),
        sa.Column("evidence_grade", sa.String(8), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
            name="fk_strategic_benchmark_snapshot_exact_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "idempotency_sha256",
            name="uq_strategic_benchmark_scope_idempotency",
        ),
        sa.UniqueConstraint(
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_snapshot_exact_scope",
        ),
        sa.UniqueConstraint(
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "as_of",
            "registry_sha256",
            name="uq_strategic_benchmark_snapshot_exact_context",
        ),
        sa.CheckConstraint(
            "group_count > 0 AND observation_count > 0",
            name="ck_strategic_benchmark_snapshot_counts",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND registry_sha256 ~ '{HEX64}' "
            f"AND evidence_sha256 ~ '{HEX64}' "
            f"AND request_sha256 ~ '{HEX64}' "
            f"AND idempotency_sha256 ~ '{HEX64}'",
            name="ck_strategic_benchmark_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "evidence_source = 'strategic-benchmark-snapshot' "
            "AND evidence_source_ref = 'strategic-benchmark-snapshot://' || snapshot_ref "
            "AND evidence_grade = 'D' AND evidence_effective_at = as_of",
            name="ck_strategic_benchmark_snapshot_evidence_contract",
        ),
    )
    op.create_index(
        "ix_strategic_benchmark_scope_created",
        SNAPSHOTS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "created_at",
            "snapshot_ref",
        ],
    )
    op.create_index(
        "ix_strategic_benchmark_snapshot_evidence", SNAPSHOTS, ["evidence_id"]
    )

    op.create_table(
        GROUPS,
        sa.Column("group_ref", sa.String(64), primary_key=True),
        sa.Column("snapshot_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(80), nullable=False),
        sa.Column("metric_id", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("unit", sa.String(80), nullable=False),
        sa.Column("minimum_source_grade", sa.String(1), nullable=False),
        sa.Column("freshness_days", sa.Integer(), nullable=False),
        sa.Column("cohort_ref", sa.String(160), nullable=False),
        sa.Column("market", sa.String(160), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("methodology_id", sa.String(160), nullable=False),
        sa.Column("methodology_version", sa.String(80), nullable=False),
        sa.Column("methodology_sha256", sa.String(64), nullable=False),
        sa.Column("sample_definition_sha256", sa.String(64), nullable=False),
        sa.Column("source_contract_id", sa.String(160), nullable=False),
        sa.Column("source_contract_version", sa.String(80), nullable=False),
        sa.Column("source_contract_sha256", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(80), nullable=False),
        sa.Column("comparison_state", sa.String(24), nullable=False),
        sa.Column("leader_label", sa.String(40), nullable=True),
        sa.Column("leader_observation_refs_json", sa.JSON(), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("comparable_count", sa.Integer(), nullable=False),
        sa.Column("ineligible_count", sa.Integer(), nullable=False),
        sa.Column("leader_count", sa.Integer(), nullable=False),
        sa.Column("group_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "as_of",
                "registry_sha256",
            ],
            [
                f"{SNAPSHOTS}.snapshot_ref",
                f"{SNAPSHOTS}.tenant_ref",
                f"{SNAPSHOTS}.entity_ref",
                f"{SNAPSHOTS}.store_ref",
                f"{SNAPSHOTS}.scope_authority_sha256",
                f"{SNAPSHOTS}.as_of",
                f"{SNAPSHOTS}.registry_sha256",
            ],
            name="fk_strategic_benchmark_group_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_group_exact_scope",
        ),
        sa.UniqueConstraint(
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "window_start",
            "window_end",
            name="uq_strategic_benchmark_group_exact_window",
        ),
        sa.UniqueConstraint(
            "snapshot_ref",
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            name="uq_strategic_benchmark_group_comparison_key",
        ),
        sa.UniqueConstraint(
            "snapshot_ref", "ordinal", name="uq_strategic_benchmark_group_ordinal"
        ),
        sa.UniqueConstraint(
            "snapshot_ref", "group_sha256", name="uq_strategic_benchmark_group_hash"
        ),
        sa.CheckConstraint(
            "direction IN ('higher_is_better','lower_is_better')",
            name="ck_strategic_benchmark_direction",
        ),
        sa.CheckConstraint(
            "minimum_source_grade IN ('A','B')",
            name="ck_strategic_benchmark_minimum_grade",
        ),
        sa.CheckConstraint(
            "source_kind IN ('official_first_party','audited_filing',"
            "'licensed_primary','independently_reviewed_internal',"
            "'terms_permitted_public_measurement')",
            name="ck_strategic_benchmark_source_kind",
        ),
        sa.CheckConstraint(
            "comparison_state IN ('comparable','partial','not_comparable',"
            "'no_data','stale','invalidated')",
            name="ck_strategic_benchmark_comparison_state",
        ),
        sa.CheckConstraint(
            "leader_label IS NULL OR leader_label IN "
            "('metric_leader','frontier_candidate','best_feasible_for_kjds')",
            name="ck_strategic_benchmark_leader_label",
        ),
        sa.CheckConstraint(
            "((comparison_state IN ('no_data','stale','invalidated','not_comparable') "
            "AND leader_count = 0 AND leader_label IS NULL) OR "
            "(comparison_state = 'partial' AND leader_count = 0 "
            "AND leader_label IS NULL) OR "
            "(comparison_state = 'comparable' AND "
            "((leader_label = 'metric_leader' AND leader_count = 1) OR "
            "(leader_label IN ('frontier_candidate','best_feasible_for_kjds') "
            "AND leader_count > 0))))",
            name="ck_strategic_benchmark_leader_consistency",
        ),
        sa.CheckConstraint(
            "window_start < window_end AND window_end <= as_of",
            name="ck_strategic_benchmark_window",
        ),
        sa.CheckConstraint(
            "observation_count > 0 AND comparable_count >= 0 "
            "AND ineligible_count >= 0 "
            "AND comparable_count + ineligible_count = observation_count "
            "AND leader_count >= 0 AND leader_count <= comparable_count",
            name="ck_strategic_benchmark_group_counts",
        ),
        sa.CheckConstraint(
            "json_typeof(leader_observation_refs_json) = 'array' "
            "AND json_array_length(leader_observation_refs_json) = leader_count",
            name="ck_strategic_benchmark_leader_projection",
        ),
        sa.CheckConstraint(
            "length(trim(methodology_id)) > 0 "
            "AND length(trim(methodology_version)) > 0 "
            "AND length(trim(source_contract_id)) > 0 "
            "AND length(trim(source_contract_version)) > 0 "
            "AND length(trim(reason_code)) > 0",
            name="ck_strategic_benchmark_group_nonempty_contract",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND registry_sha256 ~ '{HEX64}' "
            f"AND methodology_sha256 ~ '{HEX64}' "
            f"AND sample_definition_sha256 ~ '{HEX64}' "
            f"AND source_contract_sha256 ~ '{HEX64}' "
            f"AND group_sha256 ~ '{HEX64}' AND result_sha256 ~ '{HEX64}'",
            name="ck_strategic_benchmark_group_hashes",
        ),
    )
    op.create_index(
        "ix_strategic_benchmark_dimension",
        GROUPS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            "as_of",
        ],
    )
    op.create_index(
        "ix_strategic_benchmark_scope_metric_snapshot",
        GROUPS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "domain",
            "metric_id",
            "snapshot_ref",
        ],
    )

    op.create_table(
        OBSERVATIONS,
        sa.Column("observation_ref", sa.String(64), primary_key=True),
        sa.Column("group_ref", sa.String(64), nullable=False),
        sa.Column("snapshot_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("subject_token_sha256", sa.String(64), nullable=False),
        sa.Column("subject_class", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(38, 12), nullable=False),
        sa.Column("uncertainty_lower", sa.Numeric(38, 12), nullable=False),
        sa.Column("uncertainty_upper", sa.Numeric(38, 12), nullable=False),
        sa.Column("confidence_bps", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("source_grade", sa.String(8), nullable=False),
        sa.Column("citation_token_hashes_json", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligibility_state", sa.String(32), nullable=False),
        sa.Column("evidence_link_count", sa.Integer(), nullable=False),
        sa.Column("observation_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
                "window_start",
                "window_end",
            ],
            [
                f"{GROUPS}.group_ref",
                f"{GROUPS}.snapshot_ref",
                f"{GROUPS}.tenant_ref",
                f"{GROUPS}.entity_ref",
                f"{GROUPS}.store_ref",
                f"{GROUPS}.scope_authority_sha256",
                f"{GROUPS}.window_start",
                f"{GROUPS}.window_end",
            ],
            name="fk_strategic_benchmark_observation_exact_scope",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "group_ref", "ordinal", name="uq_strategic_benchmark_observation_ordinal"
        ),
        sa.UniqueConstraint(
            "group_ref",
            "subject_token_sha256",
            name="uq_strategic_benchmark_observation_subject",
        ),
        sa.UniqueConstraint(
            "observation_ref",
            "group_ref",
            "snapshot_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            name="uq_strategic_benchmark_observation_exact_scope",
        ),
        sa.CheckConstraint(
            "subject_class IN ('kjds_current','peer','frontier_candidate')",
            name="ck_strategic_benchmark_subject_class",
        ),
        sa.CheckConstraint(
            "value::text NOT IN ('NaN','Infinity','-Infinity') "
            "AND uncertainty_lower::text NOT IN ('NaN','Infinity','-Infinity') "
            "AND uncertainty_upper::text NOT IN ('NaN','Infinity','-Infinity') "
            "AND value >= 0 AND uncertainty_lower >= 0 AND uncertainty_upper >= 0 "
            "AND uncertainty_lower <= value AND value <= uncertainty_upper",
            name="ck_strategic_benchmark_observation_values",
        ),
        sa.CheckConstraint(
            "confidence_bps >= 0 AND confidence_bps <= 10000 AND sample_size > 0",
            name="ck_strategic_benchmark_observation_quality",
        ),
        sa.CheckConstraint(
            "source_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_strategic_benchmark_observation_grade",
        ),
        sa.CheckConstraint(
            "eligibility_state IN ('eligible','ineligible_grade','stale',"
            "'invalidated_source','ineligible_confidence','ineligible_sample')",
            name="ck_strategic_benchmark_observation_state",
        ),
        sa.CheckConstraint(
            "window_start <= observed_at AND observed_at < window_end "
            "AND freshness_due_at >= observed_at",
            name="ck_strategic_benchmark_observation_time",
        ),
        sa.CheckConstraint(
            "evidence_link_count > 0 "
            "AND json_typeof(citation_token_hashes_json) = 'array' "
            "AND json_array_length(citation_token_hashes_json) = evidence_link_count",
            name="ck_strategic_benchmark_observation_evidence_count",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND subject_token_sha256 ~ '{HEX64}' "
            f"AND evidence_snapshot_sha256 ~ '{HEX64}' "
            f"AND observation_sha256 ~ '{HEX64}'",
            name="ck_strategic_benchmark_observation_hashes",
        ),
    )
    op.create_index(
        "ix_strategic_benchmark_observation_subject",
        OBSERVATIONS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_authority_sha256",
            "subject_token_sha256",
            "observed_at",
        ],
    )

    op.create_table(
        LEADERS,
        sa.Column("leader_ref", sa.String(64), primary_key=True),
        sa.Column("observation_ref", sa.String(64), nullable=False),
        sa.Column("group_ref", sa.String(64), nullable=False),
        sa.Column("snapshot_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "observation_ref",
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                f"{OBSERVATIONS}.observation_ref",
                f"{OBSERVATIONS}.group_ref",
                f"{OBSERVATIONS}.snapshot_ref",
                f"{OBSERVATIONS}.tenant_ref",
                f"{OBSERVATIONS}.entity_ref",
                f"{OBSERVATIONS}.store_ref",
                f"{OBSERVATIONS}.scope_authority_sha256",
            ],
            name="fk_strategic_benchmark_leader_exact_observation",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "group_ref",
            "observation_ref",
            name="uq_strategic_benchmark_leader_observation",
        ),
        sa.UniqueConstraint(
            "group_ref", "ordinal", name="uq_strategic_benchmark_leader_ordinal"
        ),
    )
    op.create_index(
        "ix_strategic_benchmark_leader_observation", LEADERS, ["observation_ref"]
    )

    op.create_table(
        EVIDENCE_LINKS,
        sa.Column("link_ref", sa.String(64), primary_key=True),
        sa.Column("observation_ref", sa.String(64), nullable=False),
        sa.Column("group_ref", sa.String(64), nullable=False),
        sa.Column("snapshot_ref", sa.String(64), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_authority_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(80), nullable=False),
        sa.Column("evidence_source_ref", sa.String(240), nullable=False),
        sa.Column("evidence_grade", sa.String(8), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("citation_token_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "observation_ref",
                "group_ref",
                "snapshot_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_authority_sha256",
            ],
            [
                f"{OBSERVATIONS}.observation_ref",
                f"{OBSERVATIONS}.group_ref",
                f"{OBSERVATIONS}.snapshot_ref",
                f"{OBSERVATIONS}.tenant_ref",
                f"{OBSERVATIONS}.entity_ref",
                f"{OBSERVATIONS}.store_ref",
                f"{OBSERVATIONS}.scope_authority_sha256",
            ],
            name="fk_strategic_benchmark_evidence_link_exact_observation",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
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
            name="fk_strategic_benchmark_link_exact_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "observation_ref",
            "evidence_id",
            name="uq_strategic_benchmark_observation_evidence_link",
        ),
        sa.UniqueConstraint(
            "observation_ref",
            "ordinal",
            name="uq_strategic_benchmark_evidence_link_ordinal",
        ),
        sa.UniqueConstraint(
            "snapshot_ref",
            "citation_token_sha256",
            name="uq_strategic_benchmark_citation_token",
        ),
        sa.CheckConstraint(
            "evidence_source = 'strategic-benchmark-observation' "
            "AND evidence_source_ref = "
            "'strategic-benchmark-observation://sha256/' || evidence_sha256",
            name="ck_strategic_benchmark_link_evidence_contract",
        ),
        sa.CheckConstraint(
            "evidence_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_strategic_benchmark_link_grade",
        ),
        sa.CheckConstraint(
            f"scope_authority_sha256 ~ '{HEX64}' "
            f"AND evidence_sha256 ~ '{HEX64}' "
            f"AND citation_token_sha256 ~ '{HEX64}'",
            name="ck_strategic_benchmark_link_hashes",
        ),
    )
    op.create_index(
        "ix_strategic_benchmark_evidence_link_evidence",
        EVIDENCE_LINKS,
        ["evidence_id"],
    )

    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION kjds_check_strategic_benchmark_conservation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_snapshot text;
            snapshot_row strategic_benchmark_snapshots%ROWTYPE;
            group_row strategic_benchmark_groups%ROWTYPE;
            observation_row strategic_benchmark_observations%ROWTYPE;
            actual_count bigint;
            eligible_count bigint;
            ineligible_leader_count bigint;
            relation_json json;
            weakest_grade text;
        BEGIN
            target_snapshot := NEW.snapshot_ref;
            SELECT * INTO snapshot_row
            FROM strategic_benchmark_snapshots
            WHERE snapshot_ref = target_snapshot;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;

            SELECT count(*) INTO actual_count
            FROM strategic_benchmark_groups
            WHERE snapshot_ref = target_snapshot;
            IF actual_count <> snapshot_row.group_count THEN
                RAISE EXCEPTION 'strategic benchmark group count conservation failed';
            END IF;

            SELECT count(*) INTO actual_count
            FROM strategic_benchmark_observations
            WHERE snapshot_ref = target_snapshot;
            IF actual_count <> snapshot_row.observation_count THEN
                RAISE EXCEPTION 'strategic benchmark observation count conservation failed';
            END IF;

            FOR group_row IN
                SELECT * FROM strategic_benchmark_groups
                WHERE snapshot_ref = target_snapshot
            LOOP
                SELECT count(*), count(*) FILTER (WHERE eligibility_state = 'eligible')
                INTO actual_count, eligible_count
                FROM strategic_benchmark_observations
                WHERE group_ref = group_row.group_ref;
                IF actual_count <> group_row.observation_count
                   OR eligible_count <> group_row.comparable_count
                   OR actual_count - eligible_count <> group_row.ineligible_count THEN
                    RAISE EXCEPTION 'strategic benchmark group observation conservation failed';
                END IF;

                SELECT count(*) INTO actual_count
                FROM strategic_benchmark_leaders
                WHERE group_ref = group_row.group_ref;
                SELECT count(*) INTO ineligible_leader_count
                FROM strategic_benchmark_leaders leader
                JOIN strategic_benchmark_observations observation
                  ON observation.observation_ref = leader.observation_ref
                 AND observation.group_ref = leader.group_ref
                 AND observation.snapshot_ref = leader.snapshot_ref
                 AND observation.tenant_ref = leader.tenant_ref
                 AND observation.entity_ref = leader.entity_ref
                 AND observation.store_ref = leader.store_ref
                 AND observation.scope_authority_sha256 = leader.scope_authority_sha256
                WHERE leader.group_ref = group_row.group_ref
                  AND observation.eligibility_state <> 'eligible';
                IF ineligible_leader_count <> 0 THEN
                    RAISE EXCEPTION 'strategic benchmark leader eligibility conservation failed';
                END IF;
                SELECT COALESCE(json_agg(observation_ref ORDER BY ordinal), '[]'::json)
                INTO relation_json
                FROM strategic_benchmark_leaders
                WHERE group_ref = group_row.group_ref;
                IF actual_count <> group_row.leader_count
                   OR relation_json::jsonb <> group_row.leader_observation_refs_json::jsonb THEN
                    RAISE EXCEPTION 'strategic benchmark leader conservation failed';
                END IF;
            END LOOP;

            FOR observation_row IN
                SELECT * FROM strategic_benchmark_observations
                WHERE snapshot_ref = target_snapshot
            LOOP
                SELECT count(*) INTO actual_count
                FROM strategic_benchmark_evidence_links
                WHERE observation_ref = observation_row.observation_ref;
                SELECT COALESCE(json_agg(citation_token_sha256 ORDER BY ordinal), '[]'::json)
                INTO relation_json
                FROM strategic_benchmark_evidence_links
                WHERE observation_ref = observation_row.observation_ref;
                SELECT CASE max(
                    CASE evidence_grade
                        WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3
                        WHEN 'D' THEN 4 ELSE 5
                    END
                )
                    WHEN 1 THEN 'A' WHEN 2 THEN 'B' WHEN 3 THEN 'C'
                    WHEN 4 THEN 'D' WHEN 5 THEN 'UNKNOWN' ELSE NULL
                END INTO weakest_grade
                FROM strategic_benchmark_evidence_links
                WHERE observation_ref = observation_row.observation_ref;
                IF actual_count <> observation_row.evidence_link_count
                   OR relation_json::jsonb <> observation_row.citation_token_hashes_json::jsonb
                   OR weakest_grade IS DISTINCT FROM observation_row.source_grade THEN
                    RAISE EXCEPTION 'strategic benchmark evidence link conservation failed';
                END IF;
            END LOOP;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_conservation "
            f"AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION "
            "kjds_check_strategic_benchmark_conservation()"
        )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE evidence_records, lineage_edges, "
        "strategic_benchmark_snapshots, strategic_benchmark_groups, "
        "strategic_benchmark_observations, strategic_benchmark_leaders, "
        "strategic_benchmark_evidence_links IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM strategic_benchmark_snapshots)
               OR EXISTS (SELECT 1 FROM strategic_benchmark_groups)
               OR EXISTS (SELECT 1 FROM strategic_benchmark_observations)
               OR EXISTS (SELECT 1 FROM strategic_benchmark_leaders)
               OR EXISTS (SELECT 1 FROM strategic_benchmark_evidence_links)
               OR EXISTS (
                   SELECT 1 FROM evidence_records
                   WHERE source IN (
                       'strategic-benchmark-snapshot',
                       'strategic-benchmark-observation'
                   )
               )
               OR EXISTS (
                   SELECT 1 FROM lineage_edges le
                   WHERE le.from_id IN (
                       SELECT id FROM evidence_records
                       WHERE source IN (
                           'strategic-benchmark-snapshot',
                           'strategic-benchmark-observation'
                       )
                   )
                   OR le.to_id IN (
                       SELECT id FROM evidence_records
                       WHERE source IN (
                           'strategic-benchmark-snapshot',
                           'strategic-benchmark-observation'
                       )
                   )
               ) THEN
                RAISE EXCEPTION
                    '0093 downgrade blocked: strategic benchmark evidence exists';
            END IF;
        END;
        $$
        """
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_conservation ON {table}")
    op.execute("DROP FUNCTION kjds_check_strategic_benchmark_conservation()")
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
        op.drop_table(table)
    op.drop_index(
        "uq_strategic_benchmark_observation_source_ref",
        table_name="evidence_records",
    )
    op.drop_index(
        "uq_strategic_benchmark_evidence_source_ref",
        table_name="evidence_records",
    )
    op.drop_constraint(
        "uq_evidence_record_strategic_binding",
        "evidence_records",
        type_="unique",
    )
