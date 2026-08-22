from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.exc import IntegrityError

from app.daily_questions_seed import BUILTIN_QUESTIONS, CATEGORY_LABELS
from app.models import Base, SessionLocal, Setting, User, engine


class DailyQuestion(Base):
    __tablename__ = 'dailyQuestions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    seedKey = Column(String(64), unique=True, nullable=False, index=True)
    questionText = Column(Text, nullable=False)
    category = Column(String(40), nullable=False, index=True)
    sortIndex = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True, index=True)
    dateCreated = Column(DateTime, server_default=func.now())


class CoupleDailyQuestion(Base):
    __tablename__ = 'coupleDailyQuestions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    questionID = Column(Integer, ForeignKey('dailyQuestions.id'), nullable=False, index=True)
    questionDate = Column(Date, nullable=False, unique=True, index=True)
    revealedAt = Column(DateTime, nullable=True)
    dateCreated = Column(DateTime, server_default=func.now())


class DailyQuestionAnswer(Base):
    __tablename__ = 'dailyQuestionAnswers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    coupleQuestionID = Column(
        Integer,
        ForeignKey('coupleDailyQuestions.id'),
        nullable=False,
        index=True,
    )
    userID = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    answer = Column(Text, nullable=False)
    submittedAt = Column(DateTime, nullable=False, default=datetime.utcnow)
    dateModified = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            'coupleQuestionID',
            'userID',
            name='uq_daily_question_answer_user',
        ),
    )


def ensure_daily_questions_schema():
    """Create the daily-question tables and idempotently seed the built-in pool."""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            DailyQuestion.__table__,
            CoupleDailyQuestion.__table__,
            DailyQuestionAnswer.__table__,
        ],
    )

    session = SessionLocal()
    try:
        existing = {
            row.seedKey: row
            for row in session.query(DailyQuestion).all()
        }

        for index, (category, text) in enumerate(BUILTIN_QUESTIONS, start=1):
            seed_key = f'builtin-{index:03d}'
            row = existing.get(seed_key)
            if row is None:
                session.add(DailyQuestion(
                    seedKey=seed_key,
                    questionText=text,
                    category=category,
                    sortIndex=index,
                    active=True,
                ))
            else:
                # This lets later releases improve wording without duplicating rows.
                row.questionText = text
                row.category = category
                row.sortIndex = index
                row.active = True

        feature_setting = (
            session.query(Setting)
            .filter(Setting.name == 'daily_questions_enabled')
            .first()
        )
        if feature_setting is None:
            session.add(Setting(
                name='daily_questions_enabled',
                value='True',
            ))

        session.commit()
    finally:
        session.close()


def daily_questions_enabled():
    """Return whether the global Daily Questions feature is enabled."""
    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.name == 'daily_questions_enabled')
            .first()
        )
        if setting is None or setting.value is None:
            return True
        return str(setting.value).strip().lower() in {
            'true', '1', 'yes', 'on'
        }
    finally:
        session.close()


def _get_couple_users(session):
    users = (
        session.query(User)
        .filter(User.id != 1)
        .order_by(User.id.asc())
        .limit(2)
        .all()
    )
    if len(users) != 2:
        raise ValueError('Für die Frage des Tages werden genau zwei Partner benötigt.')
    return users


def _assert_couple_user(users, user_id):
    if user_id not in {user.id for user in users}:
        raise PermissionError('Dieser Benutzer gehört nicht zum aktiven Paar.')


def _get_or_create_assignment(session, question_day=None):
    question_day = question_day or date.today()

    assignment = (
        session.query(CoupleDailyQuestion)
        .filter(CoupleDailyQuestion.questionDate == question_day)
        .first()
    )
    if assignment:
        return assignment

    active_questions = (
        session.query(DailyQuestion)
        .filter(DailyQuestion.active.is_(True))
        .order_by(DailyQuestion.sortIndex.asc(), DailyQuestion.id.asc())
        .all()
    )
    if not active_questions:
        raise RuntimeError('Der Fragenpool ist leer.')

    # Avoid repeats until the pool has been consumed once.
    used_ids = {
        row[0]
        for row in session.query(CoupleDailyQuestion.questionID).all()
    }
    available = [question for question in active_questions if question.id not in used_ids]
    if not available:
        available = active_questions

    # Deterministic but not simply sequential. The assignment is persisted, so
    # both users and all workers always see the exact same question.
    offset = (question_day.toordinal() * 37 + len(used_ids) * 17) % len(available)
    selected = available[offset]

    assignment = CoupleDailyQuestion(
        questionID=selected.id,
        questionDate=question_day,
    )
    session.add(assignment)

    try:
        session.commit()
        session.refresh(assignment)
        return assignment
    except IntegrityError:
        # Another worker may have created today's assignment simultaneously.
        session.rollback()
        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.questionDate == question_day)
            .first()
        )
        if assignment:
            return assignment
        raise


