from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import HeartMoment, SessionLocal


EXPECTED_COLUMNS = {
    'id',
    'authorUserID',
    'momentDate',
    'description',
    'feeling',
    'visibility',
    'mediaFilename',
    'dateCreated',
    'dateModified',
}


def ensure_heart_moments_schema():
    """
    Ensure that the Heart Moments table exists.

    This is intentionally independent from init_db(), because init_db()
    skips already initialized SharedMoments databases.

    The function is idempotent and may safely run on every application
    startup.
    """
    session = SessionLocal()

    try:
        bind = session.get_bind()

        # Use the database-level IF NOT EXISTS form. This is safer than a
        # separate check/create sequence when multiple application workers
        # start at approximately the same time.
        with bind.begin() as connection:
            connection.execute(
                CreateTable(
                    HeartMoment.__table__,
                    if_not_exists=True,
                )
            )

            for index in HeartMoment.__table__.indexes:
                connection.execute(
                    CreateIndex(
                        index,
                        if_not_exists=True,
                    )
                )

        inspector = inspect(bind)

        if HeartMoment.__tablename__ not in inspector.get_table_names():
            raise RuntimeError(
                f'Table {HeartMoment.__tablename__} does not exist '
                'after schema initialization'
            )

        columns = {
            column['name']
            for column in inspector.get_columns(
                HeartMoment.__tablename__
            )
        }

        missing_columns = EXPECTED_COLUMNS - columns

        if missing_columns:
            raise RuntimeError(
                'Heart Moments schema is incompatible. Missing columns: '
                + ', '.join(sorted(missing_columns))
            )

        return columns

    finally:
        session.close()
