import json
from datetime import date, datetime, timezone
from flask import Blueprint, g, jsonify, make_response, render_template, send_file, request, redirect, url_for, session
from app.db_queries import (get_all_list_types, get_items_by_type,
    get_supported_languages, get_translation_for_entity, get_translation_progress,
    get_translations_by_language, get_user_by_id, get_user_setting, update_user_setting, get_setting_by_name,
    get_item_by_id, create_item, update_item, delete_item, get_user_settings,
    get_list_type_by_content_url, get_all_settings,
    get_shared_item_ids, get_list_type_by_title, ensure_countdown_list_type,
    ensure_banner_song_setting, get_all_reminders, get_user_muted_reminder_ids,
    ensure_notification_settings, get_passkeys_by_user, get_all_users,
    get_couple_chapters, get_couple_chapter, create_couple_chapter,
    update_couple_chapter, delete_couple_chapter, get_couple_chapter_links,
    replace_couple_chapter_links, get_couple_chapter_link_map,
    get_couple_plans, get_couple_plan, create_couple_plan,
    update_couple_plan, delete_couple_plan, set_couple_plan_chapter,
    get_couple_bucket_plan_map, link_couple_bucket_plan,
    sync_bucket_item_to_plan, return_couple_plan_to_bucketlist,
    get_couple_places, get_couple_place,
    create_couple_place, update_couple_place, delete_couple_place,
    sync_couple_source_location, bootstrap_couple_places_from_existing_locations,
    get_couple_place_link_map, replace_couple_place_manual_links,
    copy_couple_place_links,
    get_private_entries, get_private_entry, create_private_entry,
    update_private_entry, delete_private_entry, count_private_entries,
    get_private_lists, get_private_list, count_private_lists,
    create_private_list, update_private_list, delete_private_list,
    create_private_list_item, toggle_private_list_item, delete_private_list_item,
    PRIVATE_GIFT_STATUSES
)
from app.feature_flags import is_feature_enabled
from app.logger import log
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from app.utils import generate_banner_text
from app.translation import _, set_locale
from app.routes.auth import jwt_required, login_jwt
from app.permissions import require_permission, has_list_permission, has_permission

pages_bp = Blueprint('pages', __name__)

# Paths that bypass the migration gate
_MIGRATION_ALLOWED_PREFIXES = ('/static/', '/api/v2/migration/', '/migration-complete',
                                '/migration-progress', '/manifest.json', '/sw.js',
                                '/offline', '/favicon.ico', '/.well-known/')


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

@pages_bp.route('/.well-known/assetlinks.json')
def asset_links():
    """Digital Asset Links: der Nachweis, dass diese Domain zur App gehoert.

    Ohne diese Datei zeigt die Android-App eine Adresszeile ueber der Seite -
    sie laeuft dann als Browser-Tab statt als App. Android laedt sie beim
    ersten Start und danach gelegentlich neu, immer ohne Anmeldung.

    Der Fingerabdruck kommt aus der Umgebung (ANDROID_APP_FINGERPRINT), damit
    der Wechsel vom Debug- auf einen eigenen Signaturschluessel keine
    Codeaenderung braucht. Mehrere Fingerabdruecke mit Komma trennen - so
    laufen alte und neue Installationen waehrend eines Wechsels parallel.
    """
    raw = os.environ.get('ANDROID_APP_FINGERPRINT', '').strip()
    fingerprints = [f.strip().upper() for f in raw.split(',') if f.strip()]

    payload = [{
        'relation': ['delegate_permission/common.handle_all_urls'],
        'target': {
            'namespace': 'android_app',
            'package_name': os.environ.get('ANDROID_APP_PACKAGE', 'de.sidebyside.app'),
            'sha256_cert_fingerprints': fingerprints,
        },
    }]

    response = make_response(jsonify(payload))
    response.headers['Content-Type'] = 'application/json'
    # Android faellt bei einem 404 dauerhaft auf die Adresszeile zurueck,
    # deshalb hier keine lange Zwischenspeicherung.
    response.headers['Cache-Control'] = 'public, max-age=300'
    return response


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
    return dict(_=_, translations_json=translations_json)



# Daily Questions navigation visibility v3
@pages_bp.app_context_processor
def inject_daily_questions_navigation():
    try:
        from app.daily_questions import daily_questions_enabled
        sm_edition = get_setting_by_name('sm_edition').value
        enabled = (
            sm_edition == 'couples'
            and daily_questions_enabled()
        )
    except Exception:
        enabled = False

    return {
        'daily_questions_nav_enabled': enabled,
    }


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
            response.data = render_template('pages/setup.html')
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
    private_gifts=None,
    private_birthdays=None,
):
    """Build a small, permission-aware list for the couple dashboard.

    Geschenke mit Anlassdatum kommen mit hinein, aber nur die eigenen: die
    Startseite wird pro Anmeldung gerendert, der Partner bekommt seine eigene
    Liste. Der Titel bleibt bewusst neutral - wer neben einem sitzt, soll
    nicht mitlesen koennen, was er bekommt.
    """
    today = date.today()
    upcoming = []

    for birthday in private_birthdays or []:
        next_date = birthday.get('next_date')
        if not next_date:
            continue

        name = birthday.get('title') or 'Geburtstag'
        upcoming.append({
            'type': 'birthday',
            'icon': 'cake',
            'title': f'Geburtstag {name}',
            'date': next_date,
            'date_label': next_date.strftime('%d.%m.%Y'),
            'relative_label': _relative_day_label(next_date, today),
            'private': True,
            'href': '/private?kind=birthday',
        })

    for gift in private_gifts or []:
        target_date = gift.get('targetDate')
        if not target_date or target_date < today or gift.get('status') == 'given':
            continue

        upcoming.append({
            'type': 'gift',
            'icon': 'card_giftcard',
            'title': gift.get('occasion') or 'Geschenkidee',
            'date': target_date,
            'date_label': target_date.strftime('%d.%m.%Y'),
            'relative_label': _relative_day_label(target_date, today),
            'private': True,
            'href': '/private?kind=gift',
        })

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
                'title': item.title or '',
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
        # Zweite Schranke neben dem Query-Filter: ein privater Herzmoment darf
        # niemals in Story, Startseite oder Jahresrueckblick auftauchen. Die
        # Aufrufer holen bereits nur 'shared' - hier wird es garantiert.
        if str(heart_moment.get('visibility') or 'shared') != 'shared':
            log(
                'warning',
                'Privater Herzmoment wurde aus der Chronik gefiltert '
                f"(id={heart_moment.get('id')})",
            )
            continue

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


