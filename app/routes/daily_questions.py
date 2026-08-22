from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from app.daily_questions import (
    CATEGORY_LABELS,
    create_custom_question,
    create_heart_moment_from_question,
    daily_questions_enabled,
    get_daily_question_history,
    get_daily_question_memory,
    get_daily_question_state,
    save_daily_question_answer,
    set_daily_question_favorite,
    skip_daily_question,
)
from app.db_queries import (
    get_all_list_types,
    get_setting_by_name,
    get_user_by_id,
    get_user_setting,
)
from app.logger import log
from app.routes.auth import jwt_required


daily_questions_bp = Blueprint('daily_questions', __name__)


def _couples_only():
    setting = get_setting_by_name('sm_edition')
    return bool(setting and setting.value == 'couples')


@daily_questions_bp.before_request
def _daily_questions_feature_gate():
    if daily_questions_enabled():
        return None

    if request.path.startswith('/api/'):
        return jsonify({
            'status': 'disabled',
            'feature_disabled': True,
            'message': 'Frage des Tages ist durch den Admin deaktiviert.',
        }), 404
    return redirect(url_for('pages.home'))


def _api_error(message, status=400):
    return jsonify({
        'status': 'error',
        'message': str(message),
    }), status


def _archive_redirect(
    assignment_id=None,
    *,
    status=None,
    category=None,
    search_query=None,
    error=None,
    message=None,
):
    params = {}
    if status:
        params['status'] = status
    if category and category != 'all':
        params['category'] = category
    if search_query:
        params['q'] = search_query
    if error:
        params['error'] = error
    if message:
        params['message'] = message
    if assignment_id:
        params['_anchor'] = f'question-{assignment_id}'
    return redirect(url_for('daily_questions.questions', **params))


@daily_questions_bp.route('/api/v2/daily-question', methods=['GET'])
@jwt_required
def daily_question_state():
    if not _couples_only():
        return _api_error('Nur in der Couples-Edition verfügbar.', 403)
    try:
        state = get_daily_question_state(g.user_id)
        return jsonify({'status': 'success', 'data': state})
    except (ValueError, PermissionError) as exc:
        return _api_error(exc, 400)
    except Exception as exc:
        log('error', f'Daily question state failed: {exc}')
        return _api_error(
            'Die Frage des Tages konnte nicht geladen werden.',
            500,
        )


@daily_questions_bp.route('/api/v2/daily-question/memory', methods=['GET'])
@jwt_required
def daily_question_memory():
    if not _couples_only():
        return _api_error('Nur in der Couples-Edition verfügbar.', 403)
    try:
        memory = get_daily_question_memory(g.user_id)
        return jsonify({
            'status': 'success',
            'data': memory,
        })
    except (ValueError, PermissionError) as exc:
        return _api_error(exc, 400)
    except Exception as exc:
        log('error', f'Daily question memory failed: {exc}')
        return _api_error(
            'Der Fragen-Rückblick konnte nicht geladen werden.',
            500,
        )


@daily_questions_bp.route('/api/v2/daily-question/answer', methods=['POST'])
@jwt_required
def daily_question_answer():
    if not _couples_only():
        return _api_error('Nur in der Couples-Edition verfügbar.', 403)

    payload = request.get_json(silent=True) or {}
    answer = payload.get('answer', '')
    assignment_id = payload.get('assignment_id')
    try:
        if assignment_id is not None:
            assignment_id = int(assignment_id)
        state = save_daily_question_answer(
            g.user_id,
            answer,
            assignment_id=assignment_id,
        )
        return jsonify({'status': 'success', 'data': state})
    except (TypeError, ValueError, PermissionError) as exc:
        return _api_error(exc, 400)
    except Exception as exc:
        log('error', f'Daily question answer failed: {exc}')
        return _api_error('Die Antwort konnte nicht gespeichert werden.', 500)


@daily_questions_bp.route('/api/v2/daily-question/skip', methods=['POST'])
@jwt_required
def daily_question_skip():
    if not _couples_only():
        return _api_error('Nur in der Couples-Edition verfügbar.', 403)

    payload = request.get_json(silent=True) or {}
    assignment_id = payload.get('assignment_id')
    try:
        if assignment_id is not None:
            assignment_id = int(assignment_id)
        state = skip_daily_question(
            g.user_id,
            assignment_id=assignment_id,
        )
        return jsonify({
            'status': 'success',
            'message': 'Es wurde eine neue Frage ausgewählt.',
            'data': state,
        })
    except (TypeError, ValueError, PermissionError) as exc:
        return _api_error(exc, 400)
    except Exception as exc:
        log('error', f'Daily question skip failed: {exc}')
        return _api_error('Die Frage konnte nicht übersprungen werden.', 500)


