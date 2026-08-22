from functools import wraps
from flask import Blueprint, abort, g, make_response, request, jsonify, redirect, url_for, session
from app.db_queries import get_user_by_credential_id, get_user_by_email, get_setting_by_name, get_user_by_id, update_passkey_sign_count, ensure_pwa_settings, ensure_notification_settings
from app.permissions import load_user_permissions, require_permission
from datetime import datetime, timedelta
from app.logger import log
import hashlib, json, jwt, secrets
from app.models import MobileOIDCCode, Passkey, SessionLocal
from app.translation import _, set_locale
from config import Config
import os
from webauthn import generate_authentication_options, generate_registration_options, options_to_json, verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
)

auth_bp = Blueprint('auth', __name__)


def _get_webauthn_rp_id():
    """Return RP ID from config or auto-detect from request host."""
    from app import app
    configured = app.config.get('WEBAUTHN_RP_ID')
    if configured and configured != 'localhost':
        return configured
    # Auto-detect: hostname without port
    hostname = request.host.split(':')[0]
    return hostname


def _get_webauthn_origin():
    """Return origin from config or auto-detect from request."""
    from app import app
    configured = app.config.get('WEBAUTHN_ORIGIN')
    if configured:
        return configured
    # Auto-detect from request
    return request.origin or f"{request.scheme}://{request.host}"


def get_secret_key():
    from app import app
    return app.config['SECRET_KEY']


def local_login_enabled():
    from app.auth_settings import (
        get_effective_auth_settings,
    )

    return get_effective_auth_settings()[
        'local_login_enabled'
    ]


def passkey_login_enabled():
    from app.auth_settings import (
        get_effective_auth_settings,
    )

    return get_effective_auth_settings()[
        'passkey_login_enabled'
    ]


def oidc_login_enabled():
    """Return whether Pocket ID is completely configured."""
    from app.oidc import oidc_configured
    return bool(oidc_configured())


def jwt_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('jwt_token')

        if not token:
            return redirect(url_for('auth.login'))

        try:
            decoded_token = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
            user_id = decoded_token.get('user_id')
            g.user_id = user_id
        except jwt.ExpiredSignatureError:
            log('debug', f'Expired JWT token on {request.path}')
            return redirect(url_for('auth.login'))
        except jwt.InvalidTokenError:
            log('debug', f'Invalid JWT token on {request.path}')
            return redirect(url_for('auth.login'))

        # Block access during setup — only /setup and assets are allowed
        setup_setting = get_setting_by_name('setup_complete')
        if setup_setting and setup_setting.value == 'False':
            allowed_paths = ('/static/', '/api/v2/media/', '/api/v2/setup', '/api/v2/translations/', '/api/v2/upload', '/api/v2/data/import/status/', '/api/v2/data/export/status/')
            if not any(request.path.startswith(p) for p in allowed_paths):
                return redirect(url_for('pages.setup'))

        return f(*args, **kwargs)

    return decorated_function


def login_jwt(user, remember_me=False):
    if remember_me:
        expiration = datetime.utcnow() + timedelta(days=30)
    else:
        expiration = datetime.utcnow() + timedelta(hours=24)

    token = jwt.encode({
        'user_id': user.id,
        'exp': expiration
    }, get_secret_key(), algorithm='HS256')

    next_url = request.args.get('next')

    response = make_response(jsonify({
        'status': 'success',
        'message': _('Login successful'),
        'data': {
            'next_url': next_url
        }
    }))

    response.set_cookie(
        'jwt_token', token,
        httponly=True,
        secure=request.is_secure,
        samesite='Lax',
        expires=expiration
    )
    return response


def login_jwt_redirect(
    user,
    target=None,
    remember_me=True
):
    """
    Create the normal SideBySide JWT cookie and
    return an HTTP redirect.

    Used after successful external OIDC authentication.
    """

    if remember_me:
        expiration = (
            datetime.utcnow()
            + timedelta(days=30)
        )
    else:
        expiration = (
            datetime.utcnow()
            + timedelta(hours=24)
        )

    token = jwt.encode(
        {
            'user_id': user.id,
            'exp': expiration
        },
        get_secret_key(),
        algorithm='HS256'
    )

    response = make_response(
        redirect(
            target
            or url_for('pages.home')
        )
    )

    response.set_cookie(
        'jwt_token',
        token,
        httponly=True,
        secure=request.is_secure,
        samesite='Lax',
        expires=expiration
    )

    return response


