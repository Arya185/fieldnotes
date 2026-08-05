from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "registry_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO schema_version (version) VALUES (2)")

    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.Text(), primary_key=True),
        sa.Column("root", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('idle','indexing','ready','empty','error')"),
    )
    op.create_index("idx_workspace_root", "workspaces", ["root"])

    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=True, unique=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        sa.CheckConstraint("role IN ('owner','teacher','student','viewer')"),
    )
    op.create_index("idx_workspace_member_user", "workspace_members", ["user_id"])
    op.create_index("idx_workspace_member_workspace", "workspace_members", ["workspace_id"])

    op.create_table(
        "google_drive_credentials",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("google_drive_credentials")
    op.drop_index("idx_workspace_member_workspace", table_name="workspace_members")
    op.drop_index("idx_workspace_member_user", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_table("users")
    op.drop_index("idx_workspace_root", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("schema_version")
