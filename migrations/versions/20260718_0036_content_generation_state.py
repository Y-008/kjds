"""Persist controlled image generation state on content assets."""

import sqlalchemy as sa
from alembic import op

revision = "20260718_0036"
down_revision = "20260717_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_assets",
        sa.Column("generation_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.alter_column("content_assets", "generation_json", server_default=None)


def downgrade() -> None:
    op.drop_column("content_assets", "generation_json")
