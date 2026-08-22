"""Plaene bekommen ein Erlebt-Datum.

Bis hierher hatte ein Plan nur Wunschtermine (targetStartDate/targetEndDate).
Beim Umwandeln in ein Kapitel gab es deshalb keinen echten Zeitraum, wenn der
Plan ohne geplante Daten erlebt wurde.

Revision ID: 0002_plan_experienced_date
Revises: 0001_baseline
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = '0002_plan_experienced_date'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('couplePlans')}
    if 'experiencedDate' in columns:
        # create_all() kann die Spalte in einer frischen Datenbank schon
        # angelegt haben - dann ist hier nichts zu tun.
        return

    op.add_column('couplePlans', sa.Column('experiencedDate', sa.Date(), nullable=True))
    op.create_index(
        'ix_couplePlans_experiencedDate',
        'couplePlans',
        ['experiencedDate'],
    )


def downgrade() -> None:
    op.drop_index('ix_couplePlans_experiencedDate', table_name='couplePlans')
    op.drop_column('couplePlans', 'experiencedDate')
