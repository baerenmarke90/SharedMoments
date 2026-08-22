# DQ MODULAR SUITE V1
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.exc import IntegrityError

from app.models import Base, SessionLocal, Setting, User, engine
from app.daily_questions import DailyQuestion, CoupleDailyQuestion, DailyQuestionAnswer, daily_questions_enabled, get_daily_question_history
from app.daily_questions_seed import CATEGORY_LABELS


DEFAULT_TIMEZONE = 'Europe/Berlin'
MONTH_NAMES = {
    1: 'Januar', 2: 'Februar', 3: 'März', 4: 'April', 5: 'Mai', 6: 'Juni',
    7: 'Juli', 8: 'August', 9: 'September', 10: 'Oktober', 11: 'November', 12: 'Dezember',
}


class DailyQuestionMeta(Base):
    __tablename__ = 'dailyQuestionMeta'
    id = Column(Integer, primary_key=True, autoincrement=True)
    questionID = Column(Integer, ForeignKey('dailyQuestions.id'), nullable=False, unique=True, index=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    plannedDate = Column(Date, nullable=True, unique=True, index=True)
    dateCreated = Column(DateTime, server_default=func.now())


class DailyQuestionFavorite(Base):
    __tablename__ = 'dailyQuestionFavorites'
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignmentID = Column(Integer, ForeignKey('coupleDailyQuestions.id'), nullable=False, unique=True, index=True)
    markedByUser = Column(Integer, ForeignKey('users.id'), nullable=False)
    dateCreated = Column(DateTime, server_default=func.now())


class DailyQuestionSkip(Base):
    __tablename__ = 'dailyQuestionSkips'
    id = Column(Integer, primary_key=True, autoincrement=True)
    questionDate = Column(Date, nullable=False, index=True)
    questionID = Column(Integer, ForeignKey('dailyQuestions.id'), nullable=False)
    skippedByUser = Column(Integer, ForeignKey('users.id'), nullable=False)
    dateCreated = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint('questionDate', 'questionID', name='uq_daily_question_skip_date_question'),
    )


class DailyQuestionRevealNotice(Base):
    __tablename__ = 'dailyQuestionRevealNotices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignmentID = Column(Integer, ForeignKey('coupleDailyQuestions.id'), nullable=False, unique=True, index=True)
    sentAt = Column(DateTime, nullable=False, default=datetime.utcnow)


class DailyQuestionHeartLink(Base):
    __tablename__ = 'dailyQuestionHeartLinks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    assignmentID = Column(Integer, ForeignKey('coupleDailyQuestions.id'), nullable=False, unique=True, index=True)
    heartMomentID = Column(Integer, nullable=False, index=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=False)
    dateCreated = Column(DateTime, server_default=func.now())


def _bool_value(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() in {'true', '1', 'yes', 'on'}


def ensure_daily_questions_extras_schema():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            DailyQuestionMeta.__table__,
            DailyQuestionFavorite.__table__,
            DailyQuestionSkip.__table__,
            DailyQuestionRevealNotice.__table__,
            DailyQuestionHeartLink.__table__,
        ],
    )
    session = SessionLocal()
    try:
        defaults = {
            'daily_questions_timezone': DEFAULT_TIMEZONE,
            'daily_questions_reveal_notifications_enabled': 'True',
        }
        for name, value in defaults.items():
            setting = session.query(Setting).filter(Setting.name == name).first()
            if setting is None:
                session.add(Setting(name=name, value=value))
        session.commit()
    finally:
        session.close()


def daily_questions_template_context():
    try:
        session = SessionLocal()
        try:
            edition = session.query(Setting).filter(Setting.name == 'sm_edition').first()
            couples = edition is None or edition.value == 'couples'
        finally:
            session.close()
        return {'daily_questions_nav_enabled': bool(couples and daily_questions_enabled())}
    except Exception:
        return {'daily_questions_nav_enabled': False}