@daily_questions_bp.route('/questions')
@jwt_required
def questions():
    if not _couples_only():
        return redirect(url_for('pages.home'))

    selected_status = request.args.get('status', 'all')
    selected_category = request.args.get('category', 'all')
    search_query = request.args.get('q', '')

    try:
        history = get_daily_question_history(
            g.user_id,
            selected_status,
            selected_category,
            search_query,
        )
        return render_template(
            'pages/questions.html',
            title=get_setting_by_name('title'),
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            sm_edition='couples',
            page_title='Unsere Fragen',
            questions=history['items'],
            question_stats=history['stats'],
            selected_status=history['selected_status'],
            selected_category=history['selected_category'],
            search_query=history['search_query'],
            question_categories=history['categories'],
            category_labels=CATEGORY_LABELS,
        )
    except Exception as exc:
        log('error', f'Daily question archive failed: {exc}')
        return (
            'An error occurred while rendering the questions page. '
            'Please check the server logs for details.',
            500,
        )


@daily_questions_bp.route(
    '/questions/<int:assignment_id>/answer',
    methods=['POST'],
)
@jwt_required
def answer_question_page(assignment_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))

    answer = request.form.get('answer', '')
    status = request.form.get('status', 'all')
    category = request.form.get('category', 'all')
    search_query = request.form.get('q', '')

    try:
        save_daily_question_answer(
            g.user_id,
            answer,
            assignment_id=assignment_id,
        )
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error=str(exc),
        )
    except Exception as exc:
        log('error', f'Daily question archive answer failed: {exc}')
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error='Die Antwort konnte nicht gespeichert werden.',
        )


@daily_questions_bp.route(
    '/questions/<int:assignment_id>/skip',
    methods=['POST'],
)
@jwt_required
def skip_question_page(assignment_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))

    status = request.form.get('status', 'all')
    category = request.form.get('category', 'all')
    search_query = request.form.get('q', '')

    try:
        skip_daily_question(g.user_id, assignment_id)
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            message='Neue Frage ausgewählt.',
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error=str(exc),
        )
    except Exception as exc:
        log('error', f'Daily question page skip failed: {exc}')
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error='Die Frage konnte nicht übersprungen werden.',
        )


@daily_questions_bp.route(
    '/questions/<int:assignment_id>/favorite',
    methods=['POST'],
)
@jwt_required
def favorite_question_page(assignment_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))

    status = request.form.get('status', 'all')
    category = request.form.get('category', 'all')
    search_query = request.form.get('q', '')
    desired = request.form.get('favorite')
    favorite = None
    if desired in {'true', 'false'}:
        favorite = desired == 'true'

    try:
        set_daily_question_favorite(
            g.user_id,
            assignment_id,
            favorite=favorite,
        )
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error=str(exc),
        )


@daily_questions_bp.route(
    '/questions/<int:assignment_id>/heart-moment',
    methods=['POST'],
)
@jwt_required
def question_to_heart_moment_page(assignment_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))

    status = request.form.get('status', 'all')
    category = request.form.get('category', 'all')
    search_query = request.form.get('q', '')

    try:
        result = create_heart_moment_from_question(
            g.user_id,
            assignment_id,
        )
        message = (
            'Als Herzmoment gespeichert.'
            if result.get('created')
            else 'Diese Frage ist bereits als Herzmoment gespeichert.'
        )
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            message=message,
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error=str(exc),
        )
    except Exception as exc:
        log('error', f'Daily question to Heart Moment failed: {exc}')
        return _archive_redirect(
            assignment_id,
            status=status,
            category=category,
            search_query=search_query,
            error='Der Herzmoment konnte nicht erstellt werden.',
        )


@daily_questions_bp.route('/questions/custom', methods=['POST'])
@jwt_required
def create_custom_question_page():
    if not _couples_only():
        return redirect(url_for('pages.home'))

    question_text = request.form.get('question', '')
    category = request.form.get('question_category', '')
    schedule_mode = request.form.get('schedule_mode', 'random')
    scheduled_date = request.form.get('scheduled_date', '')
    status = request.form.get('status', 'all')
    category_filter = request.form.get('category_filter', 'all')
    search_query = request.form.get('q', '')
    try:
        created = create_custom_question(
            g.user_id,
            question_text,
            category,
            schedule_mode=schedule_mode,
            scheduled_date=scheduled_date,
        )
        if created.get('scheduled_date'):
            message = (
                'Eure eigene Frage wurde hinzugefügt und für '
                + created['scheduled_date']
                + ' eingeplant.'
            )
        else:
            message = 'Eure eigene Frage wurde dem gemeinsamen Pool hinzugefügt.'
        return _archive_redirect(
            status=status,
            category=category_filter,
            search_query=search_query,
            message=message,
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(
            status=status,
            category=category_filter,
            search_query=search_query,
            error=str(exc),
        )
    except Exception as exc:
        log('error', f'Creating custom Daily Question failed: {exc}')
        return _archive_redirect(
            status=status,
            category=category_filter,
            search_query=search_query,
            error='Die eigene Frage konnte nicht gespeichert werden.',
        )
