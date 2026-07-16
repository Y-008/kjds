"""Make evidence-backed sourcing facts immutable."""

from alembic import op

revision = "20260716_0009"
down_revision = "20260716_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("source_offers", "profit_scenarios"):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )


def downgrade() -> None:
    for table in ("profit_scenarios", "source_offers"):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