def get_timezone_name():
    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.name == 'daily_questions_timezone').first()
        value = str(setting.value or '').strip() if setting else ''
        return value or DEFAULT_TIMEZONE
    finally:
        session.close()


def set_timezone_name(timezone_name):
    timezone_name = str(timezone_name or '').strip()
    if not timezone_name:
        raise ValueError('Bitte gib eine Zeitzone an.')
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError('Unbekannte Zeitzone. Beispiel: Europe/Berlin') from exc
    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.name == 'daily_questions_timezone').first()
        if setting is None:
            session.add(Setting(name='daily_questions_timezone', value=timezone_name))
        else:
            setting.value = timezone_name
        session.commit()
    finally:
        session.close()


def current_question_date():
    try:
        timezone = ZoneInfo(get_timezone_name())
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(timezone).date()


def _couple_users(session):
    users = session.query(User).filter(User.id != 1).order_by(User.id.asc()).limit(2).all()
    if len(users) != 2:
        raise ValueError('Für die Frage des Tages werden genau zwei Partner benötigt.')
    return users


def _assert_couple_user(session, user_id):
    users = _couple_users(session)
    if user_id not in {user.id for user in users}:
        raise PermissionError('Dieser Benutzer gehört nicht zum aktiven Paar.')
    return users


def choose_question_for_day(session, question_day):
    skipped_ids = {
        row[0]
        for row in session.query(DailyQuestionSkip.questionID).filter(DailyQuestionSkip.questionDate == question_day).all()
    }
    scheduled = (
        session.query(DailyQuestion)
        .join(DailyQuestionMeta, DailyQuestionMeta.questionID == DailyQuestion.id)
        .filter(DailyQuestionMeta.plannedDate == question_day, DailyQuestion.active.is_(True))
        .order_by(DailyQuestion.id.asc())
        .first()
    )
    if scheduled and scheduled.id not in skipped_ids:
        return scheduled

    future_planned_ids = {
        row[0]
        for row in session.query(DailyQuestionMeta.questionID).filter(DailyQuestionMeta.plannedDate > question_day).all()
    }
    excluded_ids = future_planned_ids | skipped_ids
    query = session.query(DailyQuestion).filter(DailyQuestion.active.is_(True)).order_by(DailyQuestion.sortIndex.asc(), DailyQuestion.id.asc())
    if excluded_ids:
        query = query.filter(~DailyQuestion.id.in_(excluded_ids))
    candidates = query.all()
    if not candidates:
        raise RuntimeError('Der Fragenpool ist leer.')

    used_ids = {row[0] for row in session.query(CoupleDailyQuestion.questionID).all()}
    available = [question for question in candidates if question.id not in used_ids]
    if not available:
        available = candidates
    offset = (question_day.toordinal() * 37 + len(used_ids) * 17) % len(available)
    return available[offset]


def _favorite_map(session, assignment_ids):
    if not assignment_ids:
        return {}
    return {row.assignmentID: row for row in session.query(DailyQuestionFavorite).filter(DailyQuestionFavorite.assignmentID.in_(assignment_ids)).all()}


def _heart_link_map(session, assignment_ids):
    if not assignment_ids:
        return {}
    return {row.assignmentID: row for row in session.query(DailyQuestionHeartLink).filter(DailyQuestionHeartLink.assignmentID.in_(assignment_ids)).all()}


