from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import uuid

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
    inspect,
    text as sql_text,
)
from sqlalchemy.exc import IntegrityError

from app.daily_questions_seed import BUILTIN_QUESTIONS, CATEGORY_LABELS
from app.models import Base, SessionLocal, Setting, User, engine


DEFAULT_TIMEZONE = 'Europe/Berlin'
MAX_QUESTION_LENGTH = 500
MAX_ANSWER_LENGTH = 500
VALID_STATUS_FILTERS = {'all', 'answered', 'open', 'favorites'}
VALID_SOURCES = {'builtin', 'custom', 'admin'}


class DailyQuestion(Base):
    __tablename__ = 'dailyQuestions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    seedKey = Column(String(64), unique=True, nullable=False, index=True)
    questionText = Column(Text, nullable=False)
    category = Column(String(40), nullable=False, index=True)
    sortIndex = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True, index=True)
    source = Column(String(20), nullable=False, default='builtin', index=True)
    createdByUserID = Column(Integer, nullable=True, index=True)
    adminEdited = Column(Boolean, nullable=False, default=False)
    dateCreated = Column(DateTime, server_default=func.now())
    dateModified = Column(DateTime, nullable=True)


class CoupleDailyQuestion(Base):
    __tablename__ = 'coupleDailyQuestions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    questionID = Column(Integer, ForeignKey('dailyQuestions.id'), nullable=False, index=True)
    questionDate = Column(Date, nullable=False, unique=True, index=True)
    revealedAt = Column(DateTime, nullable=True)
    favorite = Column(Boolean, nullable=False, default=False, index=True)
    heartMomentID = Column(Integer, nullable=True)
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


class DailyQuestionSkip(Base):
    __tablename__ = 'dailyQuestionSkips'

    id = Column(Integer, primary_key=True, autoincrement=True)
    questionDate = Column(Date, nullable=False, index=True)
    questionID = Column(Integer, ForeignKey('dailyQuestions.id'), nullable=False, index=True)
    skippedByUserID = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    dateCreated = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            'questionDate',
            'questionID',
            name='uq_daily_question_skip_date_question',
        ),
    )


def _ensure_column(table_name, column_name, ddl):
    inspector = inspect(engine)
    existing = {column['name'] for column in inspector.get_columns(table_name)}
    if column_name in existing:
        return

    with engine.begin() as connection:
        connection.execute(sql_text(
            f'ALTER TABLE "{table_name}" ADD COLUMN {ddl}'
        ))


def ensure_daily_questions_schema():
    """Create/upgrade Daily Questions storage and seed the built-in pool."""
    Base.metadata.create_all(
        bind=engine,
        tables=[
            DailyQuestion.__table__,
            CoupleDailyQuestion.__table__,
            DailyQuestionAnswer.__table__,
            DailyQuestionSkip.__table__,
        ],
    )

    # create_all() does not alter existing SQLite tables. Keep upgrades
    # idempotent so existing installations need no manual migration.
    _ensure_column(
        'dailyQuestions',
        'source',
        "source VARCHAR(20) NOT NULL DEFAULT 'builtin'",
    )
    _ensure_column(
        'dailyQuestions',
        'createdByUserID',
        'createdByUserID INTEGER',
    )
    _ensure_column(
        'dailyQuestions',
        'adminEdited',
        'adminEdited BOOLEAN NOT NULL DEFAULT 0',
    )
    _ensure_column(
        'dailyQuestions',
        'dateModified',
        'dateModified DATETIME',
    )
    _ensure_column(
        'coupleDailyQuestions',
        'favorite',
        'favorite BOOLEAN NOT NULL DEFAULT 0',
    )
    _ensure_column(
        'coupleDailyQuestions',
        'heartMomentID',
        'heartMomentID INTEGER',
    )

    session = SessionLocal()
    try:
        existing = {
            row.seedKey: row
            for row in session.query(DailyQuestion).all()
        }

        for index, (category, question_text) in enumerate(
            BUILTIN_QUESTIONS,
            start=1,
        ):
            seed_key = f'builtin-{index:03d}'
            row = existing.get(seed_key)
            if row is None:
                session.add(DailyQuestion(
                    seedKey=seed_key,
                    questionText=question_text,
                    category=category,
                    sortIndex=index,
                    active=True,
                    source='builtin',
                    adminEdited=False,
                ))
                continue

            row.source = row.source or 'builtin'
            row.sortIndex = index
            # Admin edits are authoritative. Unedited built-ins can still
            # receive wording/category improvements in later releases.
            if not bool(row.adminEdited):
                row.questionText = question_text
                row.category = category
            if row.active is None:
                row.active = True

        _ensure_setting(session, 'daily_questions_enabled', 'True')
        _ensure_setting(session, 'daily_questions_timezone', DEFAULT_TIMEZONE)
        session.commit()
    finally:
        session.close()


