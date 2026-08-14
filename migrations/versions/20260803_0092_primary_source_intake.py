"""Add exact-scope Primary Source Intake manifests and normalized records.

Revision ID: 20260803_0092
Revises: 20260803_0091
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260803_0092"
down_revision = "20260803_0091"
branch_labels = None
depends_on = None

ENVELOPES = "primary_source_intake_envelopes"
RECORDS = "primary_source_intake_records"


def upgrade() -> None:
    op.create_index(
        "uq_primary_source_intake_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'primary-source-intake'"),
    )
    op.create_table(
        ENVELOPES,
        sa.Column("intake_ref", sa.Text(), primary_key=True),
        sa.Column("tenant_ref", sa.Text(), nullable=False),
        sa.Column("entity_ref", sa.Text(), nullable=False),
        sa.Column("store_ref", sa.Text(), nullable=False),
        sa.Column("scope_authority_sha256", sa.Text(), nullable=False),
        sa.Column("source_pack_id", sa.Text(), nullable=False),
        sa.Column("source_contract_id", sa.Text(), nullable=False),
        sa.Column("source_contract_version", sa.Text(), nullable=False),
        sa.Column("subject_ref_sha256", sa.Text(), nullable=False),
        sa.Column("source_locator_sha256", sa.Text(), nullable=False),
        sa.Column("blob_sha256", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("acquisition_mode", sa.Text(), nullable=False),
        sa.Column("admission_grade", sa.Text(), nullable=False),
        sa.Column("license_or_terms_basis", sa.Text(), nullable=False),
        sa.Column("allowed_purpose", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("retention_class", sa.Text(), nullable=False),
        sa.Column("data_classification", sa.Text(), nullable=False),
        sa.Column(
            "cross_border_transfer_classification", sa.Text(), nullable=False
        ),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("verifier_id", sa.Text(), nullable=False),
        sa.Column("verifier_version", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_total", sa.BigInteger(), nullable=False),
        sa.Column("accepted_count", sa.BigInteger(), nullable=False),
        sa.Column("suppressed_count", sa.BigInteger(), nullable=False),
        sa.Column("quarantined_count", sa.BigInteger(), nullable=False),
        sa.Column("duplicate_count", sa.BigInteger(), nullable=False),
        sa.Column("field_count", sa.Integer(), nullable=False),
        sa.Column("expected_pages", sa.Integer(), nullable=False),
        sa.Column("received_pages", sa.Integer(), nullable=False),
        sa.Column("failed_page_count", sa.Integer(), nullable=False),
        sa.Column(
            "failed_page_sha256_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("checkpoint_sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "evidence_id",
            sa.Text(),
            sa.ForeignKey("evidence_records.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_sha256", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("idempotency_sha256", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_sha256",
            name="uq_primary_source_scope_idempotency",
        ),
        sa.UniqueConstraint(
            "intake_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            name="uq_primary_source_exact_binding",
        ),
        sa.CheckConstraint(
            "intake_ref ~ '^psi_[0-9a-f]{32}$' "
            "AND length(tenant_ref) > 0 AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0",
            name="ck_primary_source_scope",
        ),
        sa.CheckConstraint(
            "source_pack_id IN ("
            "'operating_cash_truth','marketplace_demand_and_catalog',"
            "'unit_economics_supply_and_logistics',"
            "'global_trade_lead_intelligence','customer_product_and_revenue',"
            "'ai_technology_and_cost_benchmark',"
            "'competitor_enterprise_and_capital',"
            "'risk_legal_security_and_compliance')",
            name="ck_primary_source_pack",
        ),
        sa.CheckConstraint(
            "acquisition_mode IN ('official_api','account_owner_export',"
            "'licensed_dataset','terms_permitted_public_business_observation',"
            "'consented_first_party_crm_import')",
            name="ck_primary_source_acquisition_mode",
        ),
        sa.CheckConstraint(
            "admission_grade IN ('B','C')",
            name="ck_primary_source_admission_grade",
        ),
        sa.CheckConstraint(
            "retention_class IN ('operational','financial','compliance',"
            "'experiment','security')",
            name="ck_primary_source_retention_class",
        ),
        sa.CheckConstraint(
            "data_classification IN ('business_public','business_confidential',"
            "'financial_restricted','personal_professional','security_restricted')",
            name="ck_primary_source_data_classification",
        ),
        sa.CheckConstraint(
            "cross_border_transfer_classification IN ('not_applicable',"
            "'domestic_only','approved_transfer','restricted') "
            "AND NOT (data_classification = 'personal_professional' "
            "AND cross_border_transfer_classification = 'not_applicable')",
            name="ck_primary_source_transfer_classification",
        ),
        sa.CheckConstraint(
            "status IN ('complete','partial')",
            name="ck_primary_source_status",
        ),
        sa.CheckConstraint(
            "source_total >= 0 AND accepted_count >= 0 "
            "AND suppressed_count >= 0 AND quarantined_count >= 0 "
            "AND duplicate_count >= 0 "
            "AND accepted_count + suppressed_count + quarantined_count "
            "+ duplicate_count = source_total",
            name="ck_primary_source_conservation",
        ),
        sa.CheckConstraint(
            "field_count > 0 AND expected_pages > 0 AND received_pages >= 0 "
            "AND failed_page_count >= 0 "
            "AND received_pages + failed_page_count = expected_pages",
            name="ck_primary_source_pagination",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(failed_page_sha256_json) = 'array' "
            "AND jsonb_array_length(failed_page_sha256_json) = failed_page_count",
            name="ck_primary_source_failed_page_register",
        ),
        sa.CheckConstraint(
            "byte_count > 0 "
            "AND scope_authority_sha256 ~ '^[0-9a-f]{64}$' "
            "AND subject_ref_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_locator_sha256 ~ '^[0-9a-f]{64}$' "
            "AND blob_sha256 ~ '^[0-9a-f]{64}$' "
            "AND checkpoint_sha256 ~ '^[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^[0-9a-f]{64}$' "
            "AND request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND idempotency_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_primary_source_hashes",
        ),
        sa.CheckConstraint(
            "captured_at <= verified_at AND verified_at <= as_of "
            "AND effective_at <= as_of AND review_due_at > as_of "
            "AND created_at >= as_of",
            name="ck_primary_source_time_order",
        ),
    )
    op.create_index(
        "ix_primary_source_scope_created",
        ENVELOPES,
        ["tenant_ref", "entity_ref", "store_ref", "created_at", "intake_ref"],
    )
    op.create_index(
        "ix_primary_source_pack_status",
        ENVELOPES,
        ["tenant_ref", "source_pack_id", "status", "intake_ref"],
    )
    op.create_index("ix_primary_source_evidence", ENVELOPES, ["evidence_id"])

    op.create_table(
        RECORDS,
        sa.Column("record_ref", sa.Text(), primary_key=True),
        sa.Column("intake_ref", sa.Text(), nullable=False),
        sa.Column("tenant_ref", sa.Text(), nullable=False),
        sa.Column("entity_ref", sa.Text(), nullable=False),
        sa.Column("store_ref", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_record_sha256", sa.Text(), nullable=False),
        sa.Column("source_family", sa.Text(), nullable=False),
        sa.Column("marketplace_or_site", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("business_entity_name", sa.Text(), nullable=False),
        sa.Column("country_or_region", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("public_business_url", sa.Text(), nullable=True),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("signal_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("license_or_terms_basis", sa.Text(), nullable=False),
        sa.Column("contact_ref", sa.Text(), nullable=True),
        sa.Column("contact_purpose_basis", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=False),
        sa.Column("do_not_contact_status", sa.Text(), nullable=False),
        sa.Column("confidence_bps", sa.Integer(), nullable=False),
        sa.Column(
            "evidence_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("lead_stage", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["intake_ref", "tenant_ref", "entity_ref", "store_ref"],
            [
                f"{ENVELOPES}.intake_ref",
                f"{ENVELOPES}.tenant_ref",
                f"{ENVELOPES}.entity_ref",
                f"{ENVELOPES}.store_ref",
            ],
            name="fk_primary_source_record_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "intake_ref", "ordinal", name="uq_primary_source_record_ordinal"
        ),
        sa.UniqueConstraint(
            "intake_ref",
            "source_record_sha256",
            name="uq_primary_source_record_content",
        ),
        sa.CheckConstraint(
            "record_ref ~ '^psr_[0-9a-f]{32}$' AND ordinal > 0 "
            "AND source_record_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_primary_source_record_identity",
        ),
        sa.CheckConstraint(
            "source_family IN ('amazon','alibaba_com','aliexpress','shopee',"
            "'tiktok_shop','temu','mercado_libre','wildberries','ozon','ebay',"
            "'lazada','rakuten','yahoo_shopping','walmart_marketplace',"
            "'global_sources','made_in_china','world_factory','yiwugo','1688',"
            "'global_huapin','baobaoniu','17zwd','souk','eelly','toybaba',"
            "'meizhuang','zhiai_muying','shipinwang','91jiafang','gongpinhui',"
            "'global_shoes','independent_storefront','customs_data',"
            "'linkedin_company_and_public_professional_data')",
            name="ck_primary_source_record_family",
        ),
        sa.CheckConstraint(
            "entity_type IN ('seller_account','supplier_entity','prospect_account',"
            "'buyer_signal','verified_contact_point','qualified_opportunity')",
            name="ck_primary_source_record_entity_type",
        ),
        sa.CheckConstraint(
            "disposition IN ('accepted','suppressed') "
            "AND do_not_contact_status IN "
            "('unknown','clear','do_not_contact','withdrawn') "
            "AND ((do_not_contact_status IN ('do_not_contact','withdrawn') "
            "AND disposition = 'suppressed') OR "
            "(do_not_contact_status IN ('unknown','clear') "
            "AND disposition = 'accepted'))",
            name="ck_primary_source_record_suppression",
        ),
        sa.CheckConstraint(
            "contact_purpose_basis IN ('not_applicable','consent',"
            "'existing_customer','contractual_necessity',"
            "'documented_legitimate_business_interest')",
            name="ck_primary_source_record_contact_basis",
        ),
        sa.CheckConstraint(
            "contact_ref IS NULL OR "
            "(contact_ref ~ '^(crm|vault|contact)://[A-Za-z0-9._:/-]{1,144}$' "
            "AND position('@' in contact_ref) = 0)",
            name="ck_primary_source_record_contact_ref",
        ),
        sa.CheckConstraint(
            "public_business_url IS NULL OR "
            "public_business_url ~ '^https?://[^?#@]+$'",
            name="ck_primary_source_record_public_url",
        ),
        sa.CheckConstraint(
            "confidence_bps >= 0 AND confidence_bps <= 10000 "
            "AND signal_observed_at <= created_at",
            name="ck_primary_source_record_quality",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_refs_json) = 'array'",
            name="ck_primary_source_record_evidence_refs",
        ),
    )
    op.create_index(
        "ix_primary_source_record_lead_search",
        RECORDS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_family",
            "entity_type",
            "signal_observed_at",
        ],
    )
    op.create_index(
        "ix_primary_source_record_intake", RECORDS, ["intake_ref", "ordinal"]
    )

    op.execute(
        "CREATE TRIGGER trg_primary_source_envelopes_immutable "
        f"BEFORE UPDATE OR DELETE ON {ENVELOPES} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_primary_source_records_immutable "
        f"BEFORE UPDATE OR DELETE ON {RECORDS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {RECORDS} LIMIT 1)
               OR EXISTS (SELECT 1 FROM {ENVELOPES} LIMIT 1)
               OR EXISTS (
                   SELECT 1 FROM evidence_records
                   WHERE source = 'primary-source-intake' LIMIT 1
               ) THEN
                RAISE EXCEPTION
                    'BAS-198 downgrade blocked: Primary Source Intake data exists';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_primary_source_records_immutable ON {RECORDS}"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_primary_source_envelopes_immutable ON {ENVELOPES}"
    )
    op.drop_index("ix_primary_source_record_intake", table_name=RECORDS)
    op.drop_index("ix_primary_source_record_lead_search", table_name=RECORDS)
    op.drop_table(RECORDS)
    op.drop_index("ix_primary_source_evidence", table_name=ENVELOPES)
    op.drop_index("ix_primary_source_pack_status", table_name=ENVELOPES)
    op.drop_index("ix_primary_source_scope_created", table_name=ENVELOPES)
    op.drop_table(ENVELOPES)
    op.drop_index(
        "uq_primary_source_intake_evidence_source_ref",
        table_name="evidence_records",
    )
