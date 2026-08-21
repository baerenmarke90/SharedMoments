from app.models import (
    OIDCIdentity,
    SessionLocal,
)


def ensure_oidc_schema():
    """
    Create the OIDC identity table on existing
    SharedMoments installations.

    Safe to call on every application start.
    """

    db = SessionLocal()

    try:
        bind = db.get_bind()

        OIDCIdentity.__table__.create(
            bind=bind,
            checkfirst=True
        )

    finally:
        db.close()
