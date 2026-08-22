# Upgrade

## Vor jedem Upgrade

```bash
docker compose stop sharedmoments
cp -a /opt/sharedmoments/database /opt/sharedmoments/database.bak-$(date +%F)
```

Niemals `docker compose down -v`, niemals Volumes loeschen, `SECRET_KEY` nie aendern.
Immer zuerst `sharedmoments-fork-test` bauen und dort pruefen.

## Datenbankschema

Bis v0.5 ist das Schema ausschliesslich durch SQLAlchemys `create_all()`
entstanden. Das legt **fehlende Tabellen** an, aendert aber **nie** eine
bestehende Tabelle. Neue Spalten waeren damit stillschweigend nur in neuen
Installationen gelandet.

Seit v0.6 fuehrt jede Datenbank eine Alembic-Version:

- Beim Start stempelt `ensure_schema_up_to_date()` eine noch unmarkierte
  Datenbank auf die Baseline `0001_baseline`. Das aendert nichts am Schema,
  es markiert nur den Stand.
- Danach laufen ausstehende Migrationen automatisch (`upgrade head`).
  Migrationen liegen im selben Image wie der Code: waeren sie optional,
  liefe die App nach einem Deploy mit einer Spalte, die es in der Datenbank
  noch nicht gibt.
- Schlaegt ein Upgrade fehl, startet die App trotzdem und schreibt den Fehler
  ins Log. Eine lesbare Instanz ist besser als eine, die nicht hochkommt.
- `create_all()` laeuft weiterhin mit, bis alle Tabellen ueber Migrationen
  entstanden sind.

**Deshalb gilt: vor jedem Upgrade ein Backup der Datenbank.** Die Sicherung
oben im Dokument ist keine Formalie.

Aktuellen Stand pruefen:

```bash
docker compose exec sharedmoments python -c "from app.db_migrations import current_revision; print(current_revision())"
```

## Eine Schemaaenderung vornehmen

```bash
docker compose exec sharedmoments alembic revision --autogenerate -m "kurze beschreibung"
```

Die erzeugte Datei **immer lesen**, bevor sie laeuft: Autogenerate erkennt
Umbenennungen nicht und schlaegt stattdessen Loeschen und Neuanlegen vor.

Danach zuerst die Testinstanz bauen und starten - das Upgrade laeuft dort
automatisch mit. Im Log steht dann:

```text
Datenbankschema aktualisiert: 0001_baseline -> 0002_plan_experienced_date
```

Erst wenn die Testinstanz sauber laeuft, die Produktion aktualisieren - mit
frischem Backup davor.
