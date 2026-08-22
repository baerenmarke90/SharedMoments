from __future__ import annotations

import re

from flask import g, has_request_context

from app.models import Item, ListType, SessionLocal, Setting


_TRUE_VALUES = {'true', '1', 'yes', 'on'}

FEATURE_GROUPS = (
    {
        'key': 'together',
        'label': 'Gemeinsam',
        'icon': 'favorite',
        'description': 'Kleine gemeinsame Impulse und Interaktionen.',
        'features': (
            {
                'key': 'daily_questions',
                'setting': 'daily_questions_enabled',
                'label': 'Frage des Tages',
                'icon': 'local_florist',
                'description': 'Tägliche gemeinsame Frage inklusive Archiv und Antworten.',
            },
            {
                'key': 'thinking_of_you',
                'setting': 'feature_thinking_of_you_enabled',
                'label': 'Ich denk an dich',
                'icon': 'favorite',
                'description': 'Kurzes Zeichen an den Partner direkt vom Wir-Bildschirm.',
            },
            {
                'key': 'flashback',
                'setting': 'feature_flashback_enabled',
                'label': 'Weißt du noch?',
                'icon': 'history_toggle_off',
                'description': 'Automatischer Rückblick auf frühere gemeinsame Momente.',
            },
        ),
    },
    {
        'key': 'moments',
        'label': 'Erinnerungen & Momente',
        'icon': 'photo_library',
        'description': 'Gemeinsame Erinnerungen und besondere Augenblicke.',
        'features': (
            {
                'key': 'memories',
                'setting': 'feature_memories_enabled',
                'label': 'Erinnerungen',
                'icon': 'photo_library',
                'description': 'Erinnerungen mit Texten, Bildern und Medien.',
            },
            {
                'key': 'heart_moments',
                'setting': 'feature_heart_moments_enabled',
                'label': 'Herzmomente',
                'icon': 'favorite',
                'description': 'Besondere Momente von Liebe, Dankbarkeit und Nähe.',
            },
            {
                'key': 'milestones',
                'setting': 'feature_milestones_enabled',
                'label': 'Meilensteine',
                'icon': 'star',
                'description': 'Wichtige Ereignisse und Meilensteine eurer Beziehung.',
            },
        ),
    },
    {
        'key': 'story',
        'label': 'Unsere Geschichte',
        'icon': 'auto_stories',
        'description': 'Rückblick, Kapitel und automatische Beziehungsansichten.',
        'features': (
            {
                'key': 'story',
                'setting': 'feature_story_enabled',
                'label': 'Unsere Story',
                'icon': 'auto_stories',
                'description': 'Chronologische gemeinsame Geschichte.',
            },
            {
                'key': 'year_recap',
                'setting': 'feature_year_recap_enabled',
                'label': 'Unser Jahr',
                'icon': 'calendar_view_month',
                'description': 'Automatischer Jahresrückblick.',
            },
            {
                'key': 'chapters',
                'setting': 'feature_chapters_enabled',
                'label': 'Kapitel',
                'icon': 'menu_book',
                'description': 'Gemeinsame Lebensabschnitte mit verknüpften Inhalten.',
            },
        ),
    },
    {
        'key': 'planning',
        'label': 'Planen & Erleben',
        'icon': 'explore',
        'description': 'Wünsche, Pläne, Orte, Listen und Termine.',
        'features': (
            {
                'key': 'plans',
                'setting': 'feature_plans_enabled',
                'label': 'Unsere Pläne',
                'icon': 'explore',
                'description': 'Gemeinsame Ideen vom Plan bis zum erlebten Moment.',
            },
            {
                'key': 'bucketlist',
                'setting': 'feature_bucketlist_enabled',
                'label': 'Bucketlist',
                'icon': 'checklist',
                'description': 'Gemeinsame Wünsche und Dinge, die ihr erleben möchtet.',
            },
            {
                'key': 'places',
                'setting': 'feature_places_enabled',
                'label': 'Unsere Orte',
                'icon': 'map',
                'description': 'Orte sammeln und mit gemeinsamen Inhalten verknüpfen.',
            },
            {
                'key': 'custom_lists',
                'setting': 'feature_custom_lists_enabled',
                'label': 'Eigene Listen',
                'icon': 'list_alt',
                'description': 'Eigene Listen wie Filme, TrashTV oder andere Sammlungen.',
            },
            {
                'key': 'reminders',
                'setting': 'feature_reminders_enabled',
                'label': 'Termine & Benachrichtigungen',
                'icon': 'notifications_active',
                'description': 'Countdowns, Termine und Erinnerungsbenachrichtigungen.',
            },
        ),
    },
    {
        'key': 'dashboard',
        'label': 'Wir-Bildschirm',
        'icon': 'dashboard',
        'description': 'Bestimmt, welche automatischen Bereiche auf dem Wir-Bildschirm erscheinen.',
        'features': (
            {
                'key': 'dashboard_recent',
                'setting': 'feature_dashboard_recent_enabled',
                'label': 'Zuletzt bei uns',
                'icon': 'history',
                'description': 'Zeigt die zuletzt hinzugefügten gemeinsamen Inhalte.',
            },
            {
                'key': 'dashboard_upcoming',
                'setting': 'feature_dashboard_upcoming_enabled',
                'label': 'Demnächst',
                'icon': 'event_upcoming',
                'description': 'Zeigt bevorstehende Countdowns und Termine.',
            },
        ),
    },
)

_FEATURES = {
    feature['key']: feature
    for group in FEATURE_GROUPS
    for feature in group['features']
}