def _ensure_setting(session, name, default_value):
    row = session.query(Setting).filter(Setting.name == name).first()
    if row is None:
        session.add(Setting(name=name, value=default_value))
        return
    if row.value is None or str(row.value).strip() == '':
        row.value = default_value


def daily_questions_enabled():
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


def get_daily_questions_timezone_name():
    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.name == 'daily_questions_timezone')
            .first()
        )
        value = str(setting.value).strip() if setting and setting.value else DEFAULT_TIMEZONE
    finally:
        session.close()

    try:
        ZoneInfo(value)
        return value
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE


def set_daily_questions_timezone(timezone_name):
    timezone_name = str(timezone_name or '').strip()
    if not timezone_name:
        raise ValueError('Bitte gib eine Zeitzone an.')

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            'Unbekannte Zeitzone. Bitte einen IANA-Namen wie Europe/Berlin verwenden.'
        ) from exc

    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.name == 'daily_questions_timezone')
            .first()
        )
        if setting is None:
            setting = Setting(
                name='daily_questions_timezone',
                value=timezone_name,
            )
            session.add(setting)
        else:
            setting.value = timezone_name
        session.commit()
    finally:
        session.close()

    return timezone_name


def current_question_date():
    timezone_name = get_daily_questions_timezone_name()
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(timezone).date()


def _get_couple_users(session):
    users = (
        session.query(User)
        .filter(User.id != 1)
        .order_by(User.id.asc())
        .limit(2)
        .all()
    )
    if len(users) != 2:
        raise ValueError(
            'Für die Frage des Tages werden genau zwei Partner benötigt.'
        )
    return users


def _assert_couple_user(users, user_id):
    if user_id not in {user.id for user in users}:
        raise PermissionError(
            'Dieser Benutzer gehört nicht zum aktiven Paar.'
        )


def _select_question(session, question_day, exclude_ids=None):
    exclude_ids = set(exclude_ids or [])

    active_questions = (
        session.query(DailyQuestion)
        .filter(DailyQuestion.active.is_(True))
        .order_by(DailyQuestion.sortIndex.asc(), DailyQuestion.id.asc())
        .all()
    )
    if not active_questions:
        raise RuntimeError('Der Fragenpool ist leer.')

    used_ids = {
        row[0]
        for row in session.query(CoupleDailyQuestion.questionID).all()
    }
    # A skipped question should not come back immediately. Treat it as used
    # until the pool has completed a cycle.
    used_ids.update({
        row[0]
        for row in session.query(DailyQuestionSkip.questionID).all()
    })

    available = [
        question
        for question in active_questions
        if question.id not in used_ids
        and question.id not in exclude_ids
    ]

    if not available:
        available = [
            question
            for question in active_questions
            if question.id not in exclude_ids
        ]

    if not available:
        raise RuntimeError('Es steht keine weitere Frage zur Verfügung.')

    offset = (
        question_day.toordinal() * 37
        + len(used_ids) * 17
        + len(exclude_ids) * 11
    ) % len(available)
    return available[offset]


def _get_or_create_assignment(session, question_day=None):
    question_day = question_day or current_question_date()

    assignment = (
        session.query(CoupleDailyQuestion)
        .filter(CoupleDailyQuestion.questionDate == question_day)
        .first()
    )
    if assignment:
        return assignment

    selected = _select_question(session, question_day)
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
        session.rollback()
        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.questionDate == question_day)
            .first()
        )
        if assignment:
            return assignment
        raise


def _answers_for_assignment(session, assignment_id, user_ids):
    return (
        session.query(DailyQuestionAnswer)
        .filter(
            DailyQuestionAnswer.coupleQuestionID == assignment_id,
            DailyQuestionAnswer.userID.in_(user_ids),
        )
        .all()
    )


