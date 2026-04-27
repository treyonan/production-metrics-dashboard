"""Add is_sold_out to books

Revision ID: 32be7d3d3ef9
Revises: 
Create Date: 2025-09-28 12:47:14.801693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32be7d3d3ef9'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('books', sa.Column('is_sold_out', sa.Boolean, nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('books', 'is_sold_out')
