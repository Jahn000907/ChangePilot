"""Add persistent assistant conversations and material substitution case type.

Revision ID: 0012_assistant
Revises: 0011_agent_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_assistant"
down_revision: str | Sequence[str] | None = "0011_agent_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("context_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_assistant_conversations_status"),
        schema="agent",
    )
    op.create_index(
        "ix_assistant_conversations_updated_at", "assistant_conversations", ["updated_at"], schema="agent"
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_assistant_messages_role"),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent.assistant_conversations.id"], ondelete="CASCADE"),
        schema="agent",
    )
    op.create_index(
        "ix_assistant_messages_conversation_created", "assistant_messages",
        ["conversation_id", "created_at"], schema="agent",
    )
    op.drop_constraint("ck_change_cases_case_type", "change_cases", schema="ecm", type_="check")
    op.create_check_constraint(
        "ck_change_cases_case_type", "change_cases",
        "case_type IN ('SUPPLIER_EOL', 'QUALITY_ISSUE', 'CUSTOMER_CHANGE', "
        "'COST_REDUCTION', 'REGULATORY_CHANGE', 'MATERIAL_SUBSTITUTION')",
        schema="ecm",
    )


def downgrade() -> None:
    op.drop_constraint("ck_change_cases_case_type", "change_cases", schema="ecm", type_="check")
    op.create_check_constraint(
        "ck_change_cases_case_type", "change_cases",
        "case_type IN ('SUPPLIER_EOL', 'QUALITY_ISSUE', 'CUSTOMER_CHANGE', "
        "'COST_REDUCTION', 'REGULATORY_CHANGE')", schema="ecm",
    )
    op.drop_index("ix_assistant_messages_conversation_created", table_name="assistant_messages", schema="agent")
    op.drop_table("assistant_messages", schema="agent")
    op.drop_index("ix_assistant_conversations_updated_at", table_name="assistant_conversations", schema="agent")
    op.drop_table("assistant_conversations", schema="agent")