def _reveal_if_complete(session, assignment, couple_user_ids):
    answers = _answers_for_assignment(
        session,
        assignment.id,
        couple_user_ids,
    )
    answered_user_ids = {answer.userID for answer in answers}
    newly_revealed = False

    if (
        set(couple_user_ids).issubset(answered_user_ids)
        and assignment.revealedAt is None
    ):
        assignment.revealedAt = datetime.utcnow()
        newly_revealed = True
        session.commit()
        session.refresh(assignment)

    return answers, newly_revealed


def _question_for_assignment(session, assignment):
    question = (
        session.query(DailyQuestion)
        .filter(DailyQuestion.id == assignment.questionID)
        .first()
    )
    if not question:
        raise RuntimeError('Die zugeordnete Frage wurde nicht gefunden.')
    return question


def _serialize_state(session, assignment, user_id):
    users = _get_couple_users(session)
    _assert_couple_user(users, user_id)
    user_ids = [user.id for user in users]
    answers, _ = _reveal_if_complete(
        session,
        assignment,
        user_ids,
    )
    question = _question_for_assignment(session, assignment)

    answer_by_user = {answer.userID: answer for answer in answers}
    own_answer = answer_by_user.get(user_id)
    revealed = assignment.revealedAt is not None
    partner = next(user for user in users if user.id != user_id)
    status = (
        'revealed'
        if revealed
        else ('waiting' if own_answer else 'unanswered')
    )

    data = {
        'id': assignment.id,
        'question_date': assignment.questionDate.isoformat(),
        'question': question.questionText,
        'question_id': question.id,
        'category': question.category,
        'category_label': CATEGORY_LABELS.get(
            question.category,
            question.category,
        ),
        'source': question.source or 'builtin',
        'status': status,
        'revealed': revealed,
        'revealed_at': (
            assignment.revealedAt.isoformat()
            if assignment.revealedAt
            else None
        ),
        'own_answered': own_answer is not None,
        'own_answer': own_answer.answer if own_answer else '',
        'can_edit': not revealed,
        'can_skip': (
            not revealed
            and not answers
            and assignment.questionDate == current_question_date()
        ),
        'favorite': bool(assignment.favorite),
        'heart_moment_id': assignment.heartMomentID,
        'partner': {
            'id': partner.id,
            'first_name': partner.firstName or '',
            'profile_picture': (
                partner.profilePicture
                or 'profile-placeholder.jpg'
            ),
        },
        # Before reveal the partner answer is deliberately absent.
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
                'profile_picture': (
                    user.profilePicture
                    or 'profile-placeholder.jpg'
                ),
                'answer': answer.answer,
                'is_current_user': uid == user_id,
            })

    return data


def get_daily_question_state(user_id, question_day=None):
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        assignment = _get_or_create_assignment(
            session,
            question_day or current_question_date(),
        )
        return _serialize_state(session, assignment, user_id)
    finally:
        session.close()


def _notify_reveal(recipient_user_id, assignment_id):
    try:
        from app.notifications import send_notification

        send_notification(
            recipient_user_id,
            '🌸 Eure Antworten sind da',
            'Schaut euch an, was ihr beide geschrieben habt.',
            channels='all',
            url=f'/questions?status=answered#question-{assignment_id}',
        )
    except Exception:
        # Notifications are a bonus. Never fail an answer because a channel
        # is unavailable or misconfigured.
        pass


def save_daily_question_answer(
    user_id,
    answer_text,
    assignment_id=None,
):
    answer_text = str(answer_text or '').strip()
    if not answer_text:
        raise ValueError('Bitte gib eine Antwort ein.')
    if len(answer_text) > MAX_ANSWER_LENGTH:
        raise ValueError(
            f'Deine Antwort darf höchstens {MAX_ANSWER_LENGTH} Zeichen lang sein.'
        )

    notify_user_id = None
    result = None
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        user_ids = [user.id for user in users]

        if assignment_id is None:
            assignment = _get_or_create_assignment(
                session,
                current_question_date(),
            )
        else:
            assignment = (
                session.query(CoupleDailyQuestion)
                .filter(CoupleDailyQuestion.id == assignment_id)
                .first()
            )
            if not assignment:
                raise ValueError('Die Frage wurde nicht gefunden.')

        _reveal_if_complete(session, assignment, user_ids)
        if assignment.revealedAt is not None:
            raise ValueError(
                'Diese Antworten wurden bereits enthüllt und können nicht mehr geändert werden.'
            )

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
        was_revealed = assignment.revealedAt is not None
        result = _serialize_state(session, assignment, user_id)

        if not was_revealed and result.get('revealed'):
            partner = next(user for user in users if user.id != user_id)
            notify_user_id = partner.id
    finally:
        session.close()

    if notify_user_id is not None:
        _notify_reveal(notify_user_id, result['id'])

    return result