def get_archive_view(user_id, status='all', search_query='', category='all', year=None, month=None):
    requested_status = str(status or 'all').strip().lower()
    if requested_status not in {'all', 'answered', 'open', 'favorites'}:
        requested_status = 'all'
    core_status = requested_status if requested_status in {'all', 'answered', 'open'} else 'all'
    history = get_daily_question_history(user_id, core_status)
    search_query = str(search_query or '').strip()
    category = str(category or 'all').strip()
    if category != 'all' and category not in CATEGORY_LABELS:
        category = 'all'
    try:
        selected_year = int(year) if year not in (None, '') else None
    except (TypeError, ValueError):
        selected_year = None
    try:
        selected_month = int(month) if month not in (None, '') else None
    except (TypeError, ValueError):
        selected_month = None
    if selected_month is not None and not 1 <= selected_month <= 12:
        selected_month = None

    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        assignment_ids = [item['id'] for item in history['items']]
        favorites = _favorite_map(session, assignment_ids)
        heart_links = _heart_link_map(session, assignment_ids)
        needle = search_query.casefold()
        filtered = []
        for original in history['items']:
            item = dict(original)
            favorite = favorites.get(item['id'])
            heart_link = heart_links.get(item['id'])
            item['favorite'] = favorite is not None
            item['heart_moment_id'] = heart_link.heartMomentID if heart_link else None
            if requested_status == 'favorites' and not item['favorite']:
                continue
            if category != 'all' and item['category'] != category:
                continue
            if selected_year is not None and item['question_date'].year != selected_year:
                continue
            if selected_month is not None and item['question_date'].month != selected_month:
                continue
            if needle:
                haystack = [item['question']]
                if item['revealed']:
                    haystack.extend(answer.get('answer', '') for answer in item.get('answers', []))
                    haystack.extend(answer.get('first_name', '') for answer in item.get('answers', []))
                if not any(needle in str(value or '').casefold() for value in haystack):
                    continue
            filtered.append(item)
        history.update({
            'items': filtered,
            'selected_status': requested_status,
            'search_query': search_query,
            'selected_category': category,
            'selected_year': selected_year,
            'selected_month': selected_month,
            'categories': [{'key': key, 'label': label} for key, label in CATEGORY_LABELS.items()],
        })
        return history
    finally:
        session.close()


def _question_dict(question, meta, usage_count, user_by_id):
    creator = user_by_id.get(meta.createdByUser) if meta and meta.createdByUser else None
    return {
        'id': question.id,
        'seed_key': question.seedKey,
        'question': question.questionText,
        'category': question.category,
        'category_label': CATEGORY_LABELS.get(question.category, question.category),
        'active': bool(question.active),
        'sort_index': question.sortIndex,
        'custom': meta is not None,
        'planned_date': meta.plannedDate if meta else None,
        'created_by': meta.createdByUser if meta else None,
        'creator_name': creator.firstName if creator and creator.firstName else '',
        'usage_count': int(usage_count or 0),
        'used': bool(usage_count),
    }


def get_manage_data(user_id, can_admin=False, pool_query='', pool_category='all'):
    pool_query = str(pool_query or '').strip()
    pool_category = str(pool_category or 'all').strip()
    if pool_category != 'all' and pool_category not in CATEGORY_LABELS:
        pool_category = 'all'
    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        metas = {row.questionID: row for row in session.query(DailyQuestionMeta).all()}
        usage = {
            question_id: count
            for question_id, count in session.query(CoupleDailyQuestion.questionID, func.count(CoupleDailyQuestion.id)).group_by(CoupleDailyQuestion.questionID).all()
        }
        user_by_id = {user.id: user for user in session.query(User).all()}
        custom, builtins = [], []
        needle = pool_query.casefold()
        for question in session.query(DailyQuestion).order_by(DailyQuestion.sortIndex.asc(), DailyQuestion.id.asc()).all():
            meta = metas.get(question.id)
            item = _question_dict(question, meta, usage.get(question.id, 0), user_by_id)
            if meta is not None:
                custom.append(item)
                continue
            if not can_admin:
                continue
            if pool_category != 'all' and question.category != pool_category:
                continue
            if needle and needle not in question.questionText.casefold():
                continue
            builtins.append(item)
        custom.sort(key=lambda item: (item['planned_date'] is None, item['planned_date'] or date.max, item['id']))
        return {
            'custom_questions': custom,
            'builtin_questions': builtins,
            'categories': [{'key': key, 'label': label} for key, label in CATEGORY_LABELS.items()],
            'pool_query': pool_query,
            'pool_category': pool_category,
            'timezone_name': get_timezone_name(),
            'min_schedule_date': (current_question_date() + timedelta(days=1)).isoformat(),
        }
    finally:
        session.close()


