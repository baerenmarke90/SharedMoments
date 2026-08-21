#!/usr/bin/env python3

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from sqlalchemy import inspect

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


def main():
    session = SessionLocal()

    try:
        bind = session.get_bind()

        HeartMoment.__table__.create(
            bind=bind,
            checkfirst=True,
        )

        inspector = inspect(bind)
        tables = inspector.get_table_names()

        if HeartMoment.__tablename__ not in tables:
            raise RuntimeError(
                f'Table {HeartMoment.__tablename__} was not created'
            )

        columns = {
            column['name']
            for column in inspector.get_columns(HeartMoment.__tablename__)
        }

        missing_columns = EXPECTED_COLUMNS - columns

        if missing_columns:
            raise RuntimeError(
                'Heart Moments schema is incomplete. Missing columns: '
                + ', '.join(sorted(missing_columns))
            )

        print('Heart Moments schema OK')
        print(f'Table: {HeartMoment.__tablename__}')
        print('Columns:')

        for column in sorted(columns):
            print(f'  - {column}')

    finally:
        session.close()


if __name__ == '__main__':
    main()
