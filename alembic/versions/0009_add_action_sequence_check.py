"""add action sequence check

Adds ck_change_strategy_actions_sequence_no_positive (sequence_no > 0) to
ecm.change_strategy_actions.

This revision is written by hand on purpose. ``alembic revision
--autogenerate`` produced an empty migration for this change because Alembic
only loads the ``alembic.autogenerate.*`` plugins by default; the check
constraint comparison lives in ``alembic.ext.checkconstraint_byname`` and has
to be enabled explicitly through the ``autogenerate_plugins`` option.

Revision ID: 0009_action_seq_check
Revises: 0008_strategy_tables
Create Date: 2026-09-20 20:02:19.468572

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0009_action_seq_check'
down_revision: str | Sequence[str] | None = '0008_strategy_tables'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_change_strategy_actions_sequence_no_positive",
        "change_strategy_actions",
        "sequence_no > 0",
        schema="ecm",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_change_strategy_actions_sequence_no_positive",
        "change_strategy_actions",
        type_="check",
        schema="ecm",
    )
