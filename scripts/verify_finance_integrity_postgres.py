from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from apps.control_plane.database import create_database_engine, database_url
from apps.control_plane.evidence import EvidenceGrade, EvidenceService

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(f"Finance verification requires disposable database {EXPECTED_DATABASE!r}")

    engine = create_database_engine(url)
    evidence = EvidenceService(engine)
    content = b"g1 finance numeric integrity"
    source = evidence.capture(
        content=content,
        filename="g1-finance.txt",
        content_type="text/plain",
        source="g1",
        source_ref=f"g1://finance/{hashlib.sha256(content).hexdigest()}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="g1-finance-verifier",
    )
    now = datetime.now(UTC)

    statements = {
        "nan_fx_rate": (
            """INSERT INTO fx_rates (
                id, base_currency, quote_currency, rate, version, effective_at, source,
                evidence_id, created_by, recorded_at
            ) VALUES (:id, 'RUB', 'CNY', 'NaN'::numeric, 1, :now, 'g1', :evidence, 'g1', :now)""",
            {},
        ),
        "nan_finance_amount": (
            """INSERT INTO finance_entries (
                id, entry_kind, source, source_ref, reconciliation_key, raw_fee_code,
                amount, currency, effective_at, evidence_id, source_fact_id,
                review_required, created_by, recorded_at
            ) VALUES (
                :id, 'bank_receipt', 'g1', :ref, 'g1-recon', NULL, 'NaN'::numeric,
                'CNY', :now, :evidence, NULL, false, 'g1', :now
            )""",
            {"ref": uuid4().hex},
        ),
        "nan_reconciliation_tolerance": (
            """INSERT INTO reconciliation_runs (
                id, reconciliation_key, quote_currency, fx_source, tolerance_ratio,
                status, snapshot_json, created_by, recorded_at
            ) VALUES (
                :id, :ref, 'CNY', 'g1', 'NaN'::numeric, 'g1', '{}'::jsonb, 'g1', :now
            )""",
            {"ref": uuid4().hex},
        ),
        "cash_probability_above_one": (
            """INSERT INTO cash_plan_items (
                id, source, source_ref, category, amount, currency, expected_at,
                probability, status, evidence_id, created_by, recorded_at
            ) VALUES (
                :id, 'g1', :ref, 'inventory', 1, 'CNY', :now, 2, 'scenario',
                :evidence, 'g1', :now
            )""",
            {"ref": uuid4().hex},
        ),
    }

    rejected = []
    for name, (statement, extra) in statements.items():
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(statement),
                    {"id": f"g1_{uuid4().hex}", "evidence": source.id, "now": now, **extra},
                )
        except IntegrityError:
            rejected.append(name)
        else:
            raise AssertionError(f"PostgreSQL accepted invalid finance data: {name}")

    expected = {
        "ck_fx_rates_rate_positive",
        "ck_finance_entries_amount_finite",
        "ck_reconciliation_tolerance_range",
        "ck_cash_plan_amount_finite",
        "ck_cash_plan_probability_range",
    }
    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("""SELECT conname FROM pg_constraint
                WHERE conrelid IN (
                    'fx_rates'::regclass, 'finance_entries'::regclass,
                    'reconciliation_runs'::regclass, 'cash_plan_items'::regclass
                ) AND contype = 'c'""")
            ).scalars()
        )
    if not expected.issubset(constraints):
        raise AssertionError(f"Missing finance constraints: {sorted(expected - constraints)}")

    print(
        {
            "database": EXPECTED_DATABASE,
            "rejected": rejected,
            "constraint_count": len(expected),
            "status": "passed",
        }
    )


if __name__ == "__main__":
    main()
