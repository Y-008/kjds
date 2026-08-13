"""Add immutable media-job terminal result/readback receipts.

Revision ID: 20260809_0098
Revises: 20260808_0097
"""

import sqlalchemy as sa
from alembic import op

revision = '20260809_0098'
down_revision = '20260808_0097'
branch_labels = None
depends_on = None

TABLE = 'media_job_result_receipts'
WORKER_INPUT_TABLE = 'media_job_worker_inputs'
REQUEST_BINDING_TABLE = 'media_job_request_bindings'


def upgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-media-jobs-0098-result-readback'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    op.execute(
        f"LOCK TABLE {quoted_schema}.evidence_records, "
        f"{quoted_schema}.media_jobs IN SHARE ROW EXCLUSIVE MODE"
    )
    legacy_media_jobs = int(
        connection.scalar(
            sa.text("SELECT count(*) FROM media_jobs WHERE tool_name IN ('media.video_blueprint','media.video_render')")
        )
        or 0
    )
    if legacy_media_jobs:
        raise RuntimeError("0098 upgrade blocked: legacy media jobs lack governed descriptor Evidence")
    op.add_column('evidence_records', sa.Column('byte_size', sa.Integer(), nullable=True))
    # The table lock excludes every legacy Evidence writer. Temporarily disable only
    # user triggers so the migration can backfill its new derived column without
    # weakening FK enforcement or allowing an application transaction through.
    op.execute(f'ALTER TABLE {quoted_schema}.evidence_records DISABLE TRIGGER USER')
    op.execute(
        f'UPDATE {quoted_schema}.evidence_records AS evidence '
        f'SET byte_size=octet_length(blob.content_bytes) '
        f'FROM {quoted_schema}.evidence_blobs AS blob '
        'WHERE blob.sha256=evidence.blob_sha256'
    )
    op.execute(f'ALTER TABLE {quoted_schema}.evidence_records ENABLE TRIGGER USER')
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_evidence_record_fill_byte_size()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path=pg_catalog
        AS $$
        DECLARE
            actual_size integer;
        BEGIN
            SELECT octet_length(content_bytes)
              INTO actual_size
              FROM {quoted_schema}.evidence_blobs
             WHERE sha256=NEW.blob_sha256;
            IF actual_size IS NULL
               OR (NEW.byte_size IS NOT NULL AND NEW.byte_size<>actual_size) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='Evidence byte size does not match immutable blob';
            END IF;
            NEW.byte_size := actual_size;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f'CREATE TRIGGER trg_evidence_record_fill_byte_size BEFORE INSERT OR UPDATE OF blob_sha256,byte_size ON {quoted_schema}.evidence_records FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.kjds_evidence_record_fill_byte_size()')
    op.drop_index('uq_media_job_evidence_source_ref', table_name='evidence_records')
    op.execute("CREATE UNIQUE INDEX uq_media_job_evidence_source_ref ON evidence_records (source, source_ref) WHERE source IN ('governed-media-job-request','governed-media-job-tool-descriptor','governed-media-job-transition','governed-media-job-usage','governed-media-job-worker-input','governed-reference-video-analysis','governed-media-job-blueprint','kjds-ffmpeg-media-worker')")
    op.drop_constraint('ck_media_job_evidence_purpose', 'media_job_evidence_links', type_='check')
    op.drop_constraint('ck_media_job_evidence_contract', 'media_job_evidence_links', type_='check')
    op.create_check_constraint('ck_media_job_evidence_purpose', 'media_job_evidence_links', "purpose IN ('request_input','analysis_input','blueprint_input','artifact_terminal','usage_authorization','usage_settlement')")
    op.create_check_constraint('ck_media_job_evidence_contract', 'media_job_evidence_links', "blob_sha256 ~ '^[0-9a-f]{64}$' AND source IN ('governed-media-job-request','governed-reference-video-analysis','governed-media-job-blueprint','governed-media-job-transition','governed-media-job-usage')")
    op.execute('DROP TRIGGER trg_media_job_link_evidence ON media_job_evidence_links')
    op.execute("CREATE TRIGGER trg_media_job_link_evidence BEFORE INSERT ON media_job_evidence_links FOR EACH ROW WHEN (NEW.purpose NOT IN ('analysis_input','blueprint_input')) EXECUTE FUNCTION kjds_media_job_validate_evidence_binding()")
    op.create_table(
            'media_job_worker_inputs',
            sa.Column('input_ref', sa.Text(), primary_key=True),
            sa.Column('job_ref', sa.Text(), nullable=False),
            sa.Column('tenant_ref', sa.String(length=160), nullable=False),
            sa.Column('entity_ref', sa.String(length=160), nullable=False),
            sa.Column('store_ref', sa.String(length=160), nullable=False),
            sa.Column('scope_grant_authority_sha256', sa.String(length=64), nullable=False),
            sa.Column('tool_name', sa.String(length=160), nullable=False),
            sa.Column('tool_version', sa.String(length=160), nullable=False),
            sa.Column('worker_input_json', sa.JSON(), nullable=False),
            sa.Column('worker_input_sha256', sa.String(length=64), nullable=False),
            sa.Column('evidence_id', sa.Text(), sa.ForeignKey('evidence_records.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('evidence_sha256', sa.String(length=64), nullable=False),
            sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['job_ref', 'tenant_ref', 'entity_ref', 'store_ref', 'scope_grant_authority_sha256'], ['media_jobs.job_ref', 'media_jobs.tenant_ref', 'media_jobs.entity_ref', 'media_jobs.store_ref', 'media_jobs.scope_grant_authority_sha256'], name='fk_media_job_worker_input_exact_job', ondelete='RESTRICT'),
            sa.UniqueConstraint('job_ref', name='uq_media_job_worker_input_job'),
            sa.CheckConstraint("tool_name IN ('media.video_blueprint','media.video_render')", name='ck_media_job_worker_input_tool'),
            sa.CheckConstraint("scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND worker_input_sha256 ~ '^[0-9a-f]{64}$' AND evidence_sha256 ~ '^[0-9a-f]{64}$'", name='ck_media_job_worker_input_hashes'),
        )
    op.create_index('ix_media_job_worker_input_scope', 'media_job_worker_inputs', ['tenant_ref', 'entity_ref', 'store_ref', 'job_ref'])
    op.create_table(
            'media_job_request_bindings',
            sa.Column('binding_ref', sa.Text(), primary_key=True),
            sa.Column('job_ref', sa.Text(), nullable=False),
            sa.Column('tenant_ref', sa.String(length=160), nullable=False),
            sa.Column('entity_ref', sa.String(length=160), nullable=False),
            sa.Column('store_ref', sa.String(length=160), nullable=False),
            sa.Column('scope_grant_authority_sha256', sa.String(length=64), nullable=False),
            sa.Column('request_evidence_id', sa.Text(), sa.ForeignKey('evidence_records.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('request_evidence_sha256', sa.String(length=64), nullable=False),
            sa.Column('descriptor_evidence_id', sa.Text(), sa.ForeignKey('evidence_records.id', ondelete='RESTRICT'), nullable=False),
            sa.Column('descriptor_evidence_sha256', sa.String(length=64), nullable=False),
            sa.Column('tool_descriptor_sha256', sa.String(length=64), nullable=False),
            sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['job_ref', 'tenant_ref', 'entity_ref', 'store_ref', 'scope_grant_authority_sha256'], ['media_jobs.job_ref', 'media_jobs.tenant_ref', 'media_jobs.entity_ref', 'media_jobs.store_ref', 'media_jobs.scope_grant_authority_sha256'], name='fk_media_job_request_binding_exact_job', ondelete='RESTRICT'),
            sa.UniqueConstraint('job_ref', name='uq_media_job_request_binding_job'),
            sa.CheckConstraint("request_evidence_sha256 ~ '^[0-9a-f]{64}$' AND descriptor_evidence_sha256 ~ '^[0-9a-f]{64}$' AND tool_descriptor_sha256 ~ '^[0-9a-f]{64}$'", name='ck_media_job_request_binding_hashes'),
        )
    op.create_table(
            'media_job_result_receipts',
            sa.Column('receipt_ref', sa.Text(), primary_key=True),
            sa.Column('job_ref', sa.Text(), nullable=False),
            sa.Column('event_ref', sa.Text(), nullable=False),
            sa.Column('tenant_ref', sa.String(length=160), nullable=False),
            sa.Column('entity_ref', sa.String(length=160), nullable=False),
            sa.Column('store_ref', sa.String(length=160), nullable=False),
            sa.Column('scope_grant_authority_sha256', sa.String(length=64), nullable=False),
            sa.Column('tool_name', sa.String(length=160), nullable=False),
            sa.Column('tool_version', sa.String(length=160), nullable=False),
            sa.Column('provider', sa.String(length=160), nullable=False),
            sa.Column('connector_ref', sa.String(length=160), nullable=False),
            sa.Column('connector_binding_sha256', sa.String(length=64), nullable=False),
            sa.Column('state', sa.String(length=40), nullable=False),
            sa.Column('result_kind', sa.String(length=160), nullable=False),
            sa.Column('artifact_evidence_refs', sa.JSON(), nullable=False),
            sa.Column('content_asset_ref', sa.Text(), sa.ForeignKey('content_assets.id', ondelete='RESTRICT'), nullable=True),
            sa.Column('receipt_sha256', sa.String(length=64), nullable=False),
            sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['job_ref', 'tenant_ref', 'entity_ref', 'store_ref', 'scope_grant_authority_sha256'], ['media_jobs.job_ref', 'media_jobs.tenant_ref', 'media_jobs.entity_ref', 'media_jobs.store_ref', 'media_jobs.scope_grant_authority_sha256'], name='fk_media_job_result_exact_job', ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['event_ref', 'job_ref', 'tenant_ref', 'entity_ref', 'store_ref', 'scope_grant_authority_sha256'], ['media_job_events.event_ref', 'media_job_events.job_ref', 'media_job_events.tenant_ref', 'media_job_events.entity_ref', 'media_job_events.store_ref', 'media_job_events.scope_grant_authority_sha256'], name='fk_media_job_result_exact_event', ondelete='RESTRICT'),
            sa.UniqueConstraint('job_ref', 'event_ref', name='uq_media_job_result_event'),
            sa.CheckConstraint("state IN ('SUCCEEDED','FAILED','UNKNOWN_OUTCOME')", name='ck_media_job_result_terminal_state'),
            sa.CheckConstraint("tool_name IN ('media.video_blueprint','media.video_render')", name='ck_media_job_result_tool'),
            sa.CheckConstraint("scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' AND connector_binding_sha256 ~ '^[0-9a-f]{64}$' AND receipt_sha256 ~ '^[0-9a-f]{64}$'", name='ck_media_job_result_hashes'),
            sa.CheckConstraint("json_typeof(artifact_evidence_refs) = 'array'", name='ck_media_job_result_evidence_array'),
        )
    op.create_index('ix_media_job_result_scope_recorded', 'media_job_result_receipts', ['tenant_ref', 'entity_ref', 'store_ref', 'recorded_at'])
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_validate_request_binding()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            job_row record;
            request_evidence record;
            request_blob record;
            descriptor_evidence record;
            descriptor_blob record;
            request_json jsonb;
            descriptor_json jsonb;
            descriptor_sha text;
            scope_binding_sha text;
        BEGIN
            SELECT * INTO job_row
              FROM {quoted_schema}.media_jobs
             WHERE job_ref = NEW.job_ref
               AND tenant_ref = NEW.tenant_ref
               AND entity_ref = NEW.entity_ref
               AND store_ref = NEW.store_ref
               AND scope_grant_authority_sha256 = NEW.scope_grant_authority_sha256;
            SELECT * INTO request_evidence
              FROM {quoted_schema}.evidence_records
             WHERE id = NEW.request_evidence_id;
            IF FOUND THEN
                SELECT * INTO request_blob
                  FROM {quoted_schema}.evidence_blobs
                 WHERE sha256 = request_evidence.blob_sha256;
            END IF;
            SELECT * INTO descriptor_evidence
              FROM {quoted_schema}.evidence_records
             WHERE id = NEW.descriptor_evidence_id;
            IF FOUND THEN
                SELECT * INTO descriptor_blob
                  FROM {quoted_schema}.evidence_blobs
                 WHERE sha256 = descriptor_evidence.blob_sha256;
            END IF;
            BEGIN
                request_json := convert_from(request_blob.content_bytes, 'UTF8')::jsonb;
                descriptor_json := convert_from(
                    descriptor_blob.content_bytes, 'UTF8'
                )::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job request binding JSON invalid';
            END;
            descriptor_sha := encode(sha256(convert_to(
                {quoted_schema}.kjds_media_job_canonical_json(
                    descriptor_json - 'descriptor_sha256'
                ), 'UTF8'
            )), 'hex');
            scope_binding_sha := encode(sha256(convert_to(
                {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                    'tenant_ref',NEW.tenant_ref,
                    'entity_ref',NEW.entity_ref,
                    'store_ref',NEW.store_ref,
                    'authority_sha256',NEW.scope_grant_authority_sha256,
                    'subject_actor_id',job_row.subject_actor_id
                )), 'UTF8'
            )), 'hex');
            IF job_row.job_ref IS NULL
               OR request_evidence.id IS NULL OR request_blob.sha256 IS NULL
               OR descriptor_evidence.id IS NULL OR descriptor_blob.sha256 IS NULL
               OR job_row.request_evidence_id IS DISTINCT FROM request_evidence.id
               OR job_row.request_evidence_sha256 IS DISTINCT FROM request_blob.sha256
               OR NEW.request_evidence_sha256 IS DISTINCT FROM request_blob.sha256
               OR request_evidence.source IS DISTINCT FROM 'governed-media-job-request'
               OR request_evidence.content_type IS DISTINCT FROM 'application/json'
               OR request_evidence.blob_sha256 IS DISTINCT FROM request_blob.sha256
               OR encode(sha256(request_blob.content_bytes), 'hex')
                  IS DISTINCT FROM request_blob.sha256
               OR job_row.request_sha256 IS DISTINCT FROM request_blob.sha256
               OR request_evidence.source_ref IS DISTINCT FROM
                  ('media-job://' || scope_binding_sha || '/' ||
                   job_row.idempotency_sha256 || '/request')
               OR request_evidence.created_by IS DISTINCT FROM job_row.subject_actor_id
               OR request_evidence.effective_at IS DISTINCT FROM job_row.created_at
               OR request_evidence.recorded_at IS DISTINCT FROM job_row.created_at
               OR request_evidence.effective_until IS NOT NULL
               OR request_evidence.metadata_json::jsonb IS DISTINCT FROM jsonb_build_object(
                    'contract_id','kjds-governed-media-job-request-v1',
                    'media_job_request_fingerprint_sha256',
                        job_row.request_fingerprint_sha256,
                    'tenant_ref',NEW.tenant_ref,
                    'entity_ref',NEW.entity_ref,
                    'store_ref',NEW.store_ref,
                    'scope_grant_authority_sha256',NEW.scope_grant_authority_sha256,
                    'subject_actor_id',job_row.subject_actor_id
               )
               OR jsonb_typeof(request_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(request_json)) <> 15
               OR NOT request_json ?& ARRAY[
                    'contract_id','tool_name','tool_version','project_ref','brief_ref',
                    'campaign_brief_sha256','provider','connector_ref',
                    'connector_binding_sha256','idempotency_sha256','output_contract',
                    'tool_descriptor_sha256','tool_inputs_sha256',
                    'tool_input_ref_count','safe_reason_codes'
               ]
               OR request_json->>'contract_id' IS DISTINCT FROM
                  'kjds-commander-media-job-request-v1'
               OR request_json->>'tool_name' IS DISTINCT FROM job_row.tool_name
               OR request_json->>'tool_version' IS DISTINCT FROM job_row.tool_version
               OR request_json->>'project_ref' IS DISTINCT FROM job_row.project_ref
               OR request_json->>'brief_ref' IS DISTINCT FROM job_row.brief_ref
               OR request_json->>'provider' IS DISTINCT FROM job_row.provider
               OR request_json->>'connector_ref' IS DISTINCT FROM job_row.connector_ref
               OR request_json->>'connector_binding_sha256' IS DISTINCT FROM
                  job_row.connector_binding_sha256
               OR request_json->>'idempotency_sha256' IS DISTINCT FROM
                  job_row.idempotency_sha256
               OR request_json->>'campaign_brief_sha256' !~ '^[0-9a-f]{{64}}$'
               OR request_json->>'connector_binding_sha256' !~ '^[0-9a-f]{{64}}$'
               OR request_json->>'idempotency_sha256' !~ '^[0-9a-f]{{64}}$'
               OR request_json->>'tool_descriptor_sha256' !~ '^[0-9a-f]{{64}}$'
               OR request_json->>'tool_inputs_sha256' !~ '^[0-9a-f]{{64}}$'
               OR jsonb_typeof(request_json->'tool_input_ref_count')
                  IS DISTINCT FROM 'number'
               OR request_json->>'tool_input_ref_count'
                  !~ '^(0|[1-9][0-9]{{0,2}}|1000)$'
               OR request_json->'safe_reason_codes' IS DISTINCT FROM '[]'::jsonb
               OR descriptor_evidence.source IS DISTINCT FROM
                  'governed-media-job-tool-descriptor'
               OR descriptor_evidence.grade IS DISTINCT FROM 'B'
               OR descriptor_evidence.content_type IS DISTINCT FROM 'application/json'
               OR descriptor_evidence.created_by IS DISTINCT FROM job_row.subject_actor_id
               OR descriptor_evidence.effective_at IS DISTINCT FROM job_row.created_at
               OR descriptor_evidence.recorded_at IS DISTINCT FROM job_row.created_at
               OR descriptor_evidence.effective_until IS NOT NULL
               OR descriptor_evidence.blob_sha256 IS DISTINCT FROM descriptor_blob.sha256
               OR NEW.descriptor_evidence_sha256 IS DISTINCT FROM descriptor_blob.sha256
               OR encode(sha256(descriptor_blob.content_bytes), 'hex')
                  IS DISTINCT FROM descriptor_blob.sha256
               OR descriptor_evidence.source_ref IS DISTINCT FROM
                  ('media-job://' || NEW.job_ref || '/tool-descriptor/' ||
                   NEW.tool_descriptor_sha256)
               OR jsonb_typeof(descriptor_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(descriptor_json)) <> 11
               OR NOT descriptor_json ?& ARRAY[
                    'contract_id','registry_sha256','tool_name','tool_version',
                    'capabilities','cost_upper_bound','output_contract','provider',
                    'connector_ref','connector_binding_sha256','descriptor_sha256'
               ]
               OR descriptor_json->>'contract_id' IS DISTINCT FROM
                  'kjds-media-tool-descriptor-seal-v1'
               OR descriptor_json->>'descriptor_sha256' IS DISTINCT FROM descriptor_sha
               OR NEW.tool_descriptor_sha256 IS DISTINCT FROM descriptor_sha
               OR NEW.recorded_at IS DISTINCT FROM job_row.created_at
               OR request_json->>'tool_descriptor_sha256' IS DISTINCT FROM descriptor_sha
               OR descriptor_json->>'tool_name' IS DISTINCT FROM job_row.tool_name
               OR descriptor_json->>'tool_version' IS DISTINCT FROM job_row.tool_version
               OR descriptor_json->>'provider' IS DISTINCT FROM job_row.provider
               OR descriptor_json->>'connector_ref' IS DISTINCT FROM job_row.connector_ref
               OR descriptor_json->>'connector_binding_sha256' IS DISTINCT FROM
                  job_row.connector_binding_sha256
               OR descriptor_json->>'connector_binding_sha256'
                  !~ '^[0-9a-f]{{64}}$'
               OR descriptor_json->>'registry_sha256' !~ '^[0-9a-f]{{64}}$'
               OR descriptor_json->>'output_contract' IS DISTINCT FROM
                  request_json->>'output_contract'
               OR jsonb_typeof(descriptor_json->'capabilities')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(descriptor_json->'capabilities') = 0
               OR EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements(descriptor_json->'capabilities') item
                     WHERE jsonb_typeof(item) IS DISTINCT FROM 'string'
                        OR length(item #>> '{{}}') = 0
               )
               OR jsonb_typeof(descriptor_json->'cost_upper_bound')
                  IS DISTINCT FROM 'object'
               OR descriptor_evidence.metadata_json::jsonb IS DISTINCT FROM jsonb_build_object(
                    'contract_id','kjds-media-tool-descriptor-evidence-v1',
                    'tenant_ref',NEW.tenant_ref,
                    'entity_ref',NEW.entity_ref,
                    'store_ref',NEW.store_ref,
                    'scope_grant_authority_sha256',NEW.scope_grant_authority_sha256,
                    'subject_actor_id',job_row.subject_actor_id,
                    'media_job_ref',NEW.job_ref,
                    'descriptor_sha256',NEW.tool_descriptor_sha256
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job request descriptor binding drifted';
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE TRIGGER trg_media_job_request_binding_validate
        BEFORE INSERT ON media_job_request_bindings
        FOR EACH ROW EXECUTE FUNCTION
            {quoted_schema}.kjds_media_job_validate_request_binding()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_request_binding_immutable()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE='55000',
                MESSAGE='media-job request binding is immutable';
        END;
        $$
        """)
    op.execute(f"""
        CREATE TRIGGER trg_media_job_request_binding_immutable
        BEFORE UPDATE OR DELETE ON media_job_request_bindings
        FOR EACH ROW EXECUTE FUNCTION
            {quoted_schema}.kjds_media_job_request_binding_immutable()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_request_binding_conserved()
        RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            binding_count integer;
            worker_count integer;
            input_link_count integer;
        BEGIN
            IF NEW.tool_name IN ('media.video_blueprint','media.video_render') THEN
                SELECT count(*) INTO binding_count
                  FROM {quoted_schema}.media_job_request_bindings binding
                 WHERE binding.job_ref = NEW.job_ref
                   AND binding.tenant_ref = NEW.tenant_ref
                   AND binding.entity_ref = NEW.entity_ref
                   AND binding.store_ref = NEW.store_ref
                   AND binding.scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256;
                IF binding_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job request descriptor binding is not conserved';
                END IF;
                SELECT count(*) INTO worker_count
                  FROM {quoted_schema}.media_job_worker_inputs worker_input
                 WHERE worker_input.job_ref = NEW.job_ref
                   AND worker_input.tenant_ref = NEW.tenant_ref
                   AND worker_input.entity_ref = NEW.entity_ref
                   AND worker_input.store_ref = NEW.store_ref
                   AND worker_input.scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256
                   AND worker_input.tool_name = NEW.tool_name
                   AND worker_input.tool_version = NEW.tool_version;
                IF worker_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job worker input is not conserved';
                END IF;
                SELECT count(*) INTO input_link_count
                  FROM {quoted_schema}.media_job_evidence_links link
                 WHERE link.job_ref = NEW.job_ref
                   AND link.tenant_ref = NEW.tenant_ref
                   AND link.entity_ref = NEW.entity_ref
                   AND link.store_ref = NEW.store_ref
                   AND link.scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256
                   AND link.event_ref IS NULL
                   AND link.purpose = CASE
                        WHEN NEW.tool_name = 'media.video_blueprint'
                            THEN 'analysis_input'
                        ELSE 'blueprint_input'
                   END;
                IF input_link_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job governed input link is not conserved';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE CONSTRAINT TRIGGER trg_media_job_request_binding_conserved
        AFTER INSERT ON media_jobs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION
            {quoted_schema}.kjds_media_job_request_binding_conserved()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_validate_worker_input() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            job_row record;
            evidence_row record;
            blob_row record;
            payload jsonb;
        BEGIN
            payload := NEW.worker_input_json::jsonb;
            SELECT * INTO job_row
              FROM {quoted_schema}.media_jobs
             WHERE job_ref = NEW.job_ref
               AND tenant_ref = NEW.tenant_ref
               AND entity_ref = NEW.entity_ref
               AND store_ref = NEW.store_ref
               AND scope_grant_authority_sha256 = NEW.scope_grant_authority_sha256;
            IF NOT FOUND
               OR job_row.tool_name IS DISTINCT FROM NEW.tool_name
               OR job_row.tool_version IS DISTINCT FROM NEW.tool_version
               OR NEW.tool_name NOT IN ('media.video_blueprint','media.video_render') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input descriptor drifted';
            END IF;
            IF jsonb_typeof(payload) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(payload)) <> 14
               OR NOT payload ?& ARRAY[
                    'contract_id','tool_name','tool_version','project_ref','brief_ref',
                    'campaign_content_asset_refs','editing_blueprint_ref',
                    'reference_asset_refs','source_asset_refs','audio_asset_refs',
                    'target_channels','analysis_evidence_ref',
                    'analysis_contract_sha256','render_profile_sha256'
               ]
               OR payload->>'contract_id' IS DISTINCT FROM
                  'kjds-governed-media-job-worker-input-v1'
               OR payload->>'tool_name' IS DISTINCT FROM NEW.tool_name
               OR payload->>'tool_version' IS DISTINCT FROM NEW.tool_version
               OR payload->>'project_ref' IS DISTINCT FROM job_row.project_ref
               OR payload->>'brief_ref' IS DISTINCT FROM job_row.brief_ref THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input shape drifted';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM (VALUES
                    (payload->'campaign_content_asset_refs'),
                    (payload->'reference_asset_refs'),
                    (payload->'source_asset_refs'),
                    (payload->'audio_asset_refs'),
                    (payload->'target_channels')
                  ) arrays(value)
                 WHERE jsonb_typeof(value) IS DISTINCT FROM 'array'
                    OR jsonb_array_length(value) > 100
                    OR (SELECT count(*) FROM jsonb_array_elements(value))
                       IS DISTINCT FROM
                       (SELECT count(DISTINCT item #>> '{{}}')
                          FROM jsonb_array_elements(value) item)
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(value) item
                         WHERE jsonb_typeof(item) IS DISTINCT FROM 'string'
                            OR length(item #>> '{{}}') = 0
                            OR length(item #>> '{{}}') > 500
                            OR btrim(item #>> '{{}}')
                               IS DISTINCT FROM item #>> '{{}}'
                            OR item #>> '{{}}' !~
                               '^[A-Za-z0-9_.:/-]+$'
                    )
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input refs drifted';
            END IF;
            IF jsonb_array_length(payload->'campaign_content_asset_refs') = 0
               OR (
                    payload->'analysis_evidence_ref' <> 'null'::jsonb
                    AND (
                        jsonb_typeof(payload->'analysis_evidence_ref')
                           IS DISTINCT FROM 'string'
                        OR length(payload->>'analysis_evidence_ref') = 0
                        OR length(payload->>'analysis_evidence_ref') > 500
                        OR btrim(payload->>'analysis_evidence_ref')
                           IS DISTINCT FROM payload->>'analysis_evidence_ref'
                        OR payload->>'analysis_evidence_ref' !~
                           '^evidence://[A-Za-z0-9_.:/-]+$'
                    )
               )
               OR (
                    payload->'editing_blueprint_ref' <> 'null'::jsonb
                    AND (
                        jsonb_typeof(payload->'editing_blueprint_ref')
                           IS DISTINCT FROM 'string'
                        OR length(payload->>'editing_blueprint_ref') = 0
                        OR length(payload->>'editing_blueprint_ref') > 500
                        OR btrim(payload->>'editing_blueprint_ref')
                           IS DISTINCT FROM payload->>'editing_blueprint_ref'
                        OR payload->>'editing_blueprint_ref' !~
                           '^[A-Za-z0-9_.:/-]+$'
                    )
               )
               OR (
                    payload->'analysis_contract_sha256' <> 'null'::jsonb
                    AND payload->>'analysis_contract_sha256'
                        !~ '^[0-9a-f]{{64}}$'
               )
               OR (
                    payload->'render_profile_sha256' <> 'null'::jsonb
                    AND payload->>'render_profile_sha256'
                        !~ '^[0-9a-f]{{64}}$'
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input scalar drifted';
            END IF;
            IF NEW.tool_name = 'media.video_blueprint' AND (
                    jsonb_array_length(payload->'reference_asset_refs') = 0
                    OR payload->'editing_blueprint_ref' <> 'null'::jsonb
                    OR jsonb_array_length(payload->'source_asset_refs') <> 0
                    OR jsonb_array_length(payload->'audio_asset_refs') <> 1
                    OR payload->'analysis_evidence_ref' = 'null'::jsonb
                    OR payload->'analysis_contract_sha256' = 'null'::jsonb
                    OR payload->>'render_profile_sha256' IS DISTINCT FROM
                       'b197700a4c9421d48ea7470359abe94c6698961c30dfd401acdcb4f69927860e'
                    OR payload->'target_channels' IS DISTINCT FROM '["ozon"]'::jsonb
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            payload->'campaign_content_asset_refs') campaign(ref)
                         WHERE payload->'reference_asset_refs' ? campaign.ref
                            OR payload->'audio_asset_refs' ? campaign.ref
                    )
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            payload->'reference_asset_refs') reference(ref)
                         WHERE payload->'audio_asset_refs' ? reference.ref
                    )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job blueprint worker input drifted';
            ELSIF NEW.tool_name = 'media.video_render' AND (
                    payload->'editing_blueprint_ref' = 'null'::jsonb
                    OR jsonb_array_length(payload->'source_asset_refs') = 0
                    OR jsonb_array_length(payload->'audio_asset_refs') <> 1
                    OR jsonb_array_length(payload->'reference_asset_refs') <> 0
                    OR payload->'analysis_evidence_ref' <> 'null'::jsonb
                    OR payload->'analysis_contract_sha256' <> 'null'::jsonb
                    OR payload->>'render_profile_sha256' IS DISTINCT FROM
                       'b197700a4c9421d48ea7470359abe94c6698961c30dfd401acdcb4f69927860e'
                    OR payload->'target_channels' IS DISTINCT FROM '["ozon"]'::jsonb
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            payload->'campaign_content_asset_refs') campaign(ref)
                         WHERE payload->'source_asset_refs' ? campaign.ref
                            OR payload->'audio_asset_refs' ? campaign.ref
                    )
                    OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            payload->'source_asset_refs') source(ref)
                         WHERE payload->'audio_asset_refs' ? source.ref
                    )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job render worker input drifted';
            END IF;
            IF NEW.tool_name = 'media.video_blueprint' THEN
                SELECT * INTO evidence_row
                  FROM {quoted_schema}.evidence_records evidence
                 WHERE evidence.id = regexp_replace(
                    payload->>'analysis_evidence_ref', '^evidence://', ''
                 );
                IF FOUND THEN
                    SELECT * INTO blob_row
                      FROM {quoted_schema}.evidence_blobs blob
                     WHERE blob.sha256 = evidence_row.blob_sha256;
                END IF;
                IF evidence_row.id IS NULL OR blob_row.sha256 IS NULL
                   OR evidence_row.source IS DISTINCT FROM
                      'governed-reference-video-analysis'
                   OR evidence_row.grade IS DISTINCT FROM 'B'
                   OR evidence_row.content_type IS DISTINCT FROM 'application/json'
                   OR evidence_row.blob_sha256 IS DISTINCT FROM
                      payload->>'analysis_contract_sha256'
                   OR evidence_row.blob_sha256 IS DISTINCT FROM encode(
                        sha256(blob_row.content_bytes), 'hex'
                      )
                   OR evidence_row.metadata_json->>'contract_id'
                      IS DISTINCT FROM 'kjds-reference-video-analysis-v1'
                   OR evidence_row.metadata_json->>'tenant_ref'
                      IS DISTINCT FROM NEW.tenant_ref
                   OR evidence_row.metadata_json->>'entity_ref'
                      IS DISTINCT FROM NEW.entity_ref
                   OR evidence_row.metadata_json->>'store_ref'
                      IS DISTINCT FROM NEW.store_ref
                   OR evidence_row.metadata_json->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM NEW.scope_grant_authority_sha256
                   OR evidence_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM job_row.subject_actor_id
                   OR evidence_row.metadata_json->>'rights_status'
                      IS DISTINCT FROM 'approved'
                   OR evidence_row.metadata_json->>'schema_version'
                      IS DISTINCT FROM '1.0.0'
                   OR evidence_row.metadata_json->>'analysis_contract_sha256'
                      IS DISTINCT FROM payload->>'analysis_contract_sha256'
                   OR evidence_row.source_ref IS DISTINCT FROM
                      ('reference-analysis://' ||
                       (evidence_row.metadata_json->>'analysis_run_ref') || '/' ||
                       (payload->>'analysis_contract_sha256'))
                   OR convert_from(blob_row.content_bytes, 'UTF8')::jsonb->>'contract_id'
                      IS DISTINCT FROM 'kjds-reference-video-analysis-v1'
                   OR convert_from(blob_row.content_bytes, 'UTF8')::jsonb->>'analysis_run_ref'
                      IS DISTINCT FROM evidence_row.metadata_json->>'analysis_run_ref'
                   OR convert_from(blob_row.content_bytes, 'UTF8')::jsonb->>'observed_at'
                      IS DISTINCT FROM evidence_row.metadata_json->>'observed_at'
                   OR encode(sha256(convert_to(
                        {quoted_schema}.kjds_media_job_canonical_json(
                            convert_from(blob_row.content_bytes, 'UTF8')::jsonb
                            ->'source_video_artifacts'
                        ), 'UTF8'
                      )), 'hex') IS DISTINCT FROM
                      evidence_row.metadata_json->>'source_video_artifacts_sha256' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job analysis input Evidence drifted';
                END IF;
            END IF;
            IF NEW.worker_input_sha256 IS DISTINCT FROM encode(sha256(convert_to(
                {quoted_schema}.kjds_media_job_canonical_json(payload), 'UTF8'
            )), 'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input seal drifted';
            END IF;
            SELECT * INTO evidence_row
              FROM {quoted_schema}.evidence_records
             WHERE id = NEW.evidence_id;
            SELECT * INTO blob_row
              FROM {quoted_schema}.evidence_blobs
             WHERE sha256 = NEW.evidence_sha256;
            IF evidence_row.id IS NULL
               OR blob_row.sha256 IS NULL
               OR evidence_row.blob_sha256 IS DISTINCT FROM NEW.evidence_sha256
               OR evidence_row.source IS DISTINCT FROM
                  'governed-media-job-worker-input'
               OR evidence_row.source_ref IS DISTINCT FROM
                  ('media-job://' || NEW.job_ref || '/worker-input')
               OR evidence_row.grade IS DISTINCT FROM 'B'
               OR evidence_row.created_by IS DISTINCT FROM job_row.subject_actor_id
               OR evidence_row.metadata_json::jsonb IS DISTINCT FROM
                  jsonb_build_object(
                    'contract_id','kjds-governed-media-job-worker-input-v1',
                    'tenant_ref',NEW.tenant_ref,
                    'entity_ref',NEW.entity_ref,
                    'store_ref',NEW.store_ref,
                    'scope_grant_authority_sha256',NEW.scope_grant_authority_sha256,
                    'subject_actor_id',job_row.subject_actor_id,
                    'media_job_ref',NEW.job_ref,
                    'worker_input_sha256',NEW.worker_input_sha256
                  )
               OR blob_row.content_bytes IS DISTINCT FROM convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(payload), 'UTF8'
                  )
               OR encode(sha256(blob_row.content_bytes), 'hex')
                  IS DISTINCT FROM NEW.evidence_sha256
               OR NEW.recorded_at < evidence_row.recorded_at
               OR NEW.recorded_at > statement_timestamp() + interval '5 minutes' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job worker input Evidence drifted';
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE TRIGGER trg_media_job_worker_input_validate
        BEFORE INSERT ON media_job_worker_inputs
        FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.kjds_media_job_validate_worker_input()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_result_receipt_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='media-job 0098 receipt is immutable';
        END;
        $$
        """)
    op.execute(f"""
        CREATE TRIGGER trg_media_job_worker_input_immutable
        BEFORE UPDATE OR DELETE ON media_job_worker_inputs
        FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.kjds_media_job_result_receipt_immutable()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_validate_blueprint_provenance(
            p_evidence_id text,
            p_render_job_ref text DEFAULT NULL
        ) RETURNS void
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            evidence_row record;
            blob_row record;
            blueprint_job record;
            render_job record;
            worker_row record;
            render_worker record;
            blueprint_terminal_event record;
            blueprint_receipt record;
            render_queued_event record;
            binding_row record;
            analysis_link record;
            analysis_evidence_row record;
            analysis_blob_row record;
            asset_row record;
            product_row record;
            artifact_evidence_row record;
            artifact_blob_row record;
            governed_text_row record;
            governed_text_blob_row record;
            blueprint_json jsonb;
            worker_json jsonb;
            render_worker_json jsonb;
            scope_json jsonb;
            analysis_json jsonb;
            analysis_content_json jsonb;
            expected_video_artifacts jsonb := '[]'::jsonb;
            expected_input_artifacts jsonb := '[]'::jsonb;
            source_snapshot_json jsonb;
            artifact_input jsonb;
            scene jsonb;
            governed_ref text;
            canonical_product_id text := NULL;
            prior_timeline_end bigint := 0;
            rendered_duration bigint := 0;
            receipt_count integer;
            terminal_count integer;
            reference_video_bytes bigint := 0;
            campaign_bytes bigint := 0;
            governed_text_bytes bigint := 0;
            validation_now timestamptz := statement_timestamp();
        BEGIN
            SELECT * INTO evidence_row
              FROM {quoted_schema}.evidence_records
             WHERE id = p_evidence_id;
            IF FOUND THEN
                SELECT * INTO blob_row
                  FROM {quoted_schema}.evidence_blobs
                 WHERE sha256 = evidence_row.blob_sha256;
            END IF;
            BEGIN
                blueprint_json := convert_from(blob_row.content_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint JSON invalid';
            END;
            SELECT * INTO blueprint_job
              FROM {quoted_schema}.media_jobs
             WHERE job_ref = blueprint_json->>'job_ref';
            SELECT * INTO worker_row
              FROM {quoted_schema}.media_job_worker_inputs
             WHERE job_ref = blueprint_job.job_ref;
            SELECT * INTO binding_row
              FROM {quoted_schema}.media_job_request_bindings
             WHERE job_ref = blueprint_job.job_ref;
            SELECT * INTO analysis_link
              FROM {quoted_schema}.media_job_evidence_links
             WHERE job_ref = blueprint_job.job_ref
               AND purpose = 'analysis_input'
               AND event_ref IS NULL;
            IF FOUND THEN
                SELECT * INTO analysis_evidence_row
                  FROM {quoted_schema}.evidence_records
                 WHERE id = analysis_link.evidence_id;
            END IF;
            IF analysis_evidence_row.id IS NOT NULL THEN
                SELECT * INTO analysis_blob_row
                  FROM {quoted_schema}.evidence_blobs
                 WHERE sha256 = analysis_evidence_row.blob_sha256;
            END IF;
            BEGIN
                analysis_content_json := convert_from(
                    analysis_blob_row.content_bytes,
                    'UTF8'
                )::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed analysis JSON invalid';
            END;
            worker_json := worker_row.worker_input_json::jsonb;
            scope_json := blueprint_json->'scope';
            analysis_json := blueprint_json->'analysis_receipt';

            -- Shape gates must run before any object_keys/array_length/elements
            -- call below.  PostgreSQL does not promise OR short-circuiting, so
            -- combining these guards with structural operators can leak 22023
            -- instead of the public 23514 contract.
            IF jsonb_typeof(blueprint_json) IS DISTINCT FROM 'object'
               OR jsonb_typeof(scope_json) IS DISTINCT FROM 'object'
               OR jsonb_typeof(analysis_json) IS DISTINCT FROM 'object'
               OR jsonb_typeof(analysis_content_json) IS DISTINCT FROM 'object'
               OR jsonb_typeof(worker_json) IS DISTINCT FROM 'object'
               OR jsonb_typeof(evidence_row.metadata_json::jsonb)
                  IS DISTINCT FROM 'object'
               OR jsonb_typeof(analysis_evidence_row.metadata_json::jsonb)
                  IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint object shape invalid';
            END IF;
            IF jsonb_typeof(blueprint_json->'campaign_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(blueprint_json->'reference_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(blueprint_json->'input_artifacts')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(blueprint_json->'scenes')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(blueprint_json->'target_channels')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(analysis_json->'source_video_artifacts')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(analysis_content_json->'source_video_artifacts')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(analysis_content_json->'scenes')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(analysis_content_json->'target_channels')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(worker_json->'campaign_content_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(worker_json->'reference_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(worker_json->'audio_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_typeof(worker_json->'target_channels')
                  IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint array shape invalid';
            END IF;

            IF jsonb_typeof(scope_json->'tenant_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(scope_json->'entity_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(scope_json->'store_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(scope_json->'authority_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(scope_json->'subject_actor_id') IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint scope scalar shape invalid';
            END IF;

            IF jsonb_typeof(blueprint_json->'contract_id') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'contract_version') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'job_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'tool_name') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'tool_version') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'provider') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'connector_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'connector_binding_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'tool_descriptor_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'scope_binding_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'source_snapshot_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'audio_asset_ref') IS DISTINCT FROM 'string'
               OR (
                    jsonb_typeof(blueprint_json->'subtitle_asset_ref')
                        IS DISTINCT FROM 'string'
                    AND jsonb_typeof(blueprint_json->'subtitle_asset_ref')
                        IS DISTINCT FROM 'null'
               )
               OR jsonb_typeof(blueprint_json->'render_profile_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(blueprint_json->'external_write_allowed') IS DISTINCT FROM 'boolean'
               OR jsonb_typeof(blueprint_json->'listing_eligible') IS DISTINCT FROM 'boolean' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint scalar shape invalid';
            END IF;

            IF jsonb_typeof(analysis_json->'contract_id') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_json->'source_snapshot_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_json->'semantic_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_json->'observed_at') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_json->'evidence_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_json->'evidence_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_content_json->'contract_id') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_content_json->'schema_version') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_content_json->'analysis_run_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(analysis_content_json->'observed_at') IS DISTINCT FROM 'string'
               OR (
                    jsonb_typeof(analysis_content_json->'subtitle_asset_ref')
                        IS DISTINCT FROM 'string'
                    AND jsonb_typeof(analysis_content_json->'subtitle_asset_ref')
                        IS DISTINCT FROM 'null'
               )
               OR jsonb_typeof(worker_json->'analysis_evidence_ref') IS DISTINCT FROM 'string'
               OR jsonb_typeof(worker_json->'analysis_contract_sha256') IS DISTINCT FROM 'string'
               OR jsonb_typeof(worker_json->'render_profile_sha256') IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed analysis scalar shape invalid';
            END IF;

            IF evidence_row.id IS NULL OR blob_row.sha256 IS NULL
               OR evidence_row.source IS DISTINCT FROM 'governed-media-job-blueprint'
               OR evidence_row.grade IS DISTINCT FROM 'B'
               OR evidence_row.content_type IS DISTINCT FROM 'application/json'
               OR evidence_row.filename IS DISTINCT FROM 'editing-blueprint.json'
               OR evidence_row.created_by IS DISTINCT FROM
                  blueprint_job.subject_actor_id
               OR evidence_row.byte_size IS DISTINCT FROM
                  octet_length(blob_row.content_bytes)
               OR evidence_row.effective_at IS DISTINCT FROM
                  evidence_row.recorded_at
               OR evidence_row.effective_at > validation_now
               OR evidence_row.blob_sha256 IS DISTINCT FROM
                  encode(sha256(blob_row.content_bytes), 'hex')
               OR blob_row.content_bytes IS DISTINCT FROM convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(blueprint_json),
                    'UTF8'
               )
               OR jsonb_typeof(blueprint_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(blueprint_json)) <> 23
               OR NOT blueprint_json ?& ARRAY[
                    'contract_id','contract_version','job_ref','tool_name','tool_version',
                    'provider','connector_ref','connector_binding_sha256',
                    'tool_descriptor_sha256','scope','scope_binding_sha256',
                    'source_snapshot_sha256','analysis_receipt','campaign_asset_refs',
                    'reference_asset_refs','input_artifacts','scenes','audio_asset_ref',
                    'subtitle_asset_ref','target_channels','render_profile_sha256',
                    'external_write_allowed','listing_eligible'
               ]
               OR blueprint_json->>'contract_id' IS DISTINCT FROM
                  'kjds-editing-blueprint-v1'
               OR blueprint_json->>'contract_version' IS DISTINCT FROM '1.0.0'
               OR blueprint_json->>'tool_name' IS DISTINCT FROM 'media.video_blueprint'
               OR blueprint_json->>'provider' IS DISTINCT FROM
                  'kjds_internal_blueprint_compiler'
               OR blueprint_json->>'connector_ref' IS DISTINCT FROM
                  'internal://editing-blueprint-compiler-v1'
                OR blueprint_json->>'connector_binding_sha256' IS DISTINCT FROM
                   '9efaed15669de37606902e0473e798323f3b2018655bf3a7d51058c15fa1a4c8'
               OR blueprint_json->>'render_profile_sha256' IS DISTINCT FROM
                  'b197700a4c9421d48ea7470359abe94c6698961c30dfd401acdcb4f69927860e'
               OR blueprint_json->'target_channels' IS DISTINCT FROM '["ozon"]'::jsonb
               OR blueprint_json->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR blueprint_json->'listing_eligible' IS DISTINCT FROM 'false'::jsonb
               OR blueprint_json->>'connector_binding_sha256' !~ '^[0-9a-f]{{64}}$'
               OR blueprint_json->>'tool_descriptor_sha256' !~ '^[0-9a-f]{{64}}$'
               OR blueprint_json->>'scope_binding_sha256' !~ '^[0-9a-f]{{64}}$'
               OR blueprint_json->>'source_snapshot_sha256' !~ '^[0-9a-f]{{64}}$'
               OR jsonb_typeof(scope_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(scope_json)) <> 5
               OR NOT scope_json ?& ARRAY[
                    'tenant_ref','entity_ref','store_ref','authority_sha256',
                    'subject_actor_id'
               ]
               OR blueprint_json->>'scope_binding_sha256' IS DISTINCT FROM
                  encode(sha256(convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(scope_json), 'UTF8'
                  )), 'hex')
               OR blueprint_job.job_ref IS NULL
               OR blueprint_job.tool_name IS DISTINCT FROM 'media.video_blueprint'
               OR blueprint_job.tool_version IS DISTINCT FROM blueprint_json->>'tool_version'
               OR blueprint_job.provider IS DISTINCT FROM blueprint_json->>'provider'
               OR blueprint_job.connector_ref IS DISTINCT FROM blueprint_json->>'connector_ref'
               OR blueprint_job.connector_binding_sha256 IS DISTINCT FROM
                  blueprint_json->>'connector_binding_sha256'
               OR (scope_json->>'tenant_ref',scope_json->>'entity_ref',
                   scope_json->>'store_ref',scope_json->>'authority_sha256',
                   scope_json->>'subject_actor_id') IS DISTINCT FROM
                  (blueprint_job.tenant_ref,blueprint_job.entity_ref,
                   blueprint_job.store_ref,blueprint_job.scope_grant_authority_sha256,
                   blueprint_job.subject_actor_id)
               OR evidence_row.source_ref IS DISTINCT FROM
                  ('media-job://' || blueprint_job.job_ref || '/blueprint/' ||
                   evidence_row.blob_sha256)
               OR jsonb_typeof(evidence_row.metadata_json::jsonb) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    evidence_row.metadata_json::jsonb
                  )) <> 11
               OR evidence_row.metadata_json::jsonb IS DISTINCT FROM jsonb_build_object(
                    'contract_id','kjds-editing-blueprint-v1',
                    'tenant_ref',blueprint_job.tenant_ref,
                    'entity_ref',blueprint_job.entity_ref,
                    'store_ref',blueprint_job.store_ref,
                    'scope_grant_authority_sha256',
                        blueprint_job.scope_grant_authority_sha256,
                    'subject_actor_id',blueprint_job.subject_actor_id,
                    'media_job_ref',blueprint_job.job_ref,
                    'blueprint_sha256',evidence_row.blob_sha256,
                    'source_snapshot_sha256',blueprint_json->>'source_snapshot_sha256',
                    'analysis_evidence_sha256',analysis_json->>'evidence_sha256',
                    'render_plan_sha256',
                        evidence_row.metadata_json::jsonb->>'render_plan_sha256'
                  )
               OR worker_row.job_ref IS NULL
               OR binding_row.job_ref IS NULL
               OR binding_row.tool_descriptor_sha256 IS DISTINCT FROM
                  blueprint_json->>'tool_descriptor_sha256'
               OR jsonb_typeof(worker_json) IS DISTINCT FROM 'object'
               OR worker_json->>'analysis_evidence_ref' IS DISTINCT FROM
                  analysis_json->>'evidence_ref'
               OR worker_json->>'analysis_contract_sha256' IS DISTINCT FROM
                  analysis_json->>'evidence_sha256'
               OR worker_json->'campaign_content_asset_refs' IS DISTINCT FROM
                  blueprint_json->'campaign_asset_refs'
               OR worker_json->'reference_asset_refs' IS DISTINCT FROM
                  blueprint_json->'reference_asset_refs'
               OR worker_json->'audio_asset_refs' IS DISTINCT FROM
                  jsonb_build_array(blueprint_json->>'audio_asset_ref')
               OR worker_json->'target_channels' IS DISTINCT FROM
                  blueprint_json->'target_channels'
               OR worker_json->>'render_profile_sha256' IS DISTINCT FROM
                  blueprint_json->>'render_profile_sha256'
               OR analysis_link.job_ref IS NULL
               OR analysis_link.evidence_id IS DISTINCT FROM
                  regexp_replace(analysis_json->>'evidence_ref','^evidence://','')
               OR analysis_link.blob_sha256 IS DISTINCT FROM
                   analysis_json->>'evidence_sha256'
               OR analysis_evidence_row.id IS NULL
               OR analysis_blob_row.sha256 IS NULL
               OR analysis_evidence_row.source IS DISTINCT FROM
                  'governed-reference-video-analysis'
               OR analysis_evidence_row.grade IS DISTINCT FROM 'B'
               OR analysis_evidence_row.content_type IS DISTINCT FROM 'application/json'
               OR analysis_evidence_row.filename IS DISTINCT FROM
                  'reference-analysis.json'
               OR analysis_evidence_row.created_by IS DISTINCT FROM
                  blueprint_job.subject_actor_id
               OR analysis_evidence_row.byte_size IS DISTINCT FROM
                  octet_length(analysis_blob_row.content_bytes)
               OR analysis_evidence_row.effective_at IS DISTINCT FROM
                  analysis_evidence_row.recorded_at
               OR analysis_evidence_row.effective_at > validation_now
               OR analysis_evidence_row.recorded_at > evidence_row.effective_at
               OR analysis_evidence_row.blob_sha256 IS DISTINCT FROM
                  encode(sha256(analysis_blob_row.content_bytes), 'hex')
               OR analysis_blob_row.content_bytes IS DISTINCT FROM convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(
                        analysis_content_json
                    ),
                    'UTF8'
               )
               OR analysis_evidence_row.source_ref IS DISTINCT FROM
                  ('reference-analysis://' ||
                   (analysis_evidence_row.metadata_json::jsonb->>'analysis_run_ref') ||
                   '/' || analysis_evidence_row.blob_sha256)
               OR jsonb_typeof(analysis_evidence_row.metadata_json::jsonb)
                  IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    analysis_evidence_row.metadata_json::jsonb)) <> 12
               OR NOT analysis_evidence_row.metadata_json::jsonb ?& ARRAY[
                    'contract_id','tenant_ref','entity_ref','store_ref',
                    'scope_grant_authority_sha256','subject_actor_id',
                    'analysis_contract_sha256','analysis_run_ref',
                    'source_video_artifacts_sha256','rights_status',
                    'schema_version','observed_at'
               ]
               OR analysis_evidence_row.metadata_json::jsonb->>'contract_id'
                  IS DISTINCT FROM 'kjds-reference-video-analysis-v1'
               OR analysis_evidence_row.metadata_json::jsonb->>'tenant_ref'
                  IS DISTINCT FROM blueprint_job.tenant_ref
               OR analysis_evidence_row.metadata_json::jsonb->>'entity_ref'
                  IS DISTINCT FROM blueprint_job.entity_ref
               OR analysis_evidence_row.metadata_json::jsonb->>'store_ref'
                  IS DISTINCT FROM blueprint_job.store_ref
               OR analysis_evidence_row.metadata_json::jsonb
                    ->>'scope_grant_authority_sha256'
                  IS DISTINCT FROM blueprint_job.scope_grant_authority_sha256
               OR analysis_evidence_row.metadata_json::jsonb->>'subject_actor_id'
                  IS DISTINCT FROM blueprint_job.subject_actor_id
               OR analysis_evidence_row.metadata_json::jsonb->>'analysis_contract_sha256'
                  IS DISTINCT FROM analysis_evidence_row.blob_sha256
               OR analysis_evidence_row.metadata_json::jsonb->>'rights_status'
                  IS DISTINCT FROM 'approved'
               OR analysis_evidence_row.metadata_json::jsonb->>'schema_version'
                  IS DISTINCT FROM '1.0.0'
               OR jsonb_typeof(analysis_content_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(analysis_content_json)) <> 8
               OR NOT analysis_content_json ?& ARRAY[
                    'contract_id','schema_version','analysis_run_ref','observed_at',
                    'source_video_artifacts','scenes','subtitle_asset_ref',
                    'target_channels'
               ]
               OR analysis_content_json->>'contract_id' IS DISTINCT FROM
                  'kjds-reference-video-analysis-v1'
               OR analysis_content_json->>'schema_version' IS DISTINCT FROM '1.0.0'
               OR analysis_content_json->>'analysis_run_ref' IS DISTINCT FROM
                  analysis_evidence_row.metadata_json::jsonb->>'analysis_run_ref'
               OR analysis_content_json->>'observed_at' IS DISTINCT FROM
                  analysis_evidence_row.metadata_json::jsonb->>'observed_at'
               OR analysis_content_json->'target_channels' IS DISTINCT FROM
                  '["ozon"]'::jsonb
               OR jsonb_typeof(analysis_json) IS DISTINCT FROM 'object'
               OR (SELECT count(*) FROM jsonb_object_keys(analysis_json)) <> 7
               OR NOT analysis_json ?& ARRAY[
                    'contract_id','source_snapshot_sha256','semantic_sha256',
                    'observed_at','evidence_ref','evidence_sha256',
                    'source_video_artifacts'
               ]
               OR analysis_json->>'contract_id' IS DISTINCT FROM
                  'kjds-reference-video-analysis-v1'
               OR analysis_json->>'source_snapshot_sha256' !~ '^[0-9a-f]{{64}}$'
               OR analysis_json->>'semantic_sha256' !~ '^[0-9a-f]{{64}}$'
               OR analysis_json->>'evidence_sha256' !~ '^[0-9a-f]{{64}}$'
               OR analysis_json->>'semantic_sha256' IS DISTINCT FROM
                  analysis_evidence_row.blob_sha256
               OR analysis_json->>'evidence_ref' IS DISTINCT FROM
                  ('evidence://' || analysis_evidence_row.id)
               OR analysis_json->>'evidence_sha256' IS DISTINCT FROM
                  analysis_evidence_row.blob_sha256
               OR (analysis_json->>'observed_at')::timestamptz IS DISTINCT FROM
                  analysis_evidence_row.effective_at
               OR analysis_content_json->>'observed_at' IS DISTINCT FROM
                  analysis_json->>'observed_at'
               OR analysis_content_json->'scenes' IS DISTINCT FROM
                  blueprint_json->'scenes'
               OR analysis_content_json->'subtitle_asset_ref' IS DISTINCT FROM
                  blueprint_json->'subtitle_asset_ref'
               OR jsonb_typeof(blueprint_json->'campaign_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(blueprint_json->'campaign_asset_refs') = 0
               OR jsonb_typeof(blueprint_json->'reference_asset_refs')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(blueprint_json->'reference_asset_refs') = 0
               OR jsonb_typeof(blueprint_json->'input_artifacts')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(blueprint_json->'input_artifacts') = 0
               OR jsonb_array_length(blueprint_json->'input_artifacts') > 300
               OR EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements_text(
                           blueprint_json->'campaign_asset_refs') campaign(ref)
                     WHERE blueprint_json->'reference_asset_refs' ? campaign.ref
                        OR campaign.ref = blueprint_json->>'audio_asset_ref'
               )
               OR blueprint_json->'reference_asset_refs' ?
                  (blueprint_json->>'audio_asset_ref')
               OR jsonb_typeof(blueprint_json->'scenes') IS DISTINCT FROM 'array'
               OR jsonb_array_length(blueprint_json->'scenes') = 0
               OR jsonb_array_length(blueprint_json->'scenes') > 200
               OR blueprint_json->>'audio_asset_ref'
                  !~ '^content-asset://[A-Za-z0-9_.:/-]+$'
               OR (blueprint_json->'subtitle_asset_ref' <> 'null'::jsonb AND (
                    jsonb_typeof(blueprint_json->'subtitle_asset_ref')
                       IS DISTINCT FROM 'string'
                    OR blueprint_json->>'subtitle_asset_ref'
                       !~ '^evidence://[A-Za-z0-9_.:/-]+$'
                    OR length(blueprint_json->>'subtitle_asset_ref') > 500
               ))
               OR (SELECT count(*) FROM jsonb_array_elements(
                    blueprint_json->'scenes')) <>
                  (SELECT count(DISTINCT item->>'caption_ref')
                     FROM jsonb_array_elements(blueprint_json->'scenes') item)
               OR EXISTS (
                    SELECT 1 FROM (VALUES
                      (blueprint_json->'campaign_asset_refs'),
                      (blueprint_json->'reference_asset_refs')
                    ) refs(value)
                    WHERE (SELECT count(*) FROM jsonb_array_elements(value)) <>
                          (SELECT count(DISTINCT item #>> '{{}}')
                             FROM jsonb_array_elements(value) item)
                       OR EXISTS (
                          SELECT 1 FROM jsonb_array_elements(value) item
                           WHERE jsonb_typeof(item) IS DISTINCT FROM 'string'
                             OR item #>> '{{}}' !~ '^content-asset://[A-Za-z0-9_.:/-]+$'
                       )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint provenance drifted';
            END IF;

            FOR artifact_input IN
                SELECT jsonb_build_object(
                    'content_asset_ref', entry.ref,
                    'role', entry.role
                )
                  FROM (
                    SELECT item #>> '{{}}' AS ref, 'campaign'::text AS role,
                           1 AS group_ordinal, item_ordinal
                      FROM jsonb_array_elements(
                           blueprint_json->'campaign_asset_refs')
                           WITH ORDINALITY AS campaign(item,item_ordinal)
                    UNION ALL
                    SELECT item #>> '{{}}', 'reference_video', 2, item_ordinal
                      FROM jsonb_array_elements(
                           blueprint_json->'reference_asset_refs')
                           WITH ORDINALITY AS reference(item,item_ordinal)
                    UNION ALL
                    SELECT blueprint_json->>'audio_asset_ref', 'audio', 3, 1
                  ) entry
                 ORDER BY entry.group_ordinal, entry.item_ordinal
            LOOP
                SELECT asset.* INTO asset_row
                  FROM {quoted_schema}.content_assets asset
                 WHERE asset.id = regexp_replace(
                    artifact_input->>'content_asset_ref',
                    '^content-asset://',
                    ''
                 );
                IF asset_row.id IS NOT NULL THEN
                    SELECT product.* INTO product_row
                      FROM {quoted_schema}.products product
                     WHERE product.id = asset_row.product_id;
                    SELECT evidence.* INTO artifact_evidence_row
                      FROM {quoted_schema}.evidence_records evidence
                     WHERE evidence.id = asset_row.artifact_ref;
                END IF;
                IF artifact_evidence_row.id IS NOT NULL THEN
                    SELECT blob.* INTO artifact_blob_row
                      FROM {quoted_schema}.evidence_blobs blob
                     WHERE blob.sha256 = artifact_evidence_row.blob_sha256;
                END IF;
                IF asset_row.id IS NULL OR product_row.id IS NULL
                   OR artifact_evidence_row.id IS NULL OR artifact_blob_row.sha256 IS NULL
                   OR asset_row.status IS DISTINCT FROM 'approved'
                   OR artifact_evidence_row.grade IS DISTINCT FROM 'B'
                   OR artifact_evidence_row.created_by IS DISTINCT FROM
                      blueprint_job.subject_actor_id
                   OR artifact_evidence_row.byte_size IS DISTINCT FROM
                      octet_length(artifact_blob_row.content_bytes)
                   OR artifact_evidence_row.effective_at > artifact_evidence_row.recorded_at
                   OR artifact_evidence_row.recorded_at > validation_now
                   OR artifact_evidence_row.recorded_at > evidence_row.effective_at
                   OR coalesce(length(artifact_evidence_row.filename), 0) = 0
                   OR length(artifact_evidence_row.filename) > 180
                   OR artifact_evidence_row.filename ~ '[\\/]'
                   OR artifact_evidence_row.filename LIKE '%..%'
                   OR artifact_evidence_row.filename ~ '[[:cntrl:]]'
                   OR artifact_evidence_row.blob_sha256 IS DISTINCT FROM
                      encode(sha256(artifact_blob_row.content_bytes), 'hex')
                   OR artifact_evidence_row.metadata_json->>'rights_status'
                      IS DISTINCT FROM 'approved'
                   OR (product_row.tenant_ref,product_row.entity_ref,product_row.store_ref,
                       product_row.scope_grant_authority_sha256) IS DISTINCT FROM
                      (blueprint_job.tenant_ref,blueprint_job.entity_ref,
                       blueprint_job.store_ref,
                       blueprint_job.scope_grant_authority_sha256)
                   OR artifact_evidence_row.metadata_json->>'tenant_ref'
                      IS DISTINCT FROM blueprint_job.tenant_ref
                   OR artifact_evidence_row.metadata_json->>'entity_ref'
                      IS DISTINCT FROM blueprint_job.entity_ref
                   OR artifact_evidence_row.metadata_json->>'store_ref'
                      IS DISTINCT FROM blueprint_job.store_ref
                   OR artifact_evidence_row.metadata_json
                        ->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM blueprint_job.scope_grant_authority_sha256
                   OR artifact_evidence_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM blueprint_job.subject_actor_id
                   OR (artifact_input->>'role' = 'reference_video' AND
                       (asset_row.content_type IS DISTINCT FROM 'video' OR
                        octet_length(artifact_blob_row.content_bytes) = 0 OR
                        octet_length(artifact_blob_row.content_bytes) > 268435456 OR
                        NOT (
                          (lower(artifact_evidence_row.filename) ~ '\\.mp4$' AND
                           artifact_evidence_row.content_type = 'video/mp4' AND
                           substring(artifact_blob_row.content_bytes FROM 5 FOR 4) =
                             convert_to('ftyp','UTF8')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.mov$' AND
                           artifact_evidence_row.content_type = 'video/quicktime' AND
                           substring(artifact_blob_row.content_bytes FROM 5 FOR 4) =
                             convert_to('ftyp','UTF8')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.webm$' AND
                           artifact_evidence_row.content_type = 'video/webm' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 4) =
                             decode('1a45dfa3','hex'))
                        )))
                   OR (artifact_input->>'role' = 'audio' AND
                       (asset_row.content_type IS DISTINCT FROM 'audio' OR
                        octet_length(artifact_blob_row.content_bytes) = 0 OR
                        octet_length(artifact_blob_row.content_bytes) > 67108864 OR
                        NOT (
                          (lower(artifact_evidence_row.filename) ~ '\\.wav$' AND
                           artifact_evidence_row.content_type = 'audio/wav' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 4) =
                             convert_to('RIFF','UTF8') AND
                           substring(artifact_blob_row.content_bytes FROM 9 FOR 4) =
                             convert_to('WAVE','UTF8')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.mp3$' AND
                           artifact_evidence_row.content_type = 'audio/mpeg' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 3) =
                             convert_to('ID3','UTF8')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.m4a$' AND
                           artifact_evidence_row.content_type = 'audio/mp4' AND
                           substring(artifact_blob_row.content_bytes FROM 5 FOR 4) =
                             convert_to('ftyp','UTF8')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.ogg$' AND
                           artifact_evidence_row.content_type = 'audio/ogg' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 4) =
                             convert_to('OggS','UTF8'))
                        )))
                   OR (artifact_input->>'role' = 'campaign' AND
                       (asset_row.content_type IS DISTINCT FROM 'image' OR
                        octet_length(artifact_blob_row.content_bytes) = 0 OR
                        octet_length(artifact_blob_row.content_bytes) > 33554432 OR
                        NOT (
                          (lower(artifact_evidence_row.filename) ~ '\\.png$' AND
                           artifact_evidence_row.content_type = 'image/png' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 8) =
                             decode('89504e470d0a1a0a','hex')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.(jpg|jpeg)$' AND
                           artifact_evidence_row.content_type = 'image/jpeg' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 3) =
                             decode('ffd8ff','hex')) OR
                          (lower(artifact_evidence_row.filename) ~ '\\.webp$' AND
                           artifact_evidence_row.content_type = 'image/webp' AND
                           substring(artifact_blob_row.content_bytes FROM 1 FOR 4) =
                             convert_to('RIFF','UTF8') AND
                           substring(artifact_blob_row.content_bytes FROM 9 FOR 4) =
                             convert_to('WEBP','UTF8'))
                        ))) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint input artifact drifted';
                END IF;
                IF canonical_product_id IS NULL THEN
                    canonical_product_id := product_row.id;
                ELSIF canonical_product_id IS DISTINCT FROM product_row.id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint products drifted';
                END IF;
                expected_input_artifacts := expected_input_artifacts ||
                    jsonb_build_array(jsonb_build_object(
                        'content_asset_ref',artifact_input->>'content_asset_ref',
                        'evidence_ref','evidence://' || artifact_evidence_row.id,
                        'evidence_sha256',artifact_evidence_row.blob_sha256,
                        'content_type',artifact_evidence_row.content_type,
                        'role',artifact_input->>'role'
                    ));
                IF artifact_input->>'role' = 'reference_video' THEN
                    reference_video_bytes := reference_video_bytes +
                        octet_length(artifact_blob_row.content_bytes);
                    expected_video_artifacts := expected_video_artifacts ||
                        jsonb_build_array(jsonb_build_object(
                            'content_asset_ref',artifact_input->>'content_asset_ref',
                            'evidence_ref','evidence://' || artifact_evidence_row.id,
                            'evidence_sha256',artifact_evidence_row.blob_sha256
                        ));
                END IF;
                IF artifact_input->>'role' = 'campaign' THEN
                    campaign_bytes := campaign_bytes +
                        octet_length(artifact_blob_row.content_bytes);
                END IF;
                asset_row := NULL;
                product_row := NULL;
                artifact_evidence_row := NULL;
                artifact_blob_row := NULL;
            END LOOP;
            IF reference_video_bytes > 536870912
               OR campaign_bytes > 134217728
               OR canonical_product_id IS NULL
               OR blueprint_json->'input_artifacts' IS DISTINCT FROM
                  expected_input_artifacts
               OR analysis_json->'source_video_artifacts' IS DISTINCT FROM
                  expected_video_artifacts
               OR analysis_content_json->'source_video_artifacts' IS DISTINCT FROM
                  expected_video_artifacts
               OR analysis_evidence_row.metadata_json::jsonb
                    ->>'source_video_artifacts_sha256' IS DISTINCT FROM
                  encode(sha256(convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(
                        expected_video_artifacts
                    ), 'UTF8')), 'hex')
               OR analysis_json->>'source_snapshot_sha256' IS DISTINCT FROM
                  encode(sha256(convert_to(
                    {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                        'contract_id','kjds-reference-video-analysis-v1',
                        'semantic_sha256',analysis_evidence_row.blob_sha256,
                        'observed_at',analysis_json->>'observed_at',
                        'evidence_ref','evidence://' || analysis_evidence_row.id,
                        'evidence_sha256',analysis_evidence_row.blob_sha256,
                        'source_video_artifacts',expected_video_artifacts
                    )), 'UTF8')), 'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint analysis receipt drifted';
            END IF;

            FOR scene IN SELECT value FROM jsonb_array_elements(blueprint_json->'scenes')
            LOOP
                IF jsonb_typeof(scene) IS DISTINCT FROM 'object'
                   OR (SELECT count(*) FROM jsonb_object_keys(scene)) <> 8
                   OR NOT scene ?& ARRAY[
                        'scene_id','source_asset_ref','source_start_ms','source_end_ms',
                        'timeline_start_ms','timeline_end_ms','transition','caption_ref'
                    ]
                   OR jsonb_typeof(scene->'scene_id') IS DISTINCT FROM 'string'
                   OR length(scene->>'scene_id') = 0
                   OR length(scene->>'scene_id') > 160
                   OR jsonb_typeof(scene->'source_start_ms') IS DISTINCT FROM 'number'
                   OR jsonb_typeof(scene->'source_end_ms') IS DISTINCT FROM 'number'
                   OR jsonb_typeof(scene->'timeline_start_ms') IS DISTINCT FROM 'number'
                   OR jsonb_typeof(scene->'timeline_end_ms') IS DISTINCT FROM 'number'
                   OR scene->>'source_start_ms' !~ '^(0|[1-9][0-9]*)$'
                   OR scene->>'source_end_ms' !~ '^[1-9][0-9]*$'
                   OR scene->>'timeline_start_ms' !~ '^(0|[1-9][0-9]*)$'
                   OR scene->>'timeline_end_ms' !~ '^[1-9][0-9]*$'
                   OR (scene->>'source_end_ms')::bigint <=
                      (scene->>'source_start_ms')::bigint
                   OR (scene->>'timeline_start_ms')::bigint <> prior_timeline_end
                   OR (scene->>'timeline_end_ms')::bigint <=
                      (scene->>'timeline_start_ms')::bigint
                   OR (scene->>'source_end_ms')::bigint -
                      (scene->>'source_start_ms')::bigint <>
                      (scene->>'timeline_end_ms')::bigint -
                      (scene->>'timeline_start_ms')::bigint
                   OR (scene->>'source_end_ms')::bigint -
                      (scene->>'source_start_ms')::bigint > 60000
                   OR (scene->>'timeline_end_ms')::bigint > 300000
                   OR scene->>'transition' NOT IN ('cut','fade','crossfade')
                   OR (scene->>'transition' = 'crossfade' AND
                       (rendered_duration < 250 OR
                        (scene->>'timeline_end_ms')::bigint -
                        (scene->>'timeline_start_ms')::bigint <= 250))
                   OR scene->>'caption_ref' !~ '^evidence://[A-Za-z0-9_.:/-]+$'
                   OR length(scene->>'caption_ref') > 500
                   OR NOT (blueprint_json->'reference_asset_refs' ?
                            (scene->>'source_asset_ref')) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint scene drifted';
                END IF;
                SELECT evidence.* INTO governed_text_row
                  FROM {quoted_schema}.evidence_records evidence
                 WHERE evidence.id = regexp_replace(
                    scene->>'caption_ref',
                    '^evidence://',
                    ''
                 );
                IF governed_text_row.id IS NOT NULL THEN
                    SELECT blob.* INTO governed_text_blob_row
                      FROM {quoted_schema}.evidence_blobs blob
                     WHERE blob.sha256 = governed_text_row.blob_sha256;
                END IF;
                IF governed_text_row.id IS NULL
                   OR governed_text_blob_row.sha256 IS NULL
                   OR governed_text_row.created_by IS DISTINCT FROM
                      blueprint_job.subject_actor_id
                   OR governed_text_row.byte_size IS DISTINCT FROM
                      octet_length(governed_text_blob_row.content_bytes)
                   OR governed_text_row.effective_at > governed_text_row.recorded_at
                   OR governed_text_row.recorded_at > validation_now
                   OR governed_text_row.recorded_at > evidence_row.effective_at
                   OR governed_text_row.blob_sha256 IS DISTINCT FROM
                      encode(sha256(governed_text_blob_row.content_bytes), 'hex')
                   OR octet_length(governed_text_blob_row.content_bytes) = 0
                   OR octet_length(governed_text_blob_row.content_bytes) > 2097152
                   OR position(decode('00','hex') in
                               governed_text_blob_row.content_bytes) <> 0
                   OR coalesce(length(governed_text_row.filename), 0) = 0
                   OR length(governed_text_row.filename) > 180
                   OR governed_text_row.filename ~ '[\\/]'
                   OR governed_text_row.filename LIKE '%..%'
                   OR governed_text_row.filename ~ '[[:cntrl:]]'
                   OR NOT (
                        (lower(governed_text_row.filename) ~ '\\.srt$' AND
                         governed_text_row.content_type = 'application/x-subrip') OR
                        (lower(governed_text_row.filename) ~ '\\.txt$' AND
                         governed_text_row.content_type = 'text/plain')
                      )
                   OR governed_text_row.metadata_json->>'rights_status'
                      IS DISTINCT FROM 'approved'
                   OR governed_text_row.metadata_json->>'tenant_ref'
                      IS DISTINCT FROM blueprint_job.tenant_ref
                   OR governed_text_row.metadata_json->>'entity_ref'
                      IS DISTINCT FROM blueprint_job.entity_ref
                   OR governed_text_row.metadata_json->>'store_ref'
                      IS DISTINCT FROM blueprint_job.store_ref
                   OR governed_text_row.metadata_json
                        ->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM blueprint_job.scope_grant_authority_sha256
                   OR governed_text_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM blueprint_job.subject_actor_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint caption drifted';
                END IF;
                BEGIN
                    PERFORM convert_from(governed_text_blob_row.content_bytes, 'UTF8');
                EXCEPTION WHEN character_not_in_repertoire THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint caption drifted';
                END;
                governed_text_bytes := governed_text_bytes +
                    octet_length(governed_text_blob_row.content_bytes);
                governed_text_row := NULL;
                governed_text_blob_row := NULL;
                rendered_duration := rendered_duration +
                    (scene->>'timeline_end_ms')::bigint -
                    (scene->>'timeline_start_ms')::bigint;
                IF scene->>'transition' = 'crossfade' THEN
                    rendered_duration := rendered_duration - 250;
                END IF;
                prior_timeline_end := (scene->>'timeline_end_ms')::bigint;
            END LOOP;
            IF (SELECT count(*) FROM jsonb_array_elements(
                    blueprint_json->'scenes')) <>
               (SELECT count(DISTINCT item->>'scene_id')
                  FROM jsonb_array_elements(blueprint_json->'scenes') item) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint scene identity drifted';
            END IF;
            governed_ref := blueprint_json->>'subtitle_asset_ref';
            IF governed_ref IS NOT NULL THEN
                SELECT evidence.* INTO governed_text_row
                  FROM {quoted_schema}.evidence_records evidence
                 WHERE evidence.id = regexp_replace(governed_ref, '^evidence://', '');
                IF governed_text_row.id IS NOT NULL THEN
                    SELECT blob.* INTO governed_text_blob_row
                      FROM {quoted_schema}.evidence_blobs blob
                     WHERE blob.sha256 = governed_text_row.blob_sha256;
                END IF;
                IF governed_text_row.id IS NULL
                   OR governed_text_blob_row.sha256 IS NULL
                   OR governed_text_row.created_by IS DISTINCT FROM
                      blueprint_job.subject_actor_id
                   OR governed_text_row.byte_size IS DISTINCT FROM
                      octet_length(governed_text_blob_row.content_bytes)
                   OR governed_text_row.effective_at > governed_text_row.recorded_at
                   OR governed_text_row.recorded_at > validation_now
                   OR governed_text_row.recorded_at > evidence_row.effective_at
                   OR governed_text_row.blob_sha256 IS DISTINCT FROM
                      encode(sha256(governed_text_blob_row.content_bytes), 'hex')
                   OR octet_length(governed_text_blob_row.content_bytes) = 0
                   OR octet_length(governed_text_blob_row.content_bytes) > 2097152
                   OR position(decode('00','hex') in
                               governed_text_blob_row.content_bytes) <> 0
                   OR coalesce(length(governed_text_row.filename), 0) = 0
                   OR length(governed_text_row.filename) > 180
                   OR governed_text_row.filename ~ '[\\/]'
                   OR governed_text_row.filename LIKE '%..%'
                   OR governed_text_row.filename ~ '[[:cntrl:]]'
                   OR NOT (
                        (lower(governed_text_row.filename) ~ '\\.srt$' AND
                         governed_text_row.content_type = 'application/x-subrip') OR
                        (lower(governed_text_row.filename) ~ '\\.txt$' AND
                         governed_text_row.content_type = 'text/plain')
                      )
                   OR governed_text_row.metadata_json->>'rights_status'
                      IS DISTINCT FROM 'approved'
                   OR governed_text_row.metadata_json->>'tenant_ref'
                      IS DISTINCT FROM blueprint_job.tenant_ref
                   OR governed_text_row.metadata_json->>'entity_ref'
                      IS DISTINCT FROM blueprint_job.entity_ref
                   OR governed_text_row.metadata_json->>'store_ref'
                      IS DISTINCT FROM blueprint_job.store_ref
                   OR governed_text_row.metadata_json
                        ->>'scope_grant_authority_sha256'
                      IS DISTINCT FROM blueprint_job.scope_grant_authority_sha256
                   OR governed_text_row.metadata_json->>'subject_actor_id'
                      IS DISTINCT FROM blueprint_job.subject_actor_id THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint subtitle drifted';
                END IF;
                BEGIN
                    PERFORM convert_from(governed_text_blob_row.content_bytes, 'UTF8');
                EXCEPTION WHEN character_not_in_repertoire THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='governed blueprint subtitle drifted';
                END;
                governed_text_bytes := governed_text_bytes +
                    octet_length(governed_text_blob_row.content_bytes);
            END IF;
            IF governed_text_bytes > 8388608 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint text budget drifted';
            END IF;
            source_snapshot_json := jsonb_build_object(
                'contract_id','kjds-editing-source-receipt-v1',
                'contract_version','1.0.0',
                'scope',scope_json,
                'scope_binding_sha256',blueprint_json->>'scope_binding_sha256',
                'rights_status','approved',
                'product_id',canonical_product_id,
                'campaign_asset_refs',blueprint_json->'campaign_asset_refs',
                'reference_asset_refs',blueprint_json->'reference_asset_refs',
                'input_artifacts',expected_input_artifacts,
                'analysis_receipt',jsonb_build_object(
                    'contract_id','kjds-reference-video-analysis-v1',
                    'semantic_sha256',analysis_evidence_row.blob_sha256,
                    'observed_at',analysis_json->>'observed_at',
                    'evidence_ref','evidence://' || analysis_evidence_row.id,
                    'evidence_sha256',analysis_evidence_row.blob_sha256,
                    'source_video_artifacts',expected_video_artifacts
                ),
                'scenes',blueprint_json->'scenes',
                'audio_asset_ref',blueprint_json->'audio_asset_ref',
                'subtitle_asset_ref',blueprint_json->'subtitle_asset_ref',
                'target_channels',blueprint_json->'target_channels',
                'render_profile_sha256',blueprint_json->>'render_profile_sha256',
                'editing_blueprint',NULL,
                'editing_blueprint_sha256',NULL
            );
            IF blueprint_json->>'source_snapshot_sha256' IS DISTINCT FROM
               encode(sha256(convert_to(
                 {quoted_schema}.kjds_media_job_canonical_json(source_snapshot_json),
                 'UTF8'
               )), 'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint source snapshot drifted';
            END IF;
            IF EXISTS (
                (SELECT item #>> '{{}}' FROM jsonb_array_elements(
                    blueprint_json->'reference_asset_refs') item)
                EXCEPT
                (SELECT DISTINCT item->>'source_asset_ref' FROM jsonb_array_elements(
                    blueprint_json->'scenes') item)
            ) OR EXISTS (
                SELECT 1
                  FROM jsonb_array_elements(blueprint_json->'input_artifacts') item
                  LEFT JOIN {quoted_schema}.content_assets asset
                    ON asset.id = regexp_replace(
                        item->>'content_asset_ref','^content-asset://','')
                  LEFT JOIN {quoted_schema}.products product
                    ON product.id = asset.product_id
                  LEFT JOIN {quoted_schema}.evidence_records artifact
                    ON artifact.id = regexp_replace(
                        item->>'evidence_ref','^evidence://','')
                 WHERE jsonb_typeof(item) IS DISTINCT FROM 'object'
                    OR (SELECT count(*) FROM jsonb_object_keys(item)) <> 5
                    OR NOT item ?& ARRAY[
                        'content_asset_ref','evidence_ref','evidence_sha256',
                        'content_type','role'
                    ]
                    OR asset.id IS NULL OR product.id IS NULL OR artifact.id IS NULL
                    OR asset.status IS DISTINCT FROM 'approved'
                    OR asset.artifact_ref IS DISTINCT FROM artifact.id
                    OR artifact.blob_sha256 IS DISTINCT FROM item->>'evidence_sha256'
                    OR artifact.content_type IS DISTINCT FROM item->>'content_type'
                    OR artifact.metadata_json->>'rights_status' IS DISTINCT FROM 'approved'
                    OR product.tenant_ref IS DISTINCT FROM blueprint_job.tenant_ref
                    OR product.entity_ref IS DISTINCT FROM blueprint_job.entity_ref
                    OR product.store_ref IS DISTINCT FROM blueprint_job.store_ref
                    OR product.scope_grant_authority_sha256 IS DISTINCT FROM
                       blueprint_job.scope_grant_authority_sha256
                    OR artifact.metadata_json->>'tenant_ref' IS DISTINCT FROM
                       blueprint_job.tenant_ref
                    OR artifact.metadata_json->>'entity_ref' IS DISTINCT FROM
                       blueprint_job.entity_ref
                    OR artifact.metadata_json->>'store_ref' IS DISTINCT FROM
                       blueprint_job.store_ref
                    OR artifact.metadata_json->>'scope_grant_authority_sha256'
                       IS DISTINCT FROM blueprint_job.scope_grant_authority_sha256
                    OR artifact.metadata_json->>'subject_actor_id' IS DISTINCT FROM
                       blueprint_job.subject_actor_id
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint asset provenance drifted';
            END IF;

            IF p_render_job_ref IS NOT NULL THEN
                SELECT * INTO render_job FROM {quoted_schema}.media_jobs
                 WHERE job_ref = p_render_job_ref;
                SELECT * INTO render_worker FROM {quoted_schema}.media_job_worker_inputs
                 WHERE job_ref = p_render_job_ref;
                render_worker_json := render_worker.worker_input_json::jsonb;
                SELECT receipt.* INTO blueprint_receipt
                  FROM {quoted_schema}.media_job_result_receipts receipt
                 WHERE receipt.job_ref = blueprint_job.job_ref
                   AND receipt.state = 'SUCCEEDED'
                   AND receipt.result_kind = 'editing_blueprint_evidence'
                   AND receipt.artifact_evidence_refs::jsonb =
                       jsonb_build_array(p_evidence_id)
                   AND receipt.content_asset_ref IS NULL;
                SELECT event.* INTO blueprint_terminal_event
                  FROM {quoted_schema}.media_job_events event
                 WHERE event.event_ref = blueprint_receipt.event_ref
                   AND event.job_ref = blueprint_job.job_ref
                   AND event.state = 'SUCCEEDED';
                SELECT event.* INTO render_queued_event
                  FROM {quoted_schema}.media_job_events event
                 WHERE event.job_ref = p_render_job_ref
                   AND event.state = 'QUEUED'
                   AND event.ordinal = 1;
                IF render_job.job_ref IS NULL OR render_worker.job_ref IS NULL
                   OR blueprint_receipt.receipt_ref IS NULL
                   OR blueprint_terminal_event.event_ref IS NULL
                   OR render_queued_event.event_ref IS NULL
                   OR blueprint_receipt.event_ref IS DISTINCT FROM
                      blueprint_terminal_event.event_ref
                   OR blueprint_terminal_event.recorded_at >
                      blueprint_receipt.recorded_at
                   OR blueprint_receipt.recorded_at > render_job.created_at
                   OR render_job.created_at IS DISTINCT FROM
                      render_worker.recorded_at
                   OR render_job.created_at IS DISTINCT FROM
                      render_queued_event.recorded_at
                   OR (render_job.tenant_ref,render_job.entity_ref,render_job.store_ref,
                       render_job.scope_grant_authority_sha256,
                       render_job.subject_actor_id) IS DISTINCT FROM
                      (blueprint_job.tenant_ref,blueprint_job.entity_ref,
                       blueprint_job.store_ref,
                       blueprint_job.scope_grant_authority_sha256,
                       blueprint_job.subject_actor_id)
                   OR render_worker_json->>'editing_blueprint_ref' IS DISTINCT FROM
                      ('evidence://' || p_evidence_id)
                   OR render_worker_json->'campaign_content_asset_refs' IS DISTINCT FROM
                      blueprint_json->'campaign_asset_refs'
                   OR render_worker_json->'source_asset_refs' IS DISTINCT FROM
                      blueprint_json->'reference_asset_refs'
                   OR render_worker_json->'audio_asset_refs' IS DISTINCT FROM
                      jsonb_build_array(blueprint_json->>'audio_asset_ref')
                   OR render_worker_json->'target_channels' IS DISTINCT FROM
                      blueprint_json->'target_channels'
                   OR render_worker_json->>'render_profile_sha256' IS DISTINCT FROM
                      blueprint_json->>'render_profile_sha256' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='render blueprint provenance drifted';
                END IF;
            END IF;
        EXCEPTION
            WHEN invalid_datetime_format OR datetime_field_overflow
              OR invalid_text_representation OR character_not_in_repertoire
              OR numeric_value_out_of_range OR invalid_parameter_value THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='governed blueprint scalar shape invalid';
        END;
        $$
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_validate_analysis_link()
        RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            worker_row record;
            evidence_row record;
        BEGIN
            IF NEW.purpose NOT IN ('analysis_input','blueprint_input') THEN
                RETURN NEW;
            END IF;
            SELECT * INTO worker_row
              FROM {quoted_schema}.media_job_worker_inputs
             WHERE job_ref = NEW.job_ref
               AND tenant_ref = NEW.tenant_ref
               AND entity_ref = NEW.entity_ref
               AND store_ref = NEW.store_ref
               AND scope_grant_authority_sha256 = NEW.scope_grant_authority_sha256;
            SELECT * INTO evidence_row
              FROM {quoted_schema}.evidence_records
             WHERE id = NEW.evidence_id;
            IF worker_row.job_ref IS NULL
               OR NEW.event_ref IS NOT NULL
               OR evidence_row.id IS NULL
               OR (NEW.blob_sha256,NEW.source,NEW.source_ref,NEW.effective_at,
                   NEW.recorded_at) IS DISTINCT FROM
                  (evidence_row.blob_sha256,evidence_row.source,
                   evidence_row.source_ref,evidence_row.effective_at,
                   evidence_row.recorded_at)
               OR (
                    NEW.purpose = 'analysis_input' AND (
                        worker_row.tool_name IS DISTINCT FROM 'media.video_blueprint'
                        OR NEW.source IS DISTINCT FROM
                           'governed-reference-video-analysis'
                        OR NEW.evidence_id IS DISTINCT FROM regexp_replace(
                            worker_row.worker_input_json::jsonb
                                ->>'analysis_evidence_ref',
                            '^evidence://', ''
                          )
                        OR NEW.blob_sha256 IS DISTINCT FROM
                           worker_row.worker_input_json::jsonb
                                ->>'analysis_contract_sha256'
                    )
               )
               OR (
                    NEW.purpose = 'blueprint_input' AND (
                        worker_row.tool_name IS DISTINCT FROM 'media.video_render'
                        OR NEW.source IS DISTINCT FROM
                           'governed-media-job-blueprint'
                        OR NEW.evidence_id IS DISTINCT FROM regexp_replace(
                            worker_row.worker_input_json::jsonb
                                ->>'editing_blueprint_ref',
                            '^evidence://', ''
                          )
                    )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job analysis input link drifted';
            END IF;
            IF NEW.purpose = 'blueprint_input' THEN
                PERFORM {quoted_schema}.kjds_media_job_validate_blueprint_provenance(
                    NEW.evidence_id,
                    NEW.job_ref
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f'CREATE TRIGGER trg_media_job_analysis_link_validate BEFORE INSERT ON media_job_evidence_links FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.kjds_media_job_validate_analysis_link()')
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_analysis_link_conserved()
        RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            link_count integer;
        BEGIN
            IF NEW.tool_name = 'media.video_blueprint' THEN
                SELECT count(*) INTO link_count
                  FROM {quoted_schema}.media_job_evidence_links link
                 WHERE link.job_ref = NEW.job_ref
                   AND link.tenant_ref = NEW.tenant_ref
                   AND link.entity_ref = NEW.entity_ref
                   AND link.store_ref = NEW.store_ref
                   AND link.scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256
                   AND link.purpose = 'analysis_input'
                   AND link.event_ref IS NULL;
                IF link_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job analysis input link is not conserved';
                END IF;
            ELSIF NEW.tool_name = 'media.video_render' THEN
                SELECT count(*) INTO link_count
                  FROM {quoted_schema}.media_job_evidence_links link
                 WHERE link.job_ref = NEW.job_ref
                   AND link.tenant_ref = NEW.tenant_ref
                   AND link.entity_ref = NEW.entity_ref
                   AND link.store_ref = NEW.store_ref
                   AND link.scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256
                   AND link.purpose = 'blueprint_input'
                   AND link.event_ref IS NULL;
                IF link_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job blueprint input link is not conserved';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE CONSTRAINT TRIGGER trg_media_job_analysis_link_conserved
        AFTER INSERT ON media_job_worker_inputs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION
            {quoted_schema}.kjds_media_job_analysis_link_conserved()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_blueprint_render_plan(
            p_blueprint jsonb
        ) RETURNS jsonb
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path=pg_catalog AS $$
          SELECT jsonb_build_object(
            'contract_id', 'kjds-ffmpeg-render-plan-v1',
            'executor', 'ffmpeg',
            'job_ref', p_blueprint->'job_ref',
            'tool_version', p_blueprint->'tool_version',
            'provider', p_blueprint->'provider',
            'connector_ref', p_blueprint->'connector_ref',
            'connector_binding_sha256', p_blueprint->'connector_binding_sha256',
            'tool_descriptor_sha256', p_blueprint->'tool_descriptor_sha256',
            'source_snapshot_sha256', p_blueprint->'source_snapshot_sha256',
            'blueprint_sha256', encode(sha256(convert_to(
                {quoted_schema}.kjds_media_job_canonical_json(p_blueprint),
                'UTF8'
            )), 'hex'),
            'reference_asset_refs', p_blueprint->'reference_asset_refs',
            'scenes', p_blueprint->'scenes',
            'audio_asset_ref', p_blueprint->'audio_asset_ref',
            'subtitle_asset_ref', p_blueprint->'subtitle_asset_ref',
            'target_channels', p_blueprint->'target_channels',
            'render_profile_sha256', p_blueprint->'render_profile_sha256',
            'external_write_allowed', false,
            'automatic_retry', false,
            'automatic_failover', false
          )
        $$
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_validate_result_receipt() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            ref_count integer;
            asset_output_count integer;
            asset_output_bytes bigint;
            job_row record;
            event_row record;
            asset_row record;
            evidence_row record;
            blob_row record;
            request_binding_row record;
            descriptor_evidence_row record;
            descriptor_blob_row record;
            render_worker_row record;
            blueprint_json jsonb;
            render_plan_json jsonb;
        BEGIN
            SELECT * INTO job_row
              FROM {quoted_schema}.media_jobs
             WHERE job_ref = NEW.job_ref
               AND tenant_ref = NEW.tenant_ref
               AND entity_ref = NEW.entity_ref
               AND store_ref = NEW.store_ref
               AND scope_grant_authority_sha256 = NEW.scope_grant_authority_sha256;
            IF NOT FOUND
               OR job_row.tool_name IS DISTINCT FROM NEW.tool_name
               OR job_row.tool_version IS DISTINCT FROM NEW.tool_version
               OR job_row.provider IS DISTINCT FROM NEW.provider
               OR job_row.connector_ref IS DISTINCT FROM NEW.connector_ref
               OR job_row.connector_binding_sha256
                  IS DISTINCT FROM NEW.connector_binding_sha256
               OR NEW.tool_name NOT IN ('media.video_blueprint','media.video_render') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result descriptor drifted';
            END IF;
            SELECT * INTO event_row
              FROM {quoted_schema}.media_job_events
             WHERE event_ref = NEW.event_ref
               AND job_ref = NEW.job_ref
               AND tenant_ref = NEW.tenant_ref
               AND entity_ref = NEW.entity_ref
               AND store_ref = NEW.store_ref
               AND scope_grant_authority_sha256 = NEW.scope_grant_authority_sha256;
            IF NOT FOUND OR event_row.state IS DISTINCT FROM NEW.state THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result event state drifted';
            END IF;
            IF NEW.recorded_at < event_row.recorded_at
               OR NEW.recorded_at > statement_timestamp() + interval '5 minutes' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result recorded time invalid';
            END IF;
            IF NEW.state = 'SUCCEEDED'
               AND NEW.recorded_at IS DISTINCT FROM event_row.recorded_at THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result terminal time drifted';
            END IF;
            IF NEW.state IS DISTINCT FROM 'SUCCEEDED' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job non-success result authority not admitted';
            END IF;
            IF jsonb_typeof(NEW.artifact_evidence_refs::jsonb)
                  IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result Evidence refs must be an array';
            END IF;
            IF jsonb_array_length(NEW.artifact_evidence_refs::jsonb) > 100
               OR EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements(NEW.artifact_evidence_refs::jsonb) item
                     WHERE jsonb_typeof(item) <> 'string'
                        OR length(item #>> '{{}}') = 0
                        OR length(item #>> '{{}}') > 500
                        OR btrim(item #>> '{{}}') IS DISTINCT FROM (item #>> '{{}}')
               )
               OR (NEW.content_asset_ref IS NOT NULL AND
                   (length(NEW.content_asset_ref) = 0 OR
                    length(NEW.content_asset_ref) > 500 OR
                    btrim(NEW.content_asset_ref) IS DISTINCT FROM NEW.content_asset_ref)) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result reference contract invalid';
            END IF;
            IF NEW.receipt_sha256 IS DISTINCT FROM encode(sha256(convert_to(
                {quoted_schema}.kjds_media_job_canonical_json(jsonb_build_object(
                    'artifact_evidence_refs', NEW.artifact_evidence_refs::jsonb,
                    'connector_binding_sha256', NEW.connector_binding_sha256,
                    'connector_ref', NEW.connector_ref,
                    'content_asset_ref', NEW.content_asset_ref,
                    'contract_id', 'kjds-governed-media-job-result-v1',
                    'event_ref', NEW.event_ref,
                    'event_sha256', event_row.event_sha256,
                    'job_ref', NEW.job_ref,
                    'provider', NEW.provider,
                    'result_kind', NEW.result_kind,
                    'state', NEW.state
                )), 'UTF8')), 'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result receipt seal drifted';
            END IF;
            IF NEW.state = 'SUCCEEDED' THEN
                IF job_row.tool_name = 'media.video_blueprint' THEN
                    IF NEW.result_kind IS DISTINCT FROM 'editing_blueprint_evidence'
                       OR jsonb_array_length(NEW.artifact_evidence_refs::jsonb) <> 1
                       OR NEW.content_asset_ref IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='successful blueprint result contract drifted';
                    END IF;
                    SELECT * INTO request_binding_row
                      FROM {quoted_schema}.media_job_request_bindings
                     WHERE job_ref = NEW.job_ref
                       AND tenant_ref = NEW.tenant_ref
                       AND entity_ref = NEW.entity_ref
                       AND store_ref = NEW.store_ref
                       AND scope_grant_authority_sha256 =
                           NEW.scope_grant_authority_sha256;
                    IF FOUND THEN
                        SELECT * INTO descriptor_evidence_row
                          FROM {quoted_schema}.evidence_records
                         WHERE id = request_binding_row.descriptor_evidence_id;
                    END IF;
                    IF descriptor_evidence_row.id IS NOT NULL THEN
                        SELECT * INTO descriptor_blob_row
                          FROM {quoted_schema}.evidence_blobs
                         WHERE sha256 = descriptor_evidence_row.blob_sha256;
                    END IF;
                    SELECT * INTO evidence_row
                      FROM {quoted_schema}.evidence_records evidence
                     WHERE evidence.id = (
                        NEW.artifact_evidence_refs::jsonb->>0
                     );
                    IF FOUND THEN
                        SELECT * INTO blob_row
                          FROM {quoted_schema}.evidence_blobs blob
                         WHERE blob.sha256 = evidence_row.blob_sha256;
                    END IF;
                    BEGIN
                        blueprint_json := convert_from(
                            blob_row.content_bytes, 'UTF8'
                        )::jsonb;
                    EXCEPTION WHEN OTHERS THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='blueprint result JSON invalid';
                    END;
                    render_plan_json :=
                        {quoted_schema}.kjds_media_job_blueprint_render_plan(
                            blueprint_json
                        );
                    PERFORM {quoted_schema}.kjds_media_job_validate_blueprint_provenance(
                        evidence_row.id,
                        NULL
                    );
                    IF evidence_row.id IS NULL OR blob_row.sha256 IS NULL
                       OR evidence_row.source IS DISTINCT FROM
                          'governed-media-job-blueprint'
                       OR evidence_row.grade IS DISTINCT FROM 'B'
                       OR evidence_row.content_type IS DISTINCT FROM 'application/json'
                       OR evidence_row.effective_at IS DISTINCT FROM NEW.recorded_at
                       OR evidence_row.recorded_at IS DISTINCT FROM NEW.recorded_at
                       OR evidence_row.blob_sha256 IS DISTINCT FROM encode(
                            sha256(blob_row.content_bytes), 'hex'
                          )
                       OR evidence_row.source_ref IS DISTINCT FROM
                          ('media-job://' || NEW.job_ref || '/blueprint/' ||
                           evidence_row.blob_sha256)
                       OR evidence_row.metadata_json->>'contract_id'
                          IS DISTINCT FROM 'kjds-editing-blueprint-v1'
                       OR evidence_row.metadata_json->>'tenant_ref'
                          IS DISTINCT FROM NEW.tenant_ref
                       OR evidence_row.metadata_json->>'entity_ref'
                          IS DISTINCT FROM NEW.entity_ref
                       OR evidence_row.metadata_json->>'store_ref'
                          IS DISTINCT FROM NEW.store_ref
                       OR evidence_row.metadata_json->>'scope_grant_authority_sha256'
                          IS DISTINCT FROM NEW.scope_grant_authority_sha256
                       OR evidence_row.metadata_json->>'subject_actor_id'
                          IS DISTINCT FROM job_row.subject_actor_id
                       OR evidence_row.metadata_json->>'media_job_ref'
                          IS DISTINCT FROM NEW.job_ref
                       OR evidence_row.metadata_json->>'blueprint_sha256'
                          IS DISTINCT FROM evidence_row.blob_sha256
                       OR evidence_row.metadata_json->>'source_snapshot_sha256'
                          !~ '^[0-9a-f]{{64}}$'
                       OR evidence_row.metadata_json->>'analysis_evidence_sha256'
                          !~ '^[0-9a-f]{{64}}$'
                       OR evidence_row.metadata_json->>'render_plan_sha256'
                          !~ '^[0-9a-f]{{64}}$'
                       OR evidence_row.metadata_json->>'render_plan_sha256'
                          IS DISTINCT FROM encode(sha256(convert_to(
                            {quoted_schema}.kjds_media_job_canonical_json(
                                render_plan_json
                            ), 'UTF8'
                          )), 'hex')
                       OR blueprint_json->>'contract_id' IS DISTINCT FROM
                          'kjds-editing-blueprint-v1'
                       OR blueprint_json->>'contract_version' IS DISTINCT FROM '1.0.0'
                       OR blueprint_json->>'job_ref' IS DISTINCT FROM NEW.job_ref
                       OR blueprint_json->>'tool_name' IS DISTINCT FROM job_row.tool_name
                       OR blueprint_json->>'tool_version' IS DISTINCT FROM job_row.tool_version
                       OR blueprint_json->>'provider' IS DISTINCT FROM job_row.provider
                       OR blueprint_json->>'connector_ref' IS DISTINCT FROM job_row.connector_ref
                       OR blueprint_json->>'connector_binding_sha256' IS DISTINCT FROM
                          job_row.connector_binding_sha256
                       OR request_binding_row.job_ref IS NULL
                       OR descriptor_evidence_row.id IS NULL
                       OR descriptor_blob_row.sha256 IS NULL
                       OR request_binding_row.tool_descriptor_sha256 IS DISTINCT FROM
                          blueprint_json->>'tool_descriptor_sha256'
                       OR descriptor_evidence_row.source IS DISTINCT FROM
                          'governed-media-job-tool-descriptor'
                       OR descriptor_evidence_row.blob_sha256 IS DISTINCT FROM
                          request_binding_row.descriptor_evidence_sha256
                       OR descriptor_blob_row.sha256 IS DISTINCT FROM
                          request_binding_row.descriptor_evidence_sha256
                       OR encode(sha256(descriptor_blob_row.content_bytes), 'hex')
                          IS DISTINCT FROM descriptor_blob_row.sha256
                       OR descriptor_evidence_row.source_ref IS DISTINCT FROM
                          ('media-job://' || NEW.job_ref || '/tool-descriptor/' ||
                           request_binding_row.tool_descriptor_sha256)
                       OR blueprint_json->>'source_snapshot_sha256' IS DISTINCT FROM
                          evidence_row.metadata_json->>'source_snapshot_sha256'
                       OR blueprint_json->'analysis_receipt'->>'evidence_sha256' IS DISTINCT FROM
                          evidence_row.metadata_json->>'analysis_evidence_sha256' THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='blueprint result Evidence drifted';
                    END IF;
                ELSIF job_row.tool_name = 'media.video_render' THEN
                SELECT * INTO render_worker_row
                  FROM {quoted_schema}.media_job_worker_inputs
                 WHERE job_ref = NEW.job_ref
                   AND tenant_ref = NEW.tenant_ref
                   AND entity_ref = NEW.entity_ref
                   AND store_ref = NEW.store_ref
                   AND scope_grant_authority_sha256 =
                       NEW.scope_grant_authority_sha256;
                IF NOT FOUND
                   OR render_worker_row.worker_input_json::jsonb
                        ->>'editing_blueprint_ref' IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='render blueprint worker input missing';
                END IF;
                PERFORM {quoted_schema}.kjds_media_job_validate_blueprint_provenance(
                    regexp_replace(
                        render_worker_row.worker_input_json::jsonb
                            ->>'editing_blueprint_ref',
                        '^evidence://',
                        ''
                    ),
                    NEW.job_ref
                );
                SELECT * INTO evidence_row
                  FROM {quoted_schema}.evidence_records
                 WHERE id = regexp_replace(
                    render_worker_row.worker_input_json::jsonb
                        ->>'editing_blueprint_ref',
                    '^evidence://',
                    ''
                 );
                IF NOT FOUND THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='render blueprint Evidence missing';
                END IF;
                SELECT * INTO blob_row
                  FROM {quoted_schema}.evidence_blobs
                 WHERE sha256 = evidence_row.blob_sha256;
                BEGIN
                    blueprint_json := convert_from(
                        blob_row.content_bytes, 'UTF8'
                    )::jsonb;
                    render_plan_json :=
                        {quoted_schema}.kjds_media_job_blueprint_render_plan(
                            blueprint_json
                        );
                EXCEPTION WHEN OTHERS THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='render blueprint lineage invalid';
                END;
                IF jsonb_array_length(NEW.artifact_evidence_refs::jsonb) = 0
                   OR NEW.result_kind IS DISTINCT FROM 'video_artifact_evidence'
                   OR NEW.content_asset_ref IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='successful media-job result lacks terminal artifact';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(NEW.artifact_evidence_refs::jsonb) item
                    WHERE jsonb_typeof(item) <> 'string'
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result Evidence refs must be strings';
                END IF;
                ref_count := jsonb_array_length(NEW.artifact_evidence_refs::jsonb);
                SELECT asset.* INTO asset_row
                  FROM {quoted_schema}.content_assets asset
                  JOIN {quoted_schema}.products product
                    ON product.id = asset.product_id
                 WHERE asset.id = NEW.content_asset_ref
                   AND product.tenant_ref = NEW.tenant_ref
                   AND product.entity_ref = NEW.entity_ref
                   AND product.store_ref = NEW.store_ref
                   AND product.scope_grant_authority_sha256
                      = NEW.scope_grant_authority_sha256;
                IF NOT FOUND THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result ContentAsset binding drifted';
                END IF;
                IF jsonb_typeof(asset_row.brief_json::jsonb)
                      IS DISTINCT FROM 'object'
                   OR jsonb_typeof(asset_row.source_facts_json::jsonb)
                      IS DISTINCT FROM 'object'
                   OR jsonb_typeof(asset_row.qa_results_json::jsonb)
                      IS DISTINCT FROM 'array'
                   OR jsonb_typeof(asset_row.generation_json::jsonb)
                      IS DISTINCT FROM 'object'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'executor')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'template_id')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'media_job_ref')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'result_receipt_sha256')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'execution_id')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'render_plan_sha256')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'source_snapshot_sha256')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'encoder_version')
                      IS DISTINCT FROM 'string'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'listing_eligible')
                      IS DISTINCT FROM 'boolean'
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'outputs')
                      IS DISTINCT FROM 'object' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result ContentAsset scalar shape invalid';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM jsonb_each(
                           asset_row.generation_json::jsonb->'outputs'
                      ) output
                     WHERE jsonb_typeof(output.value) IS DISTINCT FROM 'string'
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result ContentAsset scalar shape invalid';
                END IF;
                IF asset_row.content_type IS DISTINCT FROM 'video'
                   OR asset_row.status IS DISTINCT FROM 'generated'
                   OR asset_row.locale IS DISTINCT FROM 'ru-RU'
                   OR asset_row.channel IS DISTINCT FROM 'ozon'
                   OR asset_row.artifact_ref IS DISTINCT FROM
                      (asset_row.generation_json::jsonb->'outputs'->>'9:16')
                   OR asset_row.brief_json::jsonb IS DISTINCT FROM jsonb_build_object(
                        'contract_id', 'kjds-governed-editing-handoff-v1',
                        'job_ref', NEW.job_ref,
                        'source_snapshot_sha256',
                            asset_row.generation_json::jsonb->>'source_snapshot_sha256',
                        'render_plan_sha256',
                            asset_row.generation_json::jsonb->>'render_plan_sha256'
                      )
                   OR asset_row.source_facts_json::jsonb IS DISTINCT FROM '{{}}'::jsonb
                   OR asset_row.qa_results_json::jsonb IS DISTINCT FROM '[]'::jsonb
                   OR asset_row.generation_json->>'executor' IS DISTINCT FROM 'ffmpeg'
                   OR asset_row.generation_json->>'template_id'
                      IS DISTINCT FROM 'kjds-ffmpeg-product-video-v1'
                   OR asset_row.generation_json->>'media_job_ref'
                      IS DISTINCT FROM NEW.job_ref
                   OR asset_row.generation_json->>'result_receipt_sha256'
                      IS DISTINCT FROM NEW.receipt_sha256
                   OR coalesce(length(asset_row.generation_json->>'execution_id'), 0) = 0
                   OR length(asset_row.generation_json->>'execution_id') > 160
                   OR coalesce(length(asset_row.generation_json->>'render_plan_sha256'), 0)
                      <> 64
                   OR coalesce(length(asset_row.generation_json->>'source_snapshot_sha256'), 0)
                      <> 64
                   OR asset_row.generation_json->>'source_snapshot_sha256'
                      IS DISTINCT FROM blueprint_json->>'source_snapshot_sha256'
                   OR asset_row.generation_json->>'render_plan_sha256'
                      IS DISTINCT FROM encode(sha256(convert_to(
                           {quoted_schema}.kjds_media_job_canonical_json(
                               render_plan_json
                           ), 'UTF8'
                         )), 'hex')
                   OR jsonb_typeof(asset_row.generation_json::jsonb->'outputs')
                      IS DISTINCT FROM 'object'
                   OR asset_row.generation_json::jsonb->'outputs'->>'9:16' IS NULL
                   OR asset_row.generation_json::jsonb->'outputs'->>'1:1' IS NULL
                   OR asset_row.generation_json::jsonb->'outputs'->>'16:9' IS NULL
                   OR NEW.artifact_evidence_refs::jsonb IS DISTINCT FROM
                      jsonb_build_array(
                        asset_row.generation_json::jsonb->'outputs'->>'1:1',
                        asset_row.generation_json::jsonb->'outputs'->>'16:9',
                        asset_row.generation_json::jsonb->'outputs'->>'9:16'
                      )
                   OR coalesce(length(asset_row.generation_json->>'encoder_version'), 0)
                      = 0
                   OR length(asset_row.generation_json->>'encoder_version') > 300
                   OR asset_row.generation_json::jsonb->'listing_eligible'
                      IS DISTINCT FROM 'false'::jsonb
                   OR (
                        SELECT count(*)
                          FROM jsonb_object_keys(asset_row.brief_json::jsonb)
                      ) <> 4
                   OR (
                        SELECT count(*)
                          FROM jsonb_object_keys(asset_row.generation_json::jsonb)
                      ) <> 10
                   OR asset_row.created_at IS DISTINCT FROM NEW.recorded_at THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result ContentAsset binding drifted';
                END IF;
                SELECT count(DISTINCT output.value) INTO asset_output_count
                  FROM jsonb_each_text(asset_row.generation_json::jsonb->'outputs') output
                 WHERE NEW.artifact_evidence_refs::jsonb ? output.value;
                IF asset_output_count <> ref_count
                   OR (SELECT count(*)
                         FROM jsonb_object_keys(
                                  asset_row.generation_json::jsonb->'outputs'
                              ) output_key
                      ) <> ref_count THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result ContentAsset outputs drifted';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements_text(
                               NEW.artifact_evidence_refs::jsonb
                           ) item(ref)
                      JOIN {quoted_schema}.evidence_records evidence
                        ON evidence.id = item.ref
                     WHERE jsonb_typeof(evidence.metadata_json::jsonb)
                           IS DISTINCT FROM 'object'
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result artifact Evidence drifted';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements_text(
                               NEW.artifact_evidence_refs::jsonb
                           ) item(ref)
                      JOIN {quoted_schema}.evidence_records evidence
                        ON evidence.id = item.ref
                     WHERE (SELECT count(*) FROM jsonb_object_keys(
                              evidence.metadata_json::jsonb)) <> 12
                        OR EXISTS (
                            SELECT 1
                              FROM jsonb_each(
                                   evidence.metadata_json::jsonb
                              ) metadata_item
                             WHERE jsonb_typeof(metadata_item.value)
                                   IS DISTINCT FROM 'string'
                        )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result artifact Evidence drifted';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements_text(
                               NEW.artifact_evidence_refs::jsonb
                           ) item(ref)
                      LEFT JOIN {quoted_schema}.evidence_records evidence
                        ON evidence.id = item.ref
                      LEFT JOIN {quoted_schema}.evidence_blobs blob
                        ON blob.sha256 = evidence.blob_sha256
                     WHERE evidence.id IS NULL
                        OR blob.sha256 IS NULL
                        OR evidence.grade IS DISTINCT FROM 'B'
                        OR evidence.source IS DISTINCT FROM 'kjds-ffmpeg-media-worker'
                        OR evidence.content_type IS DISTINCT FROM 'video/mp4'
                        OR evidence.created_by IS DISTINCT FROM job_row.subject_actor_id
                        OR evidence.byte_size IS DISTINCT FROM octet_length(blob.content_bytes)
                        OR octet_length(blob.content_bytes) < 12
                        OR octet_length(blob.content_bytes) > 268435456
                        OR substring(blob.content_bytes FROM 5 FOR 4)
                           IS DISTINCT FROM convert_to('ftyp', 'UTF8')
                        OR evidence.effective_at IS DISTINCT FROM NEW.recorded_at
                        OR evidence.recorded_at IS DISTINCT FROM NEW.recorded_at
                        OR evidence.effective_at IS DISTINCT FROM evidence.recorded_at
                        OR evidence.source_ref NOT LIKE
                           ('media-job://' || NEW.job_ref || '/artifact/' ||
                            (asset_row.generation_json::jsonb->>'execution_id') || '/%')
                        OR evidence.metadata_json->>'contract_id'
                           IS DISTINCT FROM 'kjds-governed-media-job-artifact-v1'
                        OR NOT evidence.metadata_json::jsonb ?& ARRAY[
                              'contract_id','tenant_ref','entity_ref','store_ref',
                              'scope_grant_authority_sha256','subject_actor_id',
                              'artifact_sha256','media_job_ref','content_asset_id',
                              'execution_id','aspect_ratio','render_plan_sha256'
                           ]
                        OR evidence.metadata_json->>'tenant_ref'
                           IS DISTINCT FROM NEW.tenant_ref
                        OR evidence.metadata_json->>'entity_ref'
                           IS DISTINCT FROM NEW.entity_ref
                        OR evidence.metadata_json->>'store_ref'
                           IS DISTINCT FROM NEW.store_ref
                        OR evidence.metadata_json->>'scope_grant_authority_sha256'
                           IS DISTINCT FROM NEW.scope_grant_authority_sha256
                        OR evidence.metadata_json->>'subject_actor_id'
                           IS DISTINCT FROM job_row.subject_actor_id
                        OR evidence.metadata_json->>'media_job_ref'
                           IS DISTINCT FROM NEW.job_ref
                        OR evidence.metadata_json->>'content_asset_id'
                           IS DISTINCT FROM NEW.content_asset_ref
                        OR evidence.metadata_json->>'execution_id'
                           IS DISTINCT FROM
                           (asset_row.generation_json::jsonb->>'execution_id')
                        OR evidence.metadata_json->>'render_plan_sha256'
                           IS DISTINCT FROM
                           (asset_row.generation_json::jsonb->>'render_plan_sha256')
                        OR evidence.metadata_json->>'artifact_sha256'
                           IS DISTINCT FROM evidence.blob_sha256
                        OR NOT EXISTS (
                            SELECT 1
                              FROM jsonb_each_text(
                                   asset_row.generation_json::jsonb->'outputs'
                              ) output
                             WHERE output.value = item.ref
                               AND output.key = evidence.metadata_json->>'aspect_ratio'
                               AND evidence.source_ref =
                                   ('media-job://' || NEW.job_ref || '/artifact/' ||
                                    (asset_row.generation_json::jsonb->>'execution_id') ||
                                    '/' || output.key)
                               AND evidence.filename =
                                   (NEW.content_asset_ref || '-' ||
                                    replace(output.key, ':', 'x') || '.mp4')
                        )
                        OR evidence.blob_sha256 IS DISTINCT FROM encode(
                            sha256(blob.content_bytes), 'hex'
                        )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result artifact Evidence drifted';
                END IF;
                SELECT coalesce(sum(octet_length(blob.content_bytes)), 0)
                  INTO asset_output_bytes
                  FROM jsonb_array_elements_text(
                           NEW.artifact_evidence_refs::jsonb
                       ) item(ref)
                  JOIN {quoted_schema}.evidence_records evidence
                    ON evidence.id = item.ref
                  JOIN {quoted_schema}.evidence_blobs blob
                    ON blob.sha256 = evidence.blob_sha256;
                IF asset_output_bytes > 536870912 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='media-job result artifact budget drifted';
                END IF;
                ELSE
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='successful media-job result tool invalid';
                END IF;
            ELSE
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='media-job result state is not admissible';
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE TRIGGER trg_media_job_result_receipt_validate
        BEFORE INSERT ON media_job_result_receipts
        FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.kjds_media_job_validate_result_receipt()
        """)
    op.execute("""
        CREATE TRIGGER trg_media_job_result_receipt_immutable
        BEFORE UPDATE OR DELETE ON media_job_result_receipts
        FOR EACH ROW EXECUTE FUNCTION kjds_media_job_result_receipt_immutable()
        """)
    op.execute(f"""
        CREATE FUNCTION {quoted_schema}.kjds_media_job_result_terminal_conserved()
        RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog AS $$
        DECLARE
            receipt_count integer;
        BEGIN
            IF NEW.state IN ('SUCCEEDED','FAILED','UNKNOWN_OUTCOME')
               AND EXISTS (
                    SELECT 1
                      FROM {quoted_schema}.media_job_worker_inputs worker_input
                     WHERE worker_input.job_ref = NEW.job_ref
               ) THEN
                SELECT count(*) INTO receipt_count
                  FROM {quoted_schema}.media_job_result_receipts receipt
                 WHERE receipt.job_ref = NEW.job_ref
                   AND receipt.event_ref = NEW.event_ref
                   AND receipt.tenant_ref = NEW.tenant_ref
                   AND receipt.entity_ref = NEW.entity_ref
                   AND receipt.store_ref = NEW.store_ref
                   AND receipt.scope_grant_authority_sha256
                      = NEW.scope_grant_authority_sha256;
                IF receipt_count <> 1 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='terminal media-job result receipt is not conserved';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """)
    op.execute(f"""
        CREATE CONSTRAINT TRIGGER trg_media_job_result_terminal_conserved
        AFTER INSERT ON media_job_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {quoted_schema}.kjds_media_job_result_terminal_conserved()
        """)


def downgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-media-jobs-0098-result-readback'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    op.execute(
        f"LOCK TABLE {quoted_schema}.media_jobs IN EXCLUSIVE MODE"
    )
    op.execute(
        f"LOCK TABLE {quoted_schema}.evidence_records, "
        f"{quoted_schema}.media_job_evidence_links, "
        f"{quoted_schema}.media_job_events, "
        f"{quoted_schema}.media_job_request_bindings, "
        f"{quoted_schema}.media_job_result_receipts, "
        f"{quoted_schema}.media_job_worker_inputs IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM media_job_result_receipts)
               OR EXISTS (SELECT 1 FROM media_job_worker_inputs)
               OR EXISTS (SELECT 1 FROM media_job_request_bindings)
               OR EXISTS (
                    SELECT 1 FROM evidence_records
                     WHERE source IN (
                        'governed-media-job-tool-descriptor',
                        'governed-media-job-worker-input',
                        'governed-reference-video-analysis',
                        'governed-media-job-blueprint',
                        'kjds-ffmpeg-media-worker'
                     )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='0098 downgrade blocked: worker/result receipts exist';
            END IF;
        END;
        $$
        """)
    op.execute('DROP TRIGGER trg_evidence_record_fill_byte_size ON evidence_records')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_evidence_record_fill_byte_size()')
    op.execute('DROP TRIGGER trg_media_job_result_terminal_conserved ON media_job_events')
    op.execute('DROP TRIGGER trg_media_job_request_binding_conserved ON media_jobs')
    op.execute('DROP TRIGGER trg_media_job_result_receipt_immutable ON media_job_result_receipts')
    op.execute('DROP TRIGGER trg_media_job_result_receipt_validate ON media_job_result_receipts')
    op.execute('DROP TRIGGER trg_media_job_analysis_link_conserved ON media_job_worker_inputs')
    op.execute('DROP TRIGGER trg_media_job_analysis_link_validate ON media_job_evidence_links')
    op.execute('DROP TRIGGER trg_media_job_link_evidence ON media_job_evidence_links')
    op.execute('CREATE TRIGGER trg_media_job_link_evidence BEFORE INSERT ON media_job_evidence_links FOR EACH ROW EXECUTE FUNCTION kjds_media_job_validate_evidence_binding()')
    op.execute('DROP TRIGGER trg_media_job_worker_input_immutable ON media_job_worker_inputs')
    op.execute('DROP TRIGGER trg_media_job_worker_input_validate ON media_job_worker_inputs')
    op.execute('DROP TRIGGER trg_media_job_request_binding_immutable ON media_job_request_bindings')
    op.execute('DROP TRIGGER trg_media_job_request_binding_validate ON media_job_request_bindings')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_result_terminal_conserved()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_validate_result_receipt()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_blueprint_render_plan(jsonb)')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_validate_blueprint_provenance(text,text)')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_validate_worker_input()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_analysis_link_conserved()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_validate_analysis_link()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_result_receipt_immutable()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_request_binding_immutable()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_request_binding_conserved()')
    op.execute(f'DROP FUNCTION {quoted_schema}.kjds_media_job_validate_request_binding()')
    op.drop_index('ix_media_job_result_scope_recorded', table_name='media_job_result_receipts')
    op.drop_table('media_job_result_receipts')
    op.drop_index('ix_media_job_worker_input_scope', table_name='media_job_worker_inputs')
    op.drop_table('media_job_worker_inputs')
    op.drop_table('media_job_request_bindings')
    op.drop_constraint('ck_media_job_evidence_purpose', 'media_job_evidence_links', type_='check')
    op.drop_constraint('ck_media_job_evidence_contract', 'media_job_evidence_links', type_='check')
    op.create_check_constraint('ck_media_job_evidence_purpose', 'media_job_evidence_links', "purpose IN ('request_input','artifact_terminal','usage_authorization','usage_settlement')")
    op.create_check_constraint('ck_media_job_evidence_contract', 'media_job_evidence_links', "blob_sha256 ~ '^[0-9a-f]{64}$' AND source IN ('governed-media-job-request','governed-media-job-transition','governed-media-job-usage')")
    op.drop_index('uq_media_job_evidence_source_ref', table_name='evidence_records')
    op.execute("CREATE UNIQUE INDEX uq_media_job_evidence_source_ref ON evidence_records (source, source_ref) WHERE source IN ('governed-media-job-request','governed-media-job-transition','governed-media-job-usage')")
    op.drop_column('evidence_records', 'byte_size')