def skip_daily_question(user_id, assignment_id=None):
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        user_ids = [user.id for user in users]

        if assignment_id is None:
            assignment = _get_or_create_assignment(
                session,
                current_question_date(),
            )
        else:
            assignment = (
                session.query(CoupleDailyQuestion)
                .filter(CoupleDailyQuestion.id == assignment_id)
                .first()
            )

        if not assignment:
            raise ValueError('Die Frage wurde nicht gefunden.')
        if assignment.questionDate != current_question_date():
            raise ValueError('Nur die heutige Frage kann übersprungen werden.')
        if assignment.revealedAt is not None:
            raise ValueError('Eine beantwortete Frage kann nicht übersprungen werden.')

        answers = _answers_for_assignment(
            session,
            assignment.id,
            user_ids,
        )
        if answers:
            raise ValueError(
                'Die Frage kann nicht mehr übersprungen werden, nachdem jemand geantwortet hat.'
            )

        previous_question_id = assignment.questionID
        existing_skip = (
            session.query(DailyQuestionSkip)
            .filter(
                DailyQuestionSkip.questionDate == assignment.questionDate,
                DailyQuestionSkip.questionID == previous_question_id,
            )
            .first()
        )
        if existing_skip is None:
            session.add(DailyQuestionSkip(
                questionDate=assignment.questionDate,
                questionID=previous_question_id,
                skippedByUserID=user_id,
            ))
            session.flush()

        replacement = _select_question(
            session,
            assignment.questionDate,
            exclude_ids={previous_question_id},
        )
        assignment.questionID = replacement.id
        assignment.revealedAt = None
        assignment.favorite = False
        assignment.heartMomentID = None
        session.commit()
        session.refresh(assignment)
        return _serialize_state(session, assignment, user_id)
    finally:
        session.close()


def create_custom_question(
    user_id,
    question_text,
    category,
    schedule_mode='random',
    scheduled_date=None,
):
    question_text = str(question_text or '').strip()
    category = str(category or '').strip()
    schedule_mode = str(schedule_mode or 'random').strip().lower()

    if not question_text:
        raise ValueError('Bitte gib eine Frage ein.')
    if len(question_text) > MAX_QUESTION_LENGTH:
        raise ValueError(
            f'Die Frage darf höchstens {MAX_QUESTION_LENGTH} Zeichen lang sein.'
        )
    if category not in CATEGORY_LABELS:
        raise ValueError('Bitte wähle eine gültige Kategorie.')
    if schedule_mode not in {'random', 'tomorrow', 'date'}:
        raise ValueError('Ungültige Auswahl für die Verwendung der Frage.')

    target_day = None
    today = current_question_date()
    if schedule_mode == 'tomorrow':
        target_day = date.fromordinal(today.toordinal() + 1)
    elif schedule_mode == 'date':
        if isinstance(scheduled_date, date):
            target_day = scheduled_date
        else:
            try:
                target_day = date.fromisoformat(str(scheduled_date or ''))
            except ValueError as exc:
                raise ValueError('Bitte wähle ein gültiges Datum.') from exc
        if target_day <= today:
            raise ValueError('Das geplante Datum muss in der Zukunft liegen.')

    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)

        if target_day is not None:
            occupied = (
                session.query(CoupleDailyQuestion)
                .filter(CoupleDailyQuestion.questionDate == target_day)
                .first()
            )
            if occupied:
                raise ValueError(
                    'Für dieses Datum ist bereits eine gemeinsame Frage eingeplant.'
                )

        max_sort = session.query(func.max(DailyQuestion.sortIndex)).scalar() or 0
        question = DailyQuestion(
            seedKey=f'custom-{uuid.uuid4().hex}',
            questionText=question_text,
            category=category,
            sortIndex=int(max_sort) + 1,
            active=True,
            source='custom',
            createdByUserID=user_id,
            adminEdited=True,
            dateModified=datetime.utcnow(),
        )
        session.add(question)
        session.flush()

        if target_day is not None:
            session.add(CoupleDailyQuestion(
                questionID=question.id,
                questionDate=target_day,
            ))

        session.commit()
        session.refresh(question)
        result = _serialize_question_admin(session, question)
        result['scheduled_date'] = (
            target_day.isoformat() if target_day is not None else None
        )
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def set_daily_question_favorite(user_id, assignment_id, favorite=None):
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.id == int(assignment_id))
            .first()
        )
        if not assignment:
            raise ValueError('Die Frage wurde nicht gefunden.')
        if assignment.revealedAt is None:
            raise ValueError(
                'Eine Frage kann erst nach dem gemeinsamen Reveal favorisiert werden.'
            )

        assignment.favorite = (
            not bool(assignment.favorite)
            if favorite is None
            else bool(favorite)
        )
        session.commit()
        session.refresh(assignment)
        return _serialize_state(session, assignment, user_id)
    finally:
        session.close()