def _jwt_user_id_from_cookie():
    """
    Return the currently logged-in SideBySide user
    without causing a redirect.

    This is used to verify OIDC account-link callbacks.
    """

    token = request.cookies.get('jwt_token')

    if not token:
        return None

    try:
        decoded = jwt.decode(
            token,
            get_secret_key(),
            algorithms=['HS256']
        )

        return decoded.get('user_id')

    except (
        jwt.ExpiredSignatureError,
        jwt.InvalidTokenError
    ):
        return None


@auth_bp.before_app_request
def before_request():
    # --- Demo Mode ---
    if Config.DEMO_MODE and not request.path.startswith('/static/'):
        from app.demo import create_demo_session, bind_demo_session, DEMO_DB_DIR

        demo_id = request.cookies.get('demo_session_id')

        # Prüfe ob Demo-DB noch existiert
        if demo_id:
            db_path = os.path.join(DEMO_DB_DIR, f'demo_{demo_id}.db')
            if not os.path.exists(db_path):
                demo_id = None

        # Neue Demo-Session erstellen (nur für navigierende Requests)
        if not demo_id:
            if request.path.startswith('/api/') or request.path.startswith('/sw') or request.path.endswith('.json'):
                abort(401)
            demo_id = create_demo_session()
            response = make_response(redirect(url_for('auth.login')))
            response.set_cookie('demo_session_id', demo_id, httponly=True, samesite='Lax')
            return response

        # Engine für diesen Request binden
        bind_demo_session(demo_id)

    # --- Rest des bestehenden before_request ---
    if request.path.startswith('/s/') or request.path.startswith('/api/v2/data/import/status/') or request.path.startswith('/api/v2/data/export/status/'):
        return
    token = request.cookies.get('jwt_token')
    if not token:
        # Set locale from browser language for non-authenticated pages (login, reset-password)
        try:
            set_locale()
        except Exception:
            pass
    if token:
        try:
            decoded_token = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
            user_id = decoded_token.get('user_id')
            setup_complete = get_setting_by_name('setup_complete').value

            if not Config.DEMO_MODE and user_id != 1 and setup_complete == 'False' and request.endpoint != 'pages.setup':
                if not request.path.startswith(('/migration-progress', '/migration-complete', '/api/v2/migration/')):
                    return redirect(url_for('pages.setup'))

            user = get_user_by_id(user_id)
            if user:
                g.user_id = user_id
                g.user_name = f'{user.firstName} {user.lastName}'.strip() or f'User {user_id}'
                g.user_permissions = load_user_permissions(user_id)
                try:
                    set_locale(user.id)
                except Exception as e:
                    log('warning', f'Failed to set user locale for user {user_id}, falling back to "en": {e}')

                # Ensure PWA and notification settings exist (once per session)
                if not session.get('user_settings_ensured'):
                    try:
                        ensure_pwa_settings(user_id)
                        ensure_notification_settings(user_id)
                        session['user_settings_ensured'] = True
                    except Exception as e:
                        log('warning', f'Failed to ensure user settings for user {user_id}: {e}')

                if request.endpoint == 'auth.login':
                    return redirect(url_for('pages.home'))

        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
            log('debug', f'Invalid or expired JWT token in before_request: {e}')
            response = make_response(redirect(url_for('auth.login')))
            response.delete_cookie('jwt_token')
            return response


# ============================================================
# AUTHENTICATION SETTINGS
# ============================================================

