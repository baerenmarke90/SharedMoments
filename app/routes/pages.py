import json
from datetime import date, datetime
from flask import Blueprint, g, make_response, render_template, send_file, request, redirect, url_for, session
from app.db_queries import (get_all_list_types, get_all_relationship_statuses,
    get_relationship_statuses_with_names, get_items_by_type,
    get_supported_languages, get_translation_for_entity, get_translation_progress,
    get_translations_by_language, get_user_by_id, get_user_setting, get_setting_by_name,
    get_item_by_id, get_user_settings, get_list_type_by_content_url, get_all_settings,
    get_shared_item_ids, get_list_type_by_title, ensure_countdown_list_type,
    ensure_banner_song_setting, get_all_reminders, get_user_muted_reminder_ids,
    ensure_notification_settings, get_passkeys_by_user, get_all_users,
    get_couple_chapters, get_couple_chapter, create_couple_chapter,
    update_couple_chapter, delete_couple_chapter, get_couple_chapter_links,
    replace_couple_chapter_links, get_couple_chapter_link_map,
    get_couple_plans, get_couple_plan, create_couple_plan,
    update_couple_plan, delete_couple_plan, set_couple_plan_chapter)
from app.logger import log
import os
from app.utils import generate_banner_text
from app.translation import _, set_locale
from app.routes.auth import jwt_required, login_jwt
from app.permissions import require_permission, has_list_permission, has_permission

pages_bp = Blueprint('pages', __name__)


def get_display_title():
    """Returns the appropriate title setting based on the current edition."""
    edition = get_setting_by_name('sm_edition').value
    if edition == 'family':
        family_name = get_setting_by_name('family_name')
        if family_name and family_name.value:
            return family_name
    elif edition == 'friends':
        friend_name = get_setting_by_name('friend_group_name')
        if friend_name and friend_name.value:
            return friend_name
    return get_setting_by_name('title')

# Paths that bypass the migration gate
_MIGRATION_ALLOWED_PREFIXES = ('/static/', '/api/v2/migration/', '/migration-complete',
                                '/migration-progress', '/manifest.json', '/sw.js',
                                '/offline', '/favicon.ico')


def _get_migration_target():
    """Determine where to redirect based on migration state. Returns URL or None."""
    # 1. Check if migration review is pending (real migration done, user must review)
    try:
        review = get_setting_by_name('migration_review_complete')
        if review and review.value == 'False':
            return '/migration-complete'
    except Exception:
        pass

    # 2. Check if migration is currently running or dry-run completed
    try:
        from app.migration.status import load_status
        status = load_status()
        if status:
            if status.get('dry_run', False):
                return '/migration-progress'
            if not status.get('completed_at'):
                return '/migration-progress'
    except ImportError:
        pass

    return None


@pages_bp.before_app_request
def _migration_gate():
    """Redirect all non-migration pages when migration is active."""
    path = request.path
    if any(path.startswith(p) for p in _MIGRATION_ALLOWED_PREFIXES):
        return None

    target = _get_migration_target()
    if target:
        return redirect(target)
    return None


# ===== PWA Routes (no auth required) =====

@pages_bp.route('/manifest.json')
def manifest():
    return send_file('static/pwa/manifest.json', mimetype='application/manifest+json')


@pages_bp.route('/sw.js')
def service_worker():
    response = make_response(send_file('static/pwa/sw.js', mimetype='application/javascript'))
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@pages_bp.route('/offline')
def offline():
    return render_template('pages/offline.html')


@pages_bp.app_context_processor
def inject_static_text():
    translations_json = '{}'
    try:
        lang = session.get('lang', os.environ.get('LANG', 'en-US'))
        translations = get_translations_by_language(lang)
        translations_json = json.dumps({
            t.fieldName: {'translatedText': t.translatedText}
            for t in translations
        }, ensure_ascii=False)
    except Exception:
        pass
    try:
        nav_edition = get_setting_by_name('sm_edition').value
    except Exception:
        nav_edition = 'couples'
    return dict(_=_, translations_json=translations_json, nav_edition=nav_edition)


@pages_bp.route('/')
def index():
    if get_setting_by_name('setup_complete').value == 'False':
        return redirect(url_for('pages.setup'))
    else:
        return redirect(url_for('auth.login'))


@pages_bp.route('/static/js/<filename>')
@jwt_required
def serve_js(filename):
    return send_file('static/js/' + filename), 200


