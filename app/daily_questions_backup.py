# DQ MODULAR SUITE V1
from datetime import date, datetime

from app.models import SessionLocal, User
from app.daily_questions import DailyQuestion, CoupleDailyQuestion, DailyQuestionAnswer, ensure_daily_questions_schema
from app.daily_questions_extras import (
    DailyQuestionMeta,
    DailyQuestionFavorite,
    DailyQuestionSkip,
    DailyQuestionRevealNotice,
    DailyQuestionHeartLink,
    ensure_daily_questions_extras_schema,
)


def _iso(value):
    return value.isoformat() if value is not None else None


def _parse_date(value):
    return date.fromisoformat(str(value)) if value else None


def _parse_datetime(value):
    return datetime.fromisoformat(str(value)) if value else None


def export_daily_questions_data():
    ensure_daily_questions_extras_schema()
    session = SessionLocal()
    try:
        users = {user.id: user for user in session.query(User).all()}
        questions = session.query(DailyQuestion).all()
        question_by_id = {question.id: question for question in questions}
        metas = {meta.questionID: meta for meta in session.query(DailyQuestionMeta).all()}
        assignments = session.query(CoupleDailyQuestion).all()
        assignment_by_id = {assignment.id: assignment for assignment in assignments}
        favorites = {favorite.assignmentID: favorite for favorite in session.query(DailyQuestionFavorite).all()}
        notices = {notice.assignmentID: notice for notice in session.query(DailyQuestionRevealNotice).all()}

        result = {'version': 1, 'questions': [], 'assignments': [], 'answers': [], 'skips': []}
        for question in questions:
            meta = metas.get(question.id)
            creator = users.get(meta.createdByUser) if meta and meta.createdByUser else None
            result['questions'].append({
                'seedKey': question.seedKey,
                'questionText': question.questionText,
                'category': question.category,
                'sortIndex': question.sortIndex,
                'active': bool(question.active),
                'custom': meta is not None,
                'createdByEmail': creator.email if creator else None,
                'plannedDate': _iso(meta.plannedDate) if meta else None,
            })

        for assignment in assignments:
            question = question_by_id.get(assignment.questionID)
            if not question:
                continue
            favorite = favorites.get(assignment.id)
            notice = notices.get(assignment.id)
            favorite_user = users.get(favorite.markedByUser) if favorite else None
            result['assignments'].append({
                'questionDate': _iso(assignment.questionDate),
                'questionSeedKey': question.seedKey,
                'revealedAt': _iso(assignment.revealedAt),
                'favorite': favorite is not None,
                'favoriteByEmail': favorite_user.email if favorite_user else None,
                'revealNoticeSentAt': _iso(notice.sentAt) if notice else None,
            })

        for answer in session.query(DailyQuestionAnswer).all():
            assignment = assignment_by_id.get(answer.coupleQuestionID)
            user = users.get(answer.userID)
            if not assignment or not user:
                continue
            result['answers'].append({
                'questionDate': _iso(assignment.questionDate),
                'userEmail': user.email,
                'answer': answer.answer,
                'submittedAt': _iso(answer.submittedAt),
                'dateModified': _iso(answer.dateModified),
            })

        for skip in session.query(DailyQuestionSkip).all():
            question = question_by_id.get(skip.questionID)
            user = users.get(skip.skippedByUser)
            if not question or not user:
                continue
            result['skips'].append({
                'questionDate': _iso(skip.questionDate),
                'questionSeedKey': question.seedKey,
                'userEmail': user.email,
                'dateCreated': _iso(skip.dateCreated),
            })
        return result
    finally:
        session.close()


