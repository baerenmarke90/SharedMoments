#!/usr/bin/env python3

import os
import sys

ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

sys.path.insert(0, ROOT_DIR)

from app.heart_moments_schema import (
    ensure_heart_moments_schema,
)
from app.models import HeartMoment


def main():
    columns = ensure_heart_moments_schema()

    print('Heart Moments schema OK')
    print(f'Table: {HeartMoment.__tablename__}')
    print('Columns:')

    for column in sorted(columns):
        print(f'  - {column}')


if __name__ == '__main__':
    main()