def _reveal_if_complete(session, assignment, couple_user_ids):
    answers = (
        session.query(DailyQuestionAnswer)
        .filter(
            DailyQuestionAnswer.coupleQuestionID == assignment.id,
            DailyQuestionAnswer.userID.in_(couple_user_ids),
        )
        .all()
    )

    answered_user_ids = {answer.userID for answer in answers}
    if set(couple_user_ids).issubset(answered_user_ids) and assignment.revealedAt is None:
        assignment.revealedAt = datetime.utcnow()
        session.commit()
        session.refresh(assignment)

    return answers


def _serialize_state(session, assignment, user_id):
    users = _get_couple_users(session)
    _assert_couple_user(users, user_id)
    user_ids = [user.id for user in users]

    answers = _reveal_if_complete(session, assignment, user_ids)
    question = (
        session.query(DailyQuestion)
        .filter(DailyQuestion.id == assignment.questionID)
        .first()
    )
    if not question:
        raise RuntimeError('Die zugeordnete Frage wurde nicht gefunden.')

    answer_by_user = {answer.userID: answer for answer in answers}
    own_answer = answer_by_user.get(user_id)
    revealed = assignment.revealedAt is not None

    partner = next(user for user in users if user.id != user_id)
    status = 'revealed' if revealed else ('waiting' if own_answer else 'unanswered')

    data = {
        'id': assignment.id,
        'question_date': assignment.questionDate.isoformat(),
        'question': question.questionText,
        'category': question.category,
        'category_label': CATEGORY_LABELS.get(question.category, question.category),
        'status': status,
        'revealed': revealed,
        'revealed_at': assignment.revealedAt.isoformat() if assignment.revealedAt else None,
        'own_answered': own_answer is not None,
        'own_answer': own_answer.answer if own_answer else '',
        'can_edit': not revealed,
        'partner': {
            'id': partner.id,
            'first_name': partner.firstName or '',
            'profile_picture': partner.profilePicture or 'profile-placeholder.jpg',
        },
        # Deliberately do not expose whether the partner already answered before
        # reveal. That keeps the "both answer independently" rule server-side.
        'answers': [],
    }

    if revealed:
        user_by_id = {user.id: user for user in users}
        for uid in user_ids:
            answer = answer_by_user.get(uid)
            if not answer:
                continue
            user = user_by_id[uid]
            data['answers'].append({
                'user_id': uid,
                'first_name': user.firstName or '',
                'profile_picture': user.profilePicture or 'profile-placeholder.jpg',
                'answer': answer.answer,
                'is_current_user': uid == user_id,
            })

    return data


def get_daily_question_state(user_id, question_day=None):
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        assignment = _get_or_create_assignment(session, question_day)
        return _serialize_state(session, assignment, user_id)
    finally:
        session.close()


def save_daily_question_answer(user_id, answer_text, assignment_id=None):
    answer_text = (answer_text or '').strip()
    if not answer_text:
        raise ValueError('Bitte gib eine Antwort ein.')
    if len(answer_text) > 500:
        raise ValueError('Deine Antwort darf höchstens 500 Zeichen lang sein.')

    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)

        if assignment_id is None:
            assignment = _get_or_create_assignment(session, date.today())
        else:
            assignment = (
                session.query(CoupleDailyQuestion)
                .filter(CoupleDailyQuestion.id == assignment_id)
                .first()
            )
            if not assignment:
                raise ValueError('Die Frage wurde nicht gefunden.')

        _reveal_if_complete(session, assignment, [user.id for user in users])
        if assignment.revealedAt is not None:
            raise ValueError('Diese Antworten wurden bereits enthüllt und können nicht mehr geändert werden.')

        existing = (
            session.query(DailyQuestionAnswer)
            .filter(
                DailyQuestionAnswer.coupleQuestionID == assignment.id,
                DailyQuestionAnswer.userID == user_id,
            )
            .first()
        )

        now = datetime.utcnow()
        if existing:
            existing.answer = answer_text
            existing.dateModified = now
        else:
            session.add(DailyQuestionAnswer(
                coupleQuestionID=assignment.id,
                userID=user_id,
                answer=answer_text,
                submittedAt=now,
                dateModified=now,
            ))

        session.commit()
        return _serialize_state(session, assignment, user_id)
    finally:
        session.close()



