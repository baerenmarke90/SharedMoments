from datetime import date

from sqlalchemy import or_

from .models import HeartMoment, User, SessionLocal
from .heart_moment_media import delete_heart_moment_image


ALLOWED_FEELINGS = {
    'loved',
    'seen',
    'appreciated',
    'supported',
    'grateful',
    'happy',
}

ALLOWED_VISIBILITIES = {
    'shared',
    'private',
}

ALLOWED_FILTERS = {
    'all',
    'shared',
    'mine',
    'private',
    'partner',
}


def _normalize_date(value):
    if value is None or value == '':
        return date.today()

    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(
            'momentDate must use YYYY-MM-DD format'
        ) from exc


def _normalize_choice(
    value,
    allowed,
    field_name,
):
    value = str(
        value or ''
    ).strip().lower()

    if value not in allowed:
        raise ValueError(
            f'Invalid {field_name}. '
            f'Allowed values: '
            + ', '.join(sorted(allowed))
        )

    return value


def _serialize(session, moment):
    author = (
        session.query(User)
        .filter(
            User.id == moment.authorUserID
        )
        .first()
    )

    return {
        'id': moment.id,
        'authorUserID': moment.authorUserID,

        'author': {
            'id': author.id,
            'firstName': author.firstName,
            'lastName': author.lastName,
        } if author else None,

        'momentDate': (
            moment.momentDate.isoformat()
            if moment.momentDate
            else None
        ),

        'description': moment.description,
        'feeling': moment.feeling,
        'visibility': moment.visibility,

        # Only used by the UI as "has image".
        # The actual image is always retrieved
        # through the protected image endpoint.
        'mediaFilename': moment.mediaFilename,

        'dateCreated': (
            moment.dateCreated.isoformat()
            if moment.dateCreated
            else None
        ),

        'dateModified': (
            moment.dateModified.isoformat()
            if moment.dateModified
            else None
        ),
    }


def list_heart_moments(
    user_id,
    filter_name='all',
    feeling=None,
):
    filter_name = str(
        filter_name or 'all'
    ).strip().lower()

    if filter_name not in ALLOWED_FILTERS:
        raise ValueError(
            'Invalid filter. Allowed values: '
            + ', '.join(
                sorted(ALLOWED_FILTERS)
            )
        )

    normalized_feeling = None

    if feeling:
        normalized_feeling = (
            _normalize_choice(
                feeling,
                ALLOWED_FEELINGS,
                'feeling',
            )
        )

    session = SessionLocal()

    try:
        query = (
            session.query(HeartMoment)
            .filter(
                or_(
                    HeartMoment.visibility
                    == 'shared',

                    HeartMoment.authorUserID
                    == user_id,
                )
            )
        )

        if filter_name == 'shared':
            query = query.filter(
                HeartMoment.visibility
                == 'shared'
            )

        elif filter_name == 'mine':
            query = query.filter(
                HeartMoment.authorUserID
                == user_id
            )

        elif filter_name == 'private':
            query = query.filter(
                HeartMoment.authorUserID
                == user_id,

                HeartMoment.visibility
                == 'private',
            )

        elif filter_name == 'partner':
            query = query.filter(
                HeartMoment.authorUserID
                != user_id,

                HeartMoment.visibility
                == 'shared',
            )

        if normalized_feeling:
            query = query.filter(
                HeartMoment.feeling
                == normalized_feeling
            )

        moments = query.order_by(
            HeartMoment.momentDate.desc(),
            HeartMoment.dateCreated.desc(),
        ).all()

        return [
            _serialize(session, moment)
            for moment in moments
        ]

    finally:
        session.close()


def get_visible_heart_moment(
    moment_id,
    user_id,
):
    session = SessionLocal()

    try:
        moment = (
            session.query(HeartMoment)
            .filter(
                HeartMoment.id == moment_id,

                or_(
                    HeartMoment.visibility
                    == 'shared',

                    HeartMoment.authorUserID
                    == user_id,
                ),
            )
            .first()
        )

        if not moment:
            return None

        return _serialize(
            session,
            moment,
        )

    finally:
        session.close()


