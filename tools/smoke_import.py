#!/usr/bin/env python3
"""Startet die App genau so weit, wie Gunicorn es tut: run.py importieren.

Am 22.08.2026 hat run.py eine Funktion importiert, die es nicht mehr gab -
py_compile konnte das nicht sehen, weil es jede Datei einzeln uebersetzt und
keine Importe aufloest. Dieser Test haette es sofort gefunden.

Laeuft gegen eine Wegwerf-Datenbank in einem temporaeren Verzeichnis.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

workdir = tempfile.mkdtemp(prefix='sm-smoke-')
os.environ.setdefault('SECRET_KEY', 'smoke-test-only')
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(workdir, 'smoke.db')

# Die App legt beim Start Verzeichnisse relativ zum Projekt an.
for folder in ('app/database', 'app/uploads/images', 'app/uploads/videos',
               'app/uploads/music', 'app/uploads/thumbs', 'app/uploads/temp',
               'app/uploads/profiles'):
    (ROOT / folder).mkdir(parents=True, exist_ok=True)

import run  # noqa: E402

assert hasattr(run, 'app'), 'run.py stellt kein app-Objekt bereit'

# Jede registrierte Seite muss eine aufloesbare Funktion haben.
rules = sorted(str(rule) for rule in run.app.url_map.iter_rules())
assert '/story' in rules, '/story ist nicht registriert'
assert '/private' in rules, '/private ist nicht registriert'
assert '/home' in rules, '/home ist nicht registriert'

with run.app.test_client() as client:
    response = client.get('/login')
    assert response.status_code in (200, 302), f'/login antwortet mit {response.status_code}'

print(f'Import ok, {len(rules)} Routen registriert, /login antwortet')

# Der Hintergrund-Scheduler laeuft sonst weiter und haelt den Job auf.
try:
    from app import scheduler as app_scheduler

    if getattr(app_scheduler, '_scheduler', None) is not None:
        app_scheduler._scheduler.shutdown(wait=False)
except Exception:
    pass