def _normalize_question_text(value):
    value = str(value or '').strip()
    if len(value) < 5:
        raise ValueError('Die Frage ist zu kurz.')
    if len(value) > 500:
        raise ValueError('Die Frage darf hoechstens 500 Zeichen lang sein.')
    return value


def _normalize_category(value):
    value = str(value or '').strip()
    if value not in CATEGORY_LABELS:
        raise ValueError('Bitte wähle eine gültige Kategorie.')
    return value


def _planned_date_from_input(when, planned_date):
    when = str(when or 'pool').strip().lower()
    today = current_question_date()
    if when == 'pool':
        return None
    if when == 'tomorrow':
        return today + timedelta(days=1)
    if when == 'date':
        try:
            result = date.fromisoformat(str(planned_date or '').strip())
        except ValueError as exc:
            raise ValueError('Bitte wähle ein gültiges Datum.') from exc
        if result <= today:
            raise ValueError('Geplante Fragen muessen in der Zukunft liegen.')
        return result
    raise ValueError('Ungueltige Planung.')


def create_custom_question(user_id, question_text, category, when='pool', planned_date=None):
    question_text = _normalize_question_text(question_text)
    category = _normalize_category(category)
    planned = _planned_date_from_input(when, planned_date)
    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        if planned is not None:
            if session.query(DailyQuestionMeta).filter(DailyQuestionMeta.plannedDate == planned).first():
                raise ValueError('Für dieses Datum ist bereits eine eigene Frage geplant.')
            if session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.questionDate == planned).first():
                raise ValueError('Für dieses Datum wurde bereits eine Tagesfrage festgelegt.')
        max_sort = session.query(func.max(DailyQuestion.sortIndex)).scalar() or 0
        question = DailyQuestion(
            seedKey='custom-' + uuid.uuid4().hex,
            questionText=question_text,
            category=category,
            sortIndex=int(max_sort) + 1,
            active=True,
        )
        session.add(question)
        session.flush()
        session.add(DailyQuestionMeta(questionID=question.id, createdByUser=user_id, plannedDate=planned))
        session.commit()
        return question.id
    except IntegrityError as exc:
        session.rollback()
        raise ValueError('Für dieses Datum ist bereits eine eigene Frage geplant.') from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_managed_question(user_id, question_id, can_admin=False, question_text=None, category=None, active=None, when=None, planned_date=None):
    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        question = session.query(DailyQuestion).filter(DailyQuestion.id == question_id).first()
        if not question:
            raise ValueError('Die Frage wurde nicht gefunden.')
        meta = session.query(DailyQuestionMeta).filter(DailyQuestionMeta.questionID == question.id).first()
        is_custom = meta is not None
        if not is_custom and not can_admin:
            raise PermissionError('Standardfragen können nur von einem Admin verwaltet werden.')
        usage_count = session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.questionID == question.id).count()
        new_text = _normalize_question_text(question_text) if question_text not in (None, '') else question.questionText
        new_category = _normalize_category(category) if category not in (None, '') else question.category
        new_planned = meta.plannedDate if meta else None
        if is_custom and when is not None:
            new_planned = _planned_date_from_input(when, planned_date)
        changed_history_fields = new_text != question.questionText or new_category != question.category or (is_custom and new_planned != meta.plannedDate)
        if usage_count and changed_history_fields:
            raise ValueError('Diese Frage wurde bereits verwendet. Text, Kategorie und Planung bleiben unverändert.')
        if is_custom and new_planned is not None:
            conflict = session.query(DailyQuestionMeta).filter(DailyQuestionMeta.plannedDate == new_planned, DailyQuestionMeta.questionID != question.id).first()
            if conflict:
                raise ValueError('Für dieses Datum ist bereits eine eigene Frage geplant.')
        question.questionText = new_text
        question.category = new_category
        if active is not None:
            question.active = bool(active)
        if is_custom:
            meta.plannedDate = new_planned
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ValueError('Für dieses Datum ist bereits eine eigene Frage geplant.') from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def skip_today_question(user_id, assignment_id):
    today = current_question_date()
    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        assignment = session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.id == assignment_id).first()
        if not assignment or assignment.questionDate != today or assignment.revealedAt is not None:
            raise ValueError('Diese Frage kann heute nicht mehr gewechselt werden.')
        answer_count = session.query(DailyQuestionAnswer).filter(DailyQuestionAnswer.coupleQuestionID == assignment.id).count()
        if answer_count:
            raise ValueError('Diese Frage kann heute nicht mehr gewechselt werden.')
        if not session.query(DailyQuestionSkip).filter(DailyQuestionSkip.questionDate == today, DailyQuestionSkip.questionID == assignment.questionID).first():
            session.add(DailyQuestionSkip(questionDate=today, questionID=assignment.questionID, skippedByUser=user_id))
            session.flush()
        selected = choose_question_for_day(session, today)
        if selected.id == assignment.questionID:
            raise RuntimeError('Es ist keine andere Frage verfuegbar.')
        assignment.questionID = selected.id
        assignment.revealedAt = None
        session.commit()
        return assignment.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def toggle_favorite(user_id, assignment_id):
    session = SessionLocal()
    try:
        _assert_couple_user(session, user_id)
        assignment = session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.id == assignment_id).first()
        if not assignment or assignment.revealedAt is None:
            raise ValueError('Nur gemeinsam beantwortete Fragen können gemerkt werden.')
        favorite = session.query(DailyQuestionFavorite).filter(DailyQuestionFavorite.assignmentID == assignment.id).first()
        if favorite:
            session.delete(favorite)
            state = False
        else:
            session.add(DailyQuestionFavorite(assignmentID=assignment.id, markedByUser=user_id))
            state = True
        session.commit()
        return state
    finally:
        session.close()


