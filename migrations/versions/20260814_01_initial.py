"""Initial identity and learning schemas."""

from alembic import op

from sti_equations.database import Base
from sti_equations.identity import models as identity_models  # noqa: F401
from sti_equations.learning import models as learning_models  # noqa: F401

revision = "20260814_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.execute("CREATE SCHEMA IF NOT EXISTS learning")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP SCHEMA IF EXISTS learning")
    op.execute("DROP SCHEMA IF EXISTS identity")
