from __future__ import annotations

from alembic import op

revision = "registry_0002"
down_revision = "registry_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM google_drive_credentials")
    op.execute("DELETE FROM schema_version")
    op.execute("INSERT INTO schema_version (version) VALUES (2)")


def downgrade() -> None:
    pass