@pages_bp.route('/setup')
def setup():
    try:
        # If migration is active, go there instead
        target = _get_migration_target()
        if target:
            return redirect(target)

        if get_setting_by_name('setup_complete').value == 'True':
            return redirect(url_for('auth.login'))
        else:
            set_locale()
            setupUser = get_user_by_id(1)
            response = login_jwt(setupUser)
            relationship_statuses = get_all_relationship_statuses()
            relationship_statuses_translated = []
            for status in relationship_statuses:
                translated_text = get_translation_for_entity('relationship_status', status, os.environ['LANG'])
                relationship_statuses_translated.append({
                    'id': status,
                    'translatedText': translated_text
                })

            response.data = render_template('pages/setup.html', relationship_statuses=relationship_statuses, relationship_statuses_translated=relationship_statuses_translated)
            response.mimetype = 'text/html'
            return response

    except Exception as e:
        log('error', f'Error while rendering the pages/setup.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500



def _as_datetime(value):
    """Normalize Date/DateTime values for couple-home sorting."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def _item_has_explicit_date(item):
    """Return True when dateCreated came from the optional date input.

    SharedMoments currently stores both meanings in Item.dateCreated:
    - a user-selected HTML date is stored at midnight
    - no selected date keeps the real creation timestamp including time

    This lets existing data retain the intended UX without a schema migration.
    """
    value = _as_datetime(getattr(item, 'dateCreated', None))
    if not value:
        return False

    return (
        value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


def _next_annual_occurrence(month, day, today):
    """Return the next valid annual occurrence on or after today."""
    if not month or not day:
        return None

    # Search far enough ahead to cover leap-day reminders safely.
    for year in range(today.year, today.year + 9):
        try:
            candidate = date(year, int(month), int(day))
        except (TypeError, ValueError):
            continue
        if candidate >= today:
            return candidate
    return None


def _relative_day_label(target_date, today):
    days = (target_date - today).days
    if days == 0:
        return 'Heute'
    if days == 1:
        return 'Morgen'
    return f'in {days} Tagen'


def _build_couple_home_upcoming(
    countdowns,
    reminders,
    muted_ids,
    can_view_countdowns,
    can_view_reminders,
):
    """Build a small, permission-aware list for the couple dashboard."""
    today = date.today()
    upcoming = []

    if can_view_countdowns:
        for item, _user in countdowns:
            target_dt = _as_datetime(item.dateCreated)
            if not target_dt:
                continue

            target_date = target_dt.date()
            if target_date < today:
                continue

            upcoming.append({
                'type': 'countdown',
                'icon': 'timer',
                'title': item.title or 'Countdown',
                'date': target_date,
                'date_label': target_date.strftime('%d.%m.%Y'),
                'relative_label': _relative_day_label(target_date, today),
            })

    if can_view_reminders:
        for reminder in reminders:
            if reminder.id in muted_ids:
                continue

            # Countdowns already appear from their Item, so never duplicate them.
            # Also ignore any reminder linked to a countdown item even if older
            # data used another reminder_type. This prevents orphaned countdown
            # reminders from resurfacing in "Demnächst".
            if (
                reminder.reminder_type == 'countdown'
                or reminder.countdown_id is not None
            ):
                continue

            target_date = None

            if reminder.reminder_type == 'annual':
                target_date = _next_annual_occurrence(
                    reminder.month,
                    reminder.day,
                    today,
                )
            elif reminder.reminder_type == 'one_time' and reminder.target_date:
                target_date = reminder.target_date
            elif reminder.reminder_type == 'milestone' and reminder.target_date:
                # Only use milestone reminders when a concrete target date exists.
                # We deliberately do not guess dates from auto_source here.
                target_date = reminder.target_date

            if not target_date or target_date < today:
                continue

            upcoming.append({
                'type': 'reminder',
                'icon': 'event',
                'title': _translate_reminder_title(reminder),
                'date': target_date,
                'date_label': target_date.strftime('%d.%m.%Y'),
                'relative_label': _relative_day_label(target_date, today),
            })

    upcoming.sort(key=lambda entry: entry['date'])
    return upcoming[:3]


def _build_couple_home_recent(
    items,
    moments,
    shared_heart_moments,
    can_view_items,
    can_view_moments,
):
    """Aggregate existing content without introducing a new persistence model."""
    recent = []

    if can_view_items:
        for item, user in items:
            event_dt = _as_datetime(item.dateCreated)
            if not event_dt:
                continue

            image_url = None
            url = None

            if item.contentURL:
                first_media = item.contentURL.split(';')[0].strip()
                if first_media:
                    if item.contentType in ('image', 'galleryStartWithImage'):
                        image_url = f'/api/v2/media/{first_media}'
                    elif item.contentType in (
                        'video',
                        'video-mov',
                        'galleryStartWithVideo',
                    ):
                        image_url = f'/api/v2/media/thumb/{first_media}'

            if item.contentType in (
                'galleryStartWithImage',
                'galleryStartWithVideo',
                'video',
                'video-mov',
            ):
                url = f'/gallery/{item.id}'

            date_is_explicit = _item_has_explicit_date(item)

            recent.append({
                'type': 'memory',
                'icon': 'notes' if item.contentType == 'text' else 'photo',
                'title': item.title or 'Erinnerung',
                'text': item.content or '',
                'sort_date': event_dt,
                'date_label': (
                    event_dt.strftime('%d.%m.%Y')
                    if date_is_explicit
                    else ''
                ),
                'author_name': user.firstName if user else '',
                'author_picture': user.profilePicture if user else None,
                'image_url': image_url,
                'url': url,
            })

    if can_view_moments:
        for item, user in moments:
            event_dt = _as_datetime(item.dateCreated)
            if not event_dt:
                continue

            recent.append({
                'type': 'milestone',
                'icon': 'star',
                'title': item.title or 'Meilenstein',
                'text': item.content or '',
                'sort_date': event_dt,
                'date_label': event_dt.strftime('%d.%m.%Y'),
                'author_name': user.firstName if user else '',
                'author_picture': user.profilePicture if user else None,
                'image_url': None,
                'url': None,
                'timeline_id': item.id,
                'timeline_date_ymd': event_dt.strftime('%Y-%m-%d'),
            })

    for heart_moment in shared_heart_moments:
        try:
            event_dt = datetime.fromisoformat(heart_moment['momentDate'])
        except (TypeError, ValueError, KeyError):
            continue

        author = heart_moment.get('author') or {}
        media_filename = heart_moment.get('mediaFilename')

        recent.append({
            'type': 'heart',
            'icon': 'favorite',
            'title': 'Herzmoment',
            'text': heart_moment.get('description') or '',
            'sort_date': event_dt,
            'date_label': event_dt.strftime('%d.%m.%Y'),
            'author_name': author.get('firstName', ''),
            'author_picture': author.get('profilePicture'),
            'image_url': (
                f"/api/v2/heart-moments/{heart_moment['id']}/image"
                f"?v={heart_moment.get('dateModified', '')}"
                if media_filename else None
            ),
            'url': f"/heart-moments?highlight={heart_moment['id']}",
        })

    recent.sort(key=lambda entry: entry['sort_date'], reverse=True)
    return recent[:5]



_STORY_MONTH_NAMES = (
    '',
    'Januar',
    'Februar',
    'März',
    'April',
    'Mai',
    'Juni',
    'Juli',
    'August',
    'September',
    'Oktober',
    'November',
    'Dezember',
)


def _story_month_label(value):
    return f'{_STORY_MONTH_NAMES[value.month]} {value.year}'


def _build_story_entries(
    items,
    moments,
    shared_heart_moments,
    can_view_items,
    can_view_moments,
):
    """Build the relationship chronology from existing SharedMoments data."""
    entries = []

    if can_view_items:
        for item, user in items:
            event_dt = _as_datetime(item.dateCreated)
            if not event_dt:
                continue

            image_url = None
            first_media = None

            if item.contentURL:
                first_media = item.contentURL.split(';')[0].strip()

            if first_media:
                if item.contentType in ('image', 'galleryStartWithImage'):
                    image_url = f'/api/v2/media/{first_media}'
                elif item.contentType in (
                    'video',
                    'video-mov',
                    'galleryStartWithVideo',
                ):
                    image_url = f'/api/v2/media/thumb/{first_media}'

            is_gallery = item.contentType in (
                'galleryStartWithImage',
                'galleryStartWithVideo',
            )

            entries.append({
                'type': 'memory',
                'type_label': 'Erinnerung',
                'icon': 'photo_library' if is_gallery else (
                    'notes' if item.contentType == 'text' else 'photo'
                ),
                'id': item.id,
                'title': item.title or 'Erinnerung',
                'text': item.content or '',
                'event_date': event_dt,
                'date_label': (
                    event_dt.strftime('%d.%m.%Y')
                    if _item_has_explicit_date(item)
                    else ''
                ),
                'year': event_dt.year,
                'month_key': event_dt.strftime('%Y-%m'),
                'month_label': _story_month_label(event_dt),
                'author_name': user.firstName if user else '',
                'author_picture': user.profilePicture if user else None,
                'image_url': image_url,
                'href': (
                    f'/gallery/{item.id}'
                    if item.contentType in (
                        'galleryStartWithImage',
                        'galleryStartWithVideo',
                        'video',
                        'video-mov',
                    )
                    else f'/memories#article_{item.id}'
                ),
                'is_gallery': is_gallery,
            })

    if can_view_moments:
        for item, user in moments:
            event_dt = _as_datetime(item.dateCreated)
            if not event_dt:
                continue

            entries.append({
                'type': 'milestone',
                'type_label': 'Meilenstein',
                'icon': 'star',
                'id': item.id,
                'title': item.title or 'Meilenstein',
                'text': item.content or '',
                'event_date': event_dt,
                'date_label': event_dt.strftime('%d.%m.%Y'),
                'year': event_dt.year,
                'month_key': event_dt.strftime('%Y-%m'),
                'month_label': _story_month_label(event_dt),
                'author_name': user.firstName if user else '',
                'author_picture': user.profilePicture if user else None,
                'image_url': None,
                'href': f'/milestones#milestone-{item.id}',
                'is_gallery': False,
            })

    for heart_moment in shared_heart_moments:
        try:
            event_dt = datetime.fromisoformat(heart_moment['momentDate'])
        except (TypeError, ValueError, KeyError):
            continue

        author = heart_moment.get('author') or {}
        media_filename = heart_moment.get('mediaFilename')

        entries.append({
            'type': 'heart',
            'type_label': 'Herzmoment',
            'icon': 'favorite',
            'id': heart_moment['id'],
            'title': 'Herzmoment',
            'text': heart_moment.get('description') or '',
            'event_date': event_dt,
            'date_label': event_dt.strftime('%d.%m.%Y'),
            'year': event_dt.year,
            'month_key': event_dt.strftime('%Y-%m'),
            'month_label': _story_month_label(event_dt),
            'author_name': author.get('firstName', ''),
            'author_picture': author.get('profilePicture'),
            'image_url': (
                f"/api/v2/heart-moments/{heart_moment['id']}/image"
                f"?v={heart_moment.get('dateModified', '')}"
                if media_filename else None
            ),
            'href': f"/heart-moments?highlight={heart_moment['id']}",
            'is_gallery': False,
        })

    entries.sort(
        key=lambda entry: (
            entry['event_date'],
            entry['id'],
        ),
        reverse=True,
    )
    return entries


def _filter_story_entries(entries, entry_type, selected_year, search_query):
    filtered = entries

    if entry_type != 'all':
        filtered = [
            entry for entry in filtered
            if entry['type'] == entry_type
        ]

    if selected_year:
        filtered = [
            entry for entry in filtered
            if entry['year'] == selected_year
        ]

    if search_query:
        needle = search_query.casefold()

        def matches(entry):
            chapter_titles = ' '.join(
                chapter.get('title') or ''
                for chapter in entry.get('chapters', [])
            )
            haystack = ' '.join((
                entry.get('type_label') or '',
                entry.get('title') or '',
                entry.get('text') or '',
                entry.get('author_name') or '',
                chapter_titles,
            )).casefold()
            return needle in haystack

        filtered = [entry for entry in filtered if matches(entry)]

    return filtered


def _group_story_entries(entries):
    groups = []
    current_key = None

    for entry in entries:
        if entry['month_key'] != current_key:
            current_key = entry['month_key']
            groups.append({
                'key': current_key,
                'label': entry['month_label'],
                'entries': [],
            })

        groups[-1]['entries'].append(entry)

    return groups


def _parse_optional_form_date(value):
    value = str(value or '').strip()
    if not value:
        return None
    return date.fromisoformat(value)


def _chapter_date_label(chapter):
    start_date = chapter.get('startDate')
    end_date = chapter.get('endDate')

    if start_date and end_date:
        if start_date == end_date:
            return start_date.strftime('%d.%m.%Y')
        return (
            f"{start_date.strftime('%d.%m.%Y')} – "
            f"{end_date.strftime('%d.%m.%Y')}"
        )

    if start_date:
        return start_date.strftime('%d.%m.%Y')

    if end_date:
        return f"bis {end_date.strftime('%d.%m.%Y')}"

    return ''


def _couple_content_for_chapters(sm_edition, user_id):
    can_view_items = has_list_permission('View', 'Home')
    can_view_moments = has_list_permission('View', 'Moments')

    home_list_type = get_list_type_by_title('Home')
    moments_list_type = get_list_type_by_title('Moments')

    memories = (
        get_items_by_type(
            home_list_type.id,
            'desc',
            edition=sm_edition,
        )
        if can_view_items and home_list_type
        else []
    )

    moments = (
        get_items_by_type(
            moments_list_type.id,
            'desc',
            edition=sm_edition,
        )
        if can_view_moments and moments_list_type
        else []
    )

    from app.heart_moments import list_heart_moments

    shared_heart_moments = list_heart_moments(
        user_id,
        filter_name='shared',
    )

    entries = _build_story_entries(
        memories,
        moments,
        shared_heart_moments,
        can_view_items,
        can_view_moments,
    )

    return {
        'memories': memories,
        'moments': moments,
        'heart_moments': shared_heart_moments,
        'entries': entries,
        'can_view_items': can_view_items,
        'can_view_moments': can_view_moments,
    }


def _chapter_summary(chapter, links, content):
    item_ids = links.get('item_ids', set())
    heart_ids = links.get('heart_ids', set())

    entries = [
        entry
        for entry in content['entries']
        if (
            entry['id'] in heart_ids
            if entry['type'] == 'heart'
            else entry['id'] in item_ids
        )
    ]

    cover_url = next(
        (
            entry['image_url']
            for entry in entries
            if entry.get('image_url')
        ),
        None,
    )

    result = dict(chapter)
    result.update({
        'date_label': _chapter_date_label(chapter),
        'cover_url': cover_url,
        'memory_count': sum(
            1 for entry in entries if entry['type'] == 'memory'
        ),
        'heart_count': sum(
            1 for entry in entries if entry['type'] == 'heart'
        ),
        'milestone_count': sum(
            1 for entry in entries if entry['type'] == 'milestone'
        ),
        'entry_count': len(entries),
        'entries': entries,
    })
    return result


def _chapter_form_values():
    title = str(request.form.get('title', '')).strip()
    description = str(request.form.get('description', '')).strip()
    location_name = str(request.form.get('location_name', '')).strip()

    if not title:
        raise ValueError('Bitte gib dem Kapitel einen Titel.')

    if len(title) > 255:
        raise ValueError('Der Titel darf höchstens 255 Zeichen lang sein.')

    if len(location_name) > 255:
        raise ValueError('Der Ort darf höchstens 255 Zeichen lang sein.')

    try:
        start_date = _parse_optional_form_date(
            request.form.get('start_date')
        )
        end_date = _parse_optional_form_date(
            request.form.get('end_date')
        )
    except ValueError as exc:
        raise ValueError('Bitte verwende gültige Datumsangaben.') from exc

    if start_date and end_date and end_date < start_date:
        raise ValueError('Das Enddatum darf nicht vor dem Startdatum liegen.')

    return {
        'title': title,
        'description': description,
        'start_date': start_date,
        'end_date': end_date,
        'location_name': location_name,
    }


_PLAN_STATUS_META = {
    'idea': {
        'label': 'Idee',
        'icon': 'lightbulb',
    },
    'planned': {
        'label': 'Geplant',
        'icon': 'event_available',
    },
    'experienced': {
        'label': 'Erlebt',
        'icon': 'done_all',
    },
}


def _plan_date_label(plan):
    start = plan.get('targetStartDate')
    end = plan.get('targetEndDate')

    if start and end:
        if start == end:
            return start.strftime('%d.%m.%Y')
        return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"
    if start:
        return start.strftime('%d.%m.%Y')
    if end:
        return f"bis {end.strftime('%d.%m.%Y')}"
    return ''


def _present_couple_plan(plan, current_user_id=None):
    presented = dict(plan)
    meta = _PLAN_STATUS_META.get(
        plan.get('status'),
        _PLAN_STATUS_META['idea'],
    )
    presented.update({
        'status_label': meta['label'],
        'status_icon': meta['icon'],
        'date_label': _plan_date_label(plan),
        'start_input': (
            plan['targetStartDate'].isoformat()
            if plan.get('targetStartDate') else ''
        ),
        'end_input': (
            plan['targetEndDate'].isoformat()
            if plan.get('targetEndDate') else ''
        ),
        'is_owner': (
            current_user_id is not None
            and plan.get('createdByUser') == current_user_id
        ),
    })
    return presented


def _couple_home_plans(plans):
    active = [
        _present_couple_plan(plan)
        for plan in plans
        if plan.get('status') in ('idea', 'planned')
    ]

    def sort_key(plan):
        target = plan.get('targetStartDate') or plan.get('targetEndDate')
        created = plan.get('dateCreated')
        created_date = (
            created.date()
            if created and hasattr(created, 'date')
            else date.min
        )
        return (
            0 if target else 1,
            target or date.max,
            -created_date.toordinal(),
            -plan['id'],
        )

    active.sort(key=sort_key)
    return active[:3]


def _plan_form_values():
    title = str(request.form.get('title', '')).strip()
    description = str(request.form.get('description', '')).strip()
    location_name = str(request.form.get('location_name', '')).strip()
    status = str(request.form.get('status', 'idea')).strip()

    if not title:
        raise ValueError('Bitte gib dem Plan einen Titel.')
    if len(title) > 255:
        raise ValueError('Der Titel darf höchstens 255 Zeichen lang sein.')
    if len(location_name) > 255:
        raise ValueError('Der Ort darf höchstens 255 Zeichen lang sein.')
    if status not in _PLAN_STATUS_META:
        raise ValueError('Bitte wähle einen gültigen Status.')

    try:
        target_start_date = _parse_optional_form_date(
            request.form.get('target_start_date')
        )
        target_end_date = _parse_optional_form_date(
            request.form.get('target_end_date')
        )
    except ValueError as exc:
        raise ValueError('Bitte verwende gültige Datumsangaben.') from exc

    if (
        target_start_date
        and target_end_date
        and target_end_date < target_start_date
    ):
        raise ValueError('Das Enddatum darf nicht vor dem Startdatum liegen.')

    return {
        'title': title,
        'description': description,
        'status': status,
        'target_start_date': target_start_date,
        'target_end_date': target_end_date,
        'location_name': location_name,
    }


@pages_bp.route('/home')
@jwt_required
def home():
    try:
        list_type = 1
        sm_edition = get_setting_by_name('sm_edition').value
        items = get_items_by_type(list_type, 'desc', edition=sm_edition)
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        settings = get_all_settings()
        list_type_moments = 2
        moments = get_items_by_type(list_type_moments, 'asc', edition=sm_edition)
        banner_text = generate_banner_text(sm_edition)
        shared_item_ids = get_shared_item_ids()

        ensure_countdown_list_type()
        ensure_banner_song_setting()
        countdown_list_type = get_list_type_by_title('Countdown')
        countdowns = get_items_by_type(
            countdown_list_type.id,
            'asc',
            edition=sm_edition,
        ) if countdown_list_type else []
        countdown_list_type_id = countdown_list_type.id if countdown_list_type else ''

        heart_moment_memory = None
        couple_users = []
        couple_home_upcoming = []
        couple_home_recent = []
        couple_home_plans = []

        if sm_edition == 'couples':
            from app.heart_moments import (
                get_daily_shared_heart_moment_memory,
                list_heart_moments,
            )

            heart_moment_memory = get_daily_shared_heart_moment_memory()

            # Stable ordering for both partners; system user is already excluded.
            couple_users = sorted(
                get_all_users(),
                key=lambda user: user.id,
            )[:2]

            can_view_countdowns = has_list_permission('View', 'Countdown')
            can_view_reminders = has_permission('View Reminders')

            reminder_list = (
                get_all_reminders()
                if can_view_reminders
                else []
            )
            muted_ids = (
                get_user_muted_reminder_ids(g.user_id)
                if can_view_reminders
                else set()
            )

            couple_home_upcoming = _build_couple_home_upcoming(
                countdowns,
                reminder_list,
                muted_ids,
                can_view_countdowns,
                can_view_reminders,
            )

            shared_heart_moments = list_heart_moments(
                g.user_id,
                filter_name='shared',
            )

            couple_home_recent = _build_couple_home_recent(
                items,
                moments,
                shared_heart_moments,
                has_list_permission('View', 'Home'),
                has_list_permission('View', 'Moments'),
            )

            couple_home_plans = _couple_home_plans(
                get_couple_plans()
            )

        return render_template(
            'pages/home.html',
            items=items,
            list_types=list_types,
            list_type=list_type,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            moments=moments,
            settings=settings,
            banner_text=banner_text,
            sm_edition=sm_edition,
            list_type_title='Home',
            moments_title='Moments',
            shared_item_ids=shared_item_ids,
            countdowns=countdowns,
            countdown_title='Countdown',
            countdown_list_type_id=countdown_list_type_id,
            heart_moment_memory=heart_moment_memory,
            couple_users=couple_users,
            couple_home_upcoming=couple_home_upcoming,
            couple_home_recent=couple_home_recent,
            couple_home_plans=couple_home_plans,
            page_title='Wir' if sm_edition == 'couples' else None,
            memories_page=False,
            milestones_page=False,
            current_user_id=g.user_id,
        )

    except Exception as e:
        log('error', f'Error while rendering the pages/home.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/memories')
@jwt_required
def memories():
    """Dedicated shared-memory page backed by the existing Home items."""
    try:
        if not has_list_permission('View', 'Home'):
            return redirect(url_for('pages.home'))

        sm_edition = get_setting_by_name('sm_edition').value
        home_list_type = get_list_type_by_title('Home')
        if not home_list_type:
            return redirect(url_for('pages.home'))

        items = get_items_by_type(
            home_list_type.id,
            'desc',
            edition=sm_edition,
        )

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        shared_item_ids = get_shared_item_ids()

        return render_template(
            'pages/home.html',
            items=items,
            list_types=list_types,
            list_type=home_list_type.id,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            sm_edition=sm_edition,
            list_type_title='Home',
            moments_title='Moments',
            countdown_title='Countdown',
            countdown_list_type_id='',
            moments=[],
            countdowns=[],
            settings=None,
            banner_text=None,
            shared_item_ids=shared_item_ids,
            heart_moment_memory=None,
            couple_users=[],
            couple_home_upcoming=[],
            couple_home_recent=[],
            page_title='Erinnerungen',
            memories_page=True,
            milestones_page=False,
            current_user_id=g.user_id,
        )
    except Exception as e:
        log('error', f'Error while rendering memories page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/milestones')
@jwt_required
def milestones():
    """Dedicated milestone page backed by the existing Moments items."""
    try:
        if not has_list_permission('View', 'Moments'):
            return redirect(url_for('pages.home'))

        sm_edition = get_setting_by_name('sm_edition').value
        moments_list_type = get_list_type_by_title('Moments')
        home_list_type = get_list_type_by_title('Home')

        if not moments_list_type:
            return redirect(url_for('pages.home'))

        moments = get_items_by_type(
            moments_list_type.id,
            'asc',
            edition=sm_edition,
        )

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        return render_template(
            'pages/home.html',
            items=[],
            list_types=list_types,
            list_type=home_list_type.id if home_list_type else 1,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            sm_edition=sm_edition,
            list_type_title='Home',
            moments_title='Moments',
            countdown_title='Countdown',
            countdown_list_type_id='',
            moments=moments,
            countdowns=[],
            settings=None,
            banner_text=None,
            shared_item_ids=[],
            heart_moment_memory=None,
            couple_users=[],
            couple_home_upcoming=[],
            couple_home_recent=[],
            page_title='Meilensteine',
            memories_page=False,
            milestones_page=True,
            current_user_id=g.user_id,
        )
    except Exception as e:
        log('error', f'Error while rendering milestones page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/plans')
@jwt_required
def plans():
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        selected_status = str(
            request.args.get('status', 'all')
        ).strip()
        allowed_statuses = {'all'} | set(_PLAN_STATUS_META)
        if selected_status not in allowed_statuses:
            selected_status = 'all'

        all_plans = [
            _present_couple_plan(plan, g.user_id)
            for plan in get_couple_plans()
        ]

        status_rank = {
            'planned': 0,
            'idea': 1,
            'experienced': 2,
        }

        def plan_sort_key(plan):
            target = plan.get('targetStartDate') or plan.get('targetEndDate')
            created = plan.get('dateCreated')
            created_date = (
                created.date()
                if created and hasattr(created, 'date')
                else date.min
            )
            return (
                status_rank.get(plan.get('status'), 9),
                0 if target else 1,
                target or date.max,
                -created_date.toordinal(),
                -plan['id'],
            )

        all_plans.sort(key=plan_sort_key)

        visible_plans = (
            all_plans
            if selected_status == 'all'
            else [
                plan for plan in all_plans
                if plan.get('status') == selected_status
            ]
        )

        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        list_types = get_all_list_types()

        return render_template(
            'pages/plans.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
            sm_edition=sm_edition,
            page_title='Unsere Pläne',
            plans=visible_plans,
            selected_status=selected_status,
            plan_statuses=_PLAN_STATUS_META,
            plan_error=request.args.get('error', ''),
        )
    except Exception as e:
        log('error', f'Error while rendering plans page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/plans/create', methods=['POST'])
@jwt_required
def create_plan_page():
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    try:
        values = _plan_form_values()
        create_couple_plan(
            title=values['title'],
            description=values['description'],
            status=values['status'],
            target_start_date=values['target_start_date'],
            target_end_date=values['target_end_date'],
            location_name=values['location_name'],
            created_by_user=g.user_id,
        )
        return redirect(url_for('pages.plans'))
    except ValueError as exc:
        return redirect(url_for('pages.plans', error=str(exc)))
    except Exception as e:
        log('error', f'Error while creating couple plan: {e}')
        return redirect(url_for(
            'pages.plans',
            error='Der Plan konnte nicht erstellt werden.',
        ))


@pages_bp.route('/plans/<int:plan_id>/update', methods=['POST'])
@jwt_required
def update_plan_page(plan_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    plan = get_couple_plan(plan_id)
    if not plan:
        return redirect(url_for('pages.plans'))
    if plan['createdByUser'] != g.user_id:
        return redirect(url_for(
            'pages.plans',
            error='Du kannst nur deine eigenen Pläne bearbeiten.',
        ))

    try:
        values = _plan_form_values()
        update_couple_plan(
            plan_id=plan_id,
            title=values['title'],
            description=values['description'],
            status=values['status'],
            target_start_date=values['target_start_date'],
            target_end_date=values['target_end_date'],
            location_name=values['location_name'],
        )
        return redirect(url_for('pages.plans') + f'#plan-{plan_id}')
    except ValueError as exc:
        return redirect(url_for(
            'pages.plans',
            error=str(exc),
        ) + f'#plan-{plan_id}')
    except Exception as e:
        log('error', f'Error while updating couple plan {plan_id}: {e}')
        return redirect(url_for(
            'pages.plans',
            error='Der Plan konnte nicht gespeichert werden.',
        ) + f'#plan-{plan_id}')


@pages_bp.route('/plans/<int:plan_id>/delete', methods=['POST'])
@jwt_required
def delete_plan_page(plan_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    plan = get_couple_plan(plan_id)
    if not plan:
        return redirect(url_for('pages.plans'))
    if plan['createdByUser'] != g.user_id:
        return redirect(url_for(
            'pages.plans',
            error='Du kannst nur deine eigenen Pläne löschen.',
        ))

    try:
        delete_couple_plan(plan_id)
        return redirect(url_for('pages.plans'))
    except Exception as e:
        log('error', f'Error while deleting couple plan {plan_id}: {e}')
        return redirect(url_for(
            'pages.plans',
            error='Der Plan konnte nicht gelöscht werden.',
        ))


@pages_bp.route('/plans/<int:plan_id>/chapter', methods=['POST'])
@jwt_required
def plan_to_chapter_page(plan_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    plan = get_couple_plan(plan_id)
    if not plan:
        return redirect(url_for('pages.plans'))
    if plan['createdByUser'] != g.user_id:
        return redirect(url_for(
            'pages.plans',
            error='Du kannst nur deine eigenen Pläne in Kapitel umwandeln.',
        ))
    if plan.get('chapter'):
        return redirect(url_for(
            'pages.chapter',
            chapter_id=plan['chapter']['id'],
        ))
    if plan.get('status') != 'experienced':
        return redirect(url_for(
            'pages.plans',
            error='Markiere den Plan zuerst als „Erlebt“.',
        ) + f'#plan-{plan_id}')

    try:
        chapter_id = create_couple_chapter(
            title=plan['title'],
            description=plan['description'],
            start_date=plan['targetStartDate'],
            end_date=plan['targetEndDate'],
            location_name=plan['locationName'],
            created_by_user=g.user_id,
        )
        set_couple_plan_chapter(plan_id, chapter_id)
        return redirect(url_for('pages.chapter', chapter_id=chapter_id))
    except Exception as e:
        log('error', f'Error while converting plan {plan_id} to chapter: {e}')
        return redirect(url_for(
            'pages.plans',
            error='Aus dem Plan konnte kein Kapitel erstellt werden.',
        ) + f'#plan-{plan_id}')


@pages_bp.route('/chapters')
@jwt_required
def chapters():
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        content = _couple_content_for_chapters(
            sm_edition,
            g.user_id,
        )
        link_map = get_couple_chapter_link_map()

        chapter_cards = [
            _chapter_summary(
                chapter,
                link_map['by_chapter'].get(
                    chapter['id'],
                    {'item_ids': set(), 'heart_ids': set()},
                ),
                content,
            )
            for chapter in get_couple_chapters()
        ]

        return render_template(
            'pages/chapters.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
            sm_edition=sm_edition,
            page_title='Kapitel',
            chapters=chapter_cards,
            chapter_error=request.args.get('error', ''),
        )

    except Exception as e:
        log('error', f'Error while rendering chapters page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/chapters/create', methods=['POST'])
@jwt_required
def create_chapter_page():
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    try:
        values = _chapter_form_values()
        chapter_id = create_couple_chapter(
            title=values['title'],
            description=values['description'],
            start_date=values['start_date'],
            end_date=values['end_date'],
            location_name=values['location_name'],
            created_by_user=g.user_id,
        )
        return redirect(url_for('pages.chapter', chapter_id=chapter_id))
    except ValueError as exc:
        return redirect(url_for('pages.chapters', error=str(exc)))
    except Exception as e:
        log('error', f'Error while creating couple chapter: {e}')
        return redirect(url_for(
            'pages.chapters',
            error='Das Kapitel konnte nicht erstellt werden.',
        ))


@pages_bp.route('/chapters/<int:chapter_id>')
@jwt_required
def chapter(chapter_id):
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        chapter_data = get_couple_chapter(chapter_id)
        if not chapter_data:
            return redirect(url_for('pages.chapters'))

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        content = _couple_content_for_chapters(
            sm_edition,
            g.user_id,
        )
        links = get_couple_chapter_links(chapter_id)
        chapter_data = _chapter_summary(
            chapter_data,
            links,
            content,
        )

        linked_item_ids = links['item_ids']
        linked_heart_ids = links['heart_ids']

        candidates = []
        for entry in content['entries']:
            candidate = dict(entry)
            candidate['linked'] = (
                entry['id'] in linked_heart_ids
                if entry['type'] == 'heart'
                else entry['id'] in linked_item_ids
            )
            candidates.append(candidate)

        return render_template(
            'pages/chapter.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
            sm_edition=sm_edition,
            page_title=chapter_data['title'],
            chapter=chapter_data,
            chapter_entries=chapter_data['entries'],
            chapter_candidates=candidates,
            chapter_error=request.args.get('error', ''),
        )

    except Exception as e:
        log('error', f'Error while rendering chapter {chapter_id}: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/chapters/<int:chapter_id>/update', methods=['POST'])
@jwt_required
def update_chapter_page(chapter_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    if not get_couple_chapter(chapter_id):
        return redirect(url_for('pages.chapters'))

    try:
        values = _chapter_form_values()
        update_couple_chapter(
            chapter_id=chapter_id,
            title=values['title'],
            description=values['description'],
            start_date=values['start_date'],
            end_date=values['end_date'],
            location_name=values['location_name'],
        )
        return redirect(url_for('pages.chapter', chapter_id=chapter_id))
    except ValueError as exc:
        return redirect(url_for(
            'pages.chapter',
            chapter_id=chapter_id,
            error=str(exc),
        ))
    except Exception as e:
        log('error', f'Error while updating couple chapter {chapter_id}: {e}')
        return redirect(url_for(
            'pages.chapter',
            chapter_id=chapter_id,
            error='Das Kapitel konnte nicht gespeichert werden.',
        ))


@pages_bp.route('/chapters/<int:chapter_id>/links', methods=['POST'])
@jwt_required
def update_chapter_links_page(chapter_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    if not get_couple_chapter(chapter_id):
        return redirect(url_for('pages.chapters'))

    try:
        content = _couple_content_for_chapters(
            sm_edition,
            g.user_id,
        )

        valid_item_ids = {
            entry['id']
            for entry in content['entries']
            if entry['type'] in {'memory', 'milestone'}
        }
        valid_heart_ids = {
            entry['id']
            for entry in content['entries']
            if entry['type'] == 'heart'
        }

        def parse_ids(values):
            parsed = set()
            for value in values:
                try:
                    parsed.add(int(value))
                except (TypeError, ValueError):
                    continue
            return parsed

        requested_item_ids = parse_ids(
            request.form.getlist('item_ids')
        )
        requested_heart_ids = parse_ids(
            request.form.getlist('heart_ids')
        )

        replace_couple_chapter_links(
            chapter_id,
            requested_item_ids & valid_item_ids,
            requested_heart_ids & valid_heart_ids,
        )

        return redirect(url_for('pages.chapter', chapter_id=chapter_id))

    except Exception as e:
        log('error', f'Error while linking couple chapter {chapter_id}: {e}')
        return redirect(url_for(
            'pages.chapter',
            chapter_id=chapter_id,
            error='Die Verknüpfungen konnten nicht gespeichert werden.',
        ))


@pages_bp.route('/chapters/<int:chapter_id>/delete', methods=['POST'])
@jwt_required
def delete_chapter_page(chapter_id):
    sm_edition = get_setting_by_name('sm_edition').value
    if sm_edition != 'couples':
        return redirect(url_for('pages.home'))

    try:
        delete_couple_chapter(chapter_id)
    except Exception as e:
        log('error', f'Error while deleting couple chapter {chapter_id}: {e}')
        return redirect(url_for(
            'pages.chapter',
            chapter_id=chapter_id,
            error='Das Kapitel konnte nicht gelöscht werden.',
        ))

    return redirect(url_for('pages.chapters'))


@pages_bp.route('/story')
@jwt_required
def story():
    """Relationship-first chronology for the Couples edition."""
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        can_view_items = has_list_permission('View', 'Home')
        can_view_moments = has_list_permission('View', 'Moments')

        home_list_type = get_list_type_by_title('Home')
        moments_list_type = get_list_type_by_title('Moments')

        items = (
            get_items_by_type(
                home_list_type.id,
                'desc',
                edition=sm_edition,
            )
            if can_view_items and home_list_type
            else []
        )

        moments = (
            get_items_by_type(
                moments_list_type.id,
                'desc',
                edition=sm_edition,
            )
            if can_view_moments and moments_list_type
            else []
        )

        from app.heart_moments import list_heart_moments

        shared_heart_moments = list_heart_moments(
            g.user_id,
            filter_name='shared',
        )

        all_entries = _build_story_entries(
            items,
            moments,
            shared_heart_moments,
            can_view_items,
            can_view_moments,
        )

        chapter_link_map = get_couple_chapter_link_map()
        for entry in all_entries:
            if entry['type'] == 'heart':
                entry['chapters'] = chapter_link_map[
                    'heart_chapters'
                ].get(entry['id'], [])
            else:
                entry['chapters'] = chapter_link_map[
                    'item_chapters'
                ].get(entry['id'], [])

        entry_type = str(request.args.get('type', 'all')).strip().lower()
        allowed_types = {'all', 'memory', 'heart', 'milestone'}
        if entry_type not in allowed_types:
            entry_type = 'all'

        search_query = str(request.args.get('q', '')).strip()

        year_value = str(request.args.get('year', '')).strip()
        selected_year = None
        if year_value:
            try:
                selected_year = int(year_value)
            except ValueError:
                selected_year = None

        available_years = sorted(
            {entry['year'] for entry in all_entries},
            reverse=True,
        )

        if selected_year not in available_years:
            selected_year = None

        filtered_entries = _filter_story_entries(
            all_entries,
            entry_type,
            selected_year,
            search_query,
        )

        story_groups = _group_story_entries(filtered_entries)

        return render_template(
            'pages/story.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
            sm_edition=sm_edition,
            page_title='Unsere Geschichte',
            story_groups=story_groups,
            story_total=len(filtered_entries),
            story_type=entry_type,
            story_year=selected_year,
            story_years=available_years,
            story_query=search_query,
        )

    except Exception as e:
        log('error', f'Error while rendering story page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/manage-translations')
@jwt_required
@require_permission('Manage Translations')
def manage_translations():
    try:
        dev = request.args.get('dev')
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        settings = get_all_settings()
        supported_languages = get_supported_languages()
        translation_progresses = get_translation_progress()

        return render_template('pages/manage-translations.html', dev=dev, list_types=list_types, title=title, darkmode=darkmode, user_data=user_data, settings=settings, supported_languages=supported_languages, translation_progresses=translation_progresses)

    except Exception as e:
        log('error', f'Error while rendering the pages/manage-translations.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/settings')
@jwt_required
@require_permission('Read Setting')
def settings():
    try:
        settings = get_all_settings()
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        settings_type = 'settings'
        lang = os.environ.get('LANG', 'en')
        relationship_statuses = get_relationship_statuses_with_names(lang)
        supported_languages = get_supported_languages()

        sm_edition = get_setting_by_name('sm_edition').value

        from app.auth_settings import (
            get_auth_settings,
            get_effective_auth_settings,
        )
        from app.oidc import oidc_configured
        from app.oidc_identity import (
            get_oidc_identity_for_user,
        )
        from config import Config

        auth_settings = get_auth_settings()
        auth_effective_settings = (
            get_effective_auth_settings()
        )

        auth_current_user_oidc_linked = bool(
            get_oidc_identity_for_user(g.user_id)
        )

        return render_template(
            'pages/settings.html',
            settings=settings,
            list_types=list_types,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            settings_type=settings_type,
            relationship_statuses=relationship_statuses,
            supported_languages=supported_languages,
            sm_edition=sm_edition,
            auth_settings=auth_settings,
            auth_effective_settings=(
                auth_effective_settings
            ),
            auth_oidc_enabled=oidc_configured(),
            auth_current_user_oidc_linked=(
                auth_current_user_oidc_linked
            ),
            auth_force_local_login=(
                Config.AUTH_FORCE_LOCAL_LOGIN
            )
        )
    except Exception as e:
        log('error', f'Error while rendering the settings.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/user-settings')
@jwt_required
def user_settings():
    try:
        ensure_notification_settings(g.user_id)
        settings = get_all_settings()
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        user_settings = get_user_settings(g.user_id)
        settings_type = 'user-settings'
        supported_languages = get_supported_languages()

        smtp_available = bool(os.environ.get('SMTP_HOST', ''))
        telegram_available = bool(os.environ.get('TELEGRAM_BOT_TOKEN', ''))
        telegram_chat_id_setting = get_user_setting(g.user_id, 'notification_telegram_chat_id')
        telegram_chat_id = telegram_chat_id_setting.value if telegram_chat_id_setting else ''
        passkeys = get_passkeys_by_user(g.user_id)

        from app.oidc import oidc_configured
        from app.oidc_identity import (
            get_oidc_identity_for_user,
        )
        from config import Config

        oidc_identity = (
            get_oidc_identity_for_user(
                g.user_id
            )
        )

        return render_template(
            'pages/settings.html',
            settings=settings,
            list_types=list_types,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            user_settings=user_settings,
            settings_type=settings_type,
            supported_languages=supported_languages,
            smtp_available=smtp_available,
            telegram_available=telegram_available,
            telegram_chat_id=telegram_chat_id,
            passkeys=passkeys,
            oidc_enabled=oidc_configured(),
            oidc_identity=oidc_identity,
            oidc_provider_name=(
                Config.OIDC_PROVIDER_NAME
            ),
            oidc_result=request.args.get(
                'oidc'
            ),
            oidc_error=request.args.get(
                'oidc_error'
            )
        )
    except Exception as e:
        log('error', f'Error while rendering the settings.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/gallery/<int:id>')
@jwt_required
def gallery(id):
    try:
        item = get_item_by_id(id)

        if not item:
            return redirect(url_for('pages.home'))

        if not item.contentType.startswith('gallery'):
            return redirect(url_for('pages.home'))

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        return render_template('pages/gallery.html', item=item, list_types=list_types, title=title, darkmode=darkmode, user_data=user_data)
    except Exception as e:
        log('error', f'Error while rendering the pages/gallery.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/favicon.ico')
def favicon():
    favicon_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'images', 'favicon.ico')
    if os.path.exists(favicon_path):
        return send_file(favicon_path)
    return '', 204


@pages_bp.route('/migration-progress')
def migration_progress():
    try:
        from app.migration.status import load_status, STEPS
        status = load_status()
    except ImportError:
        status = None
        STEPS = []

    # If real migration is done, redirect to review page
    if status and status.get('completed_at') and not status.get('dry_run', False):
        return redirect('/migration-complete')

    error = None
    if status:
        # Top-level error (e.g. MySQL connection failure)
        if status.get('error'):
            error = status['error']
        else:
            for step_info in status.get('steps', {}).values():
                if step_info.get('status') == 'failed' and step_info.get('error'):
                    error = step_info['error']
                    break

    # Build ordered steps list
    steps_ordered = []
    status_steps = status.get('steps', {}) if status else {}
    for step_name in STEPS:
        steps_ordered.append((step_name, status_steps.get(step_name, {'status': 'pending'})))

    dry_run = status.get('dry_run', False) if status else False
    return render_template('pages/migration-progress.html', status=status, error=error, dry_run=dry_run, steps_ordered=steps_ordered)


@pages_bp.route('/migration-complete')
def migration_complete():
    from app.models import User, UserRole, Role, Item, SessionLocal
    try:
        from app.migration.status import load_status as load_migration_status
        status = load_migration_status()
    except ImportError:
        status = None

    # Dry-run: show progress instead
    if status and status.get('dry_run', False):
        return redirect('/migration-progress')

    # Only block access if migration review is already done (no loop risk)
    try:
        review = get_setting_by_name('migration_review_complete')
        if review and review.value == 'True':
            return redirect('/')
    except Exception:
        pass

    db_session = SessionLocal()
    try:
        users = db_session.query(User).filter(User.id > 1).all()
        roles = db_session.query(Role).all()

        # Build user data with current role
        user_data = []
        for u in users:
            user_role = db_session.query(UserRole).filter(UserRole.userID == u.id).first()
            current_role = ''
            if user_role:
                role = db_session.query(Role).filter(Role.id == user_role.roleID).first()
                current_role = role.roleName if role else ''
            user_data.append({
                'id': u.id,
                'firstName': u.firstName,
                'lastName': u.lastName or '',
                'email': u.email,
                'role': current_role,
            })

        has_placeholder = any(u['email'].endswith('@placeholder.local') for u in user_data)

        # Build summary
        summary = {}
        summary['Users'] = len(user_data)
        summary['Home Items'] = db_session.query(Item).filter(Item.listType == 1).count()
        summary['Moments'] = db_session.query(Item).filter(Item.listType == 2).count()
        summary['Movie List'] = db_session.query(Item).filter(Item.listType == 3).count()
        summary['Bucket List'] = db_session.query(Item).filter(Item.listType == 4).count()
    finally:
        db_session.close()

    languages = get_supported_languages()
    role_names = [r.roleName for r in roles if r.roleName != 'System']

    return render_template('pages/migration-complete.html',
        status=status, users=user_data, has_placeholder=has_placeholder, summary=summary,
        languages=languages, roles=role_names)


def _translate_reminder_title(reminder):
    """Translate auto-reminder titles using the current locale."""
    if not reminder.is_auto:
        return reminder.title

    if reminder.title in ('Anniversary', 'Wedding Day', 'Engagement Day', 'Family Day', 'Friendship Day'):
        return _(reminder.title)

    if reminder.auto_source and reminder.auto_source.startswith('user_birthday_'):
        try:
            uid = int(reminder.auto_source.replace('user_birthday_', ''))
            user = get_user_by_id(uid)
            if user:
                return _('Birthday of {name}').format(name=user.firstName)
        except (ValueError, TypeError):
            pass
        return reminder.title

    if reminder.auto_source and 'milestone_' in reminder.auto_source:
        days = reminder.milestone_days
        if days:
            if days % 365 == 0:
                return _('{n}-Year Milestone').format(n=days // 365)
            else:
                return _('{n}-Day Milestone').format(n=days)
        return reminder.title

    if reminder.auto_source and reminder.auto_source.startswith('countdown_'):
        item_title = reminder.title
        if item_title.startswith('Countdown: '):
            item_title = item_title[len('Countdown: '):]
        return _('Countdown: {title}').format(title=item_title)

    return _(reminder.title)


def _translate_reminder_description(reminder):
    """Translate auto-reminder descriptions using the current locale."""
    if not reminder.is_auto or not reminder.description:
        return reminder.description

    if reminder.auto_source and 'milestone_' in reminder.auto_source:
        return ''

    if reminder.auto_source and reminder.auto_source.startswith('countdown_'):
        item_title = reminder.title
        if item_title.startswith('Countdown: '):
            item_title = item_title[len('Countdown: '):]
        return _('Countdown "{title}" reached!').format(title=item_title)

    return reminder.description


@pages_bp.route('/reminders')
@jwt_required
@require_permission('View Reminders')
def reminders():
    try:
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        reminder_list = get_all_reminders()
        muted_ids = get_user_muted_reminder_ids(g.user_id)
        sm_edition = get_setting_by_name('sm_edition').value

        return render_template('pages/reminders.html',
            list_types=list_types, title=title, darkmode=darkmode, user_data=user_data,
            reminders=reminder_list, muted_ids=muted_ids,
            translate_title=_translate_reminder_title,
            translate_desc=_translate_reminder_description,
            page_title='Termine & Benachrichtigungen' if sm_edition == 'couples' else None)
    except Exception as e:
        log('error', f'Error while rendering reminders page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/<path:content_url>')
@jwt_required
def list_view(content_url):
    try:
        error_msg = []
        list_type = get_list_type_by_content_url(content_url)
        if not list_type:
            raise Exception(_('List type not found'))

        if not has_list_permission('View', list_type.title):
            return redirect(url_for('pages.home'))

        sm_edition = get_setting_by_name('sm_edition').value
        items = get_items_by_type(list_type.id, edition=sm_edition, checked_last=True)
        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        return render_template('pages/list.html',
                               items=items,
                               list_type=list_type.id,
                               list_types=list_types,
                               mainTitle=list_type.mainTitle,
                               title=title,
                               darkmode=darkmode,
                               user_data=user_data,
                               error_msg=error_msg,
                               list_type_title=list_type.title,
                               sm_edition=sm_edition)
    except Exception as e:
        log('error', f'Error while processing the list view: {e}')
        return "An error occurred while processing your request. Page not found.", 500


# ============================================================
# HEART MOMENTS PAGE START
# ============================================================

@pages_bp.route('/heart-moments')
@jwt_required
def heart_moments_page():
    try:
        sm_edition = get_setting_by_name('sm_edition').value

        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        list_types = get_all_list_types()
        title = get_display_title()
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        return render_template(
            'pages/heart-moments.html',
            list_types=list_types,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            current_user_id=g.user_id,
            sm_edition=sm_edition,
        )

    except Exception as e:
        log(
            'error',
            f'Error while rendering Heart Moments page: {e}'
        )

        return (
            'An error occurred while rendering the Heart Moments page.',
            500
        )


# ============================================================
# HEART MOMENTS PAGE END
# ============================================================