@auth_bp.route(
    '/api/v2/auth/settings',
    methods=['PUT']
)
@jwt_required
@require_permission('Update Setting')
def update_authentication_settings():
    from app.auth_settings import (
        set_auth_settings,
    )
    from app.db_queries import (
        get_passkeys_by_user,
    )
    from app.oidc_identity import (
        get_oidc_identity_for_user,
    )

    data = request.get_json(silent=True) or {}

    local_enabled = data.get(
        'local_login_enabled'
    )

    passkey_enabled = data.get(
        'passkey_login_enabled'
    )

    if (
        not isinstance(local_enabled, bool)
        or not isinstance(passkey_enabled, bool)
    ):
        return jsonify({
            'status': 'error',
            'message': _(
                'Invalid authentication settings.'
            ),
            'data': {
                'error_code': 400
            }
        }), 400

    future_local_effective = bool(
        Config.AUTH_FORCE_LOCAL_LOGIN
        or (
            Config.AUTH_LOCAL_LOGIN_ENABLED
            and local_enabled
        )
    )

    future_passkey_effective = bool(
        Config.AUTH_PASSKEY_LOGIN_ENABLED
        and passkey_enabled
    )

    # Lockout protection:
    # If password login will no longer exist,
    # the user making this change must personally
    # have another working authentication method.
    if not future_local_effective:

        has_passkey = bool(
            future_passkey_effective
            and get_passkeys_by_user(g.user_id)
        )

        has_oidc = bool(
            oidc_login_enabled()
            and get_oidc_identity_for_user(
                g.user_id
            )
        )

        if not has_passkey and not has_oidc:
            return jsonify({
                'status': 'error',
                'message': _(
                    'Password login cannot be disabled '
                    'until your account has a working '
                    'Passkey or Pocket ID connection.'
                ),
                'data': {
                    'error_code': 409
                }
            }), 409

    settings = set_auth_settings(
        local_login_enabled=local_enabled,
        passkey_login_enabled=passkey_enabled
    )

    log(
        'info',
        'Authentication settings updated by '
        f'user {g.user_id}: '
        f'local={local_enabled}, '
        f'passkey={passkey_enabled}'
    )

    return jsonify({
        'status': 'success',
        'message': _(
            'Authentication settings updated.'
        ),
        'data': settings
    }), 200


# ============================================================
# OPENID CONNECT / POCKET ID
# ============================================================

MOBILE_OIDC_CODE_TTL_SECONDS = 120


def _create_mobile_oidc_code(user_id):
    """Create a short-lived single-use handoff code for Android."""
    raw_code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(raw_code.encode('utf-8')).hexdigest()
    now = datetime.utcnow()

    db = SessionLocal()
    try:
        db.query(MobileOIDCCode).filter(
            MobileOIDCCode.expiresAt < now
        ).delete(synchronize_session=False)

        db.add(
            MobileOIDCCode(
                codeHash=code_hash,
                userID=int(user_id),
                expiresAt=now + timedelta(seconds=MOBILE_OIDC_CODE_TTL_SECONDS)
            )
        )
        db.commit()
        return raw_code
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _consume_mobile_oidc_code(raw_code):
    """Consume a handoff code exactly once and return its user ID."""
    if not raw_code:
        return None

    code_hash = hashlib.sha256(raw_code.encode('utf-8')).hexdigest()
    now = datetime.utcnow()
    db = SessionLocal()

    try:
        row = db.query(MobileOIDCCode).filter_by(codeHash=code_hash).first()
        if not row or row.expiresAt < now:
            if row:
                db.delete(row)
                db.commit()
            return None

        user_id = row.userID
        db.delete(row)
        db.commit()
        return user_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@auth_bp.route('/oidc/login')
def oidc_login():
    """Start normal Pocket ID authentication."""

    from app.oidc import get_pocketid_client

    if not oidc_login_enabled():
        return redirect(
            url_for(
                'auth.login',
                oidc_error='not_configured'
            )
        )

    client = get_pocketid_client()

    if client is None:
        return redirect(
            url_for(
                'auth.login',
                oidc_error='not_configured'
            )
        )

    session['oidc_action'] = 'login'
    session.pop('oidc_mobile', None)
    session.pop('oidc_link_user_id', None)

    return client.authorize_redirect(
        Config.OIDC_REDIRECT_URI
    )