def _reveal_notifications_enabled(session):
    setting = session.query(Setting).filter(Setting.name == 'daily_questions_reveal_notifications_enabled').first()
    return _bool_value(setting.value if setting else None, default=True)


def notify_reveal_if_needed(assignment_id):
    session = SessionLocal()
    user_ids = []
    try:
        assignment = session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.id == assignment_id).first()
        if not assignment or assignment.revealedAt is None or not _reveal_notifications_enabled(session):
            return False
        if session.query(DailyQuestionRevealNotice).filter(DailyQuestionRevealNotice.assignmentID == assignment.id).first():
            return False
        users = _couple_users(session)
        user_ids = [user.id for user in users]
        session.add(DailyQuestionRevealNotice(assignmentID=assignment.id, sentAt=datetime.utcnow()))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    finally:
        session.close()
    from app.notifications import send_notification
    for user_id in user_ids:
        try:
            send_notification(
                user_id,
                'Eure Antworten sind da',
                'Schaut euch an, was ihr beide geschrieben habt.',
                channels='all',
                url=f'/questions#question-{assignment_id}',
            )
        except Exception:
            pass
    return True


def get_flashback(user_id):
    today = current_question_date()
    try:
        flashback_date = today.replace(year=today.year - 1)
    except ValueError:
        return None
    session = SessionLocal()
    try:
        users = _assert_couple_user(session, user_id)
        assignment = session.query(CoupleDailyQuestion).filter(
            CoupleDailyQuestion.questionDate == flashback_date,
            CoupleDailyQuestion.revealedAt.isnot(None),
        ).first()
        if not assignment:
            return None
        question = session.query(DailyQuestion).filter(DailyQuestion.id == assignment.questionID).first()
        if not question:
            return None
        answers = session.query(DailyQuestionAnswer).filter(DailyQuestionAnswer.coupleQuestionID == assignment.id).all()
        answer_by_user = {answer.userID: answer for answer in answers}
        serialized = []
        for user in users:
            answer = answer_by_user.get(user.id)
            if not answer:
                return None
            serialized.append({
                'first_name': user.firstName or '',
                'profile_picture': user.profilePicture or 'profile-placeholder.jpg',
                'answer': answer.answer,
            })
        return {
            'assignment_id': assignment.id,
            'date': assignment.questionDate.isoformat(),
            'question': question.questionText,
            'category': question.category,
            'category_label': CATEGORY_LABELS.get(question.category, question.category),
            'answers': serialized,
        }
    finally:
        session.close()


