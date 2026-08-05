from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "workspace_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("parse_status", sa.Text(), nullable=False),
        sa.Column("parse_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('pdf','pptx','docx','md','txt','csv')"),
        sa.CheckConstraint("parse_status IN ('parsed','failed','skipped')"),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("anchor", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("file_id", "ordinal"),
    )
    op.create_index("idx_chunks_file", "chunks", ["file_id"])

    op.create_table(
        "dataset_profiles",
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("file_id"),
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("touch_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("miss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_anchor", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("state IN ('touched','shaky')"),
    )

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("concept_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("chosen_index", sa.Integer(), nullable=True),
        sa.Column("is_correct", sa.Integer(), nullable=True),
        sa.Column("source_anchor", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"]),
    )
    op.create_index("idx_quiz_concept", "quiz_attempts", ["concept_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("payload_path", sa.Text(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("answer_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('chart','explainer','quiz_result','script')"),
    )
    op.create_index("idx_artifacts_answer", "artifacts", ["answer_id"])

    op.create_table(
        "workspace_meta",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO schema_version (version) VALUES (2)")

    op.create_table(
        "embeddings",
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index("idx_embeddings_provider_model", "embeddings", ["provider", "model"])


def downgrade() -> None:
    op.drop_index("idx_embeddings_provider_model", table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_table("schema_version")
    op.drop_table("workspace_meta")
    op.drop_index("idx_artifacts_answer", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("idx_quiz_concept", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    op.drop_table("concepts")
    op.drop_table("dataset_profiles")
    op.drop_index("idx_chunks_file", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("files")
