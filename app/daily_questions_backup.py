from datetime import date, datetime

from app.daily_questions import (
    CoupleDailyQuestion,
    DailyQuestion,
    DailyQuestionAnswer,
    DailyQuestionSkip,
    ensure_daily_questions_schema,
)
from app.models import SessionLocal, User


def _dt(value):
    return value.isoformat() if value else None


def export_daily_questions_data():
    ensure_daily_questions_schema()
    session = SessionLocal()
    try:
        users = session.query(User).all()
        user_email = {user.id: user.email for user in users}
        question_rows = (
            session.query(DailyQuestion)
            .order_by(DailyQuestion.sortIndex.asc(), DailyQuestion.id.asc())
            .all()
        )
        assignments = (
            session.query(CoupleDailyQuestion)
            .order_by(CoupleDailyQuestion.questionDate.asc())
            .all()
        )
        answers = session.query(DailyQuestionAnswer).all()
        skips = session.query(DailyQuestionSkip).all()

        question_key = {
            row.id: row.seedKey
            for row in question_rows
        }
        assignment_date = {
            row.id: row.questionDate.isoformat()
            for row in assignments
        }

        return {
            'schemaVersion': 1,
            'questions': [
                {
                    'seedKey': row.seedKey,
                    'questionText': row.questionText,
                    'category': row.category,
                    'sortIndex': row.sortIndex,
                    'active': bool(row.active),
                    'source': row.source or 'builtin',
                    'createdByEmail': user_email.get(row.createdByUserID),
                    'adminEdited': bool(row.adminEdited),
                    'dateCreated': _dt(row.dateCreated),
                    'dateModified': _dt(row.dateModified),
                }
                for row in question_rows
            ],
            'assignments': [
                {
                    'questionDate': row.questionDate.isoformat(),
                    'questionKey': question_key.get(row.questionID),
                    'revealedAt': _dt(row.revealedAt),
                    'favorite': bool(row.favorite),
                    # Heart Moments are not part of the upstream data export.
                    # Do not persist a dangling DB id across restores.
                    'savedAsHeartMoment': bool(row.heartMomentID),
                    'dateCreated': _dt(row.dateCreated),
                }
                for row in assignments
                if question_key.get(row.questionID)
            ],
            'answers': [
                {
                    'questionDate': assignment_date.get(row.coupleQuestionID),
                    'userEmail': user_email.get(row.userID),
                    'answer': row.answer,
                    'submittedAt': _dt(row.submittedAt),
                    'dateModified': _dt(row.dateModified),
                }
                for row in answers
                if assignment_date.get(row.coupleQuestionID)
                and user_email.get(row.userID)
            ],
            'skips': [
                {
                    'questionDate': row.questionDate.isoformat(),
                    'questionKey': question_key.get(row.questionID),
                    'userEmail': user_email.get(row.skippedByUserID),
                    'dateCreated': _dt(row.dateCreated),
                }
                for row in skips
                if question_key.get(row.questionID)
                and user_email.get(row.skippedByUserID)
            ],
        }
    finally:
        session.close()


def _parse_date(value):
    if not value:
        return None
    return date.fromisoformat(str(value))


def _parse_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def import_daily_questions_data(payload, user_email_to_id):
    """Restore Daily Questions from export data.

    This is a full restore: assignments/answers/skips and non-built-in pool
    entries are reset first. Built-ins remain as stable seed rows and are
    updated from the backup when present.
    """
    ensure_daily_questions_schema()
    payload = payload or {}
    user_email_to_id = user_email_to_id or {}

    session = SessionLocal()
    try:
        # Child tables first.
        session.query(DailyQuestionAnswer).delete(synchronize_session=False)
        session.query(DailyQuestionSkip).delete(synchronize_session=False)
        session.query(CoupleDailyQuestion).delete(synchronize_session=False)
        session.query(DailyQuestion).filter(
            DailyQuestion.source != 'builtin'
        ).delete(synchronize_session=False)
        # Keep the entire restore atomic. If any later insert fails, rollback
        # restores the previous Daily Questions data instead of leaving an
        # empty/partial feature database behind.
        session.flush()

        existing = {
            row.seedKey: row
            for row in session.query(DailyQuestion).all()
        }

        imported_questions = 0
        for data in payload.get('questions', []):
            seed_key = str(data.get('seedKey') or '').strip()
            question_text = str(data.get('questionText') or '').strip()
            category = str(data.get('category') or '').strip()
            if not seed_key or not question_text or not category:
                continue

            row = existing.get(seed_key)
            if row is None:
                row = DailyQuestion(seedKey=seed_key)
                session.add(row)
                existing[seed_key] = row

            row.questionText = question_text
            row.category = category
            row.sortIndex = int(data.get('sortIndex') or 0)
            row.active = bool(data.get('active', True))
            row.source = str(data.get('source') or 'custom')
            row.createdByUserID = user_email_to_id.get(
                data.get('createdByEmail')
            )
            row.adminEdited = bool(data.get('adminEdited', False))
            row.dateModified = _parse_datetime(data.get('dateModified'))
            if data.get('dateCreated'):
                row.dateCreated = _parse_datetime(data.get('dateCreated'))
            imported_questions += 1

        session.flush()
        key_to_id = {
            row.seedKey: row.id
            for row in session.query(DailyQuestion).all()
        }

        imported_assignments = 0
        date_to_assignment = {}
        for data in payload.get('assignments', []):
            question_date = _parse_date(data.get('questionDate'))
            question_id = key_to_id.get(data.get('questionKey'))
            if not question_date or not question_id:
                continue

            row = CoupleDailyQuestion(
                questionID=question_id,
                questionDate=question_date,
                revealedAt=_parse_datetime(data.get('revealedAt')),
                favorite=bool(data.get('favorite', False)),
                heartMomentID=None,
            )
            if data.get('dateCreated'):
                row.dateCreated = _parse_datetime(data.get('dateCreated'))
            session.add(row)
            session.flush()
            date_to_assignment[question_date.isoformat()] = row.id
            imported_assignments += 1

        imported_answers = 0
        for data in payload.get('answers', []):
            assignment_id = date_to_assignment.get(data.get('questionDate'))
            user_id = user_email_to_id.get(data.get('userEmail'))
            answer = str(data.get('answer') or '').strip()
            if not assignment_id or not user_id or not answer:
                continue

            row = DailyQuestionAnswer(
                coupleQuestionID=assignment_id,
                userID=user_id,
                answer=answer,
                submittedAt=(
                    _parse_datetime(data.get('submittedAt'))
                    or datetime.utcnow()
                ),
                dateModified=(
                    _parse_datetime(data.get('dateModified'))
                    or datetime.utcnow()
                ),
            )
            session.add(row)
            imported_answers += 1

        imported_skips = 0
        for data in payload.get('skips', []):
            question_date = _parse_date(data.get('questionDate'))
            question_id = key_to_id.get(data.get('questionKey'))
            user_id = user_email_to_id.get(data.get('userEmail'))
            if not question_date or not question_id or not user_id:
                continue

            row = DailyQuestionSkip(
                questionDate=question_date,
                questionID=question_id,
                skippedByUserID=user_id,
            )
            if data.get('dateCreated'):
                row.dateCreated = _parse_datetime(data.get('dateCreated'))
            session.add(row)
            imported_skips += 1

        session.commit()
        return {
            'questions': imported_questions,
            'assignments': imported_assignments,
            'answers': imported_answers,
            'skips': imported_skips,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
