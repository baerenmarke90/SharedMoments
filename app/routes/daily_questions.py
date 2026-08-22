from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from app.daily_questions import (
    daily_questions_enabled,
    get_daily_question_history,
    get_daily_question_state,
    save_daily_question_answer,
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


@daily_questions_bp.route('/api/v2/daily-question', methods=['GET'])
@jwt_required
def daily_question_state():
    if not _couples_only():
        return jsonify({'status': 'error', 'message': 'Nur in der Couples-Edition verfügbar.'}), 403

    try:
        state = get_daily_question_state(g.user_id)
        return jsonify({'status': 'success', 'data': state})
    except (ValueError, PermissionError) as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400
    except Exception as exc:
        log('error', f'Daily question state failed: {exc}')
        return jsonify({'status': 'error', 'message': 'Die Frage des Tages konnte nicht geladen werden.'}), 500


@daily_questions_bp.route('/api/v2/daily-question/answer', methods=['POST'])
@jwt_required
def daily_question_answer():
    if not _couples_only():
        return jsonify({'status': 'error', 'message': 'Nur in der Couples-Edition verfügbar.'}), 403

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
        return jsonify({'status': 'error', 'message': str(exc)}), 400
    except Exception as exc:
        log('error', f'Daily question answer failed: {exc}')
        return jsonify({'status': 'error', 'message': 'Die Antwort konnte nicht gespeichert werden.'}), 500


@daily_questions_bp.route('/questions')
@jwt_required
def questions():
    if not _couples_only():
        return redirect(url_for('pages.home'))

    selected_status = request.args.get('status', 'all')
    try:
        history = get_daily_question_history(g.user_id, selected_status)
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
        )
    except Exception as exc:
        log('error', f'Daily question archive failed: {exc}')
        return 'An error occurred while rendering the questions page. Please check the server logs for details.', 500


@daily_questions_bp.route('/questions/<int:assignment_id>/answer', methods=['POST'])
@jwt_required
def answer_question_page(assignment_id):
    if not _couples_only():
        return redirect(url_for('pages.home'))

    answer = request.form.get('answer', '')
    selected_status = request.form.get('status', 'all')

    try:
        save_daily_question_answer(
            g.user_id,
            answer,
            assignment_id=assignment_id,
        )
        return redirect(url_for(
            'daily_questions.questions',
            status=selected_status,
            _anchor=f'question-{assignment_id}',
        ))
    except (ValueError, PermissionError) as exc:
        return redirect(url_for(
            'daily_questions.questions',
            status=selected_status,
            error=str(exc),
            _anchor=f'question-{assignment_id}',
        ))
    except Exception as exc:
        log('error', f'Daily question archive answer failed: {exc}')
        return redirect(url_for(
            'daily_questions.questions',
            status=selected_status,
            error='Die Antwort konnte nicht gespeichert werden.',
            _anchor=f'question-{assignment_id}',
        ))
