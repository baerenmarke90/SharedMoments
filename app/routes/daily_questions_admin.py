from flask import Blueprint, jsonify, request

from app.daily_questions import (
    create_admin_question,
    delete_admin_question,
    get_admin_question_catalog,
    set_daily_questions_timezone,
    update_admin_question,
)
from app.logger import log
from app.permissions import require_permission
from app.routes.auth import jwt_required


daily_questions_admin_bp = Blueprint(
    'daily_questions_admin',
    __name__,
)


def _error(message, status=400):
    return jsonify({
        'status': 'error',
        'message': str(message),
    }), status


@daily_questions_admin_bp.route(
    '/api/v2/admin/daily-questions',
    methods=['GET', 'POST'],
)
@jwt_required
@require_permission('Access Admin Panel')
def admin_daily_questions():
    try:
        if request.method == 'GET':
            data = get_admin_question_catalog(
                request.args.get('q', ''),
                request.args.get('source', 'all'),
            )
            return jsonify({
                'status': 'success',
                'data': data,
            })

        payload = request.get_json(silent=True) or {}
        question = create_admin_question(
            payload.get('question', ''),
            payload.get('category', ''),
        )
        return jsonify({
            'status': 'success',
            'message': 'Frage wurde hinzugefügt.',
            'data': question,
        }), 201
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        log('error', f'Admin Daily Questions failed: {exc}')
        return _error('Die Fragenverwaltung konnte nicht geladen werden.', 500)


@daily_questions_admin_bp.route(
    '/api/v2/admin/daily-questions/<int:question_id>',
    methods=['PUT', 'DELETE'],
)
@jwt_required
@require_permission('Access Admin Panel')
def admin_daily_question(question_id):
    try:
        if request.method == 'DELETE':
            result = delete_admin_question(question_id)
            return jsonify({
                'status': 'success',
                'message': (
                    'Frage wurde gelöscht.'
                    if result.get('deleted')
                    else 'Frage wurde deaktiviert, weil sie bereits verwendet wurde oder zum Standardpool gehört.'
                ),
                'data': result,
            })

        payload = request.get_json(silent=True) or {}
        question = update_admin_question(
            question_id,
            payload,
        )
        return jsonify({
            'status': 'success',
            'message': 'Frage wurde gespeichert.',
            'data': question,
        })
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        log('error', f'Admin Daily Question update failed: {exc}')
        return _error('Die Frage konnte nicht gespeichert werden.', 500)


@daily_questions_admin_bp.route(
    '/api/v2/admin/daily-questions/timezone',
    methods=['PUT'],
)
@jwt_required
@require_permission('Access Admin Panel')
def admin_daily_questions_timezone():
    try:
        payload = request.get_json(silent=True) or {}
        timezone_name = set_daily_questions_timezone(
            payload.get('timezone', '')
        )
        return jsonify({
            'status': 'success',
            'message': 'Zeitzone wurde gespeichert.',
            'data': {'timezone': timezone_name},
        })
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        log('error', f'Admin Daily Questions timezone failed: {exc}')
        return _error('Die Zeitzone konnte nicht gespeichert werden.', 500)
