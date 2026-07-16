"""Make reviewed passport versions immutable."""

from alembic import op

revision = "20260716_0008"
down_revision = "20260716_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'CREATE TRIGGER "trg_passports_immutable" BEFORE UPDATE OR DELETE ON "passports" '
        "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS "trg_passports_immutable" ON "passports"')