def create_heart_moment_from_question(user_id, assignment_id):
    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        user_ids = [user.id for user in users]
        user_by_id = {user.id: user for user in users}

        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.id == int(assignment_id))
            .first()
        )
        if not assignment:
            raise ValueError('Die Frage wurde nicht gefunden.')
        if assignment.revealedAt is None:
            raise ValueError(
                'Die Frage kann erst nach dem gemeinsamen Reveal als Herzmoment gespeichert werden.'
            )

        if assignment.heartMomentID:
            try:
                from app.models import HeartMoment

                exists = (
                    session.query(HeartMoment)
                    .filter(HeartMoment.id == assignment.heartMomentID)
                    .first()
                )
                if exists:
                    return {
                        'created': False,
                        'heart_moment_id': assignment.heartMomentID,
                    }
            except Exception:
                pass
            assignment.heartMomentID = None
            session.commit()

        question = _question_for_assignment(session, assignment)
        answers = _answers_for_assignment(
            session,
            assignment.id,
            user_ids,
        )
        answer_by_user = {answer.userID: answer for answer in answers}

        lines = [
            f'Frage des Tages: {question.questionText}',
            '',
        ]
        for uid in user_ids:
            answer = answer_by_user.get(uid)
            if not answer:
                continue
            user = user_by_id[uid]
            lines.append(f'{user.firstName or "Partner"}: {answer.answer}')

        description = '\n'.join(lines).strip()
        moment_date = assignment.questionDate
    finally:
        session.close()

    from app.heart_moments import create_heart_moment

    moment = create_heart_moment(
        user_id=user_id,
        description=description,
        feeling='grateful',
        moment_date=moment_date,
        visibility='shared',
    )

    session = SessionLocal()
    try:
        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.id == int(assignment_id))
            .first()
        )
        if assignment:
            assignment.heartMomentID = moment['id']
            session.commit()
    finally:
        session.close()

    return {
        'created': True,
        'heart_moment_id': moment['id'],
    }


def _matches_search(item, search_query):
    search_query = str(search_query or '').strip().casefold()
    if not search_query:
        return True

    haystack = [
        item.get('question', ''),
        item.get('category_label', ''),
        item.get('own_answer', ''),
    ]
    for answer in item.get('answers', []):
        haystack.append(answer.get('answer', ''))
        haystack.append(answer.get('first_name', ''))

    return search_query in ' '.join(haystack).casefold()