def convert_question_to_heart_moment(user_id, assignment_id):
    session = SessionLocal()
    try:
        users = _assert_couple_user(session, user_id)
        existing = session.query(DailyQuestionHeartLink).filter(DailyQuestionHeartLink.assignmentID == assignment_id).first()
        if existing:
            return existing.heartMomentID, False
        assignment = session.query(CoupleDailyQuestion).filter(CoupleDailyQuestion.id == assignment_id).first()
        if not assignment or assignment.revealedAt is None:
            raise ValueError('Die Frage muss zuerst gemeinsam beantwortet sein.')
        question = session.query(DailyQuestion).filter(DailyQuestion.id == assignment.questionID).first()
        answers = session.query(DailyQuestionAnswer).filter(DailyQuestionAnswer.coupleQuestionID == assignment.id).all()
        answer_by_user = {answer.userID: answer for answer in answers}
        lines = [f'Frage des Tages - {assignment.questionDate.strftime("%d.%m.%Y")}', '', question.questionText if question else 'Gemeinsame Frage', '']
        for user in users:
            answer = answer_by_user.get(user.id)
            if not answer:
                raise ValueError('Die Frage ist noch nicht vollstaendig beantwortet.')
            lines.append(f'{user.firstName or "Partner"}: {answer.answer}')
        description = '\n'.join(lines)
        moment_date = assignment.questionDate
    finally:
        session.close()

    from app.heart_moments import create_heart_moment, delete_heart_moment
    heart = create_heart_moment(user_id=user_id, description=description, feeling='grateful', moment_date=moment_date, visibility='shared')
    heart_id = int(heart['id'])
    session = SessionLocal()
    try:
        existing = session.query(DailyQuestionHeartLink).filter(DailyQuestionHeartLink.assignmentID == assignment_id).first()
        if existing:
            try:
                delete_heart_moment(heart_id, user_id)
            except Exception:
                pass
            return existing.heartMomentID, False
        session.add(DailyQuestionHeartLink(assignmentID=assignment_id, heartMomentID=heart_id, createdByUser=user_id))
        session.commit()
        return heart_id, True
    except IntegrityError:
        session.rollback()
        try:
            delete_heart_moment(heart_id, user_id)
        except Exception:
            pass
        existing = session.query(DailyQuestionHeartLink).filter(DailyQuestionHeartLink.assignmentID == assignment_id).first()
        if existing:
            return existing.heartMomentID, False
        raise
    finally:
        session.close()


def get_daily_question_recap_stats(selected_year):
    selected_year = int(selected_year)
    result = {'enabled': daily_questions_enabled(), 'answered': 0, 'by_month': {}, 'latest_by_month': {}, 'available_years': []}
    if not result['enabled']:
        return result
    session = SessionLocal()
    try:
        start, end = date(selected_year, 1, 1), date(selected_year + 1, 1, 1)
        assignments = session.query(CoupleDailyQuestion).filter(
            CoupleDailyQuestion.questionDate >= start,
            CoupleDailyQuestion.questionDate < end,
            CoupleDailyQuestion.revealedAt.isnot(None),
        ).order_by(CoupleDailyQuestion.questionDate.asc()).all()
        for assignment in assignments:
            month = assignment.questionDate.month
            result['by_month'][month] = result['by_month'].get(month, 0) + 1
            result['latest_by_month'][month] = assignment.questionDate
        year_rows = session.query(CoupleDailyQuestion.questionDate).filter(CoupleDailyQuestion.revealedAt.isnot(None)).all()
        result['available_years'] = sorted({row[0].year for row in year_rows if row and row[0]}, reverse=True)
        result['answered'] = len(assignments)
        return result
    finally:
        session.close()


