from app.models import (
    AuthConfiguration,
    SessionLocal,
)
from config import Config


DEFAULT_LOCAL_LOGIN = True
DEFAULT_PASSKEY_LOGIN = True


def ensure_auth_settings_schema():
    db = SessionLocal()

    try:
        bind = db.get_bind()

        AuthConfiguration.__table__.create(
            bind=bind,
            checkfirst=True
        )

        config = (
            db.query(AuthConfiguration)
            .filter(AuthConfiguration.id == 1)
            .first()
        )

        if not config:
            db.add(
                AuthConfiguration(
                    id=1,
                    localLoginEnabled=True,
                    passkeyLoginEnabled=True
                )
            )
            db.commit()

    finally:
        db.close()


def get_auth_settings():
    db = SessionLocal()

    try:
        config = (
            db.query(AuthConfiguration)
            .filter(AuthConfiguration.id == 1)
            .first()
        )

        if not config:
            return {
                'local_login_enabled':
                    DEFAULT_LOCAL_LOGIN,
                'passkey_login_enabled':
                    DEFAULT_PASSKEY_LOGIN,
            }

        return {
            'local_login_enabled':
                bool(config.localLoginEnabled),

            'passkey_login_enabled':
                bool(config.passkeyLoginEnabled),
        }

    finally:
        db.close()


def get_effective_auth_settings():
    settings = get_auth_settings()

    local_enabled = bool(
        Config.AUTH_FORCE_LOCAL_LOGIN
        or (
            Config.AUTH_LOCAL_LOGIN_ENABLED
            and settings['local_login_enabled']
        )
    )

    passkey_enabled = bool(
        Config.AUTH_PASSKEY_LOGIN_ENABLED
        and settings['passkey_login_enabled']
    )

    return {
        'local_login_enabled': local_enabled,
        'passkey_login_enabled': passkey_enabled,
    }


def set_auth_settings(
    local_login_enabled,
    passkey_login_enabled
):
    db = SessionLocal()

    try:
        config = (
            db.query(AuthConfiguration)
            .filter(AuthConfiguration.id == 1)
            .first()
        )

        if not config:
            config = AuthConfiguration(id=1)
            db.add(config)

        config.localLoginEnabled = bool(
            local_login_enabled
        )

        config.passkeyLoginEnabled = bool(
            passkey_login_enabled
        )

        db.commit()

        return {
            'local_login_enabled':
                bool(config.localLoginEnabled),

            'passkey_login_enabled':
                bool(config.passkeyLoginEnabled),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