def get_daily_question_history(
    user_id,
    status_filter='all',
    category_filter='all',
    search_query='',
):
    if status_filter not in VALID_STATUS_FILTERS:
        status_filter = 'all'
    if category_filter != 'all' and category_filter not in CATEGORY_LABELS:
        category_filter = 'all'

    search_query = str(search_query or '').strip()[:120]

    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        user_ids = [user.id for user in users]
        user_by_id = {user.id: user for user in users}

        today = current_question_date()
        _get_or_create_assignment(session, today)

        assignments = (
            session.query(CoupleDailyQuestion)
            .order_by(
                CoupleDailyQuestion.questionDate.desc(),
                CoupleDailyQuestion.id.desc(),
            )
            .all()
        )
        question_ids = {assignment.questionID for assignment in assignments}
        questions = {
            question.id: question
            for question in (
                session.query(DailyQuestion)
                .filter(DailyQuestion.id.in_(question_ids))
                .all()
                if question_ids
                else []
            )
        }
        assignment_ids = [assignment.id for assignment in assignments]
        all_answers = (
            session.query(DailyQuestionAnswer)
            .filter(
                DailyQuestionAnswer.coupleQuestionID.in_(assignment_ids)
            )
            .all()
            if assignment_ids
            else []
        )
        answers_by_assignment = {}
        for answer in all_answers:
            answers_by_assignment.setdefault(
                answer.coupleQuestionID,
                {},
            )[answer.userID] = answer

        result = []
        revealed_count = 0
        favorite_count = 0

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
            if bool(assignment.favorite):
                favorite_count += 1

            if status_filter == 'answered' and not revealed:
                continue
            if status_filter == 'open' and revealed:
                continue
            if status_filter == 'favorites' and not bool(assignment.favorite):
                continue

            question = questions.get(assignment.questionID)
            if not question:
                continue
            if (
                category_filter != 'all'
                and question.category != category_filter
            ):
                continue

            mine = answer_map.get(user_id)
            item = {
                'id': assignment.id,
                'question_date': assignment.questionDate,
                'question': question.questionText,
                'question_id': question.id,
                'category': question.category,
                'category_label': CATEGORY_LABELS.get(
                    question.category,
                    question.category,
                ),
                'source': question.source or 'builtin',
                'revealed': revealed,
                'favorite': bool(assignment.favorite),
                'heart_moment_id': assignment.heartMomentID,
                'own_answer': mine.answer if mine else '',
                'can_edit': not revealed,
                'can_skip': (
                    not revealed
                    and not answer_map
                    and assignment.questionDate == today
                ),
                'answers': [],
                'is_today': assignment.questionDate == today,
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
                        'profile_picture': (
                            user.profilePicture
                            or 'profile-placeholder.jpg'
                        ),
                        'answer': answer.answer,
                        'is_current_user': uid == user_id,
                    })

            if _matches_search(item, search_query):
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
                'favorites': favorite_count,
            },
            'selected_status': status_filter,
            'selected_category': category_filter,
            'search_query': search_query,
            'categories': [
                {'key': key, 'label': label}
                for key, label in CATEGORY_LABELS.items()
            ],
        }
    finally:
        session.close()


def get_daily_question_memory(user_id, reference_date=None):
    today = reference_date or current_question_date()
    try:
        target = today.replace(year=today.year - 1)
    except ValueError:
        # 29 February -> 28 February in non-leap years.
        target = today.replace(year=today.year - 1, day=28)

    session = SessionLocal()
    try:
        users = _get_couple_users(session)
        _assert_couple_user(users, user_id)
        assignment = (
            session.query(CoupleDailyQuestion)
            .filter(
                CoupleDailyQuestion.questionDate == target,
                CoupleDailyQuestion.revealedAt.isnot(None),
            )
            .first()
        )
        if not assignment:
            return None

        data = _serialize_state(session, assignment, user_id)
        data['memory_date'] = target.isoformat()
        data['years_ago'] = 1
        return data
    finally:
        session.close()


