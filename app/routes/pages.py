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
    ensure_notification_settings, get_passkeys_by_user, get_all_users)
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
            if reminder.reminder_type == 'countdown':
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
                'href': None,
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
            haystack = ' '.join((
                entry.get('type_label') or '',
                entry.get('title') or '',
                entry.get('text') or '',
                entry.get('author_name') or '',
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
            page_title='Wir' if sm_edition == 'couples' else None,
            memories_page=False,
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
            current_user_id=g.user_id,
        )
    except Exception as e:
        log('error', f'Error while rendering memories page: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


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
