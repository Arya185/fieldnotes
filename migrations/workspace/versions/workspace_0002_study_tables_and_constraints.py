from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "workspace_0002"
down_revision = "workspace_0001"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _foreign_key_columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    columns: set[str] = set()
    for foreign_key in inspector.get_foreign_keys(table_name):
        for column in foreign_key.get("constrained_columns", []):
            columns.add(column)
    return columns


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "topics"):
        op.create_table(
            "topics",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("difficulty", sa.Text(), nullable=True),
            sa.Column("est_minutes", sa.Integer(), nullable=True),
            sa.Column("prerequisites_json", sa.Text(), nullable=True),
            sa.Column("file_id", sa.Text(), nullable=True),
            sa.Column("mastery_score", sa.Float(), nullable=True, server_default="0"),
            sa.Column("last_review", sa.Text(), nullable=True),
            sa.Column("review_count", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("quiz_average", sa.Float(), nullable=True, server_default="0"),
            sa.Column("completion_percentage", sa.Float(), nullable=True, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        )
    else:
        topic_fk_columns = _foreign_key_columns(inspector, "topics")
        with op.batch_alter_table("topics", recreate="always") as batch_op:
            if "file_id" not in topic_fk_columns:
                batch_op.create_foreign_key(
                    "fk_topics_file_id_files",
                    "files",
                    ["file_id"],
                    ["id"],
                )
        inspector = sa.inspect(bind)
    if "idx_topics_file_id" not in _index_names(inspector, "topics"):
        op.create_index("idx_topics_file_id", "topics", ["file_id"])

    if not _table_exists(inspector, "topic_dependencies"):
        op.create_table(
            "topic_dependencies",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("prereq_id", sa.Text(), nullable=False),
            sa.Column("topic_id", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["prereq_id"], ["topics.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        )
    else:
        dependency_fk_columns = _foreign_key_columns(inspector, "topic_dependencies")
        with op.batch_alter_table("topic_dependencies", recreate="always") as batch_op:
            if "prereq_id" not in dependency_fk_columns:
                batch_op.create_foreign_key(
                    "fk_topic_dependencies_prereq_id_topics",
                    "topics",
                    ["prereq_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if "topic_id" not in dependency_fk_columns:
                batch_op.create_foreign_key(
                    "fk_topic_dependencies_topic_id_topics",
                    "topics",
                    ["topic_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
        inspector = sa.inspect(bind)
    if "idx_topic_dependencies_topic_id" not in _index_names(inspector, "topic_dependencies"):
        op.create_index("idx_topic_dependencies_topic_id", "topic_dependencies", ["topic_id"])
    if "idx_topic_dependencies_prereq_id" not in _index_names(inspector, "topic_dependencies"):
        op.create_index("idx_topic_dependencies_prereq_id", "topic_dependencies", ["prereq_id"])

    if not _table_exists(inspector, "study_plans"):
        op.create_table(
            "study_plans",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("exam_date", sa.Text(), nullable=True),
            sa.Column("hours_per_day", sa.Float(), nullable=True),
            sa.Column("pace", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=True),
        )

    if not _table_exists(inspector, "study_plan_items"):
        op.create_table(
            "study_plan_items",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("plan_id", sa.Text(), nullable=False),
            sa.Column("topic_id", sa.Text(), nullable=True),
            sa.Column("date", sa.Text(), nullable=False),
            sa.Column("task_type", sa.Text(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("completed", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("score", sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(["plan_id"], ["study_plans.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        )
    else:
        item_fk_columns = _foreign_key_columns(inspector, "study_plan_items")
        with op.batch_alter_table("study_plan_items", recreate="always") as batch_op:
            if "plan_id" not in item_fk_columns:
                batch_op.create_foreign_key(
                    "fk_study_plan_items_plan_id_study_plans",
                    "study_plans",
                    ["plan_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if "topic_id" not in item_fk_columns:
                batch_op.create_foreign_key(
                    "fk_study_plan_items_topic_id_topics",
                    "topics",
                    ["topic_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        inspector = sa.inspect(bind)
    if "idx_study_plan_items_plan_date" not in _index_names(inspector, "study_plan_items"):
        op.create_index("idx_study_plan_items_plan_date", "study_plan_items", ["plan_id", "date"])

    if not _table_exists(inspector, "flashcards"):
        op.create_table(
            "flashcards",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("topic_id", sa.Text(), nullable=True),
            sa.Column("card_type", sa.Text(), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("difficulty", sa.Text(), nullable=False),
            sa.Column("bloom_level", sa.Text(), nullable=False),
            sa.Column("source_document", sa.Text(), nullable=False),
            sa.Column("source_locator", sa.Text(), nullable=False),
            sa.Column("source_anchor", sa.Text(), nullable=False),
            sa.Column("source_chunk_id", sa.Text(), nullable=True),
            sa.Column("review_interval", sa.Float(), nullable=False, server_default="0"),
            sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
            sa.Column("next_review", sa.Text(), nullable=False),
            sa.Column("last_review", sa.Text(), nullable=True),
            sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mastery_weight", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["source_chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        )
        op.create_index("idx_flashcards_topic", "flashcards", ["topic_id"])
        op.create_index("idx_flashcards_next_review", "flashcards", ["next_review"])
        op.create_index("idx_flashcards_source_chunk_id", "flashcards", ["source_chunk_id"])
    else:
        flashcard_columns = _column_names(inspector, "flashcards")
        if "source_chunk_id" not in flashcard_columns:
            op.add_column("flashcards", sa.Column("source_chunk_id", sa.Text(), nullable=True))
            op.execute(
                """
                UPDATE flashcards
                SET source_chunk_id = (
                    SELECT chunks.id
                    FROM chunks
                    WHERE flashcards.source_anchor = chunks.file_id || '#' || chunks.anchor
                )
                """
            )
        flashcard_fk_columns = _foreign_key_columns(inspector, "flashcards")
        with op.batch_alter_table("flashcards", recreate="always") as batch_op:
            if "topic_id" not in flashcard_fk_columns:
                batch_op.create_foreign_key(
                    "fk_flashcards_topic_id_topics",
                    "topics",
                    ["topic_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if "source_chunk_id" not in flashcard_fk_columns:
                batch_op.create_foreign_key(
                    "fk_flashcards_source_chunk_id_chunks",
                    "chunks",
                    ["source_chunk_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        inspector = sa.inspect(bind)
        existing_indexes = _index_names(inspector, "flashcards")
        if "idx_flashcards_topic" not in existing_indexes:
            op.create_index("idx_flashcards_topic", "flashcards", ["topic_id"])
        if "idx_flashcards_next_review" not in existing_indexes:
            op.create_index("idx_flashcards_next_review", "flashcards", ["next_review"])
        if "idx_flashcards_source_chunk_id" not in existing_indexes:
            op.create_index("idx_flashcards_source_chunk_id", "flashcards", ["source_chunk_id"])


def downgrade() -> None:
    with op.batch_alter_table("flashcards", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_flashcards_source_chunk_id_chunks", type_="foreignkey")
        batch_op.drop_constraint("fk_flashcards_topic_id_topics", type_="foreignkey")
        batch_op.drop_column("source_chunk_id")
    op.drop_index("idx_flashcards_source_chunk_id", table_name="flashcards")

    op.drop_index("idx_study_plan_items_plan_date", table_name="study_plan_items")
    with op.batch_alter_table("study_plan_items", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_study_plan_items_plan_id_study_plans", type_="foreignkey")
        batch_op.drop_constraint("fk_study_plan_items_topic_id_topics", type_="foreignkey")

    op.drop_index("idx_topic_dependencies_topic_id", table_name="topic_dependencies")
    op.drop_index("idx_topic_dependencies_prereq_id", table_name="topic_dependencies")
    with op.batch_alter_table("topic_dependencies", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_topic_dependencies_prereq_id_topics", type_="foreignkey")
        batch_op.drop_constraint("fk_topic_dependencies_topic_id_topics", type_="foreignkey")

    op.drop_index("idx_topics_file_id", table_name="topics")
    with op.batch_alter_table("topics", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_topics_file_id_files", type_="foreignkey")