def get_daily_question_recap_stats(selected_year):
    try:
        selected_year = int(selected_year)
    except (TypeError, ValueError):
        raise ValueError('Ungültiges Jahr für den Fragen-Rückblick.')

    if not daily_questions_enabled():
        return {
            'enabled': False,
            'answered': 0,
            'answers': 0,
            'by_month': {},
            'available_years': [],
        }

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

        ids = [assignment.id for assignment in revealed]
        answer_count = (
            session.query(DailyQuestionAnswer)
            .filter(DailyQuestionAnswer.coupleQuestionID.in_(ids))
            .count()
            if ids
            else 0
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


def _serialize_question_admin(session, question):
    usage_count = (
        session.query(CoupleDailyQuestion)
        .filter(CoupleDailyQuestion.questionID == question.id)
        .count()
    )
    creator = None
    if question.createdByUserID:
        creator = (
            session.query(User)
            .filter(User.id == question.createdByUserID)
            .first()
        )

    return {
        'id': question.id,
        'seed_key': question.seedKey,
        'question': question.questionText,
        'category': question.category,
        'category_label': CATEGORY_LABELS.get(
            question.category,
            question.category,
        ),
        'sort_index': question.sortIndex,
        'active': bool(question.active),
        'source': question.source or 'builtin',
        'admin_edited': bool(question.adminEdited),
        'created_by_user_id': question.createdByUserID,
        'created_by': (
            creator.firstName
            if creator and creator.firstName
            else None
        ),
        'usage_count': usage_count,
    }


def get_admin_question_catalog(search_query='', source_filter='all'):
    search_query = str(search_query or '').strip()[:120]
    source_filter = str(source_filter or 'all').strip().lower()
    if source_filter not in VALID_SOURCES | {'all'}:
        source_filter = 'all'

    session = SessionLocal()
    try:
        query = session.query(DailyQuestion)
        if source_filter != 'all':
            query = query.filter(DailyQuestion.source == source_filter)
        rows = query.order_by(
            DailyQuestion.sortIndex.asc(),
            DailyQuestion.id.asc(),
        ).all()

        items = []
        for row in rows:
            item = _serialize_question_admin(session, row)
            if search_query:
                haystack = (
                    item['question']
                    + ' '
                    + item['category_label']
                    + ' '
                    + item['source']
                ).casefold()
                if search_query.casefold() not in haystack:
                    continue
            items.append(item)

        return {
            'items': items,
            'categories': [
                {'key': key, 'label': label}
                for key, label in CATEGORY_LABELS.items()
            ],
            'timezone': get_daily_questions_timezone_name(),
            'counts': {
                'all': session.query(DailyQuestion).count(),
                'active': (
                    session.query(DailyQuestion)
                    .filter(DailyQuestion.active.is_(True))
                    .count()
                ),
                'custom': (
                    session.query(DailyQuestion)
                    .filter(DailyQuestion.source != 'builtin')
                    .count()
                ),
            },
        }
    finally:
        session.close()


def create_admin_question(question_text, category):
    question_text = str(question_text or '').strip()
    category = str(category or '').strip()
    if not question_text:
        raise ValueError('Bitte gib eine Frage ein.')
    if len(question_text) > MAX_QUESTION_LENGTH:
        raise ValueError(
            f'Die Frage darf höchstens {MAX_QUESTION_LENGTH} Zeichen lang sein.'
        )
    if category not in CATEGORY_LABELS:
        raise ValueError('Bitte wähle eine gültige Kategorie.')

    session = SessionLocal()
    try:
        max_sort = session.query(func.max(DailyQuestion.sortIndex)).scalar() or 0
        question = DailyQuestion(
            seedKey=f'admin-{uuid.uuid4().hex}',
            questionText=question_text,
            category=category,
            sortIndex=int(max_sort) + 1,
            active=True,
            source='admin',
            adminEdited=True,
            dateModified=datetime.utcnow(),
        )
        session.add(question)
        session.commit()
        session.refresh(question)
        return _serialize_question_admin(session, question)
    finally:
        session.close()


def update_admin_question(question_id, changes):
    changes = changes or {}
    session = SessionLocal()
    try:
        question = (
            session.query(DailyQuestion)
            .filter(DailyQuestion.id == int(question_id))
            .first()
        )
        if not question:
            raise ValueError('Die Frage wurde nicht gefunden.')

        if 'question' in changes:
            question_text = str(changes.get('question') or '').strip()
            if not question_text:
                raise ValueError('Bitte gib eine Frage ein.')
            if len(question_text) > MAX_QUESTION_LENGTH:
                raise ValueError(
                    f'Die Frage darf höchstens {MAX_QUESTION_LENGTH} Zeichen lang sein.'
                )
            question.questionText = question_text
            question.adminEdited = True

        if 'category' in changes:
            category = str(changes.get('category') or '').strip()
            if category not in CATEGORY_LABELS:
                raise ValueError('Bitte wähle eine gültige Kategorie.')
            question.category = category
            question.adminEdited = True

        if 'active' in changes:
            question.active = bool(changes.get('active'))

        question.dateModified = datetime.utcnow()
        session.commit()
        session.refresh(question)
        return _serialize_question_admin(session, question)
    finally:
        session.close()


def delete_admin_question(question_id):
    session = SessionLocal()
    try:
        question = (
            session.query(DailyQuestion)
            .filter(DailyQuestion.id == int(question_id))
            .first()
        )
        if not question:
            raise ValueError('Die Frage wurde nicht gefunden.')

        usage_count = (
            session.query(CoupleDailyQuestion)
            .filter(CoupleDailyQuestion.questionID == question.id)
            .count()
        )

        if question.source == 'builtin' or usage_count > 0:
            question.active = False
            question.dateModified = datetime.utcnow()
            session.commit()
            return {
                'deleted': False,
                'deactivated': True,
                'id': question.id,
            }

        session.delete(question)
        session.commit()
        return {
            'deleted': True,
            'deactivated': False,
            'id': int(question_id),
        }
    finally:
        session.close()