def import_daily_questions_data(feature_data, user_email_to_id):
    if not feature_data:
        # Old backups without Daily Questions must not destroy current DQ data.
        return {'questions': 0, 'assignments': 0, 'answers': 0}

    ensure_daily_questions_extras_schema()
    session = SessionLocal()
    try:
        session.query(DailyQuestionHeartLink).delete(synchronize_session=False)
        session.query(DailyQuestionRevealNotice).delete(synchronize_session=False)
        session.query(DailyQuestionFavorite).delete(synchronize_session=False)
        session.query(DailyQuestionSkip).delete(synchronize_session=False)
        session.query(DailyQuestionAnswer).delete(synchronize_session=False)
        session.query(CoupleDailyQuestion).delete(synchronize_session=False)
        session.query(DailyQuestionMeta).delete(synchronize_session=False)
        session.query(DailyQuestion).delete(synchronize_session=False)
        session.flush()

        question_by_seed = {}
        question_count = 0
        for payload in feature_data.get('questions', []):
            seed_key = str(payload.get('seedKey') or '').strip()
            question_text = str(payload.get('questionText') or '').strip()
            category = str(payload.get('category') or '').strip()
            if not seed_key or not question_text or not category:
                continue
            question = DailyQuestion(
                seedKey=seed_key,
                questionText=question_text,
                category=category,
                sortIndex=int(payload.get('sortIndex') or 0),
                active=bool(payload.get('active', True)),
            )
            session.add(question)
            session.flush()
            question_by_seed[seed_key] = question
            question_count += 1
            if payload.get('custom'):
                session.add(DailyQuestionMeta(
                    questionID=question.id,
                    createdByUser=user_email_to_id.get(payload.get('createdByEmail')),
                    plannedDate=_parse_date(payload.get('plannedDate')),
                ))

        assignment_by_date = {}
        assignment_count = 0
        for payload in feature_data.get('assignments', []):
            question = question_by_seed.get(payload.get('questionSeedKey'))
            question_date = _parse_date(payload.get('questionDate'))
            if not question or not question_date:
                continue
            assignment = CoupleDailyQuestion(
                questionID=question.id,
                questionDate=question_date,
                revealedAt=_parse_datetime(payload.get('revealedAt')),
            )
            session.add(assignment)
            session.flush()
            assignment_by_date[question_date.isoformat()] = assignment
            assignment_count += 1
            if payload.get('favorite'):
                marker_id = user_email_to_id.get(payload.get('favoriteByEmail'))
                if marker_id:
                    session.add(DailyQuestionFavorite(assignmentID=assignment.id, markedByUser=marker_id))
            notice_time = _parse_datetime(payload.get('revealNoticeSentAt'))
            if notice_time:
                session.add(DailyQuestionRevealNotice(assignmentID=assignment.id, sentAt=notice_time))

        answer_count = 0
        for payload in feature_data.get('answers', []):
            assignment = assignment_by_date.get(str(payload.get('questionDate') or ''))
            user_id = user_email_to_id.get(payload.get('userEmail'))
            answer_text = str(payload.get('answer') or '').strip()
            if not assignment or not user_id or not answer_text:
                continue
            submitted = _parse_datetime(payload.get('submittedAt')) or datetime.utcnow()
            modified = _parse_datetime(payload.get('dateModified')) or submitted
            session.add(DailyQuestionAnswer(
                coupleQuestionID=assignment.id,
                userID=user_id,
                answer=answer_text,
                submittedAt=submitted,
                dateModified=modified,
            ))
            answer_count += 1

        for payload in feature_data.get('skips', []):
            question = question_by_seed.get(payload.get('questionSeedKey'))
            user_id = user_email_to_id.get(payload.get('userEmail'))
            question_date = _parse_date(payload.get('questionDate'))
            if not question or not user_id or not question_date:
                continue
            session.add(DailyQuestionSkip(
                questionDate=question_date,
                questionID=question.id,
                skippedByUser=user_id,
                dateCreated=_parse_datetime(payload.get('dateCreated')) or datetime.utcnow(),
            ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Re-add bundled questions missing from a partial or older DQ backup.
    # The patched seeder preserves imported text/category/active state.
    ensure_daily_questions_schema()
    return {'questions': question_count, 'assignments': assignment_count, 'answers': answer_count}