@auth_bp.route('/oidc/mobile/login')
def oidc_mobile_login():
    """Start Pocket ID in the external browser for the Android app."""
    from app.oidc import get_pocketid_client

    if not oidc_login_enabled():
        return redirect(
            url_for('auth.login', oidc_error='not_configured')
        )

    client = get_pocketid_client()
    if client is None:
        return redirect(
            url_for('auth.login', oidc_error='not_configured')
        )

    session['oidc_action'] = 'login'
    session['oidc_mobile'] = True
    session.pop('oidc_link_user_id', None)

    return client.authorize_redirect(
        Config.OIDC_REDIRECT_URI
    )
@auth_bp.route('/oidc/link')
@jwt_required
def oidc_link():
    """
    Link the currently logged-in SideBySide account
    to a Pocket ID identity.
    """

    from app.oidc import get_pocketid_client

    if not oidc_login_enabled():
        return redirect(
            url_for(
                'pages.user_settings',
                oidc_error='not_configured'
            )
        )

    client = get_pocketid_client()

    if client is None:
        return redirect(
            url_for(
                'pages.user_settings',
                oidc_error='not_configured'
            )
        )

    session['oidc_action'] = 'link'
    session.pop('oidc_mobile', None)
    session['oidc_link_user_id'] = g.user_id

    return client.authorize_redirect(
        Config.OIDC_REDIRECT_URI
    )


@auth_bp.route('/oidc/callback')
def oidc_callback():
    """
    Handle both:
      - normal Pocket ID login
      - linking Pocket ID to an existing account
    """

    from app.oidc import get_pocketid_client
    from app.oidc_identity import (
        get_oidc_identity_by_subject,
        get_unique_user_by_oidc_email,
        link_oidc_identity,
    )

    action = session.pop(
        'oidc_action',
        'login'
    )

    link_user_id = session.pop(
        'oidc_link_user_id',
        None
    )

    mobile_login = bool(session.pop('oidc_mobile', False))

    if not oidc_login_enabled():
        return redirect(
            url_for(
                'auth.login',
                oidc_error='not_configured'
            )
        )

    client = get_pocketid_client()

    if client is None:
        return redirect(
            url_for(
                'auth.login',
                oidc_error='not_configured'
            )
        )

    try:
        token = client.authorize_access_token()

        userinfo = token.get('userinfo')

        if not userinfo:
            userinfo = client.userinfo(
                token=token
            )

        subject = userinfo.get('sub')

        if not subject:
            raise ValueError(
                'OIDC response contains no subject.'
            )

        issuer = Config.OIDC_ISSUER

        email = userinfo.get('email')

        preferred_username = (
            userinfo.get('preferred_username')
            or userinfo.get('name')
        )

        # -------------------------------------------------
        # Existing SideBySide account -> Pocket ID link
        # -------------------------------------------------

        if action == 'link':
            current_user_id = (
                _jwt_user_id_from_cookie()
            )

            if (
                not current_user_id
                or not link_user_id
                or int(current_user_id)
                != int(link_user_id)
            ):
                log(
                    'warning',
                    'OIDC account-link callback without '
                    'matching SideBySide session'
                )

                return redirect(
                    url_for(
                        'auth.login',
                        oidc_error='link_session'
                    )
                )

            link_oidc_identity(
                user_id=int(link_user_id),
                issuer=issuer,
                subject=subject,
                email=email,
                preferred_username=(
                    preferred_username
                )
            )

            log(
                'info',
                'Pocket ID linked to '
                f'SideBySide user {link_user_id}'
            )

            return redirect(
                url_for(
                    'pages.user_settings',
                    oidc='linked'
                )
            )

        # -------------------------------------------------
        # Normal Pocket ID login
        # -------------------------------------------------

        identity = (
            get_oidc_identity_by_subject(
                issuer=issuer,
                subject=subject
            )
        )

        if identity:
            user = get_user_by_id(
                identity.userID
            )

        else:
            # -------------------------------------------------
            # Safe first-login auto-link
            # -------------------------------------------------
            #
            # Only trust the e-mail for automatic account
            # linking when the OIDC provider explicitly marks
            # it as verified.
            #
            # issuer + sub remain the permanent identity key.
            #

            email_verified = (
                userinfo.get('email_verified')
                is True
            )

            user = None

            if email and email_verified:
                user = (
                    get_unique_user_by_oidc_email(
                        email
                    )
                )

            if user:
                link_oidc_identity(
                    user_id=user.id,
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    preferred_username=(
                        preferred_username
                    )
                )

                log(
                    'info',
                    'Pocket ID automatically linked '
                    f'to SideBySide user {user.id} '
                    'using verified e-mail'
                )

            else:
                if email and not email_verified:
                    log(
                        'warning',
                        'Pocket ID identity is not linked '
                        'and supplied e-mail is not verified'
                    )
                else:
                    log(
                        'warning',
                        'Pocket ID authentication succeeded '
                        'but no unique existing account '
                        'could be auto-linked'
                    )

                return redirect(
                    url_for(
                        'auth.login',
                        oidc_error='not_linked'
                    )
                )

        if not user:
            log(
                'error',
                'OIDC identity references missing '
                f'user {identity.userID}'
            )

            return redirect(
                url_for(
                    'auth.login',
                    oidc_error='user_missing'
                )
            )

        # Refresh non-authoritative metadata.
        # issuer + sub remain the real identity key.
        link_oidc_identity(
            user_id=user.id,
            issuer=issuer,
            subject=subject,
            email=email,
            preferred_username=(
                preferred_username
            )
        )

        log(
            'info',
            f'User {user.id} authenticated via Pocket ID'
        )

        if mobile_login:
            mobile_code = _create_mobile_oidc_code(user.id)
            log(
                'info',
                f'Pocket ID mobile login completed for user {user.id}'
            )
            return redirect(
                'sharedmoments://auth?code=' + mobile_code
            )

        return login_jwt_redirect(
            user,
            remember_me=True
        )

    except ValueError as exc:
        log(
            'warning',
            f'OIDC linking rejected: {exc}'
        )

        destination = (
            'pages.user_settings'
            if action == 'link'
            else 'auth.login'
        )

        return redirect(
            url_for(
                destination,
                oidc_error='already_linked'
            )
        )

    except Exception as exc:
        log(
            'error',
            f'OIDC authentication failed: {exc}'
        )

        destination = (
            'pages.user_settings'
            if action == 'link'
            else 'auth.login'
        )

        return redirect(
            url_for(
                destination,
                oidc_error='failed'
            )
        )