_PATH_FEATURES = (
    ('/api/v2/daily-question', 'daily_questions'),
    ('/questions', 'daily_questions'),
    ('/couple/thinking-of-you', 'thinking_of_you'),
    ('/api/v2/heart-moments', 'heart_moments'),
    ('/heart-moments', 'heart_moments'),
    ('/memories', 'memories'),
    ('/milestones', 'milestones'),
    ('/story', 'story'),
    ('/year', 'year_recap'),
    ('/chapters', 'chapters'),
    ('/plans', 'plans'),
    ('/bucketlist', 'bucketlist'),
    ('/places', 'places'),
    ('/api/v2/reminders', 'reminders'),
    ('/reminders', 'reminders'),
)


def normalize_feature_key(key):
    return str(key or '').strip().lower().replace('-', '_')


def feature_exists(key):
    return normalize_feature_key(key) in _FEATURES


def _setting_name(key):
    feature = _FEATURES.get(normalize_feature_key(key))
    return feature['setting'] if feature else None


def _read_setting_enabled(setting_name):
    session = SessionLocal()
    try:
        row = (
            session.query(Setting)
            .filter(Setting.name == setting_name)
            .order_by(Setting.id.asc())
            .first()
        )
        if row is None or row.value is None:
            return True
        return str(row.value).strip().lower() in _TRUE_VALUES
    finally:
        session.close()


def is_feature_enabled(key):
    normalized = normalize_feature_key(key)
    setting_name = _setting_name(normalized)
    if not setting_name:
        return False

    if has_request_context():
        cache = getattr(g, '_sidebyside_feature_flags', None)
        if cache is None:
            cache = {}
            g._sidebyside_feature_flags = cache
        if normalized not in cache:
            cache[normalized] = _read_setting_enabled(setting_name)
        return cache[normalized]

    return _read_setting_enabled(setting_name)


def set_feature_enabled(key, enabled):
    normalized = normalize_feature_key(key)
    setting_name = _setting_name(normalized)
    if not setting_name:
        raise KeyError(normalized)
    if not isinstance(enabled, bool):
        raise TypeError('enabled must be bool')

    session = SessionLocal()
    try:
        row = (
            session.query(Setting)
            .filter(Setting.name == setting_name)
            .order_by(Setting.id.asc())
            .first()
        )
        value = 'True' if enabled else 'False'
        if row is None:
            row = Setting(
                name=setting_name,
                value=value,
                icon='toggle_on',
                category='features',
                type='boolean',
            )
            session.add(row)
        else:
            row.value = value
        session.commit()
    finally:
        session.close()

    if has_request_context():
        cache = getattr(g, '_sidebyside_feature_flags', None)
        if cache is not None:
            cache[normalized] = enabled

    return enabled


def get_feature_groups():
    return [
        {
            'key': group['key'],
            'label': group['label'],
            'icon': group['icon'],
            'description': group['description'],
            'features': [
                {
                    **feature,
                    'enabled': is_feature_enabled(feature['key']),
                }
                for feature in group['features']
            ],
        }
        for group in FEATURE_GROUPS
    ]


def feature_key_for_list_type_id(list_type_id):
    try:
        list_type_id = int(list_type_id)
    except (TypeError, ValueError):
        return None

    session = SessionLocal()
    try:
        list_type = (
            session.query(ListType)
            .filter(ListType.id == list_type_id)
            .first()
        )
        if not list_type:
            return None
        return _feature_key_for_list_type(list_type)
    finally:
        session.close()


def _feature_key_for_list_type(list_type):
    title = str(getattr(list_type, 'title', '') or '').strip().casefold()
    content_url = str(
        getattr(list_type, 'contentURL', '') or ''
    ).strip().casefold()

    if getattr(list_type, 'id', None) == 1 or title == 'home':
        return 'memories'
    if getattr(list_type, 'id', None) == 2 or title == 'moments':
        return 'milestones'
    if content_url in {'bucket-list', 'bucketlist'}:
        return 'bucketlist'
    if title == 'countdown':
        return 'reminders'
    return 'custom_lists'


def _feature_for_content_url(content_url):
    if not content_url:
        return None

    session = SessionLocal()
    try:
        list_type = (
            session.query(ListType)
            .filter(ListType.contentURL == str(content_url))
            .first()
        )
        return _feature_key_for_list_type(list_type) if list_type else None
    finally:
        session.close()


def _feature_for_item_id(item_id):
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return None

    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None
        return feature_key_for_list_type_id(item.listType)
    finally:
        session.close()


def feature_key_for_request(req):
    path = str(req.path or '')

    for prefix, feature_key in _PATH_FEATURES:
        if path == prefix or path.startswith(prefix + '/'):
            return feature_key

    # Generic list pages are served through /<path:content_url>.
    view_args = req.view_args or {}
    content_url = view_args.get('content_url')
    if content_url:
        feature_key = _feature_for_content_url(content_url)
        if feature_key:
            return feature_key

    # Item create/delete/update APIs carry the listType in the request.
    if path == '/api/v2/items':
        raw = req.form.get('listType')
        if raw:
            return feature_key_for_list_type_id(raw)

    if path.startswith('/api/v2/item/'):
        raw = req.form.get('listType')
        if raw:
            return feature_key_for_list_type_id(raw)

        item_id = view_args.get('id')
        if item_id is None:
            match = re.match(r'^/api/v2/item/(\d+)', path)
            item_id = match.group(1) if match else None
        if item_id is not None:
            return _feature_for_item_id(item_id)

    # Share endpoints and gallery pages also expose a concrete item id.
    match = re.match(r'^/api/v2/items/(\d+)', path)
    if match:
        return _feature_for_item_id(match.group(1))

    match = re.match(r'^/gallery/(\d+)', path)
    if match:
        return _feature_for_item_id(match.group(1))

    return None


def disabled_feature_for_request(req):
    key = feature_key_for_request(req)
    if key and not is_feature_enabled(key):
        return key
    return None
