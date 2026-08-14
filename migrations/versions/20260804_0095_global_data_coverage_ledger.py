"""Add append-only global data coverage snapshot and event ledger.

Revision ID: 20260804_0095
Revises: 20260803_0094
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "20260804_0095"
down_revision = "20260803_0094"
branch_labels = None
depends_on = None

SNAPSHOTS = "global_data_coverage_snapshots"
CAPS = "global_data_coverage_native_caps"
FIELDS = "global_data_coverage_fields"
PAGES = "global_data_coverage_failed_pages"
WINDOWS = "global_data_coverage_windows"
CONFLICTS = "global_data_coverage_conflicts"
LINKS = "global_data_coverage_evidence_links"
EVENTS = "global_data_coverage_events"
ISSUANCES = "global_data_coverage_evidence_issuances"
ISSUANCE_AUTHORITIES = "global_data_coverage_issuance_authorities"
TABLES = (SNAPSHOTS, CAPS, FIELDS, PAGES, WINDOWS, CONFLICTS, LINKS, EVENTS)
COVERAGE_SOURCES = (
    "global-data-coverage-manifest",
    "global-data-coverage-native-caps",
    "global-data-coverage-denominator",
    "global-data-coverage-ledger",
)
SOURCES_SQL = ",".join(f"'{source}'" for source in COVERAGE_SOURCES)
HEX64 = "^[0-9a-f]{64}$"
ZERO_SHA256 = "0" * 64
ISSUANCE_OWNER_ROLE = "kjds_gdc_issuance_owner"
ISSUANCE_CALLER_ROLE = "kjds_gdc_issuance_runtime"


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(64), nullable=False),
        sa.Column(
            "transaction_stamp",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("txid_current()"),
        ),
    ]


def _child_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [
            "snapshot_id", "tenant_ref", "entity_ref", "store_ref",
            "scope_grant_authority_sha256", "transaction_stamp",
        ],
        [
            f"{SNAPSHOTS}.snapshot_id", f"{SNAPSHOTS}.tenant_ref",
            f"{SNAPSHOTS}.entity_ref", f"{SNAPSHOTS}.store_ref",
            f"{SNAPSHOTS}.scope_grant_authority_sha256",
            f"{SNAPSHOTS}.transaction_stamp",
        ],
        name=f"fk_gdc_{name}_exact_scope",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def _evidence_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [
            "evidence_id", "evidence_sha256", "evidence_source",
            "evidence_source_ref", "evidence_grade", "evidence_effective_at",
        ],
        [
            "evidence_records.id", "evidence_records.blob_sha256",
            "evidence_records.source", "evidence_records.source_ref",
            "evidence_records.grade", "evidence_records.effective_at",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-gdc-issuance-roles'))")
    role_contract = connection.execute(
        sa.text(
            "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
            "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
            "WHERE rolname IN (:owner,:runtime)"
        ),
        {"owner": ISSUANCE_OWNER_ROLE, "runtime": ISSUANCE_CALLER_ROLE},
    ).mappings().all()
    roles = {row["rolname"]: row for row in role_contract}
    owner = roles.get(ISSUANCE_OWNER_ROLE)
    runtime = roles.get(ISSUANCE_CALLER_ROLE)
    if owner is None or runtime is None:
        raise RuntimeError("DATA-COV-002 dedicated issuer principals are not provisioned")
    if (
        owner["rolcanlogin"]
        or owner["rolsuper"]
        or owner["rolinherit"]
        or owner["rolcreaterole"]
        or owner["rolcreatedb"]
        or owner["rolreplication"]
        or not owner["rolbypassrls"]
        or not runtime["rolcanlogin"]
        or runtime["rolsuper"]
        or runtime["rolinherit"]
        or runtime["rolcreaterole"]
        or runtime["rolcreatedb"]
        or runtime["rolreplication"]
        or runtime["rolbypassrls"]
    ):
        raise RuntimeError("DATA-COV-002 dedicated issuer principal contract drifted")
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_auth_members m "
            "JOIN pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_roles member_role ON member_role.oid=m.member "
            "WHERE granted.rolname IN (:runtime,:owner) "
            "OR member_role.rolname IN (:runtime,:owner))"
        ),
        {"runtime": ISSUANCE_CALLER_ROLE, "owner": ISSUANCE_OWNER_ROLE},
    ):
        raise RuntimeError("Coverage issuer principals must not have role members")
    op.create_index(
        "uq_global_data_coverage_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(f"source IN ({SOURCES_SQL})"),
    )
    op.create_table(
        ISSUANCE_AUTHORITIES,
        sa.Column("authority_id", sa.String(80), primary_key=True),
        sa.Column("signing_key_secret", sa.Text(), nullable=False),
        sa.Column("signing_key_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("statement_timestamp()"),
        ),
        sa.CheckConstraint(
            "authority_id='coverage-intake-v1' AND "
            "length(signing_key_secret)>=64 AND "
            "signing_key_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_issuance_authority",
        ),
    )
    op.execute(
        f"INSERT INTO {ISSUANCE_AUTHORITIES} "
        "(authority_id,signing_key_secret,signing_key_sha256) "
        "SELECT 'coverage-intake-v1',secret,encode(pg_catalog.sha256("
        "convert_to(secret,'UTF8')),'hex') FROM (SELECT encode(pg_catalog.sha256("
        "convert_to(pg_catalog.gen_random_uuid()::text || clock_timestamp()::text || "
        "txid_current()::text,'UTF8')),'hex') AS secret) generated"
    )
    op.create_table(
        ISSUANCES,
        sa.Column(
            "evidence_id",
            sa.String(160),
            sa.ForeignKey("evidence_records.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "authority_id",
            sa.String(80),
            sa.ForeignKey(
                f"{ISSUANCE_AUTHORITIES}.authority_id", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("issuance_sha256", sa.String(64), nullable=False),
        sa.Column("issuance_signature_sha256", sa.String(64), nullable=False),
        sa.Column("authority_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "evidence_id",
            "issuance_sha256",
            "issuance_signature_sha256",
            name="uq_gdc_issuance_exact_binding",
        ),
        sa.CheckConstraint(
            "evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "issuance_sha256 ~ '^[0-9a-f]{64}$' AND "
            "issuance_signature_sha256 ~ '^[0-9a-f]{64}$' AND "
            "source IN ('global-data-coverage-manifest',"
            "'global-data-coverage-native-caps',"
            "'global-data-coverage-denominator') AND "
            "source_ref LIKE (source || '://%')",
            name="ck_gdc_issuance_binding",
        ),
    )
    op.create_table(
        SNAPSHOTS,
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        *_scope_columns(),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(240), nullable=False),
        sa.Column("source_family", sa.String(80), nullable=False),
        sa.Column("source_status", sa.String(40), nullable=False),
        sa.Column("source_contract_id", sa.String(240), nullable=False),
        sa.Column("source_contract_version", sa.String(120), nullable=False),
        sa.Column("ledger_contract_id", sa.String(160), nullable=False),
        sa.Column("manifest_ref", sa.String(240), nullable=False),
        sa.Column("manifest_version", sa.String(120), nullable=False),
        sa.Column("manifest_schema_version", sa.String(120), nullable=False),
        sa.Column("manifest_evidence_contract_id", sa.String(160), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_evidence_id", sa.String(160), nullable=False),
        sa.Column("manifest_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("native_caps_schema", sa.String(120), nullable=False),
        sa.Column("native_caps_evidence_contract_id", sa.String(160), nullable=False),
        sa.Column("native_caps_sha256", sa.String(64), nullable=False),
        sa.Column("native_caps_evidence_id", sa.String(160), nullable=False),
        sa.Column("native_caps_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("registry_contract_id", sa.String(160), nullable=False),
        sa.Column("registry_schema_version", sa.String(160), nullable=False),
        sa.Column("registry_as_of", sa.String(32), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False),
        sa.Column("observation_contract_id", sa.String(160), nullable=False),
        sa.Column("observation_sha256", sa.String(64), nullable=False),
        sa.Column("observation_status", sa.String(40), nullable=False),
        sa.Column("completeness", sa.String(40), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("denominator_known", sa.Boolean(), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=True),
        sa.Column("denominator_evidence_ref", sa.String(240), nullable=True),
        sa.Column("denominator_evidence_sha256", sa.String(64), nullable=True),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("suppressed_count", sa.Integer(), nullable=False),
        sa.Column("source_total", sa.Integer(), nullable=False),
        sa.Column("page_expected_count", sa.Integer(), nullable=False),
        sa.Column("page_received_count", sa.Integer(), nullable=False),
        sa.Column("page_failed_count", sa.Integer(), nullable=False),
        sa.Column("page_duplicate_count", sa.Integer(), nullable=False),
        sa.Column("page_closed", sa.Boolean(), nullable=False),
        sa.Column("required_field_count", sa.Integer(), nullable=False),
        sa.Column("window_gap_count", sa.Integer(), nullable=False),
        sa.Column("window_overlap_count", sa.Integer(), nullable=False),
        sa.Column("window_timezone", sa.String(80), nullable=False),
        sa.Column("window_late_arrival_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(64), nullable=False),
        sa.Column("checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint_closed", sa.Boolean(), nullable=False),
        sa.Column("freshness_status", sa.String(40), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due", sa.DateTime(timezone=True), nullable=False),
        sa.Column("full_coverage_claim", sa.Boolean(), nullable=False),
        sa.Column("formal_fact", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.Boolean(), nullable=False),
        sa.Column("approval", sa.Boolean(), nullable=False),
        sa.Column("permit", sa.Boolean(), nullable=False),
        sa.Column("pilot", sa.Boolean(), nullable=False),
        sa.Column("outbox", sa.Boolean(), nullable=False),
        sa.Column("external_write", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id", "tenant_ref", "entity_ref", "store_ref",
            "scope_grant_authority_sha256", name="uq_gdc_snapshot_exact_scope",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "tenant_ref", "entity_ref", "store_ref",
            "scope_grant_authority_sha256", "transaction_stamp",
            name="uq_gdc_snapshot_exact_scope_tx",
        ),
        sa.UniqueConstraint(
            "tenant_ref", "entity_ref", "store_ref",
            "scope_grant_authority_sha256", "idempotency_sha256",
            name="uq_gdc_scope_idempotency",
        ),
        sa.CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^[0-9a-f]{64}$' AND "
            "manifest_evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "native_caps_sha256 ~ '^[0-9a-f]{64}$' AND "
            "native_caps_evidence_sha256 ~ '^[0-9a-f]{64}$' AND "
            "registry_sha256 ~ '^[0-9a-f]{64}$' AND "
            "observation_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "checkpoint_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "transaction_stamp > 0",
            name="ck_gdc_snapshot_transaction_stamp",
        ),
        sa.CheckConstraint(
            "ledger_contract_id='kjds-global-data-coverage-ledger-v1' AND "
            "length(source_contract_id)>0 AND length(source_contract_version)>0 AND "
            "manifest_schema_version='kjds-source-coverage-manifest-v1' AND "
            "manifest_evidence_contract_id='kjds-global-data-coverage-manifest-evidence-v1' AND "
            "native_caps_schema='kjds-source-native-caps-v1' AND "
            "native_caps_evidence_contract_id='kjds-global-data-coverage-native-caps-evidence-v1'",
            name="ck_gdc_snapshot_contracts",
        ),
        sa.CheckConstraint(
            "expected_count IS NULL OR expected_count >= 0",
            name="ck_gdc_expected_count",
        ),
        sa.CheckConstraint(
            "observed_count >= 0 AND accepted_count >= 0 AND quarantined_count >= 0 "
            "AND failed_count >= 0 AND duplicate_count >= 0 AND suppressed_count >= 0 "
            "AND source_total >= 0 AND page_expected_count >= 0 "
            "AND page_received_count >= 0 AND page_failed_count >= 0 "
            "AND page_duplicate_count >= 0 AND checkpoint_sequence >= 0 "
            "AND required_field_count >= 0 AND window_gap_count >= 0 "
            "AND window_overlap_count >= 0 AND window_late_arrival_count >= 0 "
            "AND conflict_count >= 0 AND evidence_count > 0",
            name="ck_gdc_snapshot_nonnegative",
        ),
        sa.CheckConstraint(
            "accepted_count+quarantined_count+failed_count+duplicate_count+suppressed_count=source_total "
            "AND observed_count=source_total",
            name="ck_gdc_snapshot_conservation",
        ),
        sa.CheckConstraint(
            "page_received_count+page_failed_count=page_expected_count",
            name="ck_gdc_page_conservation",
        ),
        sa.CheckConstraint(
            "page_duplicate_count<=page_received_count",
            name="ck_gdc_page_duplicate_conservation",
        ),
        sa.CheckConstraint(
            "(denominator_known AND expected_count IS NOT NULL AND denominator_evidence_ref IS NOT NULL "
            "AND denominator_evidence_sha256 ~ '^[0-9a-f]{64}$') OR "
            "(NOT denominator_known AND expected_count IS NULL AND denominator_evidence_ref IS NULL "
            "AND denominator_evidence_sha256 IS NULL)",
            name="ck_gdc_denominator_matrix",
        ),
        sa.CheckConstraint(
            "captured_at<=recorded_at AND recorded_at<=data_as_of AND "
            "data_as_of<=authority_checked_at AND authority_checked_at<=created_at AND "
            "fresh_until>recorded_at AND review_due>=recorded_at",
            name="ck_gdc_snapshot_chronology",
        ),
        sa.CheckConstraint(
            "NOT formal_fact AND NOT decision AND NOT approval AND NOT permit AND "
            "NOT pilot AND NOT outbox AND NOT external_write",
            name="ck_gdc_no_promotion_or_write",
        ),
        sa.CheckConstraint(
            "source_status IN ('implemented','contract_only','blocked','unsupported') AND "
            "observation_status IN ('complete','partial','unknown','missing','blocked','unsupported','not_applicable') AND "
            "completeness IN ('complete','partial','unknown','missing','blocked','unsupported','not_applicable') AND "
            "observation_status=completeness AND freshness_status IN ('fresh','stale','unknown','blocked') AND "
            "window_timezone='UTC'",
            name="ck_gdc_snapshot_status_vocabulary",
        ),
    )
    op.create_index(
        "ix_gdc_snapshot_scope_source_asof", SNAPSHOTS,
        ["tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256", "source_id", "data_as_of"],
    )

    op.create_table(
        CAPS,
        sa.Column("caps_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("schema_version", sa.String(120), nullable=False),
        sa.Column("source_id", sa.String(240), nullable=False),
        sa.Column("source_family", sa.String(80), nullable=False),
        sa.Column("adapter_id", sa.String(240), nullable=False),
        sa.Column("adapter_version", sa.String(120), nullable=False),
        sa.Column("capability_version", sa.String(120), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("universe_kind", sa.String(40), nullable=False),
        sa.Column("pagination_mode", sa.String(40), nullable=False),
        sa.Column("page_limit", sa.Integer(), nullable=True),
        sa.Column("historical_depth_days", sa.Integer(), nullable=True),
        sa.Column("rate_limit_known", sa.Boolean(), nullable=False),
        sa.Column("authentication_mode", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("caps"),
        sa.UniqueConstraint("snapshot_id", name="uq_gdc_caps_snapshot"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_gdc_caps_hash"),
    )
    op.create_table(
        FIELDS,
        sa.Column("field_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(240), nullable=False),
        sa.Column("field_name_sha256", sa.String(64), nullable=False),
        sa.Column("field_status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("field"),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_field_ordinal"),
        sa.UniqueConstraint("snapshot_id", "field_name", name="uq_gdc_field_name"),
        sa.CheckConstraint("ordinal>0 AND field_name_sha256 ~ '^[0-9a-f]{64}$'", name="ck_gdc_field_ordinal_hash"),
        sa.CheckConstraint("field_status IN ('present','missing','unparseable','conflicting')", name="ck_gdc_field_status"),
    )
    op.create_table(
        PAGES,
        sa.Column("failed_page_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("failed_ref_sha256", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("page"),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_page_ordinal"),
        sa.UniqueConstraint("snapshot_id", "failed_ref_sha256", name="uq_gdc_page_ref"),
        sa.CheckConstraint("ordinal>0 AND failed_ref_sha256 ~ '^[0-9a-f]{64}$'", name="ck_gdc_page_ordinal_hash"),
    )
    op.create_table(
        WINDOWS,
        sa.Column("window_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("segment_kind", sa.String(40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("window"),
        sa.UniqueConstraint("snapshot_id", "segment_kind", "ordinal", name="uq_gdc_window_segment"),
        sa.CheckConstraint("ordinal>0 AND start_at<end_at", name="ck_gdc_window_interval"),
        sa.CheckConstraint("segment_kind IN ('requested','effective','gap','overlap')", name="ck_gdc_window_kind"),
        sa.CheckConstraint("(segment_kind IN ('requested','effective') AND reason_code IS NULL) OR (segment_kind IN ('gap','overlap') AND reason_code IS NOT NULL)", name="ck_gdc_window_reason"),
    )
    op.create_table(
        CONFLICTS,
        sa.Column("conflict_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("conflict_ref_sha256", sa.String(64), nullable=False),
        sa.Column("subject_ref_sha256", sa.String(64), nullable=False),
        sa.Column("field_name_sha256", sa.String(64), nullable=False),
        sa.Column("valid_interval_sha256", sa.String(64), nullable=False),
        sa.Column("value_hash_count", sa.Integer(), nullable=False),
        sa.Column("value_hashes_sha256", sa.String(64), nullable=False),
        sa.Column("resolution_status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("conflict"),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_conflict_ordinal"),
        sa.UniqueConstraint("snapshot_id", "conflict_ref_sha256", name="uq_gdc_conflict_ref"),
        sa.CheckConstraint(
            "ordinal>0 AND conflict_ref_sha256 ~ '^[0-9a-f]{64}$' AND "
            "subject_ref_sha256 ~ '^[0-9a-f]{64}$' AND field_name_sha256 ~ '^[0-9a-f]{64}$' AND "
            "valid_interval_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_conflict_hashes",
        ),
        sa.CheckConstraint(
            "value_hash_count BETWEEN 2 AND 20 AND value_hashes_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_conflict_values",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('unresolved','independently_resolved')",
            name="ck_gdc_conflict_resolution",
        ),
    )
    op.create_table(
        LINKS,
        sa.Column("link_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("evidence_role", sa.String(40), nullable=False),
        sa.Column("evidence_id", sa.String(160), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(160), nullable=False),
        sa.Column("evidence_source_ref", sa.Text(), nullable=False),
        sa.Column("evidence_grade", sa.String(4), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_declared_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intake_issuance_sha256", sa.String(64), nullable=True),
        sa.Column("intake_issuance_signature_sha256", sa.String(64), nullable=True),
        sa.Column("scope_authority_contract_id", sa.String(120), nullable=True),
        sa.Column("scope_binding_evidence_id", sa.String(160), nullable=True),
        sa.Column("scope_binding_evidence_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("evidence"), _evidence_fk("fk_gdc_evidence_exact_binding"),
        sa.ForeignKeyConstraint(
            ["scope_binding_evidence_id"],
            ["evidence_records.id"],
            name="fk_gdc_scope_binding_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "evidence_id",
                "intake_issuance_sha256",
                "intake_issuance_signature_sha256",
            ],
            [
                f"{ISSUANCES}.evidence_id",
                f"{ISSUANCES}.issuance_sha256",
                f"{ISSUANCES}.issuance_signature_sha256",
            ],
            name="fk_gdc_intake_issuance",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_gdc_evidence_ordinal"),
        sa.UniqueConstraint("snapshot_id", "evidence_id", name="uq_gdc_evidence_id"),
        sa.CheckConstraint("ordinal>0 AND evidence_role IN ('manifest','native_caps','denominator','supporting')", name="ck_gdc_evidence_role"),
        sa.CheckConstraint(
            "(evidence_role='manifest' AND evidence_source='global-data-coverage-manifest' AND evidence_grade='A') OR "
            "(evidence_role='native_caps' AND evidence_source='global-data-coverage-native-caps' AND evidence_grade='A') OR "
            "(evidence_role='denominator' AND evidence_source='global-data-coverage-denominator' AND evidence_grade='A') OR "
            "evidence_role='supporting'",
            name="ck_gdc_evidence_role_binding",
        ),
        sa.CheckConstraint(
            "(evidence_role IN ('manifest','native_caps','denominator') "
            "AND intake_issuance_sha256 ~ '^[0-9a-f]{64}$' "
            "AND intake_issuance_signature_sha256 ~ '^[0-9a-f]{64}$' "
            "AND scope_authority_contract_id IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND scope_authority_contract_id='kjds-evidence-scope-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NULL AND scope_binding_evidence_sha256 IS NULL) OR "
            "(evidence_role='supporting' AND scope_authority_contract_id='kjds-evidence-scope-binding-v1' "
            "AND intake_issuance_sha256 IS NULL AND intake_issuance_signature_sha256 IS NULL "
            "AND scope_binding_evidence_id IS NOT NULL "
            "AND scope_binding_evidence_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_gdc_evidence_scope_authority",
        ),
    )
    op.create_index("ix_gdc_evidence_reverse", LINKS, ["evidence_id"])
    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(160), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(160), nullable=False),
        sa.Column("evidence_source_ref", sa.Text(), nullable=False),
        sa.Column("evidence_grade", sa.String(4), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        _child_fk("event"), _evidence_fk("fk_gdc_event_evidence_binding"),
        sa.UniqueConstraint("snapshot_id", "event_index", name="uq_gdc_event_ordinal"),
        sa.UniqueConstraint("snapshot_id", "event_sha256", name="uq_gdc_event_hash"),
        sa.UniqueConstraint("evidence_id", name="uq_gdc_event_evidence"),
        sa.CheckConstraint("event_index>0", name="ck_gdc_event_ordinal"),
        sa.CheckConstraint("event_type IN ('snapshot_started','snapshot_committed','unknown_outcome','invalidated')", name="ck_gdc_event_type"),
        sa.CheckConstraint(
            "occurred_at<=recorded_at AND evidence_effective_at=occurred_at AND "
            "evidence_source='global-data-coverage-ledger' AND evidence_grade='D' AND "
            "evidence_source_ref=('coverage-ledger://' || snapshot_id || '/' || event_id) AND "
            "previous_event_sha256 ~ '^[0-9a-f]{64}$' AND event_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gdc_event_binding",
        ),
    )
    op.create_index("ix_gdc_event_snapshot", EVENTS, ["snapshot_id", "event_index"])

    op.execute(f"""
        CREATE FUNCTION kjds_gdc_prevent_evidence_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.source IN ('global-data-coverage-manifest',
                                  'global-data-coverage-native-caps',
                                  'global-data-coverage-denominator')
                   AND (current_user<>'{ISSUANCE_OWNER_ROLE}' OR
                        session_user<>'{ISSUANCE_CALLER_ROLE}' OR
                        pg_has_role(session_user,'{ISSUANCE_OWNER_ROLE}','SET') OR
                        EXISTS (
                          SELECT 1 FROM pg_auth_members m
                          JOIN pg_roles granted ON granted.oid=m.roleid
                          JOIN pg_roles member_role ON member_role.oid=m.member
                          WHERE granted.rolname IN
                              ('{ISSUANCE_OWNER_ROLE}','{ISSUANCE_CALLER_ROLE}')
                             OR member_role.rolname IN
                              ('{ISSUANCE_OWNER_ROLE}','{ISSUANCE_CALLER_ROLE}')
                             OR granted.rolname=session_user
                             OR member_role.rolname=session_user
                         ) OR NOT EXISTS (
                           SELECT 1 FROM pg_roles owner_role
                           CROSS JOIN pg_roles runtime_role
                           WHERE owner_role.rolname='{ISSUANCE_OWNER_ROLE}'
                             AND NOT owner_role.rolcanlogin
                             AND NOT owner_role.rolsuper
                             AND NOT owner_role.rolinherit
                             AND NOT owner_role.rolcreaterole
                             AND NOT owner_role.rolcreatedb
                             AND NOT owner_role.rolreplication
                             AND owner_role.rolbypassrls
                             AND runtime_role.rolname='{ISSUANCE_CALLER_ROLE}'
                             AND runtime_role.rolcanlogin
                             AND NOT runtime_role.rolsuper
                             AND NOT runtime_role.rolinherit
                             AND NOT runtime_role.rolcreaterole
                             AND NOT runtime_role.rolcreatedb
                             AND NOT runtime_role.rolreplication
                             AND NOT runtime_role.rolbypassrls
                         )) THEN
                    RAISE EXCEPTION USING ERRCODE='42501',
                      MESSAGE='coverage intake Evidence requires the dedicated issuer';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.source IN ({SOURCES_SQL}) OR (TG_OP='UPDATE' AND NEW.source IN ({SOURCES_SQL}))
               OR EXISTS (SELECT 1 FROM {LINKS} l WHERE l.evidence_id=OLD.id
                           OR l.scope_binding_evidence_id=OLD.id) THEN
                RAISE EXCEPTION USING ERRCODE='55000', MESSAGE='global data coverage Evidence is append-only';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END; $$
    """)
    op.execute(
        "CREATE TRIGGER trg_gdc_evidence_immutable BEFORE INSERT OR UPDATE OR DELETE ON evidence_records "
        "FOR EACH ROW EXECUTE FUNCTION kjds_gdc_prevent_evidence_mutation()"
    )
    op.execute(f"""
        CREATE FUNCTION kjds_gdc_canonical_json(value jsonb) RETURNS text
        LANGUAGE plpgsql IMMUTABLE STRICT AS $$
        DECLARE result text;
        BEGIN
            CASE jsonb_typeof(value)
              WHEN 'object' THEN
                SELECT '{{' || COALESCE(string_agg(to_jsonb(key)::text || ':' ||
                       {quoted_schema}.kjds_gdc_canonical_json(item), ',' ORDER BY key), '') || '}}'
                  INTO result FROM jsonb_each(value) AS entries(key,item);
              WHEN 'array' THEN
                SELECT '[' || COALESCE(string_agg({quoted_schema}.kjds_gdc_canonical_json(item),
                       ',' ORDER BY ordinal), '') || ']'
                  INTO result FROM jsonb_array_elements(value)
                       WITH ORDINALITY AS entries(item,ordinal);
              ELSE result := value::text;
            END CASE;
            RETURN result;
        END; $$
    """)
    op.execute(f"""
        CREATE FUNCTION kjds_gdc_issue_evidence(
          p_evidence_id text, p_content bytea, p_source text, p_source_ref text,
          p_effective_at timestamptz, p_effective_until timestamptz,
          p_metadata jsonb, p_issuance_sha256 text,
          p_authority_checked_at timestamptz
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE signing_key text; trusted_key_sha256 text; content_sha256 text;
                expected_purpose text; expected_contract text; expected_schema text;
                expected_issuance text; signature text; final_metadata jsonb;
                evidence {quoted_schema}.evidence_records%ROWTYPE;
                existing {quoted_schema}.{ISSUANCES}%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('kjds-gdc-coverage-ledger-ddl'));
            IF session_user<>'{ISSUANCE_CALLER_ROLE}'
               OR current_user<>'{ISSUANCE_OWNER_ROLE}'
               OR pg_has_role(session_user,'{ISSUANCE_OWNER_ROLE}','SET')
               OR EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles granted ON granted.oid=m.roleid
                    JOIN pg_roles member_role ON member_role.oid=m.member
                    WHERE granted.rolname IN
                        ('{ISSUANCE_OWNER_ROLE}','{ISSUANCE_CALLER_ROLE}')
                       OR member_role.rolname IN
                        ('{ISSUANCE_OWNER_ROLE}','{ISSUANCE_CALLER_ROLE}')
                        OR granted.rolname=session_user
                        OR member_role.rolname=session_user
               ) OR NOT EXISTS (
                    SELECT 1 FROM pg_roles owner_role
                    CROSS JOIN pg_roles runtime_role
                    WHERE owner_role.rolname='{ISSUANCE_OWNER_ROLE}'
                      AND NOT owner_role.rolcanlogin
                      AND NOT owner_role.rolsuper
                      AND NOT owner_role.rolinherit
                      AND NOT owner_role.rolcreaterole
                      AND NOT owner_role.rolcreatedb
                      AND NOT owner_role.rolreplication
                      AND owner_role.rolbypassrls
                      AND runtime_role.rolname='{ISSUANCE_CALLER_ROLE}'
                      AND runtime_role.rolcanlogin
                      AND NOT runtime_role.rolsuper
                      AND NOT runtime_role.rolinherit
                      AND NOT runtime_role.rolcreaterole
                      AND NOT runtime_role.rolcreatedb
                      AND NOT runtime_role.rolreplication
                      AND NOT runtime_role.rolbypassrls
               ) THEN
                RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='coverage issuer principal is invalid';
            END IF;
            CASE p_source
              WHEN 'global-data-coverage-manifest' THEN
                expected_purpose := 'manifest';
                expected_contract := 'kjds-global-data-coverage-manifest-evidence-v1';
                expected_schema := 'kjds-source-coverage-manifest-v1';
              WHEN 'global-data-coverage-native-caps' THEN
                expected_purpose := 'native_caps';
                expected_contract := 'kjds-global-data-coverage-native-caps-evidence-v1';
                expected_schema := 'kjds-source-native-caps-v1';
              WHEN 'global-data-coverage-denominator' THEN
                expected_purpose := 'denominator';
                expected_contract := 'kjds-global-data-coverage-denominator-evidence-v1';
                expected_schema := 'kjds-global-data-coverage-denominator-v1';
              ELSE
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance source is invalid';
            END CASE;
            SELECT signing_key_secret,signing_key_sha256
              INTO STRICT signing_key,trusted_key_sha256
              FROM {quoted_schema}.{ISSUANCE_AUTHORITIES}
             WHERE authority_id='coverage-intake-v1';
            IF length(signing_key)<64 OR
               encode(pg_catalog.sha256(convert_to(signing_key,'UTF8')),'hex')<>
                    trusted_key_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='28000', MESSAGE='coverage issuance authority is invalid';
            END IF;
            content_sha256 := encode(pg_catalog.sha256(p_content),'hex');
            IF p_evidence_id !~ '^evd_[0-9a-z]{{20,}}$'
               OR p_issuance_sha256 !~ '^[0-9a-f]{{64}}$'
               OR p_metadata->>'contract_id' IS DISTINCT FROM expected_contract
               OR p_metadata->>'schema_version' IS DISTINCT FROM expected_schema
               OR p_metadata->>'coverage_intake_purpose' IS DISTINCT FROM expected_purpose
               OR p_metadata->>'scope_grant_authority_sha256' !~ '^[0-9a-f]{{64}}$'
               OR COALESCE(p_metadata->>'tenant_ref','')=''
               OR COALESCE(p_metadata->>'entity_ref','')=''
               OR COALESCE(p_metadata->>'store_ref','')=''
               OR COALESCE(p_metadata->>'coverage_intake_source_contract_id','')=''
               OR COALESCE(p_metadata->>'coverage_intake_source_contract_version','')=''
               OR COALESCE(p_metadata->>'coverage_intake_attestation_contract_id','')=''
               OR COALESCE(p_metadata->>'coverage_intake_attestation_contract_version','')=''
               OR p_metadata->>'coverage_intake_attestation_sha256' !~ '^[0-9a-f]{{64}}$'
               OR p_metadata->>'coverage_intake_issuer_ref_sha256' !~ '^[0-9a-f]{{64}}$'
               OR COALESCE(p_metadata->>'coverage_intake_data_as_of','')=''
               OR COALESCE(p_metadata->>'coverage_intake_upstream_recorded_at','')=''
               OR (p_metadata->>'coverage_intake_authority_checked_at')::timestamptz
                    IS DISTINCT FROM p_authority_checked_at
               OR p_authority_checked_at > statement_timestamp()
               OR (p_metadata->>'coverage_intake_data_as_of')::timestamptz > p_authority_checked_at
               OR (p_metadata->>'coverage_intake_upstream_effective_at')::timestamptz
                    IS DISTINCT FROM p_effective_at
               OR (p_metadata->>'coverage_intake_upstream_effective_at')::timestamptz >
                    (p_metadata->>'coverage_intake_upstream_recorded_at')::timestamptz
               OR (p_metadata->>'coverage_intake_upstream_recorded_at')::timestamptz >
                    (p_metadata->>'coverage_intake_data_as_of')::timestamptz
               OR p_effective_until IS DISTINCT FROM
                    NULLIF(p_metadata->>'coverage_intake_upstream_effective_until','')::timestamptz
               OR (p_effective_until IS NOT NULL AND
                    ((p_metadata->>'coverage_intake_data_as_of')::timestamptz >= p_effective_until OR
                     p_authority_checked_at >= p_effective_until))
               OR p_source_ref IS DISTINCT FROM
                    (p_source || '://' || (p_metadata->>'scope_grant_authority_sha256') ||
                     '/' || content_sha256 || '/' || p_issuance_sha256) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance contract drifted';
            END IF;
            expected_issuance := encode(pg_catalog.sha256(convert_to(
              {quoted_schema}.kjds_gdc_canonical_json(jsonb_build_object(
                'purpose',expected_purpose,'source',p_source,
                'contract_id',expected_contract,'schema_version',expected_schema,
                'content_sha256',content_sha256,
                'source_contract_id',p_metadata->>'coverage_intake_source_contract_id',
                'source_contract_version',p_metadata->>'coverage_intake_source_contract_version',
                'attestation_contract_id',p_metadata->>'coverage_intake_attestation_contract_id',
                'attestation_contract_version',p_metadata->>'coverage_intake_attestation_contract_version',
                'attestation_sha256',p_metadata->>'coverage_intake_attestation_sha256',
                'issuer_ref_sha256',p_metadata->>'coverage_intake_issuer_ref_sha256',
                'upstream_effective_at',p_metadata->>'coverage_intake_upstream_effective_at',
                'upstream_recorded_at',p_metadata->>'coverage_intake_upstream_recorded_at',
                'upstream_effective_until',p_metadata->'coverage_intake_upstream_effective_until',
                'scope',jsonb_build_object(
                  'tenant_ref',p_metadata->>'tenant_ref','entity_ref',p_metadata->>'entity_ref',
                  'store_ref',p_metadata->>'store_ref',
                  'scope_grant_authority_sha256',p_metadata->>'scope_grant_authority_sha256'
                ))),'UTF8')),'hex');
            IF expected_issuance<>p_issuance_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance hash drifted';
            END IF;
            signature := encode(pg_catalog.sha256(
              convert_to(signing_key || ':' || p_issuance_sha256,'UTF8')),'hex');
            final_metadata := p_metadata || jsonb_build_object(
              'coverage_intake_issuance_sha256',p_issuance_sha256,
              'coverage_intake_issuance_signature_sha256',signature);
            INSERT INTO {quoted_schema}.evidence_blobs
              (sha256,byte_size,content_bytes,created_at)
            VALUES (content_sha256,octet_length(p_content),p_content,statement_timestamp())
            ON CONFLICT (sha256) DO NOTHING;
            IF NOT EXISTS (SELECT 1 FROM {quoted_schema}.evidence_blobs b
                            WHERE b.sha256=content_sha256
                              AND b.byte_size=octet_length(p_content)
                              AND b.content_bytes=p_content) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance blob drifted';
            END IF;
            INSERT INTO {quoted_schema}.evidence_records
              (id,blob_sha256,filename,content_type,source,source_ref,grade,
               effective_at,effective_until,recorded_at,created_by,metadata_json)
            VALUES (p_evidence_id,content_sha256,expected_purpose || '-' || content_sha256 || '.json',
                    'application/json',p_source,p_source_ref,'A',p_effective_at,p_effective_until,
                    statement_timestamp(),'kjds-global-data-coverage-intake-authority',final_metadata)
            ON CONFLICT DO NOTHING;
            SELECT * INTO STRICT evidence FROM {quoted_schema}.evidence_records
             WHERE source=p_source AND source_ref=p_source_ref;
            IF evidence.blob_sha256<>content_sha256 OR evidence.grade<>'A'
               OR evidence.effective_at<>p_effective_at
               OR evidence.effective_until IS DISTINCT FROM p_effective_until
               OR evidence.metadata_json::jsonb<>final_metadata THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance Evidence replay drifted';
            END IF;
            INSERT INTO {quoted_schema}.{ISSUANCES}
              (evidence_id,authority_id,evidence_sha256,source,source_ref,
               issuance_sha256,issuance_signature_sha256,authority_checked_at,created_at)
            VALUES (evidence.id,'coverage-intake-v1',content_sha256,p_source,
                    p_source_ref,p_issuance_sha256,signature,p_authority_checked_at,
                    statement_timestamp())
            ON CONFLICT (evidence_id) DO NOTHING;
            SELECT * INTO STRICT existing FROM {quoted_schema}.{ISSUANCES}
             WHERE evidence_id=evidence.id;
            IF existing.evidence_sha256<>content_sha256 OR existing.source<>p_source
               OR existing.source_ref<>p_source_ref
               OR existing.issuance_sha256<>p_issuance_sha256
               OR existing.issuance_signature_sha256<>signature
               OR existing.authority_checked_at<>p_authority_checked_at THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage issuance replay drifted';
            END IF;
            RETURN evidence.id;
        END; $$
    """)
    op.execute(f"ALTER TABLE {quoted_schema}.{ISSUANCE_AUTHORITIES} OWNER TO {ISSUANCE_OWNER_ROLE}")
    op.execute(f"ALTER TABLE {quoted_schema}.{ISSUANCES} OWNER TO {ISSUANCE_OWNER_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA {quoted_schema} TO {ISSUANCE_OWNER_ROLE},{ISSUANCE_CALLER_ROLE}")
    op.execute(
        f"GRANT SELECT,INSERT ON {quoted_schema}.evidence_records,"
        f"{quoted_schema}.evidence_blobs TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(f"REVOKE ALL ON {quoted_schema}.{ISSUANCE_AUTHORITIES} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON {quoted_schema}.{ISSUANCES} FROM PUBLIC")
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_gdc_issue_evidence"
        "(text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz) "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_gdc_issue_evidence"
        "(text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz) FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION {quoted_schema}.kjds_gdc_issue_evidence"
        "(text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz) "
        f"TO {ISSUANCE_CALLER_ROLE}"
    )
    op.execute(
        f"CREATE TRIGGER trg_{ISSUANCES}_immutable BEFORE UPDATE OR DELETE ON {ISSUANCES} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER trg_{ISSUANCE_AUTHORITIES}_immutable BEFORE UPDATE OR DELETE ON "
        f"{ISSUANCE_AUTHORITIES} FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )

    op.execute("""
        CREATE FUNCTION kjds_gdc_stamp_parent_transaction() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.transaction_stamp := txid_current();
            NEW.created_at := statement_timestamp();
            RETURN NEW;
        END; $$
    """)
    op.execute(
        f"CREATE TRIGGER trg_{SNAPSHOTS}_stamp BEFORE INSERT ON {SNAPSHOTS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_gdc_stamp_parent_transaction()"
    )
    op.execute(f"""
        CREATE FUNCTION kjds_gdc_child_same_transaction() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_tx bigint;
        BEGIN
            SELECT transaction_stamp INTO parent_tx FROM {SNAPSHOTS}
             WHERE snapshot_id=NEW.snapshot_id
               AND tenant_ref=NEW.tenant_ref AND entity_ref=NEW.entity_ref
               AND store_ref=NEW.store_ref
               AND scope_grant_authority_sha256=NEW.scope_grant_authority_sha256;
            IF parent_tx IS NULL OR NEW.transaction_stamp<>parent_tx OR parent_tx<>txid_current() THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage child must be inserted with parent transaction';
            END IF;
            RETURN NEW;
        END; $$
    """)
    for table in TABLES[1:]:
        op.execute(
            f"CREATE TRIGGER trg_{table}_same_tx BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kjds_gdc_child_same_transaction()"
        )

    op.execute(f"""
        CREATE FUNCTION kjds_gdc_event_sha256(
            event_row {EVENTS}, request_hash text, observation_hash text
        ) RETURNS text LANGUAGE SQL IMMUTABLE STRICT AS $$
        SELECT encode(sha256(convert_to(concat_ws(chr(31),
            'kjds-global-data-coverage-ledger-evidence-v1',
            event_row.snapshot_id, event_row.event_index::text, event_row.event_type,
            event_row.reason_code, event_row.previous_event_sha256, request_hash,
            observation_hash,
            to_char(event_row.occurred_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00'
        ), 'UTF8')), 'hex') $$
    """)

    op.execute(f"""
        CREATE FUNCTION kjds_gdc_conservation() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE sid text; root {SNAPSHOTS}%ROWTYPE; n bigint; starts bigint; terminals bigint;
                bad_chain bigint; supporting_bad bigint; manifest_payload jsonb;
                caps_payload jsonb; denominator_payload jsonb;
        BEGIN
            sid := COALESCE(NEW.snapshot_id, OLD.snapshot_id);
            SELECT * INTO root FROM {SNAPSHOTS} WHERE snapshot_id=sid;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO n FROM {CAPS} WHERE snapshot_id=sid;
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage caps conservation failed'; END IF;
            SELECT count(*) INTO n FROM {FIELDS} WHERE snapshot_id=sid;
            IF n<>root.required_field_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage field conservation failed'; END IF;
            SELECT count(*) INTO n FROM {PAGES} WHERE snapshot_id=sid;
            IF n<>root.page_failed_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage page conservation failed'; END IF;
            SELECT count(*) INTO n FROM {WINDOWS} WHERE snapshot_id=sid AND segment_kind='requested';
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage requested window conservation failed'; END IF;
            SELECT count(*) INTO n FROM {WINDOWS} WHERE snapshot_id=sid AND segment_kind='effective';
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage effective window conservation failed'; END IF;
            SELECT count(*) INTO n FROM {WINDOWS} WHERE snapshot_id=sid AND segment_kind='gap';
            IF n<>root.window_gap_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage gap conservation failed'; END IF;
            SELECT count(*) INTO n FROM {WINDOWS} WHERE snapshot_id=sid AND segment_kind='overlap';
            IF n<>root.window_overlap_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage overlap conservation failed'; END IF;
            SELECT count(*) INTO n FROM {CONFLICTS} WHERE snapshot_id=sid;
            IF n<>root.conflict_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage conflict conservation failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} WHERE snapshot_id=sid;
            IF n<>root.evidence_count THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage Evidence conservation failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} WHERE snapshot_id=sid AND evidence_role='manifest';
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage manifest Evidence conservation failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
             WHERE l.snapshot_id=sid AND l.evidence_role='manifest'
               AND l.evidence_id=root.manifest_evidence_id
               AND l.evidence_sha256=root.manifest_evidence_sha256
               AND l.evidence_source='global-data-coverage-manifest'
               AND l.evidence_source_ref=('global-data-coverage-manifest://' || root.scope_grant_authority_sha256 || '/' || root.manifest_evidence_sha256 || '/' || (e.metadata_json->>'coverage_intake_issuance_sha256'))
               AND l.evidence_effective_until IS NOT DISTINCT FROM e.effective_until
               AND e.metadata_json->>'contract_id'='kjds-global-data-coverage-manifest-evidence-v1'
               AND e.metadata_json->>'schema_version'=root.manifest_schema_version
               AND e.metadata_json->>'coverage_intake_purpose'='manifest'
               AND e.metadata_json->>'coverage_intake_source_contract_id'=root.source_contract_id
               AND e.metadata_json->>'coverage_intake_source_contract_version'=root.source_contract_version
               AND e.metadata_json->>'tenant_ref'=root.tenant_ref
               AND e.metadata_json->>'entity_ref'=root.entity_ref
               AND e.metadata_json->>'store_ref'=root.store_ref
               AND e.metadata_json->>'scope_grant_authority_sha256'=root.scope_grant_authority_sha256
               AND e.metadata_json->>'coverage_intake_attestation_sha256' ~ '{HEX64}'
               AND e.metadata_json->>'coverage_intake_issuer_ref_sha256' ~ '{HEX64}'
               AND e.effective_at=(e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
               AND e.recorded_at<=root.authority_checked_at
               AND (e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
                   <=(e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz
               AND (e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz<=root.data_as_of
               AND root.data_as_of<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
               AND root.authority_checked_at<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
               AND e.effective_until=(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz;
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage manifest Evidence exact binding failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} WHERE snapshot_id=sid AND evidence_role='native_caps';
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage caps Evidence conservation failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
             WHERE l.snapshot_id=sid AND l.evidence_role='native_caps'
               AND l.evidence_id=root.native_caps_evidence_id
               AND l.evidence_sha256=root.native_caps_evidence_sha256
               AND l.evidence_source='global-data-coverage-native-caps'
               AND l.evidence_source_ref=('global-data-coverage-native-caps://' || root.scope_grant_authority_sha256 || '/' || root.native_caps_evidence_sha256 || '/' || (e.metadata_json->>'coverage_intake_issuance_sha256'))
               AND l.evidence_effective_until IS NOT DISTINCT FROM e.effective_until
               AND e.metadata_json->>'contract_id'='kjds-global-data-coverage-native-caps-evidence-v1'
               AND e.metadata_json->>'schema_version'=root.native_caps_schema
               AND e.metadata_json->>'coverage_intake_purpose'='native_caps'
               AND e.metadata_json->>'coverage_intake_source_contract_id'=root.source_contract_id
               AND e.metadata_json->>'coverage_intake_source_contract_version'=root.source_contract_version
               AND e.metadata_json->>'tenant_ref'=root.tenant_ref
               AND e.metadata_json->>'entity_ref'=root.entity_ref
               AND e.metadata_json->>'store_ref'=root.store_ref
               AND e.metadata_json->>'scope_grant_authority_sha256'=root.scope_grant_authority_sha256
               AND e.metadata_json->>'coverage_intake_attestation_sha256' ~ '{HEX64}'
               AND e.metadata_json->>'coverage_intake_issuer_ref_sha256' ~ '{HEX64}'
               AND e.effective_at=(e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
               AND e.recorded_at<=root.authority_checked_at
               AND (e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
                   <=(e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz
               AND (e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz<=root.data_as_of
               AND root.data_as_of<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
               AND root.authority_checked_at<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
               AND e.effective_until=(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz;
            IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage caps Evidence exact binding failed'; END IF;
            SELECT count(*) INTO n FROM {LINKS} WHERE snapshot_id=sid AND evidence_role='denominator';
            IF n<>(CASE WHEN root.denominator_known THEN 1 ELSE 0 END) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage denominator Evidence conservation failed';
            END IF;
            IF root.denominator_known THEN
                SELECT count(*) INTO n FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
                 WHERE l.snapshot_id=sid AND l.evidence_role='denominator'
                   AND l.evidence_id=root.denominator_evidence_ref
                   AND l.evidence_sha256=root.denominator_evidence_sha256
                   AND l.evidence_source='global-data-coverage-denominator'
                   AND l.evidence_source_ref=('global-data-coverage-denominator://' || root.scope_grant_authority_sha256 || '/' || root.denominator_evidence_sha256 || '/' || (e.metadata_json->>'coverage_intake_issuance_sha256'))
                   AND l.evidence_effective_until IS NOT DISTINCT FROM e.effective_until
                   AND e.metadata_json->>'contract_id'='kjds-global-data-coverage-denominator-evidence-v1'
                   AND e.metadata_json->>'coverage_intake_purpose'='denominator'
                   AND e.metadata_json->>'coverage_intake_source_contract_id'=root.source_contract_id
                   AND e.metadata_json->>'coverage_intake_source_contract_version'=root.source_contract_version
                   AND e.metadata_json->>'tenant_ref'=root.tenant_ref
                   AND e.metadata_json->>'entity_ref'=root.entity_ref
                   AND e.metadata_json->>'store_ref'=root.store_ref
                    AND e.metadata_json->>'scope_grant_authority_sha256'=root.scope_grant_authority_sha256
                    AND e.metadata_json->>'coverage_intake_attestation_sha256' ~ '{HEX64}'
                    AND e.metadata_json->>'coverage_intake_issuer_ref_sha256' ~ '{HEX64}'
                    AND e.effective_at=(e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
                    AND e.recorded_at<=root.authority_checked_at
                    AND (e.metadata_json->>'coverage_intake_upstream_effective_at')::timestamptz
                        <=(e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz
                    AND (e.metadata_json->>'coverage_intake_upstream_recorded_at')::timestamptz<=root.data_as_of
                    AND root.data_as_of<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
                    AND root.authority_checked_at<(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz
                    AND e.effective_until=(e.metadata_json->>'coverage_intake_upstream_effective_until')::timestamptz;
                IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage denominator Evidence exact binding failed'; END IF;
            END IF;

            SELECT convert_from(b.content_bytes,'UTF8')::jsonb INTO STRICT manifest_payload
              FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
              JOIN evidence_blobs b ON b.sha256=e.blob_sha256
             WHERE l.snapshot_id=sid AND l.evidence_role='manifest';
            SELECT convert_from(b.content_bytes,'UTF8')::jsonb INTO STRICT caps_payload
              FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
              JOIN evidence_blobs b ON b.sha256=e.blob_sha256
             WHERE l.snapshot_id=sid AND l.evidence_role='native_caps';
            IF manifest_payload->>'content_sha256' IS DISTINCT FROM root.manifest_sha256
               OR manifest_payload->>'schema_version' IS DISTINCT FROM root.manifest_schema_version
               OR manifest_payload->>'manifest_ref' IS DISTINCT FROM root.manifest_ref
               OR manifest_payload->>'manifest_version' IS DISTINCT FROM root.manifest_version
               OR manifest_payload->>'registry_sha256' IS DISTINCT FROM root.registry_sha256
               OR manifest_payload->>'native_caps_sha256' IS DISTINCT FROM root.native_caps_sha256
               OR manifest_payload#>>'{{source,source_id}}' IS DISTINCT FROM root.source_id
               OR manifest_payload#>>'{{source,source_family}}' IS DISTINCT FROM root.source_family
               OR manifest_payload#>>'{{source,source_status}}' IS DISTINCT FROM root.source_status
               OR manifest_payload#>>'{{source,source_contract_id}}' IS DISTINCT FROM root.source_contract_id
               OR manifest_payload#>>'{{source,source_contract_version}}' IS DISTINCT FROM root.source_contract_version
               OR (manifest_payload->>'as_of')::timestamptz IS DISTINCT FROM root.data_as_of
               OR (manifest_payload->>'captured_at')::timestamptz IS DISTINCT FROM root.captured_at
               OR (manifest_payload->>'recorded_at')::timestamptz IS DISTINCT FROM root.recorded_at
               OR (manifest_payload#>>'{{universe,denominator_known}}')::boolean IS DISTINCT FROM root.denominator_known
               OR (manifest_payload#>>'{{universe,expected_count}}')::bigint IS DISTINCT FROM root.expected_count
               OR manifest_payload#>>'{{universe,expected_count_evidence_ref}}' IS DISTINCT FROM root.denominator_evidence_ref
               OR manifest_payload#>>'{{universe,expected_count_evidence_sha256}}' IS DISTINCT FROM root.denominator_evidence_sha256
               OR (manifest_payload#>>'{{conservation,observed_count}}')::bigint IS DISTINCT FROM root.observed_count
               OR (manifest_payload#>>'{{conservation,accepted_count}}')::bigint IS DISTINCT FROM root.accepted_count
               OR (manifest_payload#>>'{{conservation,quarantined_count}}')::bigint IS DISTINCT FROM root.quarantined_count
               OR (manifest_payload#>>'{{conservation,failed_count}}')::bigint IS DISTINCT FROM root.failed_count
               OR (manifest_payload#>>'{{conservation,duplicate_count}}')::bigint IS DISTINCT FROM root.duplicate_count
               OR (manifest_payload#>>'{{conservation,suppressed_count}}')::bigint IS DISTINCT FROM root.suppressed_count
               OR (manifest_payload#>>'{{conservation,source_total}}')::bigint IS DISTINCT FROM root.source_total
               OR (manifest_payload#>>'{{coverage,pages,expected_count}}')::bigint IS DISTINCT FROM root.page_expected_count
               OR (manifest_payload#>>'{{coverage,pages,received_count}}')::bigint IS DISTINCT FROM root.page_received_count
               OR (manifest_payload#>>'{{coverage,pages,failed_count}}')::bigint IS DISTINCT FROM root.page_failed_count
               OR (manifest_payload#>>'{{coverage,pages,duplicate_count}}')::bigint IS DISTINCT FROM root.page_duplicate_count
               OR (manifest_payload#>>'{{coverage,pages,closed}}')::boolean IS DISTINCT FROM root.page_closed
               OR jsonb_array_length(manifest_payload#>'{{coverage,pages,failed_refs}}') IS DISTINCT FROM root.page_failed_count
               OR (manifest_payload#>>'{{coverage,fields,required_count}}')::bigint IS DISTINCT FROM root.required_field_count
               OR jsonb_array_length(manifest_payload#>'{{coverage,window,gaps}}') IS DISTINCT FROM root.window_gap_count
               OR jsonb_array_length(manifest_payload#>'{{coverage,window,overlaps}}') IS DISTINCT FROM root.window_overlap_count
               OR manifest_payload#>>'{{coverage,window,timezone}}' IS DISTINCT FROM root.window_timezone
               OR (manifest_payload#>>'{{coverage,window,late_arrival_count}}')::bigint IS DISTINCT FROM root.window_late_arrival_count
               OR jsonb_array_length(manifest_payload->'conflicts') IS DISTINCT FROM root.conflict_count
               OR manifest_payload#>>'{{checkpoint,sha256}}' IS DISTINCT FROM root.checkpoint_sha256
               OR (manifest_payload#>>'{{checkpoint,sequence}}')::bigint IS DISTINCT FROM root.checkpoint_sequence
               OR (manifest_payload#>>'{{checkpoint,closed}}')::boolean IS DISTINCT FROM root.checkpoint_closed
               OR manifest_payload#>>'{{freshness,status}}' IS DISTINCT FROM root.freshness_status
               OR (manifest_payload#>>'{{freshness,fresh_until}}')::timestamptz IS DISTINCT FROM root.fresh_until
               OR (manifest_payload#>>'{{freshness,review_due}}')::timestamptz IS DISTINCT FROM root.review_due
               OR manifest_payload#>>'{{coverage_claim,denominator_evidence_ref}}' IS DISTINCT FROM root.denominator_evidence_ref
               OR manifest_payload#>>'{{coverage_claim,denominator_evidence_sha256}}' IS DISTINCT FROM root.denominator_evidence_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage manifest canonical projection drifted';
            END IF;
            IF caps_payload->>'content_sha256' IS DISTINCT FROM root.native_caps_sha256
               OR caps_payload->>'schema_version' IS DISTINCT FROM root.native_caps_schema
               OR caps_payload->>'source_id' IS DISTINCT FROM root.source_id
               OR caps_payload->>'source_family' IS DISTINCT FROM root.source_family
               OR caps_payload->>'source_status' IS DISTINCT FROM root.source_status
               OR caps_payload->>'universe_kind' IS DISTINCT FROM manifest_payload#>>'{{universe,kind}}'
               OR NOT EXISTS (SELECT 1 FROM {CAPS} c WHERE c.snapshot_id=sid
                    AND c.schema_version=root.native_caps_schema
                    AND c.source_id=root.source_id
                    AND c.source_family=root.source_family
                    AND c.universe_kind=caps_payload->>'universe_kind'
                    AND c.content_sha256=root.native_caps_sha256
                   AND c.adapter_id=caps_payload->>'adapter_id'
                   AND c.adapter_version=caps_payload->>'adapter_version'
                   AND c.capability_version=caps_payload->>'capability_version'
                   AND c.pagination_mode=caps_payload#>>'{{capabilities,pagination,mode}}'
                   AND c.page_limit IS NOT DISTINCT FROM (caps_payload#>>'{{capabilities,pagination,page_limit}}')::integer
                   AND c.historical_depth_days IS NOT DISTINCT FROM (caps_payload#>>'{{capabilities,window,historical_depth_days}}')::integer
                   AND c.rate_limit_known=(caps_payload#>>'{{capabilities,rate_limit,known}}')::boolean
                   AND c.authentication_mode=caps_payload#>>'{{capabilities,authentication_mode}}') THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage native caps canonical projection drifted';
            END IF;
            SELECT count(*) INTO n FROM {FIELDS} f WHERE f.snapshot_id=sid AND NOT (
                (f.field_status='present' AND (manifest_payload#>'{{coverage,fields,present}}') ? f.field_name) OR
                (f.field_status='missing' AND (manifest_payload#>'{{coverage,fields,missing}}') ? f.field_name) OR
                (f.field_status='unparseable' AND (manifest_payload#>'{{coverage,fields,unparseable}}') ? f.field_name) OR
                (f.field_status='conflicting' AND (manifest_payload#>'{{coverage,fields,conflicting}}') ? f.field_name));
            IF n<>0 OR (
                jsonb_array_length(manifest_payload#>'{{coverage,fields,present}}')+
                jsonb_array_length(manifest_payload#>'{{coverage,fields,missing}}')+
                jsonb_array_length(manifest_payload#>'{{coverage,fields,unparseable}}')+
                jsonb_array_length(manifest_payload#>'{{coverage,fields,conflicting}}')
            )<>root.required_field_count THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage field canonical projection drifted';
            END IF;
            WITH expected_fields AS (
                SELECT value AS field_name, ord::integer AS ordinal, 'present'::text AS field_status
                  FROM jsonb_array_elements_text(manifest_payload#>'{{coverage,fields,present}}') WITH ORDINALITY AS x(value,ord)
                UNION ALL
                SELECT value, (jsonb_array_length(manifest_payload#>'{{coverage,fields,present}}')+ord)::integer, 'missing'
                  FROM jsonb_array_elements_text(manifest_payload#>'{{coverage,fields,missing}}') WITH ORDINALITY AS x(value,ord)
                UNION ALL
                SELECT value, (jsonb_array_length(manifest_payload#>'{{coverage,fields,present}}')+
                               jsonb_array_length(manifest_payload#>'{{coverage,fields,missing}}')+ord)::integer, 'unparseable'
                  FROM jsonb_array_elements_text(manifest_payload#>'{{coverage,fields,unparseable}}') WITH ORDINALITY AS x(value,ord)
                UNION ALL
                SELECT value, (jsonb_array_length(manifest_payload#>'{{coverage,fields,present}}')+
                               jsonb_array_length(manifest_payload#>'{{coverage,fields,missing}}')+
                               jsonb_array_length(manifest_payload#>'{{coverage,fields,unparseable}}')+ord)::integer, 'conflicting'
                  FROM jsonb_array_elements_text(manifest_payload#>'{{coverage,fields,conflicting}}') WITH ORDINALITY AS x(value,ord)
            )
            SELECT count(*) INTO n FROM {FIELDS} f
              LEFT JOIN expected_fields x ON x.field_name=f.field_name
               AND x.ordinal=f.ordinal AND x.field_status=f.field_status
             WHERE f.snapshot_id=sid AND (
               x.field_name IS NULL OR
               f.field_name_sha256<>encode(pg_catalog.sha256(
                 convert_to(f.field_name,'UTF8')),'hex'));
            IF n<>0 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage field canonical identity drifted';
            END IF;
            SELECT count(*) INTO n FROM {PAGES} p
              LEFT JOIN jsonb_array_elements_text(manifest_payload#>'{{coverage,pages,failed_refs}}')
                WITH ORDINALITY AS x(failed_ref,ordinal)
                ON x.ordinal=p.ordinal
               AND p.failed_ref_sha256=encode(pg_catalog.sha256(
                 convert_to(x.failed_ref,'UTF8')),'hex')
             WHERE p.snapshot_id=sid AND (
               x.failed_ref IS NULL OR p.reason_code<>'source_page_failed');
            IF n<>0 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage failed-page canonical projection drifted';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM {WINDOWS} w WHERE w.snapshot_id=sid AND w.segment_kind='requested'
                 AND w.ordinal=1 AND w.reason_code IS NULL
                 AND w.start_at=(manifest_payload#>>'{{coverage,window,requested_start}}')::timestamptz
                 AND w.end_at=(manifest_payload#>>'{{coverage,window,requested_end}}')::timestamptz)
               OR NOT EXISTS (SELECT 1 FROM {WINDOWS} w WHERE w.snapshot_id=sid AND w.segment_kind='effective'
                 AND w.ordinal=1 AND w.reason_code IS NULL
                 AND w.start_at=(manifest_payload#>>'{{coverage,window,effective_start}}')::timestamptz
                 AND w.end_at=(manifest_payload#>>'{{coverage,window,effective_end}}')::timestamptz) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage window canonical projection drifted';
            END IF;
            WITH expected_windows AS (
                SELECT 'gap'::text AS segment_kind, ord::integer AS ordinal,
                       (item->>'start')::timestamptz AS start_at,
                       (item->>'end')::timestamptz AS end_at,
                       item->>'reason_code' AS reason_code
                  FROM jsonb_array_elements(manifest_payload#>'{{coverage,window,gaps}}') WITH ORDINALITY AS x(item,ord)
                UNION ALL
                SELECT 'overlap', ord::integer, (item->>'start')::timestamptz,
                       (item->>'end')::timestamptz, item->>'reason_code'
                  FROM jsonb_array_elements(manifest_payload#>'{{coverage,window,overlaps}}') WITH ORDINALITY AS x(item,ord)
            )
            SELECT count(*) INTO n FROM {WINDOWS} w
              LEFT JOIN expected_windows x ON x.segment_kind=w.segment_kind
               AND x.ordinal=w.ordinal AND x.start_at=w.start_at AND x.end_at=w.end_at
               AND x.reason_code=w.reason_code
             WHERE w.snapshot_id=sid AND w.segment_kind IN ('gap','overlap')
               AND x.segment_kind IS NULL;
            IF n<>0 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage gap or overlap canonical projection drifted';
            END IF;
            SELECT count(*) INTO n FROM {CONFLICTS} c
              LEFT JOIN jsonb_array_elements(manifest_payload->'conflicts')
                WITH ORDINALITY AS x(item,ordinal)
                ON x.ordinal=c.ordinal
               AND c.conflict_ref_sha256=encode(pg_catalog.sha256(
                 convert_to(x.item->>'conflict_ref','UTF8')),'hex')
             WHERE c.snapshot_id=sid AND (
               x.item IS NULL OR
               c.subject_ref_sha256<>x.item->>'subject_ref_sha256' OR
               c.field_name_sha256<>encode(pg_catalog.sha256(
                 convert_to(x.item->>'field','UTF8')),'hex') OR
               c.valid_interval_sha256<>x.item->>'valid_interval_sha256' OR
               c.value_hash_count<>jsonb_array_length(x.item->'value_hashes') OR
               c.value_hashes_sha256<>encode(pg_catalog.sha256(convert_to(
                 '[' || COALESCE((SELECT string_agg(to_jsonb(v)::text,',' ORDER BY vo)
                                   FROM jsonb_array_elements_text(x.item->'value_hashes')
                                     WITH ORDINALITY AS values(v,vo)), '') || ']',
                 'UTF8')),'hex') OR
               c.resolution_status<>x.item->>'resolution_status');
            IF n<>0 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage conflict canonical projection drifted';
            END IF;
            IF root.denominator_known THEN
                SELECT convert_from(b.content_bytes,'UTF8')::jsonb INTO STRICT denominator_payload
                  FROM {LINKS} l JOIN evidence_records e ON e.id=l.evidence_id
                  JOIN evidence_blobs b ON b.sha256=e.blob_sha256
                 WHERE l.snapshot_id=sid AND l.evidence_role='denominator';
                IF denominator_payload->>'contract_id' IS DISTINCT FROM 'kjds-global-data-coverage-denominator-evidence-v1'
                   OR denominator_payload->>'schema_version' IS DISTINCT FROM 'kjds-global-data-coverage-denominator-v1'
                   OR denominator_payload->>'source_id' IS DISTINCT FROM root.source_id
                   OR denominator_payload->>'source_family' IS DISTINCT FROM root.source_family
                   OR denominator_payload->>'universe_kind' IS DISTINCT FROM manifest_payload#>>'{{universe,kind}}'
                   OR (denominator_payload->>'expected_count')::bigint IS DISTINCT FROM root.expected_count
                   OR denominator_payload->>'manifest_ref' IS DISTINCT FROM root.manifest_ref
                   OR denominator_payload->>'manifest_version' IS DISTINCT FROM root.manifest_version
                   OR (denominator_payload->>'data_as_of')::timestamptz IS DISTINCT FROM root.data_as_of
                   OR (denominator_payload->>'window_start')::timestamptz IS DISTINCT FROM (manifest_payload#>>'{{coverage,window,requested_start}}')::timestamptz
                   OR (denominator_payload->>'window_end')::timestamptz IS DISTINCT FROM (manifest_payload#>>'{{coverage,window,requested_end}}')::timestamptz
                   OR denominator_payload->>'partition_sha256' IS DISTINCT FROM encode(
                        pg_catalog.sha256(convert_to(kjds_gdc_canonical_json(jsonb_build_object(
                          'scope',manifest_payload->'scope',
                          'query_bounds',manifest_payload#>'{{universe,query_bounds}}',
                          'source_id',root.source_id)),'UTF8')),'hex') THEN
                    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage denominator canonical projection drifted';
                END IF;
            END IF;
            SELECT count(*) INTO n FROM {LINKS} WHERE snapshot_id=sid AND evidence_role='supporting';
            IF n<>(jsonb_array_length(manifest_payload->'evidence_refs')-
                   CASE WHEN root.denominator_known THEN 1 ELSE 0 END) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage supporting Evidence declaration conservation failed';
            END IF;
            SELECT count(*) INTO supporting_bad FROM {LINKS} l
              JOIN evidence_records e ON e.id=l.evidence_id
              LEFT JOIN evidence_records b ON b.id=l.scope_binding_evidence_id
             WHERE l.snapshot_id=sid AND l.evidence_role='supporting' AND (
                NOT EXISTS (
                  SELECT 1 FROM jsonb_array_elements(manifest_payload->'evidence_refs') d
                   WHERE d->>'id'=l.evidence_id AND d->>'sha256'=l.evidence_sha256
                     AND d->>'grade'=l.evidence_grade
                     AND (d->>'effective_at')::timestamptz=l.evidence_effective_at
                     AND (d->>'effective_until')::timestamptz IS NOT DISTINCT FROM l.evidence_effective_until
                     AND (d->>'recorded_at')::timestamptz=l.evidence_declared_recorded_at
                ) OR l.evidence_effective_until IS DISTINCT FROM e.effective_until OR
                l.evidence_declared_recorded_at IS DISTINCT FROM e.recorded_at OR
                e.effective_at>root.data_as_of OR e.recorded_at>root.data_as_of OR
                (e.effective_until IS NOT NULL AND root.data_as_of>=e.effective_until) OR
                (l.scope_authority_contract_id='kjds-evidence-scope-v1' AND (
                   e.metadata_json->>'evidence_scope_contract_id'<>'kjds-evidence-scope-v1' OR
                   e.metadata_json->>'tenant_ref' IS DISTINCT FROM root.tenant_ref OR
                   e.metadata_json->>'entity_ref' IS DISTINCT FROM root.entity_ref OR
                   e.metadata_json->>'store_ref' IS DISTINCT FROM root.store_ref OR
                   e.metadata_json->>'scope_grant_authority_sha256' IS DISTINCT FROM root.scope_grant_authority_sha256 OR
                   COALESCE(e.metadata_json->>'reviewed_by','')='' OR
                   e.metadata_json->>'reviewed_by'=e.created_by
                )) OR
                (l.scope_authority_contract_id='kjds-evidence-scope-binding-v1' AND (
                   b.id IS NULL OR b.blob_sha256<>l.scope_binding_evidence_sha256 OR b.grade<>'A' OR
                   b.metadata_json->>'evidence_scope_contract_id'<>'kjds-evidence-scope-binding-v1' OR
                   b.metadata_json->>'target_evidence_id'<>e.id OR
                   b.metadata_json->>'target_evidence_sha256'<>e.blob_sha256 OR
                   b.metadata_json->>'tenant_ref' IS DISTINCT FROM root.tenant_ref OR
                   b.metadata_json->>'entity_ref' IS DISTINCT FROM root.entity_ref OR
                   b.metadata_json->>'store_ref' IS DISTINCT FROM root.store_ref OR
                   b.metadata_json->>'scope_grant_authority_sha256' IS DISTINCT FROM root.scope_grant_authority_sha256 OR
                   COALESCE(b.metadata_json->>'reviewed_by','')='' OR
                   b.metadata_json->>'reviewed_by' IN (b.created_by,e.created_by) OR
                   b.created_by=e.created_by OR b.recorded_at>root.authority_checked_at OR
                   b.effective_at>root.authority_checked_at OR
                   (b.effective_until IS NOT NULL AND root.authority_checked_at>=b.effective_until)
                )));
            IF supporting_bad<>0 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage supporting Evidence scope or time drifted';
            END IF;
            IF root.full_coverage_claim THEN
                IF root.source_status<>'implemented' OR root.observation_status<>'complete'
                   OR root.completeness<>'complete' OR NOT root.denominator_known
                   OR root.expected_count<>root.observed_count OR root.quarantined_count<>0
                   OR root.failed_count<>0 OR root.duplicate_count<>0 OR root.suppressed_count<>0
                   OR root.page_failed_count<>0 OR root.page_duplicate_count<>0
                   OR NOT root.page_closed OR NOT root.checkpoint_closed
                   OR root.window_gap_count<>0 OR root.window_overlap_count<>0
                   OR root.window_late_arrival_count<>0 OR root.conflict_count<>0
                   OR root.freshness_status<>'fresh'
                   OR root.fresh_until<=root.authority_checked_at
                   OR root.review_due<=root.authority_checked_at THEN
                    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage full claim semantic gate failed';
                END IF;
                SELECT count(*) INTO n FROM {FIELDS} WHERE snapshot_id=sid AND field_status<>'present';
                IF n<>0 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage full claim field gate failed'; END IF;
                SELECT count(*) INTO n FROM {WINDOWS} r JOIN {WINDOWS} e ON e.snapshot_id=r.snapshot_id
                 WHERE r.snapshot_id=sid AND r.segment_kind='requested' AND e.segment_kind='effective'
                   AND r.start_at=e.start_at AND r.end_at=e.end_at;
                IF n<>1 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage full claim window gate failed'; END IF;
            END IF;
            SELECT count(*), count(*) FILTER (WHERE event_type='snapshot_started'),
                   count(*) FILTER (WHERE event_type IN ('snapshot_committed','unknown_outcome','invalidated'))
              INTO n, starts, terminals FROM {EVENTS} WHERE snapshot_id=sid;
            IF n<>2 OR starts<>1 OR terminals<>1 THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage terminal event conservation failed';
            END IF;
            SELECT count(*) INTO bad_chain FROM {EVENTS} e
             JOIN evidence_records er ON er.id=e.evidence_id
             JOIN evidence_blobs eb ON eb.sha256=er.blob_sha256
             WHERE e.snapshot_id=sid AND (
               (e.event_index=1 AND (e.event_type<>'snapshot_started' OR e.previous_event_sha256<>'{ZERO_SHA256}')) OR
               (e.event_index=2 AND NOT EXISTS (
                 SELECT 1 FROM {EVENTS} p WHERE p.snapshot_id=e.snapshot_id
                  AND p.event_index=1 AND e.previous_event_sha256=p.event_sha256
                )) OR e.event_index NOT IN (1,2)
                OR e.event_sha256<>kjds_gdc_event_sha256(e,root.request_sha256,root.observation_sha256)
                OR er.source IS DISTINCT FROM 'global-data-coverage-ledger'
                OR er.source_ref IS DISTINCT FROM ('coverage-ledger://' || root.snapshot_id || '/' || e.event_id)
                OR er.grade IS DISTINCT FROM 'D' OR er.effective_at IS DISTINCT FROM e.occurred_at
                OR er.metadata_json->>'contract_id' IS DISTINCT FROM 'kjds-global-data-coverage-ledger-evidence-v1'
                OR er.metadata_json->>'tenant_ref' IS DISTINCT FROM root.tenant_ref
                OR er.metadata_json->>'entity_ref' IS DISTINCT FROM root.entity_ref
                OR er.metadata_json->>'store_ref' IS DISTINCT FROM root.store_ref
                OR er.metadata_json->>'scope_grant_authority_sha256' IS DISTINCT FROM root.scope_grant_authority_sha256
                OR er.metadata_json->>'snapshot_id' IS DISTINCT FROM root.snapshot_id
                OR er.metadata_json->>'event_id' IS DISTINCT FROM e.event_id
                OR er.metadata_json->>'event_type' IS DISTINCT FROM e.event_type
                OR er.metadata_json->>'event_sha256' IS DISTINCT FROM e.event_sha256
                OR er.metadata_json->>'request_sha256' IS DISTINCT FROM root.request_sha256
                OR er.metadata_json->>'observation_sha256' IS DISTINCT FROM root.observation_sha256
                OR (er.metadata_json->>'occurred_at')::timestamptz IS DISTINCT FROM e.occurred_at
                OR convert_from(eb.content_bytes,'UTF8')::jsonb IS DISTINCT FROM
                   jsonb_build_object(
                     'contract_id','kjds-global-data-coverage-ledger-evidence-v1',
                     'snapshot_id',e.snapshot_id,'event_index',e.event_index,
                     'event_type',e.event_type,'reason_code',e.reason_code,
                     'previous_event_sha256',e.previous_event_sha256,
                     'request_sha256',root.request_sha256,
                     'observation_sha256',root.observation_sha256,
                     'occurred_at',to_char(e.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00',
                     'event_sha256',e.event_sha256,'payload_status','hash_and_code_only',
                     'formal_fact',false,'external_write',false
                   ));
            IF bad_chain<>0 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage event chain conservation failed'; END IF;
            IF root.full_coverage_claim AND NOT EXISTS (
                SELECT 1 FROM {EVENTS} WHERE snapshot_id=sid AND event_type='snapshot_committed'
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='coverage full claim terminal gate failed';
            END IF;
            RETURN NULL;
        END; $$
    """)
    for table in TABLES:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_conservation AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kjds_gdc_conservation()"
        )


def downgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-gdc-coverage-ledger-ddl'))")
    # Writer order is root/children -> blobs -> Evidence -> lineage. Downgrade
    # follows the same global order so an in-flight writer cannot form a lock cycle.
    for table in TABLES:
        op.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE evidence_blobs IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE evidence_records IN ACCESS EXCLUSIVE MODE")
    op.execute(f"LOCK TABLE {ISSUANCES} IN ACCESS EXCLUSIVE MODE")
    op.execute(f"LOCK TABLE {ISSUANCE_AUTHORITIES} IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE lineage_edges IN ACCESS EXCLUSIVE MODE")
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")):
            raise RuntimeError("DATA-COV-002 downgrade refused: coverage ledger is populated")
    if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {ISSUANCES} LIMIT 1)")):
        raise RuntimeError("DATA-COV-002 downgrade refused: coverage issuance exists")
    if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM evidence_records WHERE source IN ({SOURCES_SQL}) LIMIT 1)")):
        raise RuntimeError("DATA-COV-002 downgrade refused: coverage Evidence exists")
    if connection.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM lineage_edges l JOIN evidence_records e ON (l.from_type='evidence' AND e.id=l.from_id) OR (l.to_type='evidence' AND e.id=l.to_id) WHERE e.source IN ({SOURCES_SQL}) LIMIT 1)")):
        raise RuntimeError("DATA-COV-002 downgrade refused: coverage lineage exists")
    op.execute(f"DROP FUNCTION kjds_gdc_event_sha256({EVENTS}, text, text)")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION kjds_gdc_conservation()")
    op.execute("DROP FUNCTION kjds_gdc_canonical_json(jsonb)")
    op.execute("DROP FUNCTION kjds_gdc_child_same_transaction()")
    op.execute("DROP FUNCTION kjds_gdc_stamp_parent_transaction()")
    op.execute(
        "DROP FUNCTION kjds_gdc_issue_evidence("
        "text,bytea,text,text,timestamptz,timestamptz,jsonb,text,timestamptz)"
    )
    op.drop_table(ISSUANCES)
    op.drop_table(ISSUANCE_AUTHORITIES)
    op.execute("DROP TRIGGER trg_gdc_evidence_immutable ON evidence_records")
    op.execute("DROP FUNCTION kjds_gdc_prevent_evidence_mutation()")
    op.drop_index("uq_global_data_coverage_evidence_source_ref", table_name="evidence_records")
