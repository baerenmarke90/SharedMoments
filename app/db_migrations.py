"""Alembic-Anbindung.

Bis v0.5 ist das Schema ausschliesslich ueber SQLAlchemys create_all()
entstanden. Das legt fehlende Tabellen an, aendert aber nie eine bestehende:
sobald eine Spalte dazukommt, laufen Test- und Produktionsdatenbank
auseinander, ohne dass es jemand merkt.

Deshalb bekommt jede Datenbank beim Start eine Alembic-Version. Bestehende
Installationen werden auf die Baseline gestempelt (ihr Schema ist bereits da),
neue ebenso, direkt nachdem create_all() gelaufen ist. Ab dann gilt fuer jede
Schemaaenderung eine eigene Revision und ein echtes upgrade.
"""
import os

from sqlalchemy import inspect

from app.logger import log
from app.models import engine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INI = os.path.join(_ROOT, 'alembic.ini')
_SCRIPTS = os.path.join(_ROOT, 'alembic')


def _alembic_config():
    from alembic.config import Config as AlembicConfig
    from config import Config

    cfg = AlembicConfig(_INI)
    cfg.set_main_option('script_location', _SCRIPTS)
    cfg.set_main_option('sqlalchemy.url', Config.SQLALCHEMY_DATABASE_URI)
    return cfg


def has_alembic_version():
    with engine.connect() as connection:
        return inspect(connection).has_table('alembic_version')


def ensure_schema_up_to_date():
    """Bringt die Datenbank auf den Schemastand des laufenden Codes.

    Zwei Faelle:

    1. Noch keine Alembic-Version vorhanden (alle Installationen bis v0.5):
       Die Datenbank wird auf die Baseline gestempelt. Ihr Schema ist bereits
       da, es wird nichts veraendert.
    2. Danach laeuft 'upgrade head'. Migrationen liegen im selben Image wie
       der Code - waeren sie optional, liefe die App nach einem Deploy mit
       einer Spalte, die es in der Datenbank noch nicht gibt.

    Schlaegt das Upgrade fehl, startet die App trotzdem und protokolliert den
    Fehler: eine lesbare Instanz ist besser als eine, die gar nicht hochkommt.
    """
    from alembic import command

    cfg = _alembic_config()

    try:
        if not has_alembic_version():
            command.stamp(cfg, '0001_baseline')
            log('info', 'Alembic-Baseline gesetzt (Schema war bereits vorhanden)')
    except Exception as exc:
        log('error', f'Alembic-Baseline konnte nicht gesetzt werden: {exc}')
        return False

    try:
        before = current_revision()
        command.upgrade(cfg, 'head')
        after = current_revision()
        if before != after:
            log('info', f'Datenbankschema aktualisiert: {before} -> {after}')
        return True
    except Exception as exc:
        log('error', f'Schema-Upgrade fehlgeschlagen: {exc}')
        return False


def current_revision():
    """Aktuelle Revision der Datenbank, oder None wenn ungestempelt."""
    try:
        from alembic.runtime.migration import MigrationContext

        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:
        log('warning', f'Alembic-Revision nicht lesbar: {exc}')
        return None