def _default_month_stats(entries):
    stats = {'memories': 0, 'hearts': 0, 'milestones': 0, 'chapters': 0, 'places': 0, 'bucket': 0, 'plans': 0, 'questions': 0}
    type_to_key = {'memory': 'memories', 'heart': 'hearts', 'milestone': 'milestones', 'chapter': 'chapters', 'bucket': 'bucket', 'plan': 'plans'}
    place_ids = set()
    for entry in entries:
        key = type_to_key.get(entry.get('type'))
        if key:
            stats[key] += 1
        for place in entry.get('places') or []:
            if place.get('id') is not None:
                place_ids.add(place['id'])
    stats['places'] = len(place_ids)
    return stats


def _month_places(entries):
    result, seen = [], set()
    for entry in entries:
        for place in entry.get('places') or []:
            key = place.get('id', place.get('name'))
            if key in seen:
                continue
            seen.add(key)
            result.append(place)
    return result


def _month_covers(entries):
    result, seen = [], set()
    for entry in entries:
        url = entry.get('image_url')
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({'url': url, 'href': entry.get('href') or '#', 'title': entry.get('title') or 'Moment'})
        if len(result) >= 5:
            break
    return result


def enrich_month_groups_with_daily_questions(month_groups, selected_year):
    recap = get_daily_question_recap_stats(selected_year)
    groups = [dict(group) for group in (month_groups or [])]
    by_month = {int(group.get('month')): group for group in groups if group.get('month')}
    for group in groups:
        entries = list(group.get('entries') or [])
        all_entries = list(group.get('all_entries') or entries)
        group['entries'] = entries
        group['all_entries'] = all_entries
        group.setdefault('cover_images', _month_covers(all_entries))
        group.setdefault('places', _month_places(all_entries))
        defaults = _default_month_stats(all_entries)
        group.setdefault('stats', defaults)
        for key, value in defaults.items():
            group['stats'].setdefault(key, value)
        group['stats'].setdefault('questions', 0)
        group['highlight_total'] = int(group.get('total') or 0)

    for month, count in recap['by_month'].items():
        group = by_month.get(month)
        if group is None:
            group = {
                'month': month, 'label': MONTH_NAMES[month], 'entries': [], 'all_entries': [], 'total': 0,
                'cover_images': [], 'places': [], 'stats': _default_month_stats([]), 'highlight_total': 0,
            }
            groups.append(group)
            by_month[month] = group
        group['stats']['questions'] = int(count)
        latest = recap['latest_by_month'].get(month)
        question_entry = {
            'type': 'question', 'type_label': 'Gemeinsame Fragen', 'icon': 'local_florist',
            'id': f'questions-{selected_year}-{month}',
            'title': f'{count} gemeinsame Frage beantwortet' if count == 1 else f'{count} gemeinsame Fragen beantwortet',
            'text': 'Eure Antworten sind in Unsere Fragen gespeichert.',
            'event_date': datetime.combine(latest, datetime.min.time()) if latest else datetime(selected_year, month, 1),
            'date_label': latest.strftime('%d.%m.%Y') if latest else '',
            'image_url': None,
            'href': f'/questions?status=answered&year={selected_year}&month={month}',
            'places': [],
        }
        existing_highlights = [
            entry
            for entry in group.get('entries', [])
            if entry.get('type') != 'question'
        ]
        # Keep the year highlight list compact: at most four rows including
        # the monthly Daily-Questions summary.
        group['entries'] = existing_highlights[:3] + [question_entry]
        group['all_entries'] = [
            entry
            for entry in group.get('all_entries', [])
            if entry.get('type') != 'question'
        ] + [question_entry]
        group['highlight_total'] = int(group.get('total') or 0) + 1
    groups.sort(key=lambda group: int(group.get('month') or 0))
    return groups, recap
