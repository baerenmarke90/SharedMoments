"""Baseline: Schema, wie es bis v0.5 durch create_all() entstanden ist.

Diese Revision aendert nichts. Sie markiert nur den Stand, auf dem alle
bestehenden Installationen stehen - inklusive Produktion. Bestehende
Datenbanken werden beim Start automatisch auf diese Revision gestempelt
(ensure_alembic_baseline), neue Datenbanken ebenfalls, nachdem create_all()
die Tabellen angelegt hat.

Ab hier gilt: jede Schemaaenderung bekommt eine eigene Revision. Solange
create_all() noch mitlaeuft, legt es nur *fehlende* Tabellen an - Spalten
aendert es nie, genau dafuer sind ab jetzt die Migrationen da.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-22
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Kein Schemaeingriff: der Stand ist bereits vorhanden."""


def downgrade() -> None:
    """Vor der Baseline gibt es nichts, worauf man zurueckgehen koennte."""
