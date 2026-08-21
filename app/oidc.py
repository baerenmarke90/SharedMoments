from authlib.integrations.flask_client import OAuth

from config import Config


oauth = OAuth()


def oidc_configured():
    return bool(
        Config.OIDC_ENABLED
        and Config.OIDC_ISSUER
        and Config.OIDC_CLIENT_ID
        and Config.OIDC_CLIENT_SECRET
        and Config.OIDC_REDIRECT_URI
    )


def init_oidc(app):
    oauth.init_app(app)

    if not oidc_configured():
        return

    metadata_url = (
        Config.OIDC_ISSUER
        + '/.well-known/openid-configuration'
    )

    oauth.register(
        name='pocketid',
        client_id=Config.OIDC_CLIENT_ID,
        client_secret=Config.OIDC_CLIENT_SECRET,
        server_metadata_url=metadata_url,
        client_kwargs={
            'scope': 'openid profile email'
        }
    )


def get_pocketid_client():
    if not oidc_configured():
        return None

    return oauth.create_client('pocketid')
