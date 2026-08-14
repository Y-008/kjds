"""Add the governed durable media-job ledger.

Revision ID: 20260808_0097
Revises: 20260805_0096
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260808_0097"
down_revision = "20260805_0096"
branch_labels = None
depends_on = None

JOBS = "media_jobs"
EVENTS = "media_job_events"
LINKS = "media_job_evidence_links"
MEDIA_SOURCES_SQL = (
    "'governed-media-job-request','governed-media-job-transition',"
    "'governed-media-job-usage'"
)


def upgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-media-jobs-0097-lifecycle'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    op.create_index(
        "uq_media_job_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(f"source IN ({MEDIA_SOURCES_SQL})"),
    )
    op.create_table(
        JOBS,
        sa.Column("job_ref", sa.Text(), primary_key=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("subject_actor_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("tool_version", sa.String(length=160), nullable=False),
        sa.Column("project_ref", sa.String(length=160), nullable=False),
        sa.Column("brief_ref", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=160), nullable=False),
        sa.Column("connector_ref", sa.String(length=160), nullable=False),
        sa.Column("connector_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_evidence_id", sa.Text(), nullable=False),
        sa.Column("request_evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_evidence_id"],
            ["evidence_records.id"],
            name="fk_media_job_request_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_media_job_exact_scope_idempotency",
        ),
        sa.UniqueConstraint(
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_exact_identity",
        ),
        sa.CheckConstraint(
            "scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "connector_binding_sha256 ~ '^[0-9a-f]{64}$' AND "
            "idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_fingerprint_sha256 ~ '^[0-9a-f]{64}$' AND "
            "request_evidence_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_media_job_hashes",
        ),
    )
    op.create_index(
        "ix_media_job_scope_created",
        JOBS,
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    op.create_table(
        EVENTS,
        sa.Column("event_ref", sa.Text(), primary_key=True),
        sa.Column("job_ref", sa.Text(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stream_kind", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("safe_reason_code", sa.String(length=80), nullable=True),
        sa.Column("previous_event_sha256", sa.String(length=64), nullable=True),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("command_idempotency_sha256", sa.String(length=64), nullable=False),
        sa.Column("command_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("public_projection_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            [
                "job_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_event_exact_identity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_ref", "ordinal", name="uq_media_job_event_ordinal"),
        sa.UniqueConstraint("job_ref", "event_sha256", name="uq_media_job_event_hash"),
        sa.UniqueConstraint(
            "event_ref",
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_event_exact_identity",
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_media_job_event_ordinal"),
        sa.CheckConstraint(
            "event_sha256 ~ '^[0-9a-f]{64}$' AND "
            "command_idempotency_sha256 ~ '^[0-9a-f]{64}$' AND "
            "command_request_sha256 ~ '^[0-9a-f]{64}$' AND "
            "(previous_event_sha256 IS NULL OR previous_event_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_media_job_event_hashes",
        ),
        sa.CheckConstraint("stream_kind = 'job_state'", name="ck_media_job_event_stream"),
        sa.CheckConstraint(
            "state IN ('QUEUED','DISPATCHED','RUNNING','UPLOADING','SUCCEEDED',"
            "'LOGIN_REQUIRED','LIMITED','FAILED','CANCELLED','UNKNOWN_OUTCOME')",
            name="ck_media_job_event_state",
        ),
    )
    op.create_index(
        "ix_media_job_event_job_recorded",
        EVENTS,
        ["job_ref", "recorded_at", "ordinal"],
    )
    op.create_table(
        LINKS,
        sa.Column("link_ref", sa.Text(), primary_key=True),
        sa.Column("job_ref", sa.Text(), nullable=False),
        sa.Column("event_ref", sa.Text(), nullable=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=60), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            [
                "job_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "event_ref",
                "job_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "media_job_events.event_ref",
                "media_job_events.job_ref",
                "media_job_events.tenant_ref",
                "media_job_events.entity_ref",
                "media_job_events.store_ref",
                "media_job_events.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.id"],
            name="fk_media_job_link_evidence",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "job_ref", "purpose", "evidence_id", name="uq_media_job_evidence_purpose"
        ),
        sa.CheckConstraint(
            "purpose IN ('request_input','artifact_terminal','usage_authorization','usage_settlement')",
            name="ck_media_job_evidence_purpose",
        ),
        sa.CheckConstraint(
            "blob_sha256 ~ '^[0-9a-f]{64}$' AND "
            f"source IN ({MEDIA_SOURCES_SQL})",
            name="ck_media_job_evidence_contract",
        ),
    )
    op.create_index(
        "ix_media_job_link_scope",
        LINKS,
        ["tenant_ref", "entity_ref", "store_ref", "job_ref"],
    )
    op.execute(
        """
        CREATE FUNCTION kjds_media_job_prevent_mutation() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='governed media-job ledgers are append-only';
        END;
        $$
        """
    )
    for table in (JOBS, EVENTS, LINKS):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kjds_media_job_prevent_mutation()"
        )
    op.execute(
        f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_canonical_json(p_value jsonb)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path=pg_catalog AS $$
          SELECT CASE jsonb_typeof(p_value)
            WHEN 'object' THEN (
              SELECT '{{' || COALESCE(string_agg(
                to_jsonb(item.key)::text || ':' ||
                {quoted_schema}.kjds_media_job_canonical_json(item.value),
                ',' ORDER BY item.key COLLATE "C"), '') || '}}'
              FROM jsonb_each(p_value) item
            )
            WHEN 'array' THEN (
              SELECT '[' || COALESCE(string_agg(
                {quoted_schema}.kjds_media_job_canonical_json(item.value),
                ',' ORDER BY item.ordinality), '') || ']'
              FROM jsonb_array_elements(p_value) WITH ORDINALITY item(value, ordinality)
            )
            ELSE p_value::text
          END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_media_job_validate_event() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            job_row RECORD;
            previous_row RECORD;
            expected_state text;
        BEGIN
            SELECT * INTO job_row FROM {quoted_schema}.{JOBS}
             WHERE job_ref=NEW.job_ref FOR UPDATE;
            IF NOT FOUND OR
               (job_row.tenant_ref,job_row.entity_ref,job_row.store_ref,
                job_row.scope_grant_authority_sha256)
               IS DISTINCT FROM
               (NEW.tenant_ref,NEW.entity_ref,NEW.store_ref,
                NEW.scope_grant_authority_sha256) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job event exact scope drifted';
            END IF;
            SELECT ordinal,state,event_sha256,occurred_at,recorded_at INTO previous_row
              FROM {quoted_schema}.{EVENTS} WHERE job_ref=NEW.job_ref
              ORDER BY ordinal DESC LIMIT 1;
            IF NOT FOUND THEN
                IF NEW.ordinal IS DISTINCT FROM 1
                   OR NEW.state IS DISTINCT FROM 'QUEUED'
                   OR NEW.previous_event_sha256 IS NOT NULL
                   OR NEW.occurred_at IS DISTINCT FROM job_row.created_at
                   OR NEW.recorded_at IS DISTINCT FROM job_row.created_at THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job initial event invalid';
                END IF;
            ELSE
                IF NEW.ordinal IS DISTINCT FROM previous_row.ordinal + 1
                   OR NEW.previous_event_sha256 IS DISTINCT FROM previous_row.event_sha256
                   OR NEW.occurred_at < previous_row.occurred_at
                   OR NEW.recorded_at < previous_row.recorded_at THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job event chain invalid';
                END IF;
                IF previous_row.state IN ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN_OUTCOME') THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job terminal state is immutable';
                END IF;
                expected_state := CASE previous_row.state
                    WHEN 'QUEUED' THEN CASE WHEN NEW.state IN
                        ('DISPATCHED','CANCELLED','LIMITED','LOGIN_REQUIRED') THEN NEW.state END
                    WHEN 'DISPATCHED' THEN CASE WHEN NEW.state IN
                        ('RUNNING','FAILED','UNKNOWN_OUTCOME') THEN NEW.state END
                    WHEN 'RUNNING' THEN CASE WHEN NEW.state IN
                        ('UPLOADING','FAILED','UNKNOWN_OUTCOME') THEN NEW.state END
                    WHEN 'UPLOADING' THEN CASE WHEN NEW.state IN
                        ('SUCCEEDED','FAILED','UNKNOWN_OUTCOME') THEN NEW.state END
                    WHEN 'LOGIN_REQUIRED' THEN CASE WHEN NEW.state IN
                        ('DISPATCHED','RUNNING','FAILED','UNKNOWN_OUTCOME') THEN NEW.state END
                    WHEN 'LIMITED' THEN CASE WHEN NEW.state IN
                        ('DISPATCHED','RUNNING','FAILED','UNKNOWN_OUTCOME') THEN NEW.state END
                    ELSE NULL END;
                IF expected_state IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job state transition invalid';
                END IF;
            END IF;
            IF NEW.occurred_at > NEW.recorded_at
               OR NEW.occurred_at > statement_timestamp() + interval '5 minutes'
               OR NEW.recorded_at > statement_timestamp() + interval '5 minutes' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job event time invalid';
            END IF;
            IF (NEW.state IN ('QUEUED','DISPATCHED','RUNNING','UPLOADING','SUCCEEDED')
                    AND NEW.safe_reason_code IS NOT NULL)
               OR (NEW.state='LOGIN_REQUIRED' AND NEW.safe_reason_code
                    IS DISTINCT FROM 'connector_login_required')
               OR (NEW.state='LIMITED' AND NEW.safe_reason_code
                    IS DISTINCT FROM 'settled_entitlement_unavailable')
               OR (NEW.state='FAILED' AND NEW.safe_reason_code
                    IS DISTINCT FROM 'provider_failed')
               OR (NEW.state='CANCELLED' AND NEW.safe_reason_code
                    IS DISTINCT FROM 'cancelled_by_request')
               OR (NEW.state='UNKNOWN_OUTCOME' AND NEW.safe_reason_code
                    IS DISTINCT FROM 'provider_outcome_unknown') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job safe reason invalid';
            END IF;
            IF jsonb_typeof(NEW.public_projection_json::jsonb) IS DISTINCT FROM 'object'
               OR (SELECT array_agg(key ORDER BY key)
                     FROM jsonb_object_keys(NEW.public_projection_json::jsonb) key)
                  IS DISTINCT FROM ARRAY['job_ref','ordinal','safe_reason_code','state']::text[] THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job public event projection invalid';
            END IF;
            IF jsonb_typeof(NEW.public_projection_json::jsonb->'job_ref')
                  IS DISTINCT FROM 'string'
               OR jsonb_typeof(NEW.public_projection_json::jsonb->'ordinal')
                  IS DISTINCT FROM 'number'
               OR jsonb_typeof(NEW.public_projection_json::jsonb->'state')
                  IS DISTINCT FROM 'string'
               OR jsonb_typeof(NEW.public_projection_json::jsonb->'safe_reason_code')
                  <> ALL(ARRAY['null','string']::text[]) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job public event projection invalid';
            END IF;
            IF (NEW.public_projection_json::jsonb->>'ordinal')::numeric
                  IS DISTINCT FROM NEW.ordinal::numeric
               OR NEW.public_projection_json::jsonb->>'job_ref' IS DISTINCT FROM NEW.job_ref
               OR NEW.public_projection_json::jsonb->>'state' IS DISTINCT FROM NEW.state
               OR NEW.public_projection_json::jsonb->>'safe_reason_code'
                  IS DISTINCT FROM NEW.safe_reason_code THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job public event projection invalid';
            END IF;
            IF NEW.event_sha256 IS DISTINCT FROM encode(
                sha256(convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                        'command_idempotency_sha256', NEW.command_idempotency_sha256,
                        'command_request_sha256', NEW.command_request_sha256,
                        'entity_ref', NEW.entity_ref,
                        'event_ref_scope', NEW.scope_grant_authority_sha256,
                        'job_ref', NEW.job_ref,
                        'ordinal', NEW.ordinal,
                        'occurred_at', to_char(NEW.occurred_at AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00',
                        'previous_event_sha256', NEW.previous_event_sha256,
                        'public_projection_json', NEW.public_projection_json::jsonb,
                        'recorded_at', to_char(NEW.recorded_at AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00',
                        'safe_reason_code', NEW.safe_reason_code,
                        'state', NEW.state,
                        'store_ref', NEW.store_ref,
                        'stream_kind', NEW.stream_kind,
                        'subject_actor_id', job_row.subject_actor_id,
                        'tenant_ref', NEW.tenant_ref
                    )), 'UTF8')),'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job event hash seal invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_media_job_event_contract BEFORE INSERT ON {EVENTS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_media_job_validate_event()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_media_job_validate_evidence_binding() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            evidence_row RECORD;
            job_row RECORD;
            event_row RECORD;
            evidence_ref text;
            expected_source_ref text;
        BEGIN
            IF TG_TABLE_NAME='{JOBS}' THEN
                evidence_ref := NEW.request_evidence_id;
            ELSE
                evidence_ref := NEW.evidence_id;
            END IF;
            SELECT id,blob_sha256,source,source_ref,grade,effective_at,
                   effective_until,recorded_at,created_by,metadata_json
              INTO evidence_row FROM {quoted_schema}.evidence_records
             WHERE id=evidence_ref;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job Evidence is missing';
            END IF;
            IF jsonb_typeof(evidence_row.metadata_json::jsonb) IS DISTINCT FROM 'object'
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(evidence_row.metadata_json::jsonb) item
                     WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'string'
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job Evidence metadata types drifted';
            END IF;
            IF TG_TABLE_NAME='{JOBS}' THEN
                expected_source_ref := 'media-job://' || encode(sha256(convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                        'authority_sha256', NEW.scope_grant_authority_sha256,
                        'entity_ref', NEW.entity_ref,
                        'store_ref', NEW.store_ref,
                        'subject_actor_id', NEW.subject_actor_id,
                        'tenant_ref', NEW.tenant_ref
                    )), 'UTF8')), 'hex') || '/' || NEW.idempotency_sha256 || '/request';
                IF evidence_row.blob_sha256 IS DISTINCT FROM NEW.request_evidence_sha256
                   OR evidence_row.blob_sha256 IS DISTINCT FROM NEW.request_sha256
                   OR NEW.request_evidence_sha256 IS DISTINCT FROM NEW.request_sha256
                   OR evidence_row.source IS DISTINCT FROM 'governed-media-job-request'
                   OR evidence_row.source_ref IS DISTINCT FROM expected_source_ref
                   OR evidence_row.grade IS DISTINCT FROM 'B'
                   OR evidence_row.effective_at IS DISTINCT FROM NEW.created_at
                   OR evidence_row.recorded_at IS DISTINCT FROM NEW.created_at
                   OR evidence_row.effective_until IS NOT NULL
                   OR evidence_row.created_by IS DISTINCT FROM NEW.subject_actor_id
                   OR (SELECT array_agg(key ORDER BY key)
                         FROM jsonb_object_keys(evidence_row.metadata_json::jsonb) key)
                      IS DISTINCT FROM ARRAY[
                        'contract_id','entity_ref','media_job_request_fingerprint_sha256',
                        'scope_grant_authority_sha256','store_ref','subject_actor_id','tenant_ref'
                      ]::text[]
                   OR evidence_row.metadata_json->>'contract_id'
                      IS DISTINCT FROM 'kjds-governed-media-job-request-v1'
                   OR evidence_row.metadata_json->>'media_job_request_fingerprint_sha256'
                      IS DISTINCT FROM NEW.request_fingerprint_sha256
                   OR evidence_row.metadata_json->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
                   OR evidence_row.metadata_json->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
                   OR evidence_row.metadata_json->>'store_ref' IS DISTINCT FROM NEW.store_ref
                   OR evidence_row.metadata_json->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM NEW.scope_grant_authority_sha256
                   OR evidence_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM NEW.subject_actor_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job request Evidence binding drifted';
                END IF;
            ELSE
                SELECT * INTO job_row FROM {quoted_schema}.{JOBS}
                 WHERE job_ref=NEW.job_ref;
                IF NOT FOUND OR
                   (job_row.tenant_ref,job_row.entity_ref,job_row.store_ref,
                    job_row.scope_grant_authority_sha256)
                   IS DISTINCT FROM
                   (NEW.tenant_ref,NEW.entity_ref,NEW.store_ref,
                    NEW.scope_grant_authority_sha256) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job Evidence link scope drifted';
                END IF;
                IF (evidence_row.blob_sha256,evidence_row.source,
                    evidence_row.source_ref,evidence_row.effective_at,
                    evidence_row.recorded_at)
                   IS DISTINCT FROM
                   (NEW.blob_sha256,NEW.source,NEW.source_ref,NEW.effective_at,
                    NEW.recorded_at)
                   OR evidence_row.grade IS DISTINCT FROM 'B'
                   OR evidence_row.effective_until IS NOT NULL
                   OR evidence_row.created_by IS DISTINCT FROM job_row.subject_actor_id
                   OR evidence_row.metadata_json->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
                   OR evidence_row.metadata_json->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
                   OR evidence_row.metadata_json->>'store_ref' IS DISTINCT FROM NEW.store_ref
                   OR evidence_row.metadata_json->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM NEW.scope_grant_authority_sha256
                   OR evidence_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM job_row.subject_actor_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job Evidence link drifted';
                END IF;
                IF (NEW.purpose='request_input' AND
                    NEW.source IS DISTINCT FROM 'governed-media-job-request') OR
                   (NEW.purpose='artifact_terminal' AND
                    NEW.source IS DISTINCT FROM 'governed-media-job-transition') OR
                   (NEW.purpose IN ('usage_authorization','usage_settlement') AND
                    NEW.source IS DISTINCT FROM 'governed-media-job-usage') THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job Evidence purpose drifted';
                END IF;
                IF NEW.purpose='request_input' THEN
                    IF NEW.event_ref IS NOT NULL
                       OR evidence_row.source_ref IS DISTINCT FROM (
                            'media-job://' || encode(sha256(convert_to(
                                {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                                    'authority_sha256', job_row.scope_grant_authority_sha256,
                                    'entity_ref', job_row.entity_ref,
                                    'store_ref', job_row.store_ref,
                                    'subject_actor_id', job_row.subject_actor_id,
                                    'tenant_ref', job_row.tenant_ref
                                )), 'UTF8')), 'hex') || '/' ||
                            job_row.idempotency_sha256 || '/request')
                       OR evidence_row.effective_at IS DISTINCT FROM job_row.created_at
                       OR evidence_row.recorded_at IS DISTINCT FROM job_row.created_at
                       OR (SELECT array_agg(key ORDER BY key)
                             FROM jsonb_object_keys(evidence_row.metadata_json::jsonb) key)
                          IS DISTINCT FROM ARRAY[
                            'contract_id','entity_ref','media_job_request_fingerprint_sha256',
                            'scope_grant_authority_sha256','store_ref','subject_actor_id','tenant_ref'
                          ]::text[]
                       OR evidence_row.metadata_json->>'contract_id'
                          IS DISTINCT FROM 'kjds-governed-media-job-request-v1'
                       OR evidence_row.metadata_json->>'media_job_request_fingerprint_sha256'
                          IS DISTINCT FROM job_row.request_fingerprint_sha256 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='media-job request Evidence link contract drifted';
                    END IF;
                ELSIF NEW.purpose='artifact_terminal' THEN
                    SELECT * INTO event_row FROM {quoted_schema}.{EVENTS}
                     WHERE event_ref=NEW.event_ref AND job_ref=NEW.job_ref;
                    IF NOT FOUND
                       OR event_row.state NOT IN ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN_OUTCOME')
                       OR evidence_row.blob_sha256 IS DISTINCT FROM encode(
                            sha256(convert_to(
                                {quoted_schema}.kjds_media_job_canonical_json(
                                    event_row.public_projection_json::jsonb
                                ), 'UTF8'
                            )), 'hex'
                          )
                       OR evidence_row.source_ref IS DISTINCT FROM
                          ('media-job://' || NEW.job_ref || '/transition/' || NEW.event_ref)
                       OR evidence_row.effective_at IS DISTINCT FROM event_row.occurred_at
                       OR evidence_row.recorded_at IS DISTINCT FROM event_row.recorded_at
                       OR (SELECT array_agg(key ORDER BY key)
                             FROM jsonb_object_keys(evidence_row.metadata_json::jsonb) key)
                          IS DISTINCT FROM ARRAY[
                            'contract_id','entity_ref','event_sha256',
                            'scope_grant_authority_sha256','store_ref','subject_actor_id','tenant_ref'
                          ]::text[]
                       OR evidence_row.metadata_json->>'contract_id'
                          IS DISTINCT FROM 'kjds-governed-media-job-transition-v1'
                       OR evidence_row.metadata_json->>'event_sha256'
                          IS DISTINCT FROM event_row.event_sha256 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='media-job terminal Evidence link contract drifted';
                    END IF;
                ELSE
                    IF (SELECT array_agg(key ORDER BY key)
                          FROM jsonb_object_keys(evidence_row.metadata_json::jsonb) key)
                       IS DISTINCT FROM ARRAY[
                         'contract_id','entity_ref','scope_grant_authority_sha256',
                         'store_ref','subject_actor_id','tenant_ref','usage_receipt_sha256'
                       ]::text[]
                       OR evidence_row.metadata_json->>'contract_id'
                          IS DISTINCT FROM 'kjds-governed-media-job-usage-v1'
                       OR evidence_row.metadata_json->>'usage_receipt_sha256'
                          !~ '^[0-9a-f]{{64}}$' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='media-job usage Evidence link contract drifted';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_media_job_request_evidence BEFORE INSERT ON {JOBS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_media_job_validate_evidence_binding()"
    )
    op.execute(
        f"CREATE TRIGGER trg_media_job_link_evidence BEFORE INSERT ON {LINKS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_media_job_validate_evidence_binding()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_media_job_terminal_evidence_conservation() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF NEW.state IN ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN_OUTCOME')
               AND (SELECT count(*) FROM {quoted_schema}.{LINKS}
                     WHERE job_ref=NEW.job_ref
                       AND event_ref=NEW.event_ref
                       AND purpose='artifact_terminal') IS DISTINCT FROM 1::bigint THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job terminal Evidence conservation violated';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER trg_media_job_terminal_evidence_conservation "
        f"AFTER INSERT ON {EVENTS} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "kjds_media_job_terminal_evidence_conservation()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_media_job_evidence_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            IF OLD.source IN ({MEDIA_SOURCES_SQL}) OR NEW.source IN ({MEDIA_SOURCES_SQL}) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job Evidence is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_media_job_evidence_immutable "
        "BEFORE UPDATE OR DELETE ON evidence_records "
        "FOR EACH ROW EXECUTE FUNCTION kjds_media_job_evidence_immutable()"
    )


def downgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-media-jobs-0097-lifecycle'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {JOBS})
               OR EXISTS (SELECT 1 FROM {EVENTS})
               OR EXISTS (SELECT 1 FROM {LINKS})
               OR EXISTS (SELECT 1 FROM evidence_records WHERE source IN ({MEDIA_SOURCES_SQL})) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='0097 downgrade blocked: governed media-job data exists';
            END IF;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER trg_media_job_evidence_immutable ON evidence_records")
    op.execute("DROP FUNCTION kjds_media_job_evidence_immutable()")
    op.execute(
        f"DROP TRIGGER trg_media_job_terminal_evidence_conservation ON {EVENTS}"
    )
    op.execute("DROP FUNCTION kjds_media_job_terminal_evidence_conservation()")
    op.execute(f"DROP TRIGGER trg_media_job_link_evidence ON {LINKS}")
    op.execute(f"DROP TRIGGER trg_media_job_request_evidence ON {JOBS}")
    op.execute("DROP FUNCTION kjds_media_job_validate_evidence_binding()")
    op.execute(f"DROP FUNCTION {quoted_schema}.kjds_media_job_canonical_json(jsonb)")
    op.execute(f"DROP TRIGGER trg_media_job_event_contract ON {EVENTS}")
    op.execute("DROP FUNCTION kjds_media_job_validate_event()")
    for table in reversed((JOBS, EVENTS, LINKS)):
        op.execute(f"DROP TRIGGER trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION kjds_media_job_prevent_mutation()")
    op.drop_table(LINKS)
    op.drop_table(EVENTS)
    op.drop_table(JOBS)
    op.drop_index("uq_media_job_evidence_source_ref", table_name="evidence_records")
