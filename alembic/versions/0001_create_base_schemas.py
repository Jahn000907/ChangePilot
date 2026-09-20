"""create base schemas

Creates the four logical PostgreSQL schemas of design doc v0.4 section 24:
erp, ecm, agent, audit.

No business table is created by this revision. The ``alembic_version`` table
stays in the default schema.

Revision ID: 0001_create_base_schemas
Revises:
Create Date: 2026-09-20

"""

from collections.abc import Sequence

from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_create_base_schemas"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Creation order; downgrade walks this list in reverse.
SCHEMAS: tuple[str, ...] = ("erp", "ecm", "agent", "audit")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(CreateSchema(schema))


def downgrade() -> None:
    # RESTRICT is the default: if a later revision left objects behind, the
    # downgrade must fail loudly instead of dropping tables silently.
    for schema in reversed(SCHEMAS):
        op.execute(DropSchema(schema))