@auth_bp.route('/oidc/mobile/exchange')
def oidc_mobile_exchange():
    """Exchange the one-time browser handoff code for the normal JWT cookie."""
    raw_code = request.args.get('code', '').strip()

    try:
        user_id = _consume_mobile_oidc_code(raw_code)
    except Exception as exc:
        log('error', f'Mobile OIDC exchange failed: {exc}')
        user_id = None

    if not user_id:
        return redirect(
            url_for('auth.login', oidc_error='mobile_expired')
        )

    user = get_user_by_id(user_id)
    if not user:
        return redirect(
            url_for('auth.login', oidc_error='user_missing')
        )

    log('info', f'User {user.id} completed Pocket ID mobile exchange')
    return login_jwt_redirect(
        user,
        remember_me=True
    )


@auth_bp.route(
    '/api/v2/user/oidc',
    methods=['DELETE']
)
@jwt_required
def oidc_unlink():
    """Remove Pocket ID from the current account."""

    from app.db_queries import (
        get_passkeys_by_user,
    )

    from app.oidc_identity import (
        get_oidc_identity_for_user,
        unlink_oidc_identity,
    )

    identity = get_oidc_identity_for_user(
        g.user_id
    )

    if not identity:
        return jsonify({
            'status': 'error',
            'message': _(
                'No Pocket ID account is linked.'
            ),
            'data': {
                'error_code': 404
            }
        }), 404

    # Never allow a user to remove their final
    # usable authentication method.
    has_local_login = local_login_enabled()

    has_passkey_login = bool(
        passkey_login_enabled()
        and get_passkeys_by_user(g.user_id)
    )

    if (
        not has_local_login
        and not has_passkey_login
    ):
        return jsonify({
            'status': 'error',
            'message': _(
                'Pocket ID cannot be unlinked '
                'because no alternative login '
                'method is available.'
            ),
            'data': {
                'error_code': 409
            }
        }), 409

    unlink_oidc_identity(
        g.user_id
    )

    log(
        'info',
        'Pocket ID unlinked from '
        f'SideBySide user {g.user_id}'
    )

    return jsonify({
        'status': 'success',
        'message': _(
            'Pocket ID account unlinked.'
        ),
        'data': {}
    }), 200


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask import render_template
    if get_setting_by_name('setup_complete').value == 'False':
        return redirect(url_for('pages.setup'))
    else:
        if request.method == 'POST':
            if not local_login_enabled():
                return jsonify({
                    'status': 'error',
                    'message': _(
                        'Password login is disabled.'
                    ),
                    'data': {
                        'error_code': 403
                    }
                }), 403

            email = request.form.get('email')
            password = request.form.get('password')

            if not email or not password:
                return jsonify({
                    'status': 'error',
                    'message': _('E-Mail or password cannot be empty'),
                    'data': {
                        'error_code': 400,
                    }
                }), 400

            try:
                user = get_user_by_email(email)

                if not user or not user.check_password(password):
                    return jsonify({
                        'status': 'error',
                        'message': _('E-Mail or password incorrect'),
                        'data': {
                            'error_code': 401,
                        }
                    }), 401

            except Exception as e:
                # app wird in dieser Datei sonst ueberall lokal importiert;
                # hier fehlte es, wodurch der Fehlerfall selbst mit einem
                # NameError abgebrochen waere statt mit sauberem JSON.
                from app import app

                log('error', f'Error while fetching user: {e}')
                return jsonify({
                    'status': 'error',
                    'message': _('An error occurred while fetching user details.'),
                    'data': {
                        'error_code': 500,
                        'error_message': str(e) if app.debug else None
                    }
                }), 500

            remember_me = request.form.get('remember_me') == 'true'
            response = login_jwt(user, remember_me=remember_me)
            return response

        if request.method == 'GET':
            try:
                smtp_configured = bool(os.environ.get('SMTP_HOST') and os.environ.get('SMTP_USER'))
                return render_template(
                    'pages/login.html',
                    smtp_configured=smtp_configured,
                    local_login_enabled=(
                        local_login_enabled()
                    ),
                    passkey_login_enabled=(
                        passkey_login_enabled()
                    ),
                    oidc_login_enabled=(
                        oidc_login_enabled()
                    ),
                    oidc_provider_name=(
                        Config.OIDC_PROVIDER_NAME
                    ),
                    oidc_error=request.args.get(
                        'oidc_error'
                    )
                )
            except Exception as e:
                log('error', f'Error while rendering the pages/login.html-Template: {e}')
                return "An error occurred while rendering the page, please see the Server-Logs for more informations.", 500


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = request.form.get('email', '').strip()
    if not email:
        return jsonify({'status': 'error', 'message': _('Please enter your e-mail address.')}), 400

    log('info', f'Password reset requested for email: {email}')

    # Always return success to avoid leaking whether an email exists
    user = get_user_by_email(email)
    if not user or not user.email:
        log('warning', f'Password reset requested for unknown or empty email: {email}')
    if user and user.email:
        smtp_host = os.environ.get('SMTP_HOST', '')
        smtp_user = os.environ.get('SMTP_USER', '')
        if smtp_host and smtp_user:
            # Generate a short-lived JWT token for password reset
            token = jwt.encode({
                'user_id': user.id,
                'purpose': 'password_reset',
                'exp': datetime.utcnow() + timedelta(hours=1)
            }, get_secret_key(), algorithm='HS256')

            reset_url = f"{request.scheme}://{request.host}/reset-password/{token}"

            from app.notifications import send_email_notification
            subject = _('Password Reset') + ' — SideBySide'
            body = (
                f"{_('Hello')} {user.firstName or ''},\n\n"
                f"{_('A password reset was requested for your account.')}\n"
                f"{_('Click the following link to set a new password:')}\n\n"
                f"{reset_url}\n\n"
                f"{_('This link is valid for 1 hour.')}\n"
                f"{_('If you did not request this, you can ignore this e-mail.')}\n\n"
                f"SideBySide"
            )
            send_email_notification(user.email, subject, body)
            log('info', f'Password reset email sent to {user.email}')

    return jsonify({'status': 'success', 'message': _('If an account with this e-mail exists, a reset link has been sent.')})


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from flask import render_template
    from app.db_queries import update_user_password

    # Validate token
    try:
        decoded = jwt.decode(token, get_secret_key(), algorithms=['HS256'])
        if decoded.get('purpose') != 'password_reset':
            raise jwt.InvalidTokenError('Invalid token purpose')
        user_id = decoded.get('user_id')
    except jwt.ExpiredSignatureError:
        return render_template('pages/reset-password.html', error=_('This reset link has expired. Please request a new one.'))
    except jwt.InvalidTokenError:
        return render_template('pages/reset-password.html', error=_('This reset link is invalid.'))

    user = get_user_by_id(user_id)
    if not user:
        return render_template('pages/reset-password.html', error=_('This reset link is invalid.'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not new_password:
            return render_template('pages/reset-password.html', token=token,
                                   error=_('Please enter a password.'))

        if new_password != confirm_password:
            return render_template('pages/reset-password.html', token=token,
                                   error=_('Passwords do not match.'))

        password_hash, password_salt = user.hash_password(new_password)
        update_user_password(user.id, password_hash, password_salt)
        log('info', f'Password reset completed for user {user.id} ({user.email})')
        return render_template('pages/reset-password.html', success=True)

    return render_template('pages/reset-password.html', token=token)


@auth_bp.route('/logout')
@jwt_required
def logout():
    response = make_response(redirect(url_for('auth.login')))
    response.delete_cookie('jwt_token')
    return response


# WebAuthn Routes

@auth_bp.route('/webauthn/register', methods=['POST'])
def webauthn_register():
    from app import app
    try:
        email = request.form['email']
        name = request.form['name']

        options = generate_registration_options(
            rp_name=app.config['WEBAUTHN_RP_NAME'],
            rp_id=_get_webauthn_rp_id(),
            user_id=email.encode(),
            user_name=name,
            attestation=AttestationConveyancePreference.DIRECT,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED
            ),
        )

        session['current_challenge'] = bytes_to_base64url(options.challenge)
        session['email'] = email

        if 'webauth_data' not in session:
            session['webauth_data'] = {}

        if email not in session['webauth_data']:
            session['webauth_data'][email] = {}

        return jsonify({
            'status': 'success',
            'message': _('Registration challenge created successfully'),
            'data': options_to_json(options)
        }), 200

    except Exception as e:
        log('error', f'Error during WebAuthn registration: {e}')
        return jsonify({
            'status': 'error',
            'message': _('An error occurred during registration'),
            'data': {
                'error_code': 500,
                'error_message': str(e) if app.debug else None
            }
        }), 500


@auth_bp.route('/webauthn/register/verify', methods=['POST'])
def webauthn_register_verify():
    from app import app
    try:
        data = json.loads(request.data)
        challenge = session.get('current_challenge')

        credential = {
            "id": data['id'],
            "rawId": bytes_to_base64url(bytes(data['rawId'])),
            "response": {
                "attestationObject": bytes_to_base64url(bytes(data['response']['attestationObject'])),
                "clientDataJSON": bytes_to_base64url(bytes(data['response']['clientDataJSON']))
            },
            "type": data['type'],
            "authenticatorAttachment": data.get('authenticatorAttachment', None),
            "clientExtensionResults": data.get('clientExtensionResults', {})
        }

        verification = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=_get_webauthn_rp_id(),
            expected_origin=_get_webauthn_origin()
        )

        if verification:
            email = session.get('email')

            if email in session['webauth_data']:
                session['webauth_data'][email]['credential_id'] = bytes_to_base64url(verification.credential_id)
                session['webauth_data'][email]['public_key'] = bytes_to_base64url(verification.credential_public_key)
                session['webauth_data'][email]['sign_count'] = verification.sign_count

            log('info', f'Passkey registered successfully for user {email}')
            return jsonify({
                'status': 'success',
                'message': _('Passkey registered successfully'),
            }), 201
        else:
            raise Exception('WebAuthn registration verification failed')

    except Exception as e:
        log('error', f'Error during WebAuthn registration verification: {e}')
        return jsonify({
            'status': 'error',
            'message': _('An error occurred during registration verification'),
            'data': {
                'error_code': 500,
                'error_message': str(e) if app.debug else None
            }
        }), 500


