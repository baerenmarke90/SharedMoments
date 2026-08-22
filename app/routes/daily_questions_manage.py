# DQ MODULAR SUITE V1
from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from app.daily_questions import daily_questions_enabled
from app.daily_questions_extras import (
    convert_question_to_heart_moment,
    create_custom_question,
    get_flashback,
    get_manage_data,
    set_timezone_name,
    skip_today_question,
    toggle_favorite,
    update_managed_question,
)
from app.db_queries import get_all_list_types, get_setting_by_name, get_user_by_id, get_user_setting
from app.logger import log
from app.permissions import has_permission
from app.routes.auth import jwt_required


daily_questions_manage_bp = Blueprint('daily_questions_manage', __name__)


def _couples_only():
    setting = get_setting_by_name('sm_edition')
    return bool(setting and setting.value == 'couples')


@daily_questions_manage_bp.before_request
def _feature_gate():
    if daily_questions_enabled():
        return None
    if request.path.startswith('/api/'):
        return jsonify({
            'status': 'disabled',
            'feature_disabled': True,
            'message': 'Frage des Tages ist durch den Admin deaktiviert.',
        }), 404
    return redirect(url_for('pages.home'))


def _archive_redirect(assignment_id, message=None, error=None):
    params = {'status': request.form.get('status', 'all')}
    for key in ('q', 'category', 'year', 'month'):
        value = request.form.get(key)
        if value not in (None, '', 'all'):
            params[key] = value
    if message:
        params['message'] = message
    if error:
        params['error'] = error
    params['_anchor'] = f'question-{assignment_id}'
    return redirect(url_for('daily_questions.questions', **params))


def _manage_redirect(message=None, error=None):
    params = {}
    for key in ('pool_q', 'pool_category'):
        value = request.form.get(key)
        if value not in (None, '', 'all'):
            params[key] = value
    if message:
        params['message'] = message
    if error:
        params['error'] = error
    return redirect(url_for('daily_questions_manage.manage_questions', **params))


@daily_questions_manage_bp.route('/questions/manage')
@jwt_required
def manage_questions():
    if not _couples_only():
        return redirect(url_for('pages.home'))
    can_admin = has_permission('Access Admin Panel')
    try:
        data = get_manage_data(
            g.user_id,
            can_admin=can_admin,
            pool_query=request.args.get('pool_q', ''),
            pool_category=request.args.get('pool_category', 'all'),
        )
        return render_template(
            'pages/questions-manage.html',
            title=get_setting_by_name('title'),
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            sm_edition='couples',
            page_title='Fragen verwalten',
            can_admin=can_admin,
            **data,
        )
    except Exception as exc:
        log('error', f'Daily Questions manage page failed: {exc}')
        return 'An error occurred while rendering the questions management page.', 500


@daily_questions_manage_bp.route('/questions/manage/create', methods=['POST'])
@jwt_required
def create_question():
    if not _couples_only():
        return redirect(url_for('pages.home'))
    try:
        create_custom_question(
            g.user_id,
            request.form.get('question'),
            request.form.get('category'),
            when=request.form.get('when', 'pool'),
            planned_date=request.form.get('planned_date'),
        )
        return _manage_redirect(message='Eigene Frage wurde hinzugefuegt.')
    except (ValueError, PermissionError) as exc:
        return _manage_redirect(error=str(exc))
    except Exception as exc:
        log('error', f'Creating custom Daily Question failed: {exc}')
        return _manage_redirect(error='Die Frage konnte nicht hinzugefuegt werden.')


@daily_questions_manage_bp.route('/questions/manage/<int:question_id>/update', methods=['POST'])
@jwt_required
def update_question(question_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))
    try:
        update_managed_question(
            g.user_id,
            question_id,
            can_admin=has_permission('Access Admin Panel'),
            question_text=request.form.get('question'),
            category=request.form.get('category'),
            active=request.form.get('active') == '1',
            when=request.form.get('when'),
            planned_date=request.form.get('planned_date'),
        )
        return _manage_redirect(message='Frage wurde gespeichert.')
    except (ValueError, PermissionError) as exc:
        return _manage_redirect(error=str(exc))
    except Exception as exc:
        log('error', f'Updating Daily Question failed: {exc}')
        return _manage_redirect(error='Die Frage konnte nicht gespeichert werden.')


@daily_questions_manage_bp.route('/questions/manage/timezone', methods=['POST'])
@jwt_required
def update_timezone():
    if not _couples_only() or not has_permission('Access Admin Panel'):
        return redirect(url_for('pages.home'))
    try:
        set_timezone_name(request.form.get('timezone'))
        return _manage_redirect(message='Zeitzone wurde gespeichert.')
    except ValueError as exc:
        return _manage_redirect(error=str(exc))
    except Exception as exc:
        log('error', f'Updating Daily Questions timezone failed: {exc}')
        return _manage_redirect(error='Die Zeitzone konnte nicht gespeichert werden.')


@daily_questions_manage_bp.route('/questions/<int:assignment_id>/skip', methods=['POST'])
@jwt_required
def skip_question(assignment_id):
    try:
        skip_today_question(g.user_id, assignment_id)
        return _archive_redirect(assignment_id, message='Für heute wurde eine andere Frage ausgewählt.')
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(assignment_id, error=str(exc))
    except Exception as exc:
        log('error', f'Skipping Daily Question failed: {exc}')
        return _archive_redirect(assignment_id, error='Die Frage konnte nicht gewechselt werden.')


@daily_questions_manage_bp.route('/questions/<int:assignment_id>/favorite', methods=['POST'])
@jwt_required
def favorite_question(assignment_id):
    try:
        is_favorite = toggle_favorite(g.user_id, assignment_id)
        return _archive_redirect(
            assignment_id,
            message='Frage wurde als Favorit gemerkt.' if is_favorite else 'Frage wurde aus den Favoriten entfernt.',
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(assignment_id, error=str(exc))
    except Exception as exc:
        log('error', f'Toggling Daily Question favorite failed: {exc}')
        return _archive_redirect(assignment_id, error='Der Favorit konnte nicht geaendert werden.')


@daily_questions_manage_bp.route('/questions/<int:assignment_id>/heart-moment', methods=['POST'])
@jwt_required
def question_to_heart_moment(assignment_id):
    try:
        _heart_id, created = convert_question_to_heart_moment(g.user_id, assignment_id)
        return _archive_redirect(
            assignment_id,
            message='Die Frage wurde als Herzmoment gespeichert.' if created else 'Diese Frage ist bereits als Herzmoment gespeichert.',
        )
    except (ValueError, PermissionError) as exc:
        return _archive_redirect(assignment_id, error=str(exc))
    except Exception as exc:
        log('error', f'Converting Daily Question to Heart Moment failed: {exc}')
        return _archive_redirect(assignment_id, error='Das Herzmoment konnte nicht erstellt werden.')


@daily_questions_manage_bp.route('/api/v2/daily-question/flashback', methods=['GET'])
@jwt_required
def daily_question_flashback():
    if not _couples_only():
        return jsonify({'status': 'error', 'message': 'Nur in der Couples-Edition verfuegbar.'}), 403
    try:
        return jsonify({'status': 'success', 'data': get_flashback(g.user_id)})
    except (ValueError, PermissionError) as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400
    except Exception as exc:
        log('error', f'Daily Question flashback failed: {exc}')
        return jsonify({'status': 'error', 'message': 'Der Fragen-Rückblick konnte nicht geladen werden.'}), 500
