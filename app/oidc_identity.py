from sqlalchemy import func

from app.models import (
    OIDCIdentity,
    SessionLocal,
    User,
)


PROVIDER_POCKET_ID = 'pocketid'


def normalize_issuer(issuer):
    return str(issuer or '').strip().rstrip('/')


def get_oidc_identity_by_subject(
    issuer,
    subject,
    provider=PROVIDER_POCKET_ID
):
    db = SessionLocal()

    try:
        identity = (
            db.query(OIDCIdentity)
            .filter(
                OIDCIdentity.provider == provider,
                OIDCIdentity.issuer
                == normalize_issuer(issuer),
                OIDCIdentity.subject
                == str(subject)
            )
            .first()
        )

        if identity:
            db.expunge(identity)

        return identity

    finally:
        db.close()


def get_oidc_identity_for_user(
    user_id,
    provider=PROVIDER_POCKET_ID
):
    db = SessionLocal()

    try:
        identity = (
            db.query(OIDCIdentity)
            .filter(
                OIDCIdentity.userID == user_id,
                OIDCIdentity.provider == provider
            )
            .first()
        )

        if identity:
            db.expunge(identity)

        return identity

    finally:
        db.close()


def get_unique_user_by_oidc_email(email):
    """
    Find exactly one existing SharedMoments user by
    e-mail address for safe OIDC auto-linking.

    Returns None when:
      - no e-mail was supplied
      - no user matches
      - multiple users match

    The system user (id=1) is never eligible.
    """

    normalized_email = str(
        email or ''
    ).strip().lower()

    if not normalized_email:
        return None

    db = SessionLocal()

    try:
        users = (
            db.query(User)
            .filter(
                User.id != 1,
                User.email.isnot(None),
                func.lower(User.email)
                == normalized_email
            )
            .limit(2)
            .all()
        )

        if len(users) != 1:
            return None

        user = users[0]
        db.expunge(user)

        return user

    finally:
        db.close()


def link_oidc_identity(
    user_id,
    issuer,
    subject,
    email=None,
    preferred_username=None,
    provider=PROVIDER_POCKET_ID
):
    issuer = normalize_issuer(issuer)
    subject = str(subject)

    db = SessionLocal()

    try:
        identity_for_subject = (
            db.query(OIDCIdentity)
            .filter(
                OIDCIdentity.provider == provider,
                OIDCIdentity.issuer == issuer,
                OIDCIdentity.subject == subject
            )
            .first()
        )

        if (
            identity_for_subject
            and identity_for_subject.userID
            != user_id
        ):
            raise ValueError(
                'This Pocket ID account is already '
                'linked to another SharedMoments user.'
            )

        identity_for_user = (
            db.query(OIDCIdentity)
            .filter(
                OIDCIdentity.userID == user_id,
                OIDCIdentity.provider == provider
            )
            .first()
        )

        if identity_for_user:
            if (
                identity_for_user.issuer != issuer
                or identity_for_user.subject
                != subject
            ):
                raise ValueError(
                    'This SharedMoments user is already '
                    'linked to another Pocket ID account.'
                )

            identity_for_user.email = email
            identity_for_user.preferredUsername = (
                preferred_username
            )

            db.commit()
            db.refresh(identity_for_user)

            identity_id = identity_for_user.id

        else:
            identity = OIDCIdentity(
                userID=user_id,
                provider=provider,
                issuer=issuer,
                subject=subject,
                email=email,
                preferredUsername=preferred_username
            )

            db.add(identity)
            db.commit()
            db.refresh(identity)

            identity_id = identity.id

        return identity_id

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def unlink_oidc_identity(
    user_id,
    provider=PROVIDER_POCKET_ID
):
    db = SessionLocal()

    try:
        identity = (
            db.query(OIDCIdentity)
            .filter(
                OIDCIdentity.userID == user_id,
                OIDCIdentity.provider == provider
            )
            .first()
        )

        if not identity:
            return False

        db.delete(identity)
        db.commit()

        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