def get_owned_heart_moment(
    moment_id,
    user_id,
):
    session = SessionLocal()

    try:
        moment = (
            session.query(HeartMoment)
            .filter(
                HeartMoment.id == moment_id,
                HeartMoment.authorUserID
                == user_id,
            )
            .first()
        )

        if not moment:
            return None

        return _serialize(
            session,
            moment,
        )

    finally:
        session.close()


def create_heart_moment(
    user_id,
    description,
    feeling,
    moment_date=None,
    visibility='shared',
):
    description = str(
        description or ''
    ).strip()

    if not description:
        raise ValueError(
            'Description is required'
        )

    feeling = _normalize_choice(
        feeling,
        ALLOWED_FEELINGS,
        'feeling',
    )

    visibility = _normalize_choice(
        visibility,
        ALLOWED_VISIBILITIES,
        'visibility',
    )

    moment_date = _normalize_date(
        moment_date
    )

    session = SessionLocal()

    try:
        moment = HeartMoment(
            authorUserID=user_id,
            momentDate=moment_date,
            description=description,
            feeling=feeling,
            visibility=visibility,
            mediaFilename=None,
        )

        session.add(moment)
        session.commit()
        session.refresh(moment)

        return _serialize(
            session,
            moment,
        )

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def update_heart_moment(
    moment_id,
    user_id,
    changes,
):
    session = SessionLocal()

    try:
        moment = (
            session.query(HeartMoment)
            .filter(
                HeartMoment.id == moment_id,
                HeartMoment.authorUserID
                == user_id,
            )
            .first()
        )

        if not moment:
            return None

        if 'description' in changes:
            description = str(
                changes.get(
                    'description'
                ) or ''
            ).strip()

            if not description:
                raise ValueError(
                    'Description is required'
                )

            moment.description = (
                description
            )

        if 'feeling' in changes:
            moment.feeling = (
                _normalize_choice(
                    changes.get(
                        'feeling'
                    ),
                    ALLOWED_FEELINGS,
                    'feeling',
                )
            )

        if 'visibility' in changes:
            moment.visibility = (
                _normalize_choice(
                    changes.get(
                        'visibility'
                    ),
                    ALLOWED_VISIBILITIES,
                    'visibility',
                )
            )

        if 'momentDate' in changes:
            moment.momentDate = (
                _normalize_date(
                    changes.get(
                        'momentDate'
                    )
                )
            )

        # mediaFilename is deliberately NOT
        # accepted here. Media can only be
        # changed through the protected
        # image endpoint.

        session.commit()
        session.refresh(moment)

        return _serialize(
            session,
            moment,
        )

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def set_heart_moment_media(
    moment_id,
    user_id,
    media_filename,
):
    session = SessionLocal()

    try:
        moment = (
            session.query(HeartMoment)
            .filter(
                HeartMoment.id == moment_id,
                HeartMoment.authorUserID
                == user_id,
            )
            .first()
        )

        if not moment:
            return None

        moment.mediaFilename = (
            media_filename
        )

        session.commit()
        session.refresh(moment)

        return _serialize(
            session,
            moment,
        )

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


def delete_heart_moment(
    moment_id,
    user_id,
):
    session = SessionLocal()

    try:
        moment = (
            session.query(HeartMoment)
            .filter(
                HeartMoment.id == moment_id,
                HeartMoment.authorUserID
                == user_id,
            )
            .first()
        )

        if not moment:
            return False

        media_filename = (
            moment.mediaFilename
        )

        session.delete(moment)
        session.commit()

        if media_filename:
            try:
                delete_heart_moment_image(
                    media_filename
                )
            except Exception:
                # DB deletion must not fail
                # because an orphaned file
                # could not be removed.
                pass

        return True

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()