def _build_couple_flashback(
    items,
    moments,
    shared_heart_moments,
    can_view_items,
    can_view_moments,
    today=None,
):
    """Was heute vor einem Jahr (oder mehr) passiert ist.

    Baut auf denselben Eintraegen auf wie die Story - keine zusaetzliche
    Tabelle, keine Kopien. Zuerst wird der exakte Tag gesucht; ist dort nichts,
    darf es die Woche drumherum sein, damit die Startseite nicht an neun von
    zehn Tagen leer bleibt.
    """
    today = today or date.today()

    entries = _build_story_entries(
        items,
        moments,
        shared_heart_moments,
        can_view_items,
        can_view_moments,
    )

    exact = []
    nearby = []

    for entry in entries:
        event_date = entry['event_date'].date() if isinstance(
            entry['event_date'], datetime
        ) else entry['event_date']

        years_ago = today.year - event_date.year
        if years_ago < 1:
            continue

        try:
            anniversary = event_date.replace(year=today.year)
        except ValueError:
            # 29. Februar in einem Nicht-Schaltjahr
            anniversary = event_date.replace(year=today.year, day=28)

        distance = abs((anniversary - today).days)
        if distance > 3:
            continue

        label = (
            'Heute vor einem Jahr' if years_ago == 1
            else f'Heute vor {years_ago} Jahren'
        )
        if distance:
            label = (
                'Vor einem Jahr' if years_ago == 1
                else f'Vor {years_ago} Jahren'
            )

        enriched = dict(entry)
        enriched['years_ago'] = years_ago
        enriched['flashback_label'] = label

        (exact if distance == 0 else nearby).append(enriched)

    selected = exact or nearby
    selected.sort(key=lambda entry: entry['event_date'], reverse=True)
    return selected[:3]


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
            place_names = ' '.join(
                place.get('name') or ''
                for place in entry.get('places', [])
            )
            haystack = ' '.join((
                entry.get('type_label') or '',
                entry.get('title') or '',
                entry.get('text') or '',
                entry.get('author_name') or '',
                chapter_titles,
                place_names,
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




def _relationship_date(value):
    """Normalize relationship feature dates to a plain date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _chapter_year_date(chapter):
    return (
        _relationship_date(chapter.get('startDate'))
        or _relationship_date(chapter.get('endDate'))
        or _relationship_date(chapter.get('dateCreated'))
    )


def _plan_year_date(plan, chapter_by_id):
    chapter_id = plan.get('chapterID')
    if chapter_id:
        chapter = chapter_by_id.get(chapter_id)
        chapter_date = _chapter_year_date(chapter) if chapter else None
        if chapter_date:
            return chapter_date

    return (
        _relationship_date(plan.get('targetStartDate'))
        or _relationship_date(plan.get('targetEndDate'))
        or _relationship_date(plan.get('dateModified'))
        or _relationship_date(plan.get('dateCreated'))
    )


def _enrich_story_entries_with_relationship_context(
    entries,
    chapter_link_map=None,
    place_link_map=None,
):
    """Attach chapters and canonical places to existing story entries."""
    chapter_link_map = chapter_link_map or get_couple_chapter_link_map()
    place_link_map = place_link_map or get_couple_place_link_map()

    for entry in entries:
        if entry['type'] == 'heart':
            entry['chapters'] = chapter_link_map['heart_chapters'].get(
                entry['id'],
                [],
            )
        else:
            entry['chapters'] = chapter_link_map['item_chapters'].get(
                entry['id'],
                [],
            )

        collected_places = []
        seen_place_ids = set()

        for place in place_link_map['source_places'].get(
            (entry['type'], entry['id']),
            [],
        ):
            if place['id'] not in seen_place_ids:
                collected_places.append(place)
                seen_place_ids.add(place['id'])

        # Story content inside a chapter inherits the chapter's place without
        # duplicating persisted links for every individual item.
        for chapter in entry['chapters']:
            for place in place_link_map['source_places'].get(
                ('chapter', chapter['id']),
                [],
            ):
                if place['id'] not in seen_place_ids:
                    collected_places.append(place)
                    seen_place_ids.add(place['id'])

        entry['places'] = collected_places

    return chapter_link_map, place_link_map


def _build_couple_year_snapshot(
    selected_year,
    user_id,
    items=None,
    moments=None,
    shared_heart_moments=None,
):
    """Build the automatic relationship recap without creating new data.

    Dates come from the source feature itself wherever possible. Legacy
    Bucketlist rows do not have a dedicated completion timestamp, so their
    existing dateModified value is used as the best available completion date.
    """
    can_view_items = has_list_permission('View', 'Home')
    can_view_moments = has_list_permission('View', 'Moments')

    if items is None:
        home_list_type = get_list_type_by_title('Home')
        items = (
            get_items_by_type(
                home_list_type.id,
                'desc',
            )
            if can_view_items and home_list_type
            else []
        )

    if moments is None:
        moments_list_type = get_list_type_by_title('Moments')
        moments = (
            get_items_by_type(
                moments_list_type.id,
                'desc',
            )
            if can_view_moments and moments_list_type
            else []
        )

    if shared_heart_moments is None:
        from app.heart_moments import list_heart_moments
        shared_heart_moments = list_heart_moments(
            user_id,
            filter_name='shared',
        )

    story_entries = _build_story_entries(
        items,
        moments,
        shared_heart_moments,
        can_view_items,
        can_view_moments,
    )

    # 4E intentionally promotes location strings to canonical places. Doing
    # this here keeps the yearly place count correct even when /places has not
    # been opened yet.
    bootstrap_couple_places_from_existing_locations()
    chapter_link_map = get_couple_chapter_link_map()
    place_link_map = get_couple_place_link_map()
    _enrich_story_entries_with_relationship_context(
        story_entries,
        chapter_link_map=chapter_link_map,
        place_link_map=place_link_map,
    )

    content = {
        'entries': story_entries,
        'memories': items,
        'moments': moments,
        'heart_moments': shared_heart_moments,
        'can_view_items': can_view_items,
        'can_view_moments': can_view_moments,
    }

    chapters = get_couple_chapters()
    chapter_by_id = {chapter['id']: chapter for chapter in chapters}
    chapter_summaries = []
    for chapter in chapters:
        summary = _chapter_summary(
            chapter,
            chapter_link_map['by_chapter'].get(
                chapter['id'],
                {'item_ids': set(), 'heart_ids': set()},
            ),
            content,
        )
        summary['year_date'] = _chapter_year_date(chapter)
        chapter_summaries.append(summary)

    plans = get_couple_plans()
    plan_by_id = {plan['id']: plan for plan in plans}
    for plan in plans:
        plan['year_date'] = _plan_year_date(plan, chapter_by_id)

    plan_map = get_couple_bucket_plan_map()
    bucket_list_type = _get_bucket_list_type()
    bucket_rows = []
    if (
        bucket_list_type
        and has_list_permission('View', bucket_list_type.title)
    ):
        bucket_rows = get_items_by_type(
            bucket_list_type.id,
            'desc',
            checked_last=True,
        )

    bucket_completed = []
    for item, creator in bucket_rows:
        if str(item.content or '').strip() != '1':
            continue

        linked_plan_meta = plan_map.get(item.id)
        linked_plan = (
            plan_by_id.get(linked_plan_meta['id'])
            if linked_plan_meta else None
        )
        completion_date = (
            linked_plan.get('year_date')
            if linked_plan
            and linked_plan.get('status') == 'experienced'
            else None
        )
        completion_date = (
            completion_date
            or _relationship_date(item.dateModified)
            or _relationship_date(item.dateCreated)
        )

        bucket_completed.append({
            'id': item.id,
            'title': item.title or 'Bucketlist-Wunsch',
            'creator': creator,
            'plan': linked_plan,
            'year_date': completion_date,
        })

    # ===== Daily Questions recap integration v3 =====
    daily_question_recap = {
        'enabled': False,
        'answered': 0,
        'answers': 0,
        'by_month': {},
        'available_years': [],
    }
    try:
        from app.daily_questions import get_daily_question_recap_stats
        daily_question_recap = get_daily_question_recap_stats(selected_year)
    except Exception as exc:
        log(
            'warning',
            f'Daily Questions recap statistics unavailable for '
            f'{selected_year}: {exc}',
        )

    years = {date.today().year, selected_year}
    years.update(daily_question_recap.get('available_years', []))
    years.update(entry['year'] for entry in story_entries)
    years.update(
        chapter['year_date'].year
        for chapter in chapter_summaries
        if chapter.get('year_date')
    )
    years.update(
        plan['year_date'].year
        for plan in plans
        if plan.get('status') == 'experienced'
        and plan.get('year_date')
    )
    years.update(
        item['year_date'].year
        for item in bucket_completed
        if item.get('year_date')
    )
    available_years = sorted(years, reverse=True)

    year_story = [
        entry for entry in story_entries
        if entry['year'] == selected_year
    ]
    year_chapters = [
        chapter for chapter in chapter_summaries
        if chapter.get('year_date')
        and chapter['year_date'].year == selected_year
    ]
    year_plans = [
        plan for plan in plans
        if plan.get('status') == 'experienced'
        and plan.get('year_date')
        and plan['year_date'].year == selected_year
    ]
    year_bucket = [
        item for item in bucket_completed
        if item.get('year_date')
        and item['year_date'].year == selected_year
    ]

    # A Bucketlist wish promoted into a Plan represents the same achievement.
    # Keep the Bucketlist card in the highlights and avoid a duplicate plan
    # highlight for that exact relationship.
    bucket_plan_ids = {
        item['plan']['id']
        for item in year_bucket
        if item.get('plan')
    }

    highlights = [dict(entry) for entry in year_story]

    for chapter in year_chapters:
        event_date = chapter['year_date']
        highlights.append({
            'type': 'chapter',
            'type_label': 'Kapitel',
            'icon': 'auto_stories',
            'id': chapter['id'],
            'title': chapter['title'],
            'text': chapter.get('description') or '',
            'event_date': datetime.combine(event_date, datetime.min.time()),
            'date_label': event_date.strftime('%d.%m.%Y'),
            'image_url': chapter.get('cover_url'),
            'href': f"/chapters/{chapter['id']}",
            'places': place_link_map['source_places'].get(
                ('chapter', chapter['id']),
                [],
            ),
        })

    for plan in year_plans:
        if plan['id'] in bucket_plan_ids or plan.get('chapterID'):
            continue
        event_date = plan['year_date']
        highlights.append({
            'type': 'plan',
            'type_label': 'Plan erlebt',
            'icon': 'done_all',
            'id': plan['id'],
            'title': plan['title'],
            'text': plan.get('description') or '',
            'event_date': datetime.combine(event_date, datetime.min.time()),
            'date_label': event_date.strftime('%d.%m.%Y'),
            'image_url': None,
            'href': f"/plans#plan-{plan['id']}",
            'places': place_link_map['source_places'].get(
                ('plan', plan['id']),
                [],
            ),
        })

    for item in year_bucket:
        event_date = item['year_date']
        linked_plan = item.get('plan')
        inherited_places = (
            place_link_map['source_places'].get(
                ('plan', linked_plan['id']),
                [],
            )
            if linked_plan else []
        )
        highlights.append({
            'type': 'bucket',
            'type_label': 'Bucketlist erfüllt',
            'icon': 'checklist',
            'id': item['id'],
            'title': item['title'],
            'text': '',
            'event_date': datetime.combine(event_date, datetime.min.time()),
            'date_label': event_date.strftime('%d.%m.%Y'),
            'image_url': None,
            'href': f"/bucketlist?status=done#bucket-{item['id']}",
            'places': inherited_places,
        })

    priority = {
        'chapter': 0,
        'heart': 1,
        'milestone': 2,
        'bucket': 3,
        'plan': 4,
        'memory': 5,
    }

    monthly = {}
    for highlight in highlights:
        event_dt = _as_datetime(highlight.get('event_date'))
        if not event_dt:
            continue
        monthly.setdefault(event_dt.month, []).append(highlight)

    month_groups = []
    for month in sorted(monthly):
        candidates = list(monthly[month])
        chronological = sorted(
            candidates,
            key=lambda entry: _as_datetime(entry['event_date']),
        )
        priority_candidates = sorted(
            candidates,
            key=lambda entry: (
                priority.get(entry.get('type'), 99),
                -_as_datetime(entry['event_date']).timestamp(),
            ),
        )
        selected = sorted(
            priority_candidates[:4],
            key=lambda entry: _as_datetime(entry['event_date']),
        )

        month_place_map = {}
        for entry in chronological:
            for place in entry.get('places') or []:
                month_place_map.setdefault(place['id'], place)
        month_places = sorted(
            month_place_map.values(),
            key=lambda place: place['name'].casefold(),
        )

        month_cover_images = []
        seen_month_images = set()
        for entry in reversed(chronological):
            image_url = entry.get('image_url')
            if not image_url or image_url in seen_month_images:
                continue
            month_cover_images.append({
                'url': image_url,
                'href': entry.get('href') or f'/story?year={selected_year}',
                'title': entry.get('title') or entry.get('type_label') or 'Moment',
            })
            seen_month_images.add(image_url)
            if len(month_cover_images) >= 8:
                break

        month_stats = {
            'memories': sum(1 for entry in chronological if entry['type'] == 'memory'),
            'hearts': sum(1 for entry in chronological if entry['type'] == 'heart'),
            'milestones': sum(1 for entry in chronological if entry['type'] == 'milestone'),
            'chapters': sum(1 for entry in chronological if entry['type'] == 'chapter'),
            'bucket': sum(1 for entry in chronological if entry['type'] == 'bucket'),
            'plans': sum(1 for entry in chronological if entry['type'] == 'plan'),
            'places': len(month_places),
        }

        month_groups.append({
            'month': month,
            'label': _STORY_MONTH_NAMES[month],
            'entries': selected,
            'all_entries': chronological,
            'total': len(chronological),
            'cover_images': month_cover_images,
            'places': month_places,
            'stats': month_stats,
        })


    # Add jointly answered Daily Questions to the monthly recap metadata.
    question_counts_by_month = {
        int(month_number): int(count)
        for month_number, count in (
            daily_question_recap.get('by_month') or {}
        ).items()
        if int(count) > 0
    }

    month_group_by_month = {
        int(group.get('month', 0)): group
        for group in month_groups
    }

    for month_number, question_count in sorted(
        question_counts_by_month.items()
    ):
        group = month_group_by_month.get(month_number)
        if group is None:
            group = {
                'month': month_number,
                'label': _STORY_MONTH_NAMES[month_number],
                'entries': [],
                'all_entries': [],
                'total': 0,
                'cover_images': [],
                'places': [],
                'stats': {},
            }
            month_groups.append(group)
            month_group_by_month[month_number] = group

        group.setdefault('stats', {})
        group['stats']['questions'] = question_count

    for group in month_groups:
        group.setdefault('stats', {})
        group['stats'].setdefault('questions', 0)

    month_groups.sort(key=lambda group: int(group.get('month', 0)))

    # Collect unique places touched by any relationship content in the year.
    place_usage = {}
    seen_place_sources = set()

    def add_places(places, source_key):
        for place in places or []:
            key = (place['id'], source_key)
            if key in seen_place_sources:
                continue
            seen_place_sources.add(key)
            bucket = place_usage.setdefault(place['id'], {
                'id': place['id'],
                'name': place['name'],
                'count': 0,
            })
            bucket['count'] += 1

    for entry in year_story:
        add_places(
            entry.get('places'),
            f"story:{entry['type']}:{entry['id']}",
        )
    for chapter in year_chapters:
        add_places(
            place_link_map['source_places'].get(
                ('chapter', chapter['id']),
                [],
            ),
            f"chapter:{chapter['id']}",
        )
    for plan in year_plans:
        add_places(
            place_link_map['source_places'].get(
                ('plan', plan['id']),
                [],
            ),
            f"plan:{plan['id']}",
        )

    year_places = sorted(
        place_usage.values(),
        key=lambda place: (-place['count'], place['name'].casefold()),
    )

    # A few real photos make the recap feel like a relationship page rather
    # than a dashboard. Reuse existing private media URLs; no copies are made.
    cover_images = []
    seen_images = set()
    for entry in sorted(
        year_story,
        key=lambda entry: entry['event_date'],
        reverse=True,
    ):
        image_url = entry.get('image_url')
        if image_url and image_url not in seen_images:
            cover_images.append({
                'url': image_url,
                'href': entry.get('href') or f'/story?year={selected_year}',
                'title': entry.get('title') or entry.get('type_label') or 'Moment',
            })
            seen_images.add(image_url)
        # Keep the hero lively without turning the recap into a full gallery.
        # Additional pictures stay available in the story/highlight sections.
        if len(cover_images) >= 12:
            break

    stats = {
        'memories': sum(1 for entry in year_story if entry['type'] == 'memory'),
        'hearts': sum(1 for entry in year_story if entry['type'] == 'heart'),
        'milestones': sum(1 for entry in year_story if entry['type'] == 'milestone'),
        'chapters': len(year_chapters),
        'places': len(year_places),
        'bucket': len(year_bucket),
        'plans': len(year_plans),
        'questions': int(daily_question_recap.get('answered', 0)),
    }
    # DQ MODULAR SUITE V3: merge questions into the existing recap model.
    from app.daily_questions_extras import enrich_month_groups_with_daily_questions
    month_groups, daily_question_recap = enrich_month_groups_with_daily_questions(
        month_groups,
        selected_year,
    )
    stats['questions'] = int(daily_question_recap.get('answered', 0))
    available_years = sorted(
        set(available_years)
        | set(daily_question_recap.get('available_years', [])),
        reverse=True,
    )

    return {
        'year': selected_year,
        'available_years': available_years,
        'story_entries': year_story,
        'chapters': year_chapters,
        'plans': year_plans,
        'plans_for_achievements': [
            plan for plan in year_plans
            if plan['id'] not in bucket_plan_ids
        ],
        'bucket_completed': year_bucket,
        'month_groups': month_groups,
        'places': year_places,
        'cover_images': cover_images,
        'stats': stats,
        'daily_questions': daily_question_recap,
        'has_content': bool(
            year_story or year_chapters or year_plans or year_bucket
            or daily_question_recap.get('answered', 0)
            or stats.get('questions', 0)
        ),
    }


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


def _couple_content_for_chapters(user_id):
    can_view_items = has_list_permission('View', 'Home')
    can_view_moments = has_list_permission('View', 'Moments')

    home_list_type = get_list_type_by_title('Home')
    moments_list_type = get_list_type_by_title('Moments')

    memories = (
        get_items_by_type(
            home_list_type.id,
            'desc',
        )
        if can_view_items and home_list_type
        else []
    )

    moments = (
        get_items_by_type(
            moments_list_type.id,
            'desc',
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
    if plan.get('status') == 'experienced' and plan.get('experiencedDate'):
        return 'Erlebt am ' + plan['experiencedDate'].strftime('%d.%m.%Y')

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
        'experienced_input': (
            plan['experiencedDate'].isoformat()
            if plan.get('experiencedDate') else ''
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
        experienced_date = _parse_optional_form_date(
            request.form.get('experienced_date')
        )
    except ValueError as exc:
        raise ValueError('Bitte verwende gültige Datumsangaben.') from exc

    if (
        target_start_date
        and target_end_date
        and target_end_date < target_start_date
    ):
        raise ValueError('Das Enddatum darf nicht vor dem Startdatum liegen.')

    if status != 'experienced':
        experienced_date = None

    return {
        'title': title,
        'description': description,
        'status': status,
        'target_start_date': target_start_date,
        'target_end_date': target_end_date,
        'experienced_date': experienced_date,
        'location_name': location_name,
    }



def _parse_optional_float(value):
    value = str(value or '').strip()
    if not value:
        return None
    return float(value.replace(',', '.'))


def _place_form_values():
    name = str(request.form.get('name', '')).strip()
    description = str(request.form.get('description', '')).strip()
    address_label = str(request.form.get('address_label', '')).strip()

    if not name:
        raise ValueError('Bitte gib dem Ort einen Namen.')
    if len(name) > 255:
        raise ValueError('Der Ortsname darf höchstens 255 Zeichen lang sein.')

    try:
        latitude = _parse_optional_float(request.form.get('latitude'))
        longitude = _parse_optional_float(request.form.get('longitude'))
    except ValueError as exc:
        raise ValueError('Die Kartenposition ist ungültig.') from exc

    if (latitude is None) != (longitude is None):
        raise ValueError('Bitte wähle eine vollständige Kartenposition.')
    if latitude is not None and not (-90 <= latitude <= 90):
        raise ValueError('Der Breitengrad ist ungültig.')
    if longitude is not None and not (-180 <= longitude <= 180):
        raise ValueError('Der Längengrad ist ungültig.')

    return {
        'name': name,
        'description': description,
        'address_label': address_label,
        'latitude': latitude,
        'longitude': longitude,
    }


def _place_map_config():
    return {
        'tile_url': os.environ.get(
            'MAP_TILE_URL',
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        ),
        'attribution': os.environ.get(
            'MAP_TILE_ATTRIBUTION',
            '&copy; OpenStreetMap-Mitwirkende',
        ),
        'default_lat': float(os.environ.get('MAP_DEFAULT_LAT', '51.1657')),
        'default_lon': float(os.environ.get('MAP_DEFAULT_LON', '10.4515')),
        'default_zoom': int(os.environ.get('MAP_DEFAULT_ZOOM', '6')),
    }


def _couple_place_candidates(user_id):
    """Return everything that can be connected to a shared place."""
    content = _couple_content_for_chapters(user_id)
    candidates = []

    for entry in content['entries']:
        candidate = dict(entry)
        candidate.update({
            'source_type': entry['type'],
            'source_id': entry['id'],
            'sort_date': (
                entry['event_date'].date()
                if isinstance(entry.get('event_date'), datetime)
                else entry.get('event_date')
            ),
        })
        candidates.append(candidate)

    for raw_plan in get_couple_plans():
        plan = _present_couple_plan(raw_plan, user_id)
        creator = plan.get('creator') or {}
        created = plan.get('dateCreated')
        candidates.append({
            'source_type': 'plan',
            'source_id': plan['id'],
            'type': 'plan',
            'type_label': 'Plan',
            'icon': plan['status_icon'],
            'id': plan['id'],
            'title': plan['title'],
            'text': plan['description'],
            'date_label': plan['date_label'],
            'author_name': creator.get('firstName', ''),
            'author_picture': creator.get('profilePicture'),
            'image_url': None,
            'href': f"/plans#plan-{plan['id']}",
            'sort_date': (
                plan.get('targetStartDate')
                or (
                    created.date()
                    if created and hasattr(created, 'date')
                    else date.min
                )
            ),
        })

    for chapter in get_couple_chapters():
        creator = chapter.get('creator') or {}
        created = chapter.get('dateCreated')
        candidates.append({
            'source_type': 'chapter',
            'source_id': chapter['id'],
            'type': 'chapter',
            'type_label': 'Kapitel',
            'icon': 'auto_stories',
            'id': chapter['id'],
            'title': chapter['title'],
            'text': chapter['description'],
            'date_label': _chapter_date_label(chapter),
            'author_name': creator.get('firstName', ''),
            'author_picture': creator.get('profilePicture'),
            'image_url': None,
            'href': f"/chapters/{chapter['id']}",
            'sort_date': (
                chapter.get('startDate')
                or (
                    created.date()
                    if created and hasattr(created, 'date')
                    else date.min
                )
            ),
        })

    candidates.sort(
        key=lambda entry: (
            entry.get('sort_date') or date.min,
            entry.get('source_id') or 0,
        ),
        reverse=True,
    )
    return candidates


def _couple_place_summary(
    place,
    link_map,
    candidate_index,
    chapter_link_map=None,
):
    linked = []
    linked_keys = set()
    linked_chapter_ids = set()

    for source in link_map['by_place'].get(place['id'], []):
        key = (source['source_type'], source['source_id'])
        candidate = candidate_index.get(key)
        if not candidate:
            continue
        entry = dict(candidate)
        entry['relation_kind'] = source['relation_kind']
        linked.append(entry)
        linked_keys.add(key)
        if source['source_type'] == 'chapter':
            linked_chapter_ids.add(source['source_id'])

    # Content inside a chapter inherits the chapter's place for display. The
    # relationship stays virtual, so no duplicate database rows are created.
    if chapter_link_map:
        for chapter_id in linked_chapter_ids:
            chapter_links = chapter_link_map['by_chapter'].get(
                chapter_id,
                {'item_ids': set(), 'heart_ids': set()},
            )

            inherited_keys = []
            for item_id in chapter_links.get('item_ids', set()):
                for source_type in ('memory', 'milestone'):
                    key = (source_type, item_id)
                    if key in candidate_index:
                        inherited_keys.append(key)
                        break
            for heart_id in chapter_links.get('heart_ids', set()):
                inherited_keys.append(('heart', heart_id))

            for key in inherited_keys:
                if key in linked_keys:
                    continue
                candidate = candidate_index.get(key)
                if not candidate:
                    continue
                entry = dict(candidate)
                entry['relation_kind'] = 'chapter'
                linked.append(entry)
                linked_keys.add(key)

    linked.sort(
        key=lambda entry: (
            entry.get('sort_date') or date.min,
            entry.get('source_id') or 0,
        ),
        reverse=True,
    )

    cover_url = next(
        (
            entry.get('image_url')
            for entry in linked
            if entry.get('image_url')
        ),
        None,
    )

    result = dict(place)
    result.update({
        'linked_entries': linked,
        'entry_count': len(linked),
        'memory_count': sum(1 for e in linked if e['type'] == 'memory'),
        'heart_count': sum(1 for e in linked if e['type'] == 'heart'),
        'milestone_count': sum(1 for e in linked if e['type'] == 'milestone'),
        'plan_count': sum(1 for e in linked if e['type'] == 'plan'),
        'chapter_count': sum(1 for e in linked if e['type'] == 'chapter'),
        'cover_url': cover_url,
        'map_ready': (
            place.get('latitude') is not None
            and place.get('longitude') is not None
        ),
    })
    return result


def _attach_source_places(entries, source_type, link_map):
    for entry in entries:
        places = list(link_map['source_places'].get(
            (source_type, entry['id']),
            [],
        ))
        places.sort(
            key=lambda place: (
                0 if place.get('relation_kind') == 'location' else 1,
                place.get('name', '').casefold(),
            )
        )
        entry['places'] = places
    return entries




_COUPLE_THINKING_SETTING = 'couple_thinking_of_you_last_sent_at'
_COUPLE_THINKING_COOLDOWN_SECONDS = 30 * 60


_COUPLE_THINKING_PENDING_SETTING = 'couple_thinking_of_you_pending'
_COUPLE_THINKING_DELIVERED_SETTING = 'couple_thinking_of_you_last_delivered'


def _couple_thinking_pending_signal(user_id):
    """Return the pending Thinking-of-you signal for a user, if valid."""
    setting = get_user_setting(user_id, _COUPLE_THINKING_PENDING_SETTING)
    if not setting or not setting.value:
        return None

    try:
        payload = json.loads(setting.value)
        signal_id = str(payload.get('id') or '').strip()
        sender_user_id = int(payload.get('sender_user_id'))
        sent_at = str(payload.get('sent_at') or '').strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not signal_id or sender_user_id <= 0 or not sent_at:
        return None

    return {
        'id': signal_id,
        'sender_user_id': sender_user_id,
        'sent_at': sent_at,
    }


def _couple_partner_for_user(user_id):
    """Return the other account from the two-user Couples setup."""
    couple_users = sorted(
        get_all_users(),
        key=lambda user: user.id,
    )[:2]

    # Never silently assign one of the first two users as partner to a third
    # account if an installation contains additional normal users.
    if not any(user.id == user_id for user in couple_users):
        return None

    return next(
        (user for user in couple_users if user.id != user_id),
        None,
    )


def _couple_thinking_retry_after(user_id, now=None):
    """Return the remaining cooldown in seconds for a Thinking-of-you ping."""
    last_sent = get_user_setting(user_id, _COUPLE_THINKING_SETTING)
    if not last_sent or not last_sent.value:
        return 0

    try:
        sent_at = datetime.fromisoformat(last_sent.value)
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        else:
            sent_at = sent_at.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return 0

    now = now or datetime.now(timezone.utc)
    elapsed = int((now - sent_at).total_seconds())
    return max(0, _COUPLE_THINKING_COOLDOWN_SECONDS - elapsed)

@pages_bp.route('/home')
@jwt_required
def home():
    try:
        list_type = 1
        items = get_items_by_type(list_type, 'desc', )
        list_types = get_all_list_types()
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        settings = get_all_settings()
        list_type_moments = 2
        moments = get_items_by_type(list_type_moments, 'asc', )
        banner_text = generate_banner_text()
        shared_item_ids = get_shared_item_ids()

        ensure_countdown_list_type()
        ensure_banner_song_setting()
        countdown_list_type = get_list_type_by_title('Countdown')
        countdowns = get_items_by_type(
            countdown_list_type.id,
            'asc',
        ) if countdown_list_type else []
        countdown_list_type_id = countdown_list_type.id if countdown_list_type else ''

        heart_moment_memory = None
        couple_users = []
        couple_partner = None
        couple_thinking_retry_after = 0
        couple_home_upcoming = []
        couple_home_recent = []
        couple_home_plans = []
        couple_home_year = None
        couple_home_flashback = []

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
        if any(user.id == g.user_id for user in couple_users):
            couple_partner = next(
                (user for user in couple_users if user.id != g.user_id),
                None,
            )
        if couple_partner:
            couple_thinking_retry_after = _couple_thinking_retry_after(g.user_id)

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

        private_gifts = []
        private_birthdays = []
        if is_feature_enabled('private_gifts'):
            private_gifts = get_private_entries(g.user_id, 'gift')
            private_birthdays = [
                _present_private_entry(entry)
                for entry in get_private_entries(g.user_id, 'birthday')
            ]

        couple_home_upcoming = _build_couple_home_upcoming(
            countdowns,
            reminder_list,
            muted_ids,
            can_view_countdowns,
            can_view_reminders,
            private_gifts,
            private_birthdays,
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

        couple_home_year = _build_couple_year_snapshot(
            date.today().year,
            g.user_id,
            items=items,
            moments=moments,
            shared_heart_moments=shared_heart_moments,
        )

        couple_home_flashback = _build_couple_flashback(
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
            list_type_title='Home',
            moments_title='Moments',
            shared_item_ids=shared_item_ids,
            countdowns=countdowns,
            countdown_title='Countdown',
            countdown_list_type_id=countdown_list_type_id,
            heart_moment_memory=heart_moment_memory,
            couple_users=couple_users,
            couple_partner=couple_partner,
            couple_thinking_retry_after=couple_thinking_retry_after,
            couple_home_upcoming=couple_home_upcoming,
            couple_home_recent=couple_home_recent,
            couple_home_plans=couple_home_plans,
            couple_home_year=couple_home_year,
            couple_home_flashback=couple_home_flashback,
            page_title='Wir',
            memories_page=False,
            milestones_page=False,
            current_user_id=g.user_id,
        )

    except Exception as e:
        log('error', f'Error while rendering the pages/home.html-Template: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500




@pages_bp.route('/couple/thinking-of-you', methods=['POST'])
@jwt_required
def couple_thinking_of_you():
    """Store an in-app couple signal and optionally nudge the partner externally."""
    if not request.is_json:
        return jsonify(
            status='error',
            message='Ungültige Anfrage.',
        ), 415

    sender = get_user_by_id(g.user_id)
    partner = _couple_partner_for_user(g.user_id)
    if not sender or not partner:
        return jsonify(
            status='error',
            message='Es konnte kein Partnerkonto ermittelt werden.',
        ), 409

    retry_after = _couple_thinking_retry_after(g.user_id)
    if retry_after > 0:
        return jsonify(
            status='error',
            message='Du hast gerade schon ein Zeichen geschickt.',
            data={'retry_after': retry_after},
        ), 429

    sender_name = (sender.firstName or '').strip() or 'Dein Partner'
    partner_name = (partner.firstName or '').strip() or 'deinen Partner'
    sent_at = datetime.now(timezone.utc)
    signal_id = uuid4().hex

    # The app itself is the reliable delivery path. This is intentionally stored
    # before trying optional push/e-mail/Telegram channels, so a missing external
    # channel never makes the signal fail.
    update_user_setting(
        partner.id,
        _COUPLE_THINKING_PENDING_SETTING,
        json.dumps({
            'id': signal_id,
            'sender_user_id': g.user_id,
            'sent_at': sent_at.isoformat(timespec='seconds'),
        }),
    )
    update_user_setting(
        g.user_id,
        _COUPLE_THINKING_SETTING,
        sent_at.isoformat(timespec='seconds'),
    )

    external_notification_sent = False
    try:
        from app.notifications import send_notification

        delivery_results = send_notification(
            partner.id,
            f'❤️ {sender_name} denkt an dich',
            'Ein kleines Zeichen nur für dich.',
            url='/home',
        )
        external_notification_sent = any(delivery_results.values())
    except Exception as exc:
        # The in-app signal is already persisted. External delivery is only a
        # best-effort nudge and must not turn a valid signal into an error.
        log('warning', f'Could not send external thinking-of-you notification: {exc}')

    log(
        'info',
        'Thinking-of-you signal stored '
        f'from user {g.user_id} to user {partner.id}; '
        f'external_notification_sent={external_notification_sent}',
    )

    return jsonify(
        status='success',
        message=f'Dein Zeichen an {partner_name} wurde gesendet.',
        data={
            'cooldown_seconds': _COUPLE_THINKING_COOLDOWN_SECONDS,
            'delivery_state': 'sent',
            'external_notification_sent': external_notification_sent,
        },
    )


@pages_bp.route('/couple/thinking-of-you/pending', methods=['GET'])
@jwt_required
def couple_thinking_of_you_pending():
    """Return the current user's pending in-app couple signal."""
    partner = _couple_partner_for_user(g.user_id)
    signal = _couple_thinking_pending_signal(g.user_id)
    if not partner or not signal or signal['sender_user_id'] != partner.id:
        return jsonify(status='success', data={'signal': None})

    sender_name = (partner.firstName or '').strip() or 'Dein Partner'
    return jsonify(
        status='success',
        data={
            'signal': {
                'id': signal['id'],
                'sender_user_id': signal['sender_user_id'],
                'sender_name': sender_name,
                'sent_at': signal['sent_at'],
            },
        },
    )


@pages_bp.route('/couple/thinking-of-you/delivered', methods=['POST'])
@jwt_required
def couple_thinking_of_you_delivered():
    """Acknowledge a signal after its in-app arrival animation has been shown."""
    if not request.is_json:
        return jsonify(status='error', message='Ungültige Anfrage.'), 415

    payload = request.get_json(silent=True) or {}
    signal_id = str(payload.get('signal_id') or '').strip()
    if not signal_id:
        return jsonify(status='error', message='Signal-ID fehlt.'), 400

    partner = _couple_partner_for_user(g.user_id)
    signal = _couple_thinking_pending_signal(g.user_id)

    # Idempotent acknowledgement: if the signal was already cleared by another
    # page lifecycle event, there is nothing left to do.
    if not signal or signal['id'] != signal_id:
        return jsonify(status='success', data={'delivered': False})

    if not partner or signal['sender_user_id'] != partner.id:
        return jsonify(status='error', message='Ungültiges Signal.'), 409

    delivered_at = datetime.now(timezone.utc)
    update_user_setting(g.user_id, _COUPLE_THINKING_PENDING_SETTING, '')
    update_user_setting(
        signal['sender_user_id'],
        _COUPLE_THINKING_DELIVERED_SETTING,
        json.dumps({
            'id': signal['id'],
            'recipient_user_id': g.user_id,
            'sent_at': signal['sent_at'],
            'delivered_at': delivered_at.isoformat(timespec='seconds'),
        }),
    )

    log(
        'info',
        f'Thinking-of-you signal {signal_id} delivered to user {g.user_id}',
    )
    return jsonify(
        status='success',
        data={
            'delivered': True,
            'delivered_at': delivered_at.isoformat(timespec='seconds'),
        },
    )


@pages_bp.route('/couple/thinking-of-you/status', methods=['GET'])
@jwt_required
def couple_thinking_of_you_status():
    """Return the delivery state of the current user's latest couple signal."""
    partner = _couple_partner_for_user(g.user_id)
    if not partner:
        return jsonify(status='success', data={'state': 'none', 'retry_after': 0})

    last_sent = get_user_setting(g.user_id, _COUPLE_THINKING_SETTING)
    retry_after = _couple_thinking_retry_after(g.user_id)
    if not last_sent or not last_sent.value:
        return jsonify(
            status='success',
            data={'state': 'none', 'retry_after': retry_after},
        )

    sent_at = str(last_sent.value).strip()
    state = 'sent'
    delivered_at = None
    delivered = get_user_setting(g.user_id, _COUPLE_THINKING_DELIVERED_SETTING)

    if delivered and delivered.value:
        try:
            payload = json.loads(delivered.value)
            delivered_sent_at = str(payload.get('sent_at') or '').strip()
            recipient_user_id = int(payload.get('recipient_user_id'))
            if delivered_sent_at == sent_at and recipient_user_id == partner.id:
                state = 'delivered'
                delivered_at = str(payload.get('delivered_at') or '').strip() or None
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    return jsonify(
        status='success',
        data={
            'state': state,
            'sent_at': sent_at,
            'delivered_at': delivered_at,
            'retry_after': retry_after,
        },
    )



# MOBILE NAVIGATION HUB V1
@pages_bp.route('/moments')
@jwt_required
def moments_hub():
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        can_view_memories = has_list_permission('View', 'Home')
        can_view_milestones = has_list_permission('View', 'Moments')
        home_list_type = get_list_type_by_title('Home')
        moments_list_type = get_list_type_by_title('Moments')

        memories_count = 0
        if can_view_memories and home_list_type:
            memories_count = len(
                get_items_by_type(
                    home_list_type.id,
                    'desc',
                )
            )

        milestones_count = 0
        if can_view_milestones and moments_list_type:
            milestones_count = len(
                get_items_by_type(
                    moments_list_type.id,
                    'asc',
                )
            )

        from app.heart_moments import list_heart_moments
        hearts_count = len(
            list_heart_moments(
                g.user_id,
                filter_name='shared',
            )
        )
        places_count = len(get_couple_places())

        return render_template(
            'pages/moments-hub.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            sm_edition=sm_edition,
            page_title='Momente',
            current_year=date.today().year,
            moments_counts={
                'memories': memories_count,
                'hearts': hearts_count,
                'milestones': milestones_count,
                'places': places_count,
            },
            moments_access={
                'memories': can_view_memories,
                'milestones': can_view_milestones,
            },
        )
    except Exception as exc:
        log('error', f'Error while rendering moments hub: {exc}')
        return "An error occurred while rendering the moments hub.", 500


@pages_bp.route('/more')
@jwt_required
def more_hub():
    try:
        sm_edition = get_setting_by_name('sm_edition').value
        if sm_edition != 'couples':
            return redirect(url_for('pages.home'))

        return render_template(
            'pages/more.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            sm_edition=sm_edition,
            page_title='Mehr',
        )
    except Exception as exc:
        log('error', f'Error while rendering more hub: {exc}')
        return "An error occurred while rendering the more hub.", 500


@pages_bp.route('/memories')
@jwt_required
def memories():
    """Dedicated shared-memory page backed by the existing Home items."""
    try:
        if not has_list_permission('View', 'Home'):
            return redirect(url_for('pages.home'))
        home_list_type = get_list_type_by_title('Home')
        if not home_list_type:
            return redirect(url_for('pages.home'))

        items = get_items_by_type(
            home_list_type.id,
            'desc',
        )

        list_types = get_all_list_types()
        title = None
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
        moments_list_type = get_list_type_by_title('Moments')
        home_list_type = get_list_type_by_title('Home')

        if not moments_list_type:
            return redirect(url_for('pages.home'))

        moments = get_items_by_type(
            moments_list_type.id,
            'asc',
        )

        list_types = get_all_list_types()
        title = None
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


@pages_bp.route('/places')
@jwt_required
def places():
    try:
        # Existing text locations from 4C/4D are kept as-is and mirrored into
        # the new place graph on first use. This is additive and idempotent.
        bootstrap_couple_places_from_existing_locations()

        candidates = _couple_place_candidates(g.user_id)
        candidate_index = {
            (entry['source_type'], entry['source_id']): entry
            for entry in candidates
        }
        link_map = get_couple_place_link_map()
        chapter_link_map = get_couple_chapter_link_map()

        place_cards = [
            _couple_place_summary(
                place,
                link_map,
                candidate_index,
                chapter_link_map,
            )
            for place in get_couple_places()
        ]
        place_cards.sort(
            key=lambda place: (
                0 if place['map_ready'] else 1,
                -(place['entry_count']),
                place['name'].casefold(),
            )
        )

        map_places = [
            {
                'id': place['id'],
                'name': place['name'],
                'latitude': place['latitude'],
                'longitude': place['longitude'],
                'entry_count': place['entry_count'],
                'url': url_for('pages.place', place_id=place['id']),
            }
            for place in place_cards
            if place['map_ready']
        ]

        return render_template(
            'pages/places.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title='Unsere Orte',
            places=place_cards,
            map_places=map_places,
            map_config=_place_map_config(),
            place_error=request.args.get('error', ''),
            open_create=request.args.get('create') == '1',
        )
    except Exception as e:
        log('error', f'Error while rendering couple places: {e}')
        return "An error occurred while rendering the places page. Please check the server logs for details.", 500


@pages_bp.route('/places/create', methods=['POST'])
@jwt_required
def create_place_page():
    try:
        values = _place_form_values()
        place_id = create_couple_place(
            name=values['name'],
            description=values['description'],
            latitude=values['latitude'],
            longitude=values['longitude'],
            address_label=values['address_label'],
            created_by_user=g.user_id,
        )
        return redirect(url_for('pages.place', place_id=place_id))
    except ValueError as exc:
        return redirect(url_for('pages.places', error=str(exc), create=1))
    except Exception as e:
        log('error', f'Error while creating couple place: {e}')
        return redirect(url_for(
            'pages.places',
            error='Der Ort konnte nicht gespeichert werden.',
            create=1,
        ))


@pages_bp.route('/places/<int:place_id>')
@jwt_required
def place(place_id):
    try:
        bootstrap_couple_places_from_existing_locations()
        place_data = get_couple_place(place_id)
        if not place_data:
            return redirect(url_for('pages.places'))

        candidates = _couple_place_candidates(g.user_id)
        candidate_index = {
            (entry['source_type'], entry['source_id']): entry
            for entry in candidates
        }
        link_map = get_couple_place_link_map()
        chapter_link_map = get_couple_chapter_link_map()
        place_data = _couple_place_summary(
            place_data,
            link_map,
            candidate_index,
            chapter_link_map,
        )

        links_for_place = {
            (source['source_type'], source['source_id']): source['relation_kind']
            for source in link_map['by_place'].get(place_id, [])
        }

        inherited_keys = set()
        for source in link_map['by_place'].get(place_id, []):
            if source['source_type'] != 'chapter':
                continue
            chapter_links = chapter_link_map['by_chapter'].get(
                source['source_id'],
                {'item_ids': set(), 'heart_ids': set()},
            )
            for item_id in chapter_links.get('item_ids', set()):
                for source_type in ('memory', 'milestone'):
                    key = (source_type, item_id)
                    if key in candidate_index:
                        inherited_keys.add(key)
                        break
            for heart_id in chapter_links.get('heart_ids', set()):
                inherited_keys.add(('heart', heart_id))

        candidate_groups = {
            'memory': [],
            'heart': [],
            'milestone': [],
            'plan': [],
            'chapter': [],
        }
        for candidate in candidates:
            item = dict(candidate)
            key = (item['source_type'], item['source_id'])
            relation_kind = links_for_place.get(key)
            item['linked'] = relation_kind is not None
            item['location_link'] = relation_kind == 'location'
            item['inherited_link'] = (
                key in inherited_keys and relation_kind is None
            )
            candidate_groups[item['source_type']].append(item)

        return render_template(
            'pages/place.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title=place_data['name'],
            place=place_data,
            candidate_groups=candidate_groups,
            map_config=_place_map_config(),
            place_error=request.args.get('error', ''),
        )
    except Exception as e:
        log('error', f'Error while rendering couple place {place_id}: {e}')
        return "An error occurred while rendering the place. Please check the server logs for details.", 500


@pages_bp.route('/places/<int:place_id>/update', methods=['POST'])
@jwt_required
def update_place_page(place_id):
    if not get_couple_place(place_id):
        return redirect(url_for('pages.places'))

    try:
        values = _place_form_values()
        update_couple_place(
            place_id=place_id,
            name=values['name'],
            description=values['description'],
            latitude=values['latitude'],
            longitude=values['longitude'],
            address_label=values['address_label'],
        )
        return redirect(url_for('pages.place', place_id=place_id))
    except ValueError as exc:
        return redirect(url_for(
            'pages.place',
            place_id=place_id,
            error=str(exc),
        ))
    except Exception as e:
        log('error', f'Error while updating couple place {place_id}: {e}')
        return redirect(url_for(
            'pages.place',
            place_id=place_id,
            error='Der Ort konnte nicht gespeichert werden.',
        ))


@pages_bp.route('/places/<int:place_id>/links', methods=['POST'])
@jwt_required
def update_place_links_page(place_id):
    if not get_couple_place(place_id):
        return redirect(url_for('pages.places'))

    try:
        valid_links = {
            (entry['source_type'], entry['source_id'])
            for entry in _couple_place_candidates(g.user_id)
        }
        requested = set()
        for raw in request.form.getlist('source_links'):
            try:
                source_type, source_id_raw = str(raw).split(':', 1)
                key = (source_type, int(source_id_raw))
            except (TypeError, ValueError):
                continue
            if key in valid_links:
                requested.add(key)

        replace_couple_place_manual_links(place_id, requested)
        return redirect(url_for('pages.place', place_id=place_id))
    except Exception as e:
        log('error', f'Error while linking couple place {place_id}: {e}')
        return redirect(url_for(
            'pages.place',
            place_id=place_id,
            error='Die Verknüpfungen konnten nicht gespeichert werden.',
        ))


@pages_bp.route('/places/<int:place_id>/delete', methods=['POST'])
@jwt_required
def delete_place_page(place_id):
    try:
        delete_couple_place(place_id)
        return redirect(url_for('pages.places'))
    except Exception as e:
        log('error', f'Error while deleting couple place {place_id}: {e}')
        return redirect(url_for(
            'pages.place',
            place_id=place_id,
            error='Der Ort konnte nicht gelöscht werden.',
        ))


@pages_bp.route('/places/geocode')
@jwt_required
def geocode_place():
    if os.environ.get('MAP_GEOCODING_ENABLED', 'true').lower() not in {
        '1', 'true', 'yes', 'on'
    }:
        return jsonify({
            'status': 'error',
            'message': 'Geocoding is disabled',
            'results': [],
        }), 503

    query = str(request.args.get('q', '')).strip()
    if len(query) < 2:
        return jsonify({'status': 'success', 'results': []})
    query = query[:200]

    endpoint = os.environ.get(
        'MAP_GEOCODER_URL',
        'https://nominatim.openstreetmap.org/search',
    )
    params = urlencode({
        'q': query,
        'format': 'jsonv2',
        'limit': 5,
        'accept-language': 'de',
    })
    separator = '&' if '?' in endpoint else '?'
    url = f'{endpoint}{separator}{params}'

    try:
        req = Request(
            url,
            headers={
                'Accept': 'application/json',
                'User-Agent': (
                    'SharedMoments-CouplePlaces/1.0 '
                    '(https://github.com/baerenmarke90/SharedMoments)'
                ),
            },
        )
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode('utf-8'))

        results = []
        for item in payload[:5]:
            try:
                results.append({
                    'label': str(item.get('display_name') or query),
                    'lat': float(item['lat']),
                    'lon': float(item['lon']),
                })
            except (KeyError, TypeError, ValueError):
                continue

        return jsonify({'status': 'success', 'results': results})
    except Exception as e:
        log('warning', f'Place geocoding failed for {query!r}: {e}')
        return jsonify({
            'status': 'error',
            'message': 'Der Ort konnte nicht gesucht werden.',
            'results': [],
        }), 502


def _get_bucket_list_type():
    return (
        get_list_type_by_content_url('bucket-list')
        or get_list_type_by_title('Bucket List')
    )


def _bucket_item_or_none(item_id, list_type):
    item = get_item_by_id(item_id)
    if not item or not list_type or item.listType != list_type.id:
        return None
    return item


@pages_bp.route('/bucketlist')
@jwt_required
def bucketlist():
    try:
        list_type = _get_bucket_list_type()
        if not list_type:
            return "Bucket List not found.", 404
        if not has_list_permission('View', list_type.title):
            return redirect(url_for('pages.home'))

        selected_status = str(request.args.get('status', 'open')).strip().lower()
        if selected_status not in {'all', 'open', 'planned', 'done'}:
            selected_status = 'open'

        search_query = str(request.args.get('q', '')).strip()
        search_needle = search_query.casefold()
        selected_sort = str(
            request.args.get('sort', 'created_desc')
        ).strip().lower()
        allowed_sorts = {
            'created_desc',
            'created_asc',
            'name_asc',
            'name_desc',
            'modified_desc',
            'status',
        }
        if selected_sort not in allowed_sorts:
            selected_sort = 'created_desc'

        plan_map = get_couple_bucket_plan_map()

        raw_items = get_items_by_type(
            list_type.id,
            'desc',
            checked_last=True,
        )

        bucket_items = []
        total_count = 0
        done_count = 0
        planned_count = 0

        for item, creator in raw_items:
            completed = str(item.content or '').strip() == '1'
            linked_plan = plan_map.get(item.id)
            plan_meta = None
            if linked_plan:
                status_meta = _PLAN_STATUS_META.get(
                    linked_plan.get('status'),
                    _PLAN_STATUS_META['idea'],
                )
                plan_meta = dict(linked_plan)
                plan_meta['status_label'] = status_meta['label']
                plan_meta['status_icon'] = status_meta['icon']

            total_count += 1
            if completed:
                done_count += 1
            if (
                linked_plan
                and linked_plan.get('status') != 'experienced'
                and not completed
            ):
                planned_count += 1

            if selected_status == 'open' and completed:
                continue
            if selected_status == 'done' and not completed:
                continue
            if selected_status == 'planned' and not (
                linked_plan
                and linked_plan.get('status') != 'experienced'
                and not completed
            ):
                continue

            if search_needle and search_needle not in (item.title or '').casefold():
                continue

            bucket_items.append({
                'id': item.id,
                'title': item.title or '',
                'completed': completed,
                'creator': creator,
                'plan': plan_meta,
                'date_created': item.dateCreated,
                'date_modified': item.dateModified,
            })

        def bucket_datetime(value):
            if isinstance(value, datetime):
                return value
            if isinstance(value, date):
                return datetime.combine(value, datetime.min.time())
            return datetime.min

        if selected_sort == 'name_asc':
            bucket_items.sort(key=lambda entry: (entry['title'].casefold(), entry['id']))
        elif selected_sort == 'name_desc':
            bucket_items.sort(
                key=lambda entry: (entry['title'].casefold(), entry['id']),
                reverse=True,
            )
        elif selected_sort == 'created_asc':
            bucket_items.sort(
                key=lambda entry: (bucket_datetime(entry['date_created']), entry['id'])
            )
        elif selected_sort == 'modified_desc':
            bucket_items.sort(
                key=lambda entry: (
                    bucket_datetime(entry['date_modified']),
                    entry['id'],
                ),
                reverse=True,
            )
        elif selected_sort == 'status':
            def bucket_status_rank(entry):
                if entry['completed']:
                    return 2
                if entry.get('plan'):
                    return 1
                return 0

            bucket_items.sort(
                key=lambda entry: (
                    bucket_status_rank(entry),
                    entry['title'].casefold(),
                    entry['id'],
                )
            )
        else:
            bucket_items.sort(
                key=lambda entry: (bucket_datetime(entry['date_created']), entry['id']),
                reverse=True,
            )

        open_count = total_count - done_count
        progress_percent = (
            round((done_count / total_count) * 100)
            if total_count else 0
        )

        return render_template(
            'pages/bucketlist.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title='Bucketlist',
            bucket_items=bucket_items,
            bucket_list_type=list_type,
            list_type_title=list_type.title,
            selected_status=selected_status,
            search_query=search_query,
            selected_sort=selected_sort,
            total_count=total_count,
            open_count=open_count,
            planned_count=planned_count,
            done_count=done_count,
            progress_percent=progress_percent,
            bucket_error=request.args.get('error', ''),
        )
    except Exception as e:
        log('error', f'Error while rendering couple bucketlist: {e}')
        return "An error occurred while rendering the Bucketlist.", 500


@pages_bp.route('/bucketlist/create', methods=['POST'])
@jwt_required
def create_bucket_item_page():
    list_type = _get_bucket_list_type()
    if not list_type or not has_list_permission('Create', list_type.title):
        return redirect(url_for('pages.bucketlist'))

    title = str(request.form.get('title', '')).strip()
    if not title:
        return redirect(url_for(
            'pages.bucketlist',
            error='Bitte gib eurem Wunsch einen Titel.',
        ))
    if len(title) > 255:
        return redirect(url_for(
            'pages.bucketlist',
            error='Der Eintrag darf höchstens 255 Zeichen lang sein.',
        ))

    try:
        create_item(
            title=title,
            content='0',
            contentType='list',
            listType=list_type.id,
            contentURL='',
            createdByUser=g.user_id,
            dateCreated=datetime.utcnow(),
        )
        return redirect(url_for('pages.bucketlist'))
    except Exception as e:
        log('error', f'Error while creating bucketlist item: {e}')
        return redirect(url_for(
            'pages.bucketlist',
            error='Der Bucketlist-Eintrag konnte nicht gespeichert werden.',
        ))


@pages_bp.route('/bucketlist/<int:item_id>/toggle', methods=['POST'])
@jwt_required
def toggle_bucket_item_page(item_id):
    list_type = _get_bucket_list_type()
    if not list_type or not has_list_permission('Update', list_type.title):
        return redirect(url_for('pages.bucketlist'))

    item = _bucket_item_or_none(item_id, list_type)
    if not item:
        return redirect(url_for('pages.bucketlist'))

    completed = str(request.form.get('completed', '0')) == '1'
    try:
        update_item(item_id, content='1' if completed else '0')
        sync_bucket_item_to_plan(item_id, completed)

        return_status = str(request.form.get('return_status', 'open')).strip()
        if return_status not in {'all', 'open', 'planned', 'done'}:
            return_status = 'open'
        return_query = str(request.form.get('return_q', '')).strip()
        return_sort = str(
            request.form.get('return_sort', 'created_desc')
        ).strip().lower()
        if return_sort not in {
            'created_desc', 'created_asc', 'name_asc', 'name_desc',
            'modified_desc', 'status',
        }:
            return_sort = 'created_desc'

        redirect_kwargs = {
            'status': return_status,
            'sort': return_sort,
        }
        if return_query:
            redirect_kwargs['q'] = return_query
        return redirect(url_for('pages.bucketlist', **redirect_kwargs))
    except Exception as e:
        log('error', f'Error while toggling bucketlist item {item_id}: {e}')
        return redirect(url_for(
            'pages.bucketlist',
            error='Der Status konnte nicht geändert werden.',
        ))


@pages_bp.route('/bucketlist/<int:item_id>/update', methods=['POST'])
@jwt_required
def update_bucket_item_page(item_id):
    list_type = _get_bucket_list_type()
    if not list_type or not has_list_permission('Update', list_type.title):
        return redirect(url_for('pages.bucketlist'))

    item = _bucket_item_or_none(item_id, list_type)
    if not item:
        return redirect(url_for('pages.bucketlist'))

    title = str(request.form.get('title', '')).strip()
    if not title:
        return redirect(url_for(
            'pages.bucketlist',
            error='Bitte gib eurem Wunsch einen Titel.',
        ))

    try:
        update_item(item_id, title=title[:255])
        return redirect(url_for('pages.bucketlist') + f'#bucket-{item_id}')
    except Exception as e:
        log('error', f'Error while updating bucketlist item {item_id}: {e}')
        return redirect(url_for(
            'pages.bucketlist',
            error='Der Eintrag konnte nicht geändert werden.',
        ))


@pages_bp.route('/bucketlist/<int:item_id>/delete', methods=['POST'])
@jwt_required
def delete_bucket_item_page(item_id):
    list_type = _get_bucket_list_type()
    if not list_type or not has_list_permission('Delete', list_type.title):
        return redirect(url_for('pages.bucketlist'))

    item = _bucket_item_or_none(item_id, list_type)
    if not item:
        return redirect(url_for('pages.bucketlist'))

    try:
        delete_item(item_id)
        return redirect(url_for('pages.bucketlist'))
    except Exception as e:
        log('error', f'Error while deleting bucketlist item {item_id}: {e}')
        return redirect(url_for(
            'pages.bucketlist',
            error='Der Eintrag konnte nicht gelöscht werden.',
        ))


@pages_bp.route('/bucketlist/<int:item_id>/plan', methods=['POST'])
@jwt_required
def bucket_item_to_plan_page(item_id):
    list_type = _get_bucket_list_type()
    if not list_type or not has_list_permission('Update', list_type.title):
        return redirect(url_for('pages.bucketlist'))

    item = _bucket_item_or_none(item_id, list_type)
    if not item:
        return redirect(url_for('pages.bucketlist'))

    existing = get_couple_bucket_plan_map().get(item_id)
    if existing:
        return redirect(url_for('pages.plans') + f"#plan-{existing['id']}")

    try:
        plan_id = create_couple_plan(
            title=item.title or 'Bucketlist-Idee',
            description='',
            status='planned',
            target_start_date=None,
            target_end_date=None,
            location_name='',
            created_by_user=g.user_id,
        )
        try:
            link_couple_bucket_plan(item_id, plan_id)
        except Exception:
            # Avoid leaving a duplicate/orphan plan if the relationship itself
            # could not be persisted.
            delete_couple_plan(plan_id)
            raise

        return redirect(url_for('pages.plans') + f'#plan-{plan_id}')
    except Exception as e:
        log('error', f'Error while promoting bucket item {item_id} to plan: {e}')
        return redirect(url_for(
            'pages.bucketlist',
            error='Aus dem Bucketlist-Eintrag konnte kein Plan erstellt werden.',
        ))


@pages_bp.route('/plans')
@jwt_required
def plans():
    try:
        selected_status = str(
            request.args.get('status', 'all')
        ).strip()
        allowed_statuses = {'all'} | set(_PLAN_STATUS_META)
        if selected_status not in allowed_statuses:
            selected_status = 'all'

        bootstrap_couple_places_from_existing_locations()
        place_link_map = get_couple_place_link_map()

        all_plans = [
            _present_couple_plan(plan, g.user_id)
            for plan in get_couple_plans()
        ]
        _attach_source_places(all_plans, 'plan', place_link_map)

        bucket_plan_map = get_couple_bucket_plan_map()
        bucket_item_by_plan_id = {
            plan_meta['id']: bucket_item_id
            for bucket_item_id, plan_meta in bucket_plan_map.items()
        }
        for plan in all_plans:
            plan['bucket_item_id'] = bucket_item_by_plan_id.get(plan['id'])

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

        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        list_types = get_all_list_types()

        return render_template(
            'pages/plans.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
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
    try:
        values = _plan_form_values()
        plan_id = create_couple_plan(
            title=values['title'],
            description=values['description'],
            status=values['status'],
            target_start_date=values['target_start_date'],
            target_end_date=values['target_end_date'],
            experienced_date=values['experienced_date'],
            location_name=values['location_name'],
            created_by_user=g.user_id,
        )
        sync_couple_source_location(
            'plan',
            plan_id,
            values['location_name'],
            g.user_id,
        )
        return redirect(url_for('pages.plans') + f'#plan-{plan_id}')
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
            experienced_date=values['experienced_date'],
            location_name=values['location_name'],
        )
        sync_couple_source_location(
            'plan',
            plan_id,
            values['location_name'],
            plan['createdByUser'],
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


@pages_bp.route('/plans/<int:plan_id>/bucketlist', methods=['POST'])
@jwt_required
def plan_back_to_bucketlist_page(plan_id):
    plan = get_couple_plan(plan_id)
    if not plan:
        return redirect(url_for('pages.plans'))
    if plan['createdByUser'] != g.user_id:
        return redirect(url_for(
            'pages.plans',
            error='Du kannst nur deine eigenen Pläne zurück in die Bucketlist legen.',
        ))
    if plan.get('status') == 'experienced' or plan.get('chapterID'):
        return redirect(url_for(
            'pages.plans',
            error='Ein erlebter oder bereits als Kapitel festgehaltener Plan kann nicht zurück in die Bucketlist.',
        ))

    try:
        bucket_item_id = return_couple_plan_to_bucketlist(plan_id)
        if not bucket_item_id:
            return redirect(url_for(
                'pages.plans',
                error='Dieser Plan stammt nicht aus der Bucketlist.',
            ))
        return redirect(
            url_for('pages.bucketlist', status='open')
            + f'#bucket-{bucket_item_id}'
        )
    except ValueError as exc:
        return redirect(url_for('pages.plans', error=str(exc)))
    except Exception as e:
        log('error', f'Error while returning plan {plan_id} to Bucketlist: {e}')
        return redirect(url_for(
            'pages.plans',
            error='Der Plan konnte nicht zurück in die Bucketlist gelegt werden.',
        ))


@pages_bp.route('/plans/<int:plan_id>/chapter', methods=['POST'])
@jwt_required
def plan_to_chapter_page(plan_id):
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
        # Reihenfolge: was wirklich war schlaegt, was geplant war.
        experienced = plan.get('experiencedDate')
        chapter_start = plan['targetStartDate'] or experienced
        chapter_end = plan['targetEndDate'] or experienced

        chapter_id = create_couple_chapter(
            title=plan['title'],
            description=plan['description'],
            start_date=chapter_start,
            end_date=chapter_end,
            location_name=plan['locationName'],
            created_by_user=g.user_id,
        )
        sync_couple_source_location(
            'chapter',
            chapter_id,
            plan['locationName'],
            g.user_id,
        )
        copy_couple_place_links('plan', plan_id, 'chapter', chapter_id)
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
        list_types = get_all_list_types()
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        content = _couple_content_for_chapters(
            g.user_id,
        )
        link_map = get_couple_chapter_link_map()

        bootstrap_couple_places_from_existing_locations()
        place_link_map = get_couple_place_link_map()

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
        _attach_source_places(chapter_cards, 'chapter', place_link_map)

        return render_template(
            'pages/chapters.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
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
        sync_couple_source_location(
            'chapter',
            chapter_id,
            values['location_name'],
            g.user_id,
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
        chapter_data = get_couple_chapter(chapter_id)
        if not chapter_data:
            return redirect(url_for('pages.chapters'))

        list_types = get_all_list_types()
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        content = _couple_content_for_chapters(
            g.user_id,
        )
        links = get_couple_chapter_links(chapter_id)
        chapter_data = _chapter_summary(
            chapter_data,
            links,
            content,
        )
        bootstrap_couple_places_from_existing_locations()
        place_link_map = get_couple_place_link_map()
        chapter_data['places'] = place_link_map['source_places'].get(
            ('chapter', chapter_id),
            [],
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
    existing_chapter = get_couple_chapter(chapter_id)
    if not existing_chapter:
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
        sync_couple_source_location(
            'chapter',
            chapter_id,
            values['location_name'],
            existing_chapter['createdByUser'],
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
    if not get_couple_chapter(chapter_id):
        return redirect(url_for('pages.chapters'))

    try:
        content = _couple_content_for_chapters(
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


@pages_bp.route('/year')
@pages_bp.route('/year/<int:selected_year>')
@jwt_required
def couple_year(selected_year=None):
    """Automatic yearly relationship recap for the Couples edition."""
    try:
        if selected_year is None:
            selected_year = date.today().year

        # Avoid nonsensical URLs while still allowing old relationship years.
        if selected_year < 1900 or selected_year > date.today().year + 2:
            return redirect(url_for(
                'pages.couple_year',
                selected_year=date.today().year,
            ))

        snapshot = _build_couple_year_snapshot(
            selected_year,
            g.user_id,
        )

        return render_template(
            'pages/year.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title=f'Unser {selected_year}',
            year_snapshot=snapshot,
            selected_year=selected_year,
            available_years=snapshot['available_years'],
        )
    except Exception as e:
        log('error', f'Error while rendering couple year recap: {e}')
        return "An error occurred while rendering the yearly recap.", 500


# ===== Monthly Scrapbook =====
@pages_bp.route('/year/<int:selected_year>/month/<int:selected_month>')
@jwt_required
def couple_month(selected_year, selected_month):
    """Render a monthly recap from the existing yearly relationship snapshot."""
    try:
        current_year = date.today().year
        if selected_year < 1900 or selected_year > current_year + 2:
            return redirect(url_for(
                'pages.couple_year',
                selected_year=current_year,
            ))
        if not 1 <= selected_month <= 12:
            return redirect(url_for(
                'pages.couple_year',
                selected_year=selected_year,
            ))

        snapshot = _build_couple_year_snapshot(
            selected_year,
            g.user_id,
        )

        month_snapshot = None
        for group in snapshot.get('month_groups', []):
            if int(group.get('month', 0)) == selected_month:
                month_snapshot = group
                break

        if month_snapshot is None:
            month_snapshot = {
                'month': selected_month,
                'label': _STORY_MONTH_NAMES[selected_month],
                'entries': [],
                'all_entries': [],
                'total': 0,
                'cover_images': [],
                'places': [],
                'stats': {
                    'memories': 0,
                    'hearts': 0,
                    'milestones': 0,
                    'chapters': 0,
                    'bucket': 0,
                    'plans': 0,
                    'places': 0,
                },
            }

        # Be defensive with recaps created by an older version of the snapshot
        # builder. This keeps the page renderable during rolling deployments.
        month_snapshot.setdefault('entries', [])
        month_snapshot.setdefault('all_entries', month_snapshot['entries'])
        month_snapshot.setdefault('cover_images', [])
        month_snapshot.setdefault('places', [])
        month_snapshot.setdefault('total', len(month_snapshot['all_entries']))
        month_snapshot.setdefault('stats', {})
        for key in (
            'memories', 'hearts', 'milestones', 'chapters',
            'bucket', 'plans', 'places',
        ):
            month_snapshot['stats'].setdefault(key, 0)

        return render_template(
            'pages/month.html',
            title=get_setting_by_name('title'),
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title=f"Unser {month_snapshot['label']} {selected_year}",
            selected_year=selected_year,
            selected_month=selected_month,
            month_snapshot=month_snapshot,
            available_years=snapshot.get('available_years', [selected_year]),
        )
    except Exception as exc:
        # Do not swallow the useful traceback. Log it both through the app logger
        # and stderr so Docker/Gunicorn logs contain the actual root cause.
        import traceback
        trace = traceback.format_exc()
        log(
            'error',
            f'Monthly recap failed for {selected_year}-{selected_month:02d}: '
            f'{exc!r}\n{trace}',
        )
        print(trace, file=__import__('sys').stderr, flush=True)
        return "An error occurred while rendering the monthly recap.", 500

@pages_bp.route('/story')
@jwt_required
def story():
    """Relationship-first chronology for the Couples edition."""
    try:
        list_types = get_all_list_types()
        title = None
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
            )
            if can_view_items and home_list_type
            else []
        )

        moments = (
            get_items_by_type(
                moments_list_type.id,
                'desc',
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
        bootstrap_couple_places_from_existing_locations()
        place_link_map = get_couple_place_link_map()

        for entry in all_entries:
            if entry['type'] == 'heart':
                entry['chapters'] = chapter_link_map[
                    'heart_chapters'
                ].get(entry['id'], [])
            else:
                entry['chapters'] = chapter_link_map[
                    'item_chapters'
                ].get(entry['id'], [])

            collected_places = []
            seen_place_ids = set()

            for place in place_link_map['source_places'].get(
                (entry['type'], entry['id']),
                [],
            ):
                if place['id'] not in seen_place_ids:
                    collected_places.append(place)
                    seen_place_ids.add(place['id'])

            # A memory/heart/milestone inside a chapter inherits the chapter's
            # place for browsing and search, without writing duplicate links.
            for chapter in entry['chapters']:
                for place in place_link_map['source_places'].get(
                    ('chapter', chapter['id']),
                    [],
                ):
                    if place['id'] not in seen_place_ids:
                        collected_places.append(place)
                        seen_place_ids.add(place['id'])

            entry['places'] = collected_places

        entry_type = str(request.args.get('type', 'all')).strip().lower()
        allowed_types = {'all', 'memory', 'heart', 'milestone'}
        if entry_type not in allowed_types:
            entry_type = 'all'

        search_query = str(request.args.get('q', '')).strip()

        # Archiv-Konvention: neueste zuerst. Wer eine Reise nachlesen will,
        # kann umschalten - deshalb nicht fest verdrahtet.
        story_order = str(request.args.get('order', 'new')).strip().lower()
        if story_order not in ('new', 'old'):
            story_order = 'new'

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

        if story_order == 'old':
            filtered_entries = list(reversed(filtered_entries))

        story_groups = _group_story_entries(filtered_entries)

        return render_template(
            'pages/story.html',
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            list_types=list_types,
            page_title='Unsere Story',
            story_groups=story_groups,
            story_total=len(filtered_entries),
            story_type=entry_type,
            story_year=selected_year,
            story_years=available_years,
            story_query=search_query,
            story_order=story_order,
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
        title = None
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
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        settings_type = 'settings'
        supported_languages = get_supported_languages()
        return render_template(
            'pages/settings.html',
            settings=settings,
            list_types=list_types,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            settings_type=settings_type,
            supported_languages=supported_languages,
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
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        all_user_settings = get_user_settings(g.user_id)
        user_settings = [
            setting for setting in all_user_settings
            if (
                setting.name in {'darkmode', 'language', 'accent_color'}
                or setting.name.startswith('notification_')
                or setting.name.startswith('pwa_')
            )
        ]
        settings_type = 'user-settings'
        supported_languages = get_supported_languages()

        smtp_available = bool(os.environ.get('SMTP_HOST', ''))
        telegram_available = bool(os.environ.get('TELEGRAM_BOT_TOKEN', ''))
        telegram_chat_id_setting = get_user_setting(g.user_id, 'notification_telegram_chat_id')
        telegram_chat_id = telegram_chat_id_setting.value if telegram_chat_id_setting else ''
        passkeys = get_passkeys_by_user(g.user_id)
        from app.auth_settings import get_effective_auth_settings
        passkey_login_enabled = bool(
            get_effective_auth_settings()['passkey_login_enabled']
        )

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
            passkey_login_enabled=passkey_login_enabled,
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
        title = None
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
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)
        reminder_list = get_all_reminders()
        muted_ids = get_user_muted_reminder_ids(g.user_id)
        return render_template('pages/reminders.html',
            list_types=list_types, title=title, darkmode=darkmode, user_data=user_data,
            reminders=reminder_list, muted_ids=muted_ids,
            translate_title=_translate_reminder_title,
            translate_desc=_translate_reminder_description,
            page_title='Termine & Benachrichtigungen')
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
        # Couples get the relationship-first Bucketlist UI while the generic
        # custom-list implementation remains untouched for other editions.
        if content_url == 'bucket-list':
            return redirect(url_for('pages.bucketlist'))

        items = get_items_by_type(list_type.id,  checked_last=True)
        list_types = get_all_list_types()
        title = None
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
                               page_title=_(list_type.mainTitle or list_type.title))
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
        list_types = get_all_list_types()
        title = None
        darkmode = get_user_setting(g.user_id, 'darkmode')
        user_data = get_user_by_id(g.user_id)

        return render_template(
            'pages/heart-moments.html',
            list_types=list_types,
            title=title,
            darkmode=darkmode,
            user_data=user_data,
            current_user_id=g.user_id,
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


# ============================================================
# PRIVATER BEREICH
#
# Alles hier gehoert genau einer Person. Die Abfragen filtern immer nach
# g.user_id, es gibt keinen Weg, fremde Eintraege zu laden - auch nicht
# ueber eine geratene ID in der URL.
# ============================================================

_PRIVATE_GIFT_STATUS_META = {
    'idea': {'label': 'Idee', 'icon': 'lightbulb'},
    'reserved': {'label': 'Vorgemerkt', 'icon': 'bookmark'},
    'bought': {'label': 'Gekauft', 'icon': 'shopping_bag'},
    'given': {'label': 'Verschenkt', 'icon': 'redeem'},
}


def _private_form_values(kind):
    title = str(request.form.get('title', '')).strip()
    content = str(request.form.get('content', '')).strip()

    if not title:
        raise ValueError('Bitte gib dem Eintrag einen Titel.')
    if len(title) > 255:
        raise ValueError('Der Titel darf höchstens 255 Zeichen lang sein.')

    values = {
        'title': title,
        'content': content,
        'recipient': None,
        'occasion': None,
        'target_date': None,
        'price': None,
        'link': None,
        'status': 'idea',
    }

    if kind == 'birthday':
        recipient = str(request.form.get('recipient', '')).strip()
        if len(recipient) > 255:
            raise ValueError('Der Name darf höchstens 255 Zeichen lang sein.')

        try:
            target_date = _parse_optional_form_date(request.form.get('target_date'))
        except ValueError as exc:
            raise ValueError('Bitte verwende ein gültiges Datum.') from exc

        if not target_date:
            raise ValueError('Bitte gib das Geburtsdatum an.')

        values.update({
            'recipient': recipient or None,
            'target_date': target_date,
        })
        return values

    if kind != 'gift':
        return values

    recipient = str(request.form.get('recipient', '')).strip()
    occasion = str(request.form.get('occasion', '')).strip()
    price = str(request.form.get('price', '')).strip()
    link = str(request.form.get('link', '')).strip()
    status = str(request.form.get('status', 'idea')).strip()

    if len(recipient) > 255 or len(occasion) > 255:
        raise ValueError('Empfänger und Anlass dürfen höchstens 255 Zeichen lang sein.')
    if len(price) > 64:
        raise ValueError('Der Preis darf höchstens 64 Zeichen lang sein.')
    if status not in PRIVATE_GIFT_STATUSES:
        status = 'idea'

    try:
        target_date = _parse_optional_form_date(request.form.get('target_date'))
    except ValueError as exc:
        raise ValueError('Bitte verwende ein gültiges Datum.') from exc

    values.update({
        'recipient': recipient or None,
        'occasion': occasion or None,
        'target_date': target_date,
        'price': price or None,
        'link': link or None,
        'status': status,
    })
    return values


def _next_birthday(birth_date, today):
    """Naechster Geburtstag ab heute - der 29.02. faellt auf den 28."""
    if not birth_date:
        return None

    for year in (today.year, today.year + 1):
        try:
            candidate = birth_date.replace(year=year)
        except ValueError:
            candidate = birth_date.replace(year=year, day=28)
        if candidate >= today:
            return candidate
    return None


def _present_private_entry(entry):
    presented = dict(entry)
    meta = _PRIVATE_GIFT_STATUS_META.get(
        entry.get('status'),
        _PRIVATE_GIFT_STATUS_META['idea'],
    )
    presented.update({
        'status_label': meta['label'],
        'status_icon': meta['icon'],
        'date_input': (
            entry['targetDate'].isoformat() if entry.get('targetDate') else ''
        ),
        'date_label': (
            entry['targetDate'].strftime('%d.%m.%Y')
            if entry.get('targetDate') else ''
        ),
    })

    if entry.get('kind') == 'birthday' and entry.get('targetDate'):
        today = date.today()
        next_date = _next_birthday(entry['targetDate'], today)
        turning = next_date.year - entry['targetDate'].year if next_date else None
        presented.update({
            'next_date': next_date,
            'next_label': next_date.strftime('%d.%m.') if next_date else '',
            'relative_label': _relative_day_label(next_date, today) if next_date else '',
            'age_label': f'wird {turning}' if turning and turning > 0 else '',
        })

    return presented


@pages_bp.route('/private')
@jwt_required
def private_area():
    try:
        # Beide Arten sind einzeln abschaltbar. Ist nur eine aktiv, zeigt die
        # Seite nur diese - sind beide aus, gibt es die Seite nicht.
        notes_on = is_feature_enabled('private_notes')
        gifts_on = is_feature_enabled('private_gifts')
        if not notes_on and not gifts_on:
            return redirect(url_for('pages.home'))

        kind = str(request.args.get('kind', 'note')).strip().lower()
        if kind not in ('note', 'gift', 'birthday'):
            kind = 'note'
        # Geburtstage haengen am selben Schalter wie die Geschenke: ohne
        # Geschenkideen hat eine private Geburtstagsliste wenig Sinn.
        if kind == 'note' and not notes_on:
            kind = 'gift'
        if kind in ('gift', 'birthday') and not gifts_on:
            kind = 'note'

        entries = [
            _present_private_entry(entry)
            for entry in get_private_entries(g.user_id, kind)
        ]

        if kind == 'birthday':
            # Nach naechster Wiederkehr statt nach Aenderungsdatum - eine
            # Geburtstagsliste beantwortet die Frage "wer kommt als Naechstes".
            entries.sort(
                key=lambda item: (
                    not item['pinned'],
                    item.get('next_date') or date.max,
                )
            )
        counts = count_private_entries(g.user_id)

        return render_template(
            'pages/private.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title='Nur für mich',
            private_kind=kind,
            private_notes_enabled=notes_on,
            private_gifts_enabled=gifts_on,
            private_entries=entries,
            private_counts=counts,
            private_list_count=count_private_lists(g.user_id),
            private_statuses=_PRIVATE_GIFT_STATUS_META,
            private_error=request.args.get('error', ''),
        )
    except Exception as e:
        log('error', f'Error while rendering private area: {e}')
        return "An error occurred while rendering the page. Please check the server logs for details.", 500


@pages_bp.route('/private/create', methods=['POST'])
@jwt_required
def create_private_entry_page():
    kind = str(request.form.get('kind', 'note')).strip().lower()
    if kind not in ('note', 'gift', 'birthday'):
        kind = 'note'
    if not is_feature_enabled('private_notes' if kind == 'note' else 'private_gifts'):
        return redirect(url_for('pages.home'))

    try:
        values = _private_form_values(kind)
        entry_id = create_private_entry(g.user_id, kind, **values)
        return redirect(url_for('pages.private_area', kind=kind) + f'#private-{entry_id}')
    except ValueError as exc:
        return redirect(url_for('pages.private_area', kind=kind, error=str(exc)))
    except Exception as e:
        log('error', f'Error while creating private entry: {e}')
        return redirect(url_for(
            'pages.private_area',
            kind=kind,
            error='Der Eintrag konnte nicht gespeichert werden.',
        ))


@pages_bp.route('/private/<int:entry_id>/update', methods=['POST'])
@jwt_required
def update_private_entry_page(entry_id):
    entry = get_private_entry(g.user_id, entry_id)
    if not entry:
        return redirect(url_for('pages.private_area'))

    try:
        values = _private_form_values(entry['kind'])
        update_private_entry(g.user_id, entry_id, **values)
        return redirect(
            url_for('pages.private_area', kind=entry['kind']) + f'#private-{entry_id}'
        )
    except ValueError as exc:
        return redirect(url_for(
            'pages.private_area', kind=entry['kind'], error=str(exc),
        ))
    except Exception as e:
        log('error', f'Error while updating private entry {entry_id}: {e}')
        return redirect(url_for(
            'pages.private_area',
            kind=entry['kind'],
            error='Der Eintrag konnte nicht gespeichert werden.',
        ))


@pages_bp.route('/private/<int:entry_id>/pin', methods=['POST'])
@jwt_required
def pin_private_entry_page(entry_id):
    entry = get_private_entry(g.user_id, entry_id)
    if not entry:
        return redirect(url_for('pages.private_area'))

    update_private_entry(g.user_id, entry_id, pinned=not entry['pinned'])
    return redirect(url_for('pages.private_area', kind=entry['kind']))


@pages_bp.route('/private/<int:entry_id>/delete', methods=['POST'])
@jwt_required
def delete_private_entry_page(entry_id):
    entry = get_private_entry(g.user_id, entry_id)
    if not entry:
        return redirect(url_for('pages.private_area'))

    delete_private_entry(g.user_id, entry_id)
    return redirect(url_for('pages.private_area', kind=entry['kind']))


# ---------------------------------------------------------------------------
# Private Listen
# ---------------------------------------------------------------------------
@pages_bp.route('/private/lists')
@jwt_required
def private_lists_page():
    try:
        notes_on = is_feature_enabled('private_notes')
        gifts_on = is_feature_enabled('private_gifts')
        lists = get_private_lists(g.user_id)
        return render_template(
            'pages/private-lists.html',
            title=None,
            darkmode=get_user_setting(g.user_id, 'darkmode'),
            user_data=get_user_by_id(g.user_id),
            list_types=get_all_list_types(),
            page_title='Nur für mich',
            private_notes_enabled=notes_on,
            private_gifts_enabled=gifts_on,
            private_counts=count_private_entries(g.user_id),
            private_list_count=len(lists),
            private_lists=lists,
            private_error=request.args.get('error', ''),
        )
    except Exception as e:
        log('error', f'Error while rendering private lists: {e}')
        return 'An error occurred while rendering the page. Please check the server logs for details.', 500


@pages_bp.route('/private/lists/create', methods=['POST'])
@jwt_required
def create_private_list_page():
    try:
        list_id = create_private_list(
            g.user_id,
            request.form.get('title', ''),
            request.form.get('icon', 'checklist'),
        )
        return redirect(url_for('pages.private_lists_page') + f'#private-list-{list_id}')
    except ValueError as exc:
        return redirect(url_for('pages.private_lists_page', error=str(exc)))
    except Exception as e:
        log('error', f'Error while creating private list: {e}')
        return redirect(url_for('pages.private_lists_page', error='Die Liste konnte nicht gespeichert werden.'))


@pages_bp.route('/private/lists/<int:list_id>/update', methods=['POST'])
@jwt_required
def update_private_list_page(list_id):
    if not get_private_list(g.user_id, list_id):
        return redirect(url_for('pages.private_lists_page'))
    try:
        update_private_list(
            g.user_id,
            list_id,
            request.form.get('title', ''),
            request.form.get('icon', 'checklist'),
        )
        return redirect(url_for('pages.private_lists_page') + f'#private-list-{list_id}')
    except ValueError as exc:
        return redirect(url_for('pages.private_lists_page', error=str(exc)) + f'#private-list-{list_id}')
    except Exception as e:
        log('error', f'Error while updating private list {list_id}: {e}')
        return redirect(url_for('pages.private_lists_page', error='Die Liste konnte nicht gespeichert werden.'))


@pages_bp.route('/private/lists/<int:list_id>/delete', methods=['POST'])
@jwt_required
def delete_private_list_page(list_id):
    delete_private_list(g.user_id, list_id)
    return redirect(url_for('pages.private_lists_page'))


@pages_bp.route('/private/lists/<int:list_id>/items/create', methods=['POST'])
@jwt_required
def create_private_list_item_page(list_id):
    if not get_private_list(g.user_id, list_id):
        return redirect(url_for('pages.private_lists_page'))
    try:
        create_private_list_item(g.user_id, list_id, request.form.get('title', ''))
        return redirect(url_for('pages.private_lists_page') + f'#private-list-{list_id}')
    except ValueError as exc:
        return redirect(url_for('pages.private_lists_page', error=str(exc)) + f'#private-list-{list_id}')
    except Exception as e:
        log('error', f'Error while creating private list item: {e}')
        return redirect(url_for('pages.private_lists_page', error='Der Listenpunkt konnte nicht gespeichert werden.'))


@pages_bp.route('/private/lists/items/<int:item_id>/toggle', methods=['POST'])
@jwt_required
def toggle_private_list_item_page(item_id):
    list_id = toggle_private_list_item(g.user_id, item_id)
    if not list_id:
        return redirect(url_for('pages.private_lists_page'))
    return redirect(url_for('pages.private_lists_page') + f'#private-list-{list_id}')


@pages_bp.route('/private/lists/items/<int:item_id>/delete', methods=['POST'])
@jwt_required
def delete_private_list_item_page(item_id):
    list_id = delete_private_list_item(g.user_id, item_id)
    if not list_id:
        return redirect(url_for('pages.private_lists_page'))
    return redirect(url_for('pages.private_lists_page') + f'#private-list-{list_id}')