# ===== Daily Questions recap statistics v3 =====
def get_daily_question_recap_stats(selected_year):
    # Counts jointly revealed Daily Questions for yearly/monthly recaps.
    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        raise ValueError('Ungültiges Jahr für den Fragen-Rückblick.')

    if selected_year < 1900 or selected_year > 9998:
        raise ValueError('Ungültiges Jahr für den Fragen-Rückblick.')

    empty = {
        'enabled': False,
        'answered': 0,
        'answers': 0,
        'by_month': {},
        'available_years': [],
    }

    if not daily_questions_enabled():
        return empty

    start = date(selected_year, 1, 1)
    end = date(selected_year + 1, 1, 1)

    session = SessionLocal()
    try:
        revealed = (
            session.query(CoupleDailyQuestion)
            .filter(
                CoupleDailyQuestion.questionDate >= start,
                CoupleDailyQuestion.questionDate < end,
                CoupleDailyQuestion.revealedAt.isnot(None),
            )
            .order_by(CoupleDailyQuestion.questionDate.asc())
            .all()
        )

        by_month = {}
        for assignment in revealed:
            month_number = int(assignment.questionDate.month)
            by_month[month_number] = by_month.get(month_number, 0) + 1

        assignment_ids = [assignment.id for assignment in revealed]
        answer_count = (
            session.query(DailyQuestionAnswer)
            .filter(DailyQuestionAnswer.coupleQuestionID.in_(assignment_ids))
            .count()
            if assignment_ids else 0
        )

        year_rows = (
            session.query(CoupleDailyQuestion.questionDate)
            .filter(CoupleDailyQuestion.revealedAt.isnot(None))
            .all()
        )
        available_years = sorted(
            {
                row[0].year
                for row in year_rows
                if row and row[0] is not None
            },
            reverse=True,
        )

        return {
            'enabled': True,
            'answered': len(revealed),
            'answers': answer_count,
            'by_month': by_month,
            'available_years': available_years,
        }
    finally:
        session.close()


def get_daily_question_history(user_id, status_filter='all'):
    if status_filter not in {'all', 'answered', 'open'}:
        status_filter = 'all'

    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        user_ids = [user.id for user in users]
        user_by_id = {user.id: user for user in users}

        # Ensure today appears in the archive even before anyone has answered.
        _get_or_create_assignment(session, date.today())

        assignments = (
            session.query(CoupleDailyQuestion)
            .order_by(CoupleDailyQuestion.questionDate.desc(), CoupleDailyQuestion.id.desc())
            .all()
        )

        question_ids = {assignment.questionID for assignment in assignments}
        questions = {
            question.id: question
            for question in (
                session.query(DailyQuestion)
                .filter(DailyQuestion.id.in_(question_ids))
                .all()
                if question_ids else []
            )
        }

        assignment_ids = [assignment.id for assignment in assignments]
        all_answers = (
            session.query(DailyQuestionAnswer)
            .filter(DailyQuestionAnswer.coupleQuestionID.in_(assignment_ids))
            .all()
            if assignment_ids else []
        )
        answers_by_assignment = {}
        for answer in all_answers:
            answers_by_assignment.setdefault(answer.coupleQuestionID, {})[answer.userID] = answer

        result = []
        revealed_count = 0

        for assignment in assignments:
            answer_map = answers_by_assignment.get(assignment.id, {})
            if (
                assignment.revealedAt is None
                and set(user_ids).issubset(set(answer_map.keys()))
            ):
                assignment.revealedAt = datetime.utcnow()

            revealed = assignment.revealedAt is not None
            if revealed:
                revealed_count += 1

            if status_filter == 'answered' and not revealed:
                continue
            if status_filter == 'open' and revealed:
                continue

            question = questions.get(assignment.questionID)
            if not question:
                continue

            mine = answer_map.get(user_id)
            item = {
                'id': assignment.id,
                'question_date': assignment.questionDate,
                'question': question.questionText,
                'category': question.category,
                'category_label': CATEGORY_LABELS.get(question.category, question.category),
                'revealed': revealed,
                'own_answer': mine.answer if mine else '',
                'can_edit': not revealed,
                'answers': [],
                'is_today': assignment.questionDate == date.today(),
            }

            if revealed:
                for uid in user_ids:
                    answer = answer_map.get(uid)
                    if not answer:
                        continue
                    user = user_by_id[uid]
                    item['answers'].append({
                        'user_id': uid,
                        'first_name': user.firstName or '',
                        'profile_picture': user.profilePicture or 'profile-placeholder.jpg',
                        'answer': answer.answer,
                        'is_current_user': uid == user_id,
                    })

            result.append(item)

        session.commit()

        total_assignments = len(assignments)
        return {
            'items': result,
            'stats': {
                'pool_size': (
                    session.query(DailyQuestion)
                    .filter(DailyQuestion.active.is_(True))
                    .count()
                ),
                'total': total_assignments,
                'answered': revealed_count,
                'open': total_assignments - revealed_count,
            },
            'selected_status': status_filter,
        }
    finally:
        session.close()
