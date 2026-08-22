from app import app
from app.models import Base, engine
from app.db_queries import init_db, sync_version_to_db, ensure_reminder_permissions
from app.db_migrations import ensure_schema_up_to_date
from app.translation import load_translation_in_cache, migrateTranslations
from app.logger import log
from app.version import __version__

# Database initialization
Base.metadata.create_all(engine)
# Direkt nach create_all: unmarkierte Datenbanken bekommen die Baseline,
# danach laufen ausstehende Migrationen. Migrationen liegen im selben Image
# wie der Code - sie duerfen nicht hinterherhinken.
ensure_schema_up_to_date()
init_db()
sync_version_to_db()
ensure_reminder_permissions()
migrateTranslations(overwrite=True)
load_translation_in_cache()

# VAPID key generation (for push notifications)
from app.notifications import _ensure_vapid_keys
_ensure_vapid_keys()

# v1 → v2 Migration (runs in background thread so the server can serve
# the migration-progress page while the migration is running)
try:
    from app.migration import check_and_run_migration
    from app.migration.v1_reader import v1_configured
    if v1_configured():
        import threading
        threading.Thread(target=check_and_run_migration, daemon=True).start()
except ImportError:
    pass

# Start scheduler
from app.scheduler import start_scheduler
start_scheduler(app)

if __name__ == '__main__':
    import os
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    port = int(os.environ.get('PORT', 5001))
    log('info', f'SharedMoments {__version__}')
    log('info', f'Starting the application on port {port} (debug={debug})')
    app.run(debug=debug, host='0.0.0.0', port=port, threaded=True)
