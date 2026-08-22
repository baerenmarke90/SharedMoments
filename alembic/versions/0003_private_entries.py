"""Privater Bereich: Notizen und Geschenkideen je Nutzer.

Getrennte Tabelle statt eines Flags an bestehenden Inhalten: so kann keine
Abfrage auf gemeinsame Inhalte versehentlich private Eintraege mitziehen.

Revision ID: 0003_private_entries
Revises: 0002_plan_experienced_date
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = '0003_private_entries'
down_revision = '0002_plan_experienced_date'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if 'privateEntries' in sa.inspect(op.get_bind()).get_table_names():
        # create_all() kann die Tabelle in einer frischen Datenbank schon
        # angelegt haben - dann ist hier nichts zu tun.
        return

    op.create_table(
        'privateEntries',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('userID', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False, server_default='note'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('content', sa.Text(), server_default=''),
        sa.Column('recipient', sa.String(255), nullable=True),
        sa.Column('occasion', sa.String(255), nullable=True),
        sa.Column('targetDate', sa.Date(), nullable=True),
        sa.Column('price', sa.String(64), nullable=True),
        sa.Column('link', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='idea'),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('dateCreated', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
        sa.Column('dateModified', sa.TIMESTAMP(), server_default=sa.func.current_timestamp()),
    )
    op.create_index('ix_privateEntries_userID', 'privateEntries', ['userID'])
    op.create_index('ix_privateEntries_kind', 'privateEntries', ['kind'])
    op.create_index('ix_privateEntries_status', 'privateEntries', ['status'])
    op.create_index('ix_privateEntries_pinned', 'privateEntries', ['pinned'])
    op.create_index('ix_privateEntries_targetDate', 'privateEntries', ['targetDate'])


def downgrade() -> None:
    op.drop_table('privateEntries')