@auth_bp.route('/webauthn/authenticate', methods=['POST'])
def webauthn_authenticate():
    from app import app

    if not passkey_login_enabled():
        return jsonify({
            'status': 'error',
            'message': _(
                'Passkey login is disabled.'
            ),
            'data': {
                'error_code': 403
            }
        }), 403

    try:
        options = generate_authentication_options(
            rp_id=_get_webauthn_rp_id()
        )

        session['current_challenge'] = bytes_to_base64url(options.challenge)

        return jsonify({
            'status': 'success',
            'message': _('Authentication challenge created successfully'),
            'data': options_to_json(options)
        }), 200

    except Exception as e:
        log('error', f'Error during WebAuthn authentication: {e}')
        return jsonify({
            'status': 'error',
            'message': _('An error occurred during authentication'),
            'data': {
                'error_code': 500,
                'error_message': str(e) if app.debug else None
            }
        }), 500


@auth_bp.route('/webauthn/authenticate/verify', methods=['POST'])
def webauthn_authenticate_verify():
    from app import app

    if not passkey_login_enabled():
        return jsonify({
            'status': 'error',
            'message': _(
                'Passkey login is disabled.'
            ),
            'data': {
                'error_code': 403
            }
        }), 403

    try:
        data = json.loads(request.data)
        challenge = session.get('current_challenge')

        credential = {
            "id": data['id'],
            "rawId": bytes_to_base64url(bytes(data['rawId'])),
            "response": {
                "authenticatorData": bytes_to_base64url(bytes(data['response']['authenticatorData'])),
                "clientDataJSON": bytes_to_base64url(bytes(data['response']['clientDataJSON'])),
                "signature": bytes_to_base64url(bytes(data['response']['signature'])),
                "userHandle": bytes_to_base64url(bytes(data['response']['userHandle'])) if data['response']['userHandle'] else None
            },
            "type": data['type'],
            "authenticatorAttachment": data.get('authenticatorAttachment', None),
            "clientExtensionResults": data.get('clientExtensionResults', {})
        }

        credentials, user = get_user_by_credential_id(credential['id'])

        if not credentials or not user:
            return jsonify({
                'status': 'error',
                'message': _('Passkey not recognized. It may have been deleted.'),
                'data': {
                    'error_code': 401,
                    'error_message': _('Passkey not recognized. It may have been deleted.')
                }
            }), 401

        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_origin=_get_webauthn_origin(),
            expected_rp_id=_get_webauthn_rp_id(),
            credential_public_key=base64url_to_bytes(credentials.public_key),
            credential_current_sign_count=credentials.sign_count
        )

        if verification:
            update_passkey_sign_count(credentials.credential_id, verification.new_sign_count)
            response = login_jwt(user, remember_me=True)
            log('info', f'User {user.id} authenticated successfully')
            return response

        else:
            raise Exception('WebAuthn authentication verification failed')

    except Exception as e:
        log('error', f'Error during WebAuthn authentication verification: {e}')
        return jsonify({
            'status': 'error',
            'message': _('An error occurred during authentication verification'),
            'data': {
                'error_code': 500,
                'error_message': str(e) if app.debug else None
            }
        }), 500
