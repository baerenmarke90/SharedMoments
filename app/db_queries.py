from sqlalchemy.exc import IntegrityError
from .models import (Passkey, User, Role, Permission, RolePermission, UserRole, Setting,
    UserSetting, Item, ItemShare, ListType, SessionLocal, Translation,
    Reminder, ReminderMute, PushSubscription, NotificationLog, CoupleChapter,
    CoupleChapterItem, CoupleChapterHeartMoment, CouplePlan, CoupleBucketPlanLink,
    CouplePlace, CouplePlaceLink, PrivateEntry)
from sqlalchemy.orm import joinedload
from datetime import date
import math
from sqlalchemy import desc, asc, and_, or_, func
from app.logger import log
from app.version import __version__


# Initial Database Setup
def init_db():
    session = SessionLocal()
    try:
        # Simple guard: if roles exist, DB was already initialized
        if session.query(Role).count() > 0:
            log('debug', 'Database already initialized — skipping')
            return

        log('info', 'Database is empty — creating default data')

        # System user
        system_user = User(firstName='system')
        session.add(system_user)

        # Roles
        roles = {
            'System': Role(roleName='System'),
            'Admin': Role(roleName='Admin'),
            'Adult': Role(roleName='Adult'),
            'Child': Role(roleName='Child'),
        }
        session.add_all(roles.values())

        # List types (English keys — displayed via translation system)
        list_types = {
            'Home': ListType(title='Home', icon='home', contentURL='home', createdByUser=1, navbar=True, navbarOrder=1, routeID='home', mainTitle='Home'),
            'Moments': ListType(title='Moments', icon='', contentURL='', createdByUser=1, navbar=False, navbarOrder=0, routeID='', mainTitle='Moments'),
            'Movie List': ListType(title='Movie List', icon='movie', contentURL='movie-list', createdByUser=1, navbar=True, navbarOrder=4, routeID='movie-list', mainTitle='Movie List'),
            'Bucket List': ListType(title='Bucket List', icon='list', contentURL='bucket-list', createdByUser=1, navbar=True, navbarOrder=5, routeID='bucket-list', mainTitle='Bucket List'),
            'Countdown': ListType(title='Countdown', icon='timer', contentURL='', createdByUser=1, navbar=False, navbarOrder=0, routeID='', mainTitle='Countdown'),
        }
        session.add_all(list_types.values())
        session.flush()  # IDs for list_types and roles available

        # Permissions — CRUD for entities + per-list + global
        perm_names = [
            'Read Setting', 'Update Setting',
        ]
        # Per-list permissions (linked to list type)
        list_perm_actions = ['View', 'Create', 'Update', 'Delete']
        list_perm_names = []
        for lt_name in ['Home', 'Moments', 'Movie List', 'Bucket List', 'Countdown']:
            for action in list_perm_actions:
                list_perm_names.append(f'{action} {lt_name}')

        # Global permissions
        global_perm_names = ['Manage Lists', 'Manage Translations', 'Access Admin Panel', 'Share Items',
                             'View Reminders', 'Create Reminder', 'Update Reminder', 'Delete Reminder']

        all_perm_names = perm_names + list_perm_names + global_perm_names
        permissions = {}
        for name in all_perm_names:
            permissions[name] = Permission(permissionName=name)
        session.add_all(permissions.values())
        session.flush()  # Permission IDs available

        # Link per-list permissions to their list types
        for lt_name, lt_obj in list_types.items():
            for action in list_perm_actions:
                perm_name = f'{action} {lt_name}'
                permissions[perm_name].listTypeID = lt_obj.id

        # Role permissions — by name instead of hardcoded IDs
        admin_role = roles['Admin']
        adult_role = roles['Adult']
        child_role = roles['Child']

        # Admin gets all permissions except Manage Translations
        for perm in permissions.values():
            if perm.permissionName == 'Manage Translations':
                continue
            session.add(RolePermission(roleID=admin_role.id, permissionID=perm.id))

        # Adult permissions
        adult_perms = [
            'Read Setting',
            'View Home', 'Create Home', 'Update Home', 'Delete Home',
            'View Moments', 'Create Moments', 'Update Moments', 'Delete Moments',
            'View Movie List', 'Create Movie List', 'Update Movie List', 'Delete Movie List',
            'View Bucket List', 'Create Bucket List', 'Update Bucket List', 'Delete Bucket List',
            'View Countdown', 'Create Countdown',
            'Share Items',
            'View Reminders', 'Create Reminder',
        ]
        for perm_name in adult_perms:
            session.add(RolePermission(roleID=adult_role.id, permissionID=permissions[perm_name].id))

        # Child permissions
        child_perms = [
            'Read Setting',
            'View Home', 'Create Home',
            'View Moments', 'Create Moments',
            'View Movie List', 'Create Movie List',
            'View Bucket List', 'Create Bucket List',
            'View Countdown',
            'View Reminders',
        ]
        for perm_name in child_perms:
            session.add(RolePermission(roleID=child_role.id, permissionID=permissions[perm_name].id))

        # System user → Admin role
        session.add(UserRole(userID=system_user.id, roleID=admin_role.id))

        # Settings
        settings = [
            Setting(name='sm_version', value=__version__, icon='update', category='about', type='text'),
            Setting(name='setup_complete', value='False', icon='', category='', type='text'),
            Setting(name='anniversary_date', value='', icon='event', category='general', type='date'),
            Setting(name='engaged_date', value='', icon='event', category='general', type='date'),
            Setting(name='wedding_date', value='', icon='event', category='general', type='date'),
            Setting(name='share_tracking', value='True', icon='analytics', category='general', type='toggle'),
            Setting(name='banner_image', value='', icon='image', category='general', type='file'),
            Setting(name='banner_song', value='', icon='music_note', category='general', type='file'),
            Setting(name='migration_review_complete', value='True', icon='', category='', type='text'),
        ]
        session.add_all(settings)
        # Default user setting
        session.add(UserSetting(userID=system_user.id, name='language', value='en-US'))

        # Seed translations for list type titles
        list_type_translations = {
            'Home':        {'en-US': 'Home',        'de-DE': 'Home'},
            'Moments':     {'en-US': 'Moments',     'de-DE': 'Momente'},
            'Movie List':  {'en-US': 'Movie List',  'de-DE': 'Filmliste'},
            'Bucket List': {'en-US': 'Bucket List', 'de-DE': 'Bucketliste'},
            'Countdown':   {'en-US': 'Countdown',   'de-DE': 'Countdown'},
        }
        for field_name, langs in list_type_translations.items():
            for lang_code, text in langs.items():
                session.add(Translation(
                    entityType='ui', entityID=0,
                    languageCode=lang_code, fieldName=field_name,
                    translatedText=text,
                ))

        session.commit()
        log('info', 'Database initialized successfully')
    finally:
        session.close()


def sync_version_to_db():
    """Update the sm_version setting in the DB to match app/version.py."""
    session = SessionLocal()
    try:
        setting = session.query(Setting).filter_by(name='sm_version').first()
        if setting and setting.value != __version__:
            setting.value = __version__
            session.commit()
            log('info', f'Updated sm_version in DB to {__version__}')
    finally:
        session.close()


# Table Users

def create_user(firstName, lastName, email, birthDate, profilePicture, passwordHash, passwordSalt, public_key=None, credential_id=None, sign_count=0):
    session = SessionLocal()
    try:
        new_user = User(
            firstName=firstName,
            lastName=lastName,
            email=email,
            birthDate=birthDate,
            profilePicture=profilePicture,
            passwordHash=str(passwordHash),
            passwordSalt=passwordSalt
        )
        session.add(new_user)
        session.flush()
        if credential_id and public_key:
            passkey = Passkey(
                userID=new_user.id,
                name='Imported Passkey',
                credential_id=credential_id,
                public_key=public_key,
                sign_count=sign_count or 0
            )
            session.add(passkey)
        session.commit()
        return new_user.id
    finally:
        session.close()

def get_user_by_id(user_id):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            session.expunge(user)
        return user
    finally:
        session.close()

def update_user_profile_picture(user_id, filename):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            user.profilePicture = filename
            session.commit()
            return True
        return False
    finally:
        session.close()

def update_user_password(user_id, password_hash, password_salt):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if user:
            user.passwordHash = password_hash
            user.passwordSalt = password_salt
            session.commit()
            return True
        return False
    finally:
        session.close()

def get_user_by_email(email):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.email == email).first()
        if user:
            session.expunge(user)
        return user
    finally:
        session.close()

def get_user_by_credential_id(credential_id):
    session = SessionLocal()
    try:
        credentials = session.query(Passkey).filter(Passkey.credential_id == credential_id).first()
        if not credentials:
            return None, None
        user = session.query(User).filter(User.id == credentials.userID).first()
        session.expunge(credentials)
        if user:
            session.expunge(user)
        return credentials, user
    finally:
        session.close()

def update_passkey_sign_count(credential_id, sign_count):
    session = SessionLocal()
    try:
        credentials = session.query(Passkey).filter(Passkey.credential_id == credential_id).first()
        if credentials:
            credentials.sign_count = sign_count
            session.commit()
    finally:
        session.close()


def get_passkeys_by_user(user_id):
    """Alle Passkeys eines Users laden."""
    session = SessionLocal()
    try:
        passkeys = session.query(Passkey).filter(Passkey.userID == user_id).all()
        for p in passkeys:
            session.expunge(p)
        return passkeys
    finally:
        session.close()


def create_passkey(user_id, name, credential_id, public_key, sign_count=0):
    """Neuen Passkey für User anlegen."""
    session = SessionLocal()
    try:
        passkey = Passkey(
            userID=user_id,
            name=name,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count
        )
        session.add(passkey)
        session.commit()
        session.refresh(passkey)
        pid = passkey.id
        return pid
    finally:
        session.close()


def delete_passkey(passkey_id, user_id):
    """Passkey löschen (nur wenn er dem User gehört)."""
    session = SessionLocal()
    try:
        passkey = session.query(Passkey).filter(
            Passkey.id == passkey_id,
            Passkey.userID == user_id
        ).first()
        if passkey:
            session.delete(passkey)
            session.commit()
            return True
        return False
    finally:
        session.close()


def rename_passkey(passkey_id, user_id, new_name):
    """Passkey umbenennen (nur wenn er dem User gehört)."""
    session = SessionLocal()
    try:
        passkey = session.query(Passkey).filter(
            Passkey.id == passkey_id,
            Passkey.userID == user_id
        ).first()
        if passkey:
            passkey.name = new_name
            session.commit()
            return True
        return False
    finally:
        session.close()

# Table Role

def create_role(roleName, description):
    session = SessionLocal()
    try:
        new_role = Role(
            roleName=roleName,
            description=description
        )
        session.add(new_role)
        session.commit()
    finally:
        session.close()

def get_role_by_name(role_name):
    session = SessionLocal()
    try:
        role = session.query(Role).filter(Role.roleName == role_name).first()
        return role.id
    finally:
        session.close()

def update_role(role_id, roleName=None, description=None):
    session = SessionLocal()
    try:
        role = session.query(Role).filter(Role.id == role_id).first()
        if role:
            if roleName:
                role.roleName = roleName
            if description:
                role.description = description
            session.commit()
    finally:
        session.close()

def delete_role(role_id):
    session = SessionLocal()
    try:
        role = session.query(Role).filter(Role.id == role_id).first()
        if role:
            session.delete(role)
            session.commit()
    finally:
        session.close()


# Admin query functions

def get_all_users():
    """Returns all users except the system user (id=1)."""
    session = SessionLocal()
    try:
        users = session.query(User).filter(User.id != 1).all()
        for user in users:
            session.expunge(user)
        return users
    finally:
        session.close()

def get_all_roles():
    """Returns all roles except System (id=1)."""
    session = SessionLocal()
    try:
        roles = session.query(Role).filter(Role.id != 1).all()
        for role in roles:
            session.expunge(role)
        return roles
    finally:
        session.close()

def get_all_permissions_list():
    """Returns all permissions."""
    session = SessionLocal()
    try:
        permissions = session.query(Permission).all()
        for p in permissions:
            session.expunge(p)
        return permissions
    finally:
        session.close()

def get_role_permissions_map():
    """Returns a dict: {roleID: [permissionID, ...]}"""
    session = SessionLocal()
    try:
        rps = session.query(RolePermission).all()
        result = {}
        for rp in rps:
            if rp.roleID not in result:
                result[rp.roleID] = []
            result[rp.roleID].append(rp.permissionID)
        return result
    finally:
        session.close()

def get_user_roles_map():
    """Returns a dict: {userID: [roleID, ...]}"""
    session = SessionLocal()
    try:
        urs = session.query(UserRole).all()
        result = {}
        for ur in urs:
            if ur.userID not in result:
                result[ur.userID] = []
            result[ur.userID].append(ur.roleID)
        return result
    finally:
        session.close()

def get_role_permissions_for_role(role_id):
    """Returns permission IDs for a specific role."""
    session = SessionLocal()
    try:
        rps = session.query(RolePermission.permissionID).filter(RolePermission.roleID == role_id).all()
        return [rp[0] for rp in rps]
    finally:
        session.close()

def get_user_roles_list(user_id):
    """Returns role IDs for a specific user."""
    session = SessionLocal()
    try:
        urs = session.query(UserRole.roleID).filter(UserRole.userID == user_id).all()
        return [ur[0] for ur in urs]
    finally:
        session.close()

def set_role_permissions(role_id, permission_ids):
    """Replaces all permissions for a role."""
    session = SessionLocal()
    try:
        session.query(RolePermission).filter(RolePermission.roleID == role_id).delete()
        for pid in permission_ids:
            session.add(RolePermission(roleID=role_id, permissionID=pid))
        session.commit()
    finally:
        session.close()

def set_user_roles(user_id, role_ids):
    """Replaces all roles for a user."""
    session = SessionLocal()
    try:
        session.query(UserRole).filter(UserRole.userID == user_id).delete()
        for rid in role_ids:
            session.add(UserRole(userID=user_id, roleID=rid))
        session.commit()
    finally:
        session.close()


# Table Permission

def create_permission(permissionName, description):
    session = SessionLocal()
    try:
        new_permission = Permission(
            permissionName=permissionName,
            description=description
        )
        session.add(new_permission)
        session.commit()
    finally:
        session.close()

def get_permission(permission_id):
    session = SessionLocal()
    try:
        permission = session.query(Permission).filter(Permission.id == permission_id).first()
        return permission
    finally:
        session.close()

def update_permission(permission_id, permissionName=None, description=None):
    session = SessionLocal()
    try:
        permission = session.query(Permission).filter(Permission.id == permission_id).first()
        if permission:
            if permissionName:
                permission.permissionName = permissionName
            if description:
                permission.description = description
            session.commit()
    finally:
        session.close()

def delete_permission(permission_id):
    session = SessionLocal()
    try:
        permission = session.query(Permission).filter(Permission.id == permission_id).first()
        if permission:
            session.delete(permission)
            session.commit()
    finally:
        session.close()


# Table RolePermission

def create_role_permission(roleID, permissionID):
    session = SessionLocal()
    try:
        new_role_permission = RolePermission(
            roleID=roleID,
            permissionID=permissionID
        )
        session.add(new_role_permission)
        session.commit()
    finally:
        session.close()

def get_role_permission(roleID, permissionID):
    session = SessionLocal()
    try:
        role_permission = session.query(RolePermission).filter_by(roleID=roleID, permissionID=permissionID).first()
        return role_permission
    finally:
        session.close()

def update_role_permission(roleID, permissionID, new_roleID=None, new_permissionID=None):
    session = SessionLocal()
    try:
        role_permission = session.query(RolePermission).filter_by(roleID=roleID, permissionID=permissionID).first()
        if role_permission:
            if new_roleID is not None:
                role_permission.roleID = new_roleID
            if new_permissionID is not None:
                role_permission.permissionID = new_permissionID
            session.commit()
    finally:
        session.close()

def delete_role_permission(roleID, permissionID):
    session = SessionLocal()
    try:
        role_permission = session.query(RolePermission).filter_by(roleID=roleID, permissionID=permissionID).first()
        if role_permission:
            session.delete(role_permission)
            session.commit()
    finally:
        session.close()


# Table UserRole

def create_user_role(userID, roleID):
    session = SessionLocal()
    try:
        new_user_role = UserRole(
            userID=userID,
            roleID=roleID
        )
        session.add(new_user_role)
        session.commit()
    finally:
        session.close()

def get_user_role(userID, roleID):
    session = SessionLocal()
    try:
        user_role = session.query(UserRole).filter_by(userID=userID, roleID=roleID).first()
        return user_role
    finally:
        session.close()

def update_user_role(userID, roleID, new_userID=None, new_roleID=None):
    session = SessionLocal()
    try:
        user_role = session.query(UserRole).filter_by(userID=userID, roleID=roleID).first()
        if user_role:
            if new_userID:
                user_role.userID = new_userID
            if new_roleID:
                user_role.roleID = new_roleID
            session.commit()
    finally:
        session.close()

def delete_user_role(userID, roleID):
    session = SessionLocal()
    try:
        user_role = session.query(UserRole).filter_by(userID=userID, roleID=roleID).first()
        if user_role:
            session.delete(user_role)
            session.commit()
    finally:
        session.close()

# Table Setting

def create_setting(name, value):
    session = SessionLocal()
    try:
        new_setting = Setting(
            name=name,
            value=value
        )
        session.add(new_setting)
        session.commit()
    finally:
        session.close()

class SettingObject:
    def __init__(self, setting):
        for column in setting.__table__.columns:
            setattr(self, column.name, getattr(setting, column.name))

class SettingsContainer:
    def __init__(self, settings_list):
        self.settings_list = settings_list
        for setting in settings_list:
            setattr(self, setting.name, SettingObject(setting))

    def __iter__(self):
        return iter(self.settings_list)

def get_all_settings():
    session = SessionLocal()
    try:
        settings_list = session.query(Setting).all()
        return SettingsContainer(settings_list)
    finally:
        session.close()

def get_setting_by_name(name):
    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.name == name).first()
        if setting is None:
            return Setting(name=name, value=None)
        return setting
    finally:
        session.close()

def update_setting(name, new_value):
    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.name == name).first()
        if setting:
            setting.value = new_value
            session.commit()
    finally:
        session.close()

# Table UserSetting

def create_user_setting(userID, setting, value):
    session = SessionLocal()
    try:
        new_user_setting = UserSetting(
            userID=userID,
            name=setting,
            value=value
        )
        session.add(new_user_setting)
        session.commit()
    finally:
        session.close()

def get_all_user_settings():
    session = SessionLocal()
    try:
        user_settings = session.query(UserSetting).all()
        return user_settings
    finally:
        session.close()

def get_user_setting(userID, name):
    session = SessionLocal()
    try:
        user_setting = session.query(UserSetting).filter(UserSetting.userID == userID, UserSetting.name == name).first()
        return user_setting
    finally:
        session.close()

def get_user_settings(userID):
    session = SessionLocal()
    try:
        user_settings = session.query(UserSetting).filter(UserSetting.userID == userID).all()
        return user_settings
    finally:
        session.close()

def update_user_setting(userID, name=None, value=None):
    session = SessionLocal()
    try:
        user_setting = session.query(UserSetting).filter(UserSetting.userID == userID, UserSetting.name == name).first()
        if user_setting:
            if value is not None:
                user_setting.value = value
        else:
            session.add(UserSetting(userID=userID, name=name, value=value or ''))
        session.commit()
    finally:
        session.close()


def ensure_notification_settings(userID):
    """Creates or updates notification settings for a user."""
    notification_defaults = {
        'notification_push_enabled': {'value': 'True', 'icon': 'notifications', 'category': 'notifications', 'type': 'toggle'},
        'notification_email_enabled': {'value': 'False', 'icon': 'email', 'category': 'notifications', 'type': 'toggle'},
        'notification_telegram_enabled': {'value': 'False', 'icon': 'chat', 'category': 'notifications', 'type': 'toggle'},
        'notification_telegram_chat_id': {'value': '', 'icon': 'chat', 'category': 'notifications', 'type': 'text'},
    }
    session = SessionLocal()
    try:
        for name, defaults in notification_defaults.items():
            existing = session.query(UserSetting).filter(
                UserSetting.userID == userID,
                UserSetting.name == name
            ).first()
            if not existing:
                session.add(UserSetting(
                    userID=userID, name=name, value=defaults['value'],
                    icon=defaults['icon'],
                    category=defaults['category'], type=defaults['type']
                ))
            elif not existing.icon:
                existing.icon = defaults['icon']
                existing.category = defaults['category']
                existing.type = defaults['type']
        session.commit()
    finally:
        session.close()


def ensure_pwa_settings(userID):
    """Creates default PWA settings for a user if they don't exist yet."""
    pwa_defaults = {
        'pwa_offline_all': 'FALSE',
        'pwa_auto_cache_count': '20',
        'pwa_cache_expiry_days': '14',
        'pwa_wifi_only_upload': 'FALSE',
        'pwa_preload_on_wifi': 'FALSE',
    }
    session = SessionLocal()
    try:
        for name, default_value in pwa_defaults.items():
            existing = session.query(UserSetting).filter(
                UserSetting.userID == userID,
                UserSetting.name == name
            ).first()
            if not existing:
                session.add(UserSetting(userID=userID, name=name, value=default_value))
        session.commit()
    finally:
        session.close()


# Table Item

def create_item(title, content, contentType, listType, contentURL, createdByUser, dateCreated, blurPlaceholder=None, mediaWidth=None, mediaHeight=None):
    session = SessionLocal()
    try:
        new_item = Item(
            title=title,
            content=content,
            contentType=contentType,
            listType=listType,
            contentURL=contentURL,
            createdByUser=createdByUser,
            dateCreated=dateCreated,
            blurPlaceholder=blurPlaceholder,
            mediaWidth=mediaWidth,
            mediaHeight=mediaHeight
        )
        session.add(new_item)
        session.commit()
        session.refresh(new_item)
        return new_item.id
    finally:
        session.close()

def get_item_by_id(item_id):
    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        return item
    finally:
        session.close()

def get_all_media_urls():
    session = SessionLocal()
    try:
        items = session.query(Item.id, Item.contentType, Item.contentURL).filter(Item.contentURL.isnot(None), Item.contentURL != '').all()
        urls = []
        for item_id, content_type, content_url in items:
            for filename in content_url.split(';'):
                filename = filename.strip()
                if filename:
                    urls.append(f'/api/v2/media/{filename}')
            # Gallery-Seiten auch cachen
            if content_type and content_type.startswith('gallery'):
                urls.append(f'/gallery/{item_id}')
        return urls
    finally:
        session.close()

def get_items_by_type(list_type_id, sort_by='desc', checked_last=False):
    session = SessionLocal()
    try:
        order_func = desc if sort_by == 'desc' else asc
        query = session.query(Item, User).join(User, Item.createdByUser == User.id).filter(Item.listType == list_type_id)
        if checked_last:
            query = query.order_by(asc(Item.content == '1'), order_func(Item.dateCreated))
        else:
            query = query.order_by(order_func(Item.dateCreated))
        items = query.all()
        return items
    finally:
        session.close()

def update_item(item_id, title=None, content=None, contentType=None, contentURL=None, dateCreated=None, blurPlaceholder=None, mediaWidth=None, mediaHeight=None):
    session = SessionLocal()
    try:
        item = session.query(Item).filter(Item.id == item_id).first()
        if item:
            if title is not None:
                item.title = title
            if content is not None:
                item.content = content
            if contentType is not None:
                item.contentType = contentType
            if contentURL is not None:
                item.contentURL = contentURL
            if dateCreated is not None:
                item.dateCreated = dateCreated
            if blurPlaceholder is not None:
                item.blurPlaceholder = blurPlaceholder
            if mediaWidth is not None:
                item.mediaWidth = mediaWidth
            if mediaHeight is not None:
                item.mediaHeight = mediaHeight
            session.commit()
    finally:
        session.close()

def delete_item(item_id):
    session = SessionLocal()
    try:
        # A Countdown is stored as an Item. Reminder rows may reference that
        # Item via countdown_id. Remove those dependent rows first so deleting
        # a countdown cannot leave a reminder orphan behind.
        linked_reminders = session.query(Reminder).filter(
            Reminder.countdown_id == item_id
        ).all()

        for reminder in linked_reminders:
            session.query(ReminderMute).filter(
                ReminderMute.reminder_id == reminder.id
            ).delete()
            session.delete(reminder)

        session.query(CoupleChapterItem).filter(
            CoupleChapterItem.itemID == item_id
        ).delete()

        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceID == item_id,
            CouplePlaceLink.sourceType.in_(['memory', 'milestone']),
        ).delete(synchronize_session=False)

        # Bucketlist items may be promoted into a concrete couple plan.
        # Deleting the wish only removes that relationship; the plan itself
        # remains intact.
        session.query(CoupleBucketPlanLink).filter(
            CoupleBucketPlanLink.bucketItemID == item_id
        ).delete()

        session.query(ItemShare).filter(ItemShare.itemID == item_id).delete()

        item = session.query(Item).filter(Item.id == item_id).first()
        if item:
            session.delete(item)

        # Commit even when the Item itself is already gone: this also cleans
        # a remaining linked reminder if delete_item() is called for that ID.
        session.commit()
    finally:
        session.close()


# Couple Chapters

def _serialize_couple_chapter(chapter, creator=None):
    return {
        'id': chapter.id,
        'title': chapter.title,
        'description': chapter.description or '',
        'startDate': chapter.startDate,
        'endDate': chapter.endDate,
        'locationName': chapter.locationName or '',
        'latitude': chapter.latitude,
        'longitude': chapter.longitude,
        'createdByUser': chapter.createdByUser,
        'dateCreated': chapter.dateCreated,
        'dateModified': chapter.dateModified,
        'creator': {
            'id': creator.id,
            'firstName': creator.firstName or '',
            'profilePicture': creator.profilePicture,
        } if creator else None,
    }


def get_couple_chapters():
    session = SessionLocal()
    try:
        rows = (
            session.query(CoupleChapter, User)
            .join(User, CoupleChapter.createdByUser == User.id)
            .all()
        )
        chapters = [
            _serialize_couple_chapter(chapter, creator)
            for chapter, creator in rows
        ]
        def chapter_sort_key(chapter):
            created = chapter['dateCreated']
            if created and hasattr(created, 'date'):
                created = created.date()
            return (
                chapter['startDate'] or created or date.min,
                created or date.min,
                chapter['id'],
            )

        chapters.sort(
            key=chapter_sort_key,
            reverse=True,
        )
        return chapters
    finally:
        session.close()


def get_couple_chapter(chapter_id):
    session = SessionLocal()
    try:
        row = (
            session.query(CoupleChapter, User)
            .join(User, CoupleChapter.createdByUser == User.id)
            .filter(CoupleChapter.id == chapter_id)
            .first()
        )
        if not row:
            return None
        return _serialize_couple_chapter(row[0], row[1])
    finally:
        session.close()


def create_couple_chapter(
    title,
    description,
    start_date,
    end_date,
    location_name,
    created_by_user,
):
    session = SessionLocal()
    try:
        chapter = CoupleChapter(
            title=title,
            description=description or '',
            startDate=start_date,
            endDate=end_date,
            locationName=location_name or '',
            createdByUser=created_by_user,
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
        return chapter.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_couple_chapter(
    chapter_id,
    title,
    description,
    start_date,
    end_date,
    location_name,
):
    session = SessionLocal()
    try:
        chapter = (
            session.query(CoupleChapter)
            .filter(CoupleChapter.id == chapter_id)
            .first()
        )
        if not chapter:
            return False

        chapter.title = title
        chapter.description = description or ''
        chapter.startDate = start_date
        chapter.endDate = end_date
        chapter.locationName = location_name or ''
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_couple_chapter(chapter_id):
    session = SessionLocal()
    try:
        chapter = (
            session.query(CoupleChapter)
            .filter(CoupleChapter.id == chapter_id)
            .first()
        )
        if not chapter:
            return False

        session.query(CoupleChapterItem).filter(
            CoupleChapterItem.chapterID == chapter_id
        ).delete()
        session.query(CoupleChapterHeartMoment).filter(
            CoupleChapterHeartMoment.chapterID == chapter_id
        ).delete()
        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceType == 'chapter',
            CouplePlaceLink.sourceID == chapter_id,
        ).delete(synchronize_session=False)
        session.query(CouplePlan).filter(
            CouplePlan.chapterID == chapter_id
        ).update(
            {CouplePlan.chapterID: None},
            synchronize_session=False,
        )
        session.delete(chapter)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_couple_chapter_links(chapter_id):
    session = SessionLocal()
    try:
        item_ids = {
            row[0]
            for row in session.query(CoupleChapterItem.itemID).filter(
                CoupleChapterItem.chapterID == chapter_id
            ).all()
        }
        heart_ids = {
            row[0]
            for row in session.query(
                CoupleChapterHeartMoment.heartMomentID
            ).filter(
                CoupleChapterHeartMoment.chapterID == chapter_id
            ).all()
        }
        return {
            'item_ids': item_ids,
            'heart_ids': heart_ids,
        }
    finally:
        session.close()


def replace_couple_chapter_links(chapter_id, item_ids, heart_ids):
    session = SessionLocal()
    try:
        session.query(CoupleChapterItem).filter(
            CoupleChapterItem.chapterID == chapter_id
        ).delete()
        session.query(CoupleChapterHeartMoment).filter(
            CoupleChapterHeartMoment.chapterID == chapter_id
        ).delete()

        for item_id in sorted(set(item_ids)):
            session.add(CoupleChapterItem(
                chapterID=chapter_id,
                itemID=item_id,
            ))

        for heart_id in sorted(set(heart_ids)):
            session.add(CoupleChapterHeartMoment(
                chapterID=chapter_id,
                heartMomentID=heart_id,
            ))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_couple_chapter_link_map():
    """Return chapter links in both directions for UI aggregation."""
    session = SessionLocal()
    try:
        chapters = {
            chapter.id: {
                'id': chapter.id,
                'title': chapter.title,
            }
            for chapter in session.query(CoupleChapter).all()
        }

        by_chapter = {
            chapter_id: {
                'item_ids': set(),
                'heart_ids': set(),
            }
            for chapter_id in chapters
        }
        item_chapters = {}
        heart_chapters = {}

        for link in session.query(CoupleChapterItem).all():
            if link.chapterID not in chapters:
                continue
            by_chapter[link.chapterID]['item_ids'].add(link.itemID)
            item_chapters.setdefault(link.itemID, []).append(
                chapters[link.chapterID]
            )

        for link in session.query(CoupleChapterHeartMoment).all():
            if link.chapterID not in chapters:
                continue
            by_chapter[link.chapterID]['heart_ids'].add(link.heartMomentID)
            heart_chapters.setdefault(link.heartMomentID, []).append(
                chapters[link.chapterID]
            )

        return {
            'chapters': chapters,
            'by_chapter': by_chapter,
            'item_chapters': item_chapters,
            'heart_chapters': heart_chapters,
        }
    finally:
        session.close()


# Couple Plans

_PLAN_STATUSES = {'idea', 'planned', 'experienced'}


def _serialize_couple_plan(plan, creator=None, chapter=None):
    return {
        'id': plan.id,
        'title': plan.title,
        'description': plan.description or '',
        'status': plan.status,
        'targetStartDate': plan.targetStartDate,
        'targetEndDate': plan.targetEndDate,
        'experiencedDate': plan.experiencedDate,
        'locationName': plan.locationName or '',
        'createdByUser': plan.createdByUser,
        'chapterID': plan.chapterID,
        'dateCreated': plan.dateCreated,
        'dateModified': plan.dateModified,
        'creator': {
            'id': creator.id,
            'firstName': creator.firstName or '',
            'profilePicture': creator.profilePicture,
        } if creator else None,
        'chapter': {
            'id': chapter.id,
            'title': chapter.title,
        } if chapter else None,
    }


def get_couple_plans():
    session = SessionLocal()
    try:
        rows = (
            session.query(CouplePlan, User, CoupleChapter)
            .join(User, CouplePlan.createdByUser == User.id)
            .outerjoin(CoupleChapter, CouplePlan.chapterID == CoupleChapter.id)
            .all()
        )
        return [
            _serialize_couple_plan(plan, creator, chapter)
            for plan, creator, chapter in rows
        ]
    finally:
        session.close()


def get_couple_plan(plan_id):
    session = SessionLocal()
    try:
        row = (
            session.query(CouplePlan, User, CoupleChapter)
            .join(User, CouplePlan.createdByUser == User.id)
            .outerjoin(CoupleChapter, CouplePlan.chapterID == CoupleChapter.id)
            .filter(CouplePlan.id == plan_id)
            .first()
        )
        if not row:
            return None
        return _serialize_couple_plan(row[0], row[1], row[2])
    finally:
        session.close()


def create_couple_plan(
    title,
    description,
    status,
    target_start_date,
    target_end_date,
    location_name,
    created_by_user,
    experienced_date=None,
):
    if status not in _PLAN_STATUSES:
        raise ValueError('Invalid plan status')

    # Ein erlebter Plan ohne Datum waere spaeter ein Kapitel ohne Zeitraum.
    if status == 'experienced' and not experienced_date:
        experienced_date = target_end_date or target_start_date or date.today()

    session = SessionLocal()
    try:
        plan = CouplePlan(
            title=title,
            description=description or '',
            status=status,
            targetStartDate=target_start_date,
            targetEndDate=target_end_date,
            experiencedDate=experienced_date if status == 'experienced' else None,
            locationName=location_name or '',
            createdByUser=created_by_user,
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return plan.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_couple_plan(
    plan_id,
    title,
    description,
    status,
    target_start_date,
    target_end_date,
    location_name,
    experienced_date=None,
):
    if status not in _PLAN_STATUSES:
        raise ValueError('Invalid plan status')

    session = SessionLocal()
    try:
        plan = (
            session.query(CouplePlan)
            .filter(CouplePlan.id == plan_id)
            .first()
        )
        if not plan:
            return False

        plan.title = title
        plan.description = description or ''
        plan.status = status
        plan.targetStartDate = target_start_date
        plan.targetEndDate = target_end_date
        plan.locationName = location_name or ''

        if status == 'experienced':
            plan.experiencedDate = (
                experienced_date
                or plan.experiencedDate
                or target_end_date
                or target_start_date
                or date.today()
            )
        else:
            # Zurueck auf Idee/Geplant: das Erlebt-Datum gilt nicht mehr.
            plan.experiencedDate = None

        # If a plan originated from the Bucketlist, reaching "Erlebt" also
        # completes the original wish. The Bucketlist remains the long-term
        # backlog while Plans represent concrete execution.
        if status == 'experienced':
            bucket_link = (
                session.query(CoupleBucketPlanLink)
                .filter(CoupleBucketPlanLink.planID == plan_id)
                .first()
            )
            if bucket_link:
                bucket_item = (
                    session.query(Item)
                    .filter(Item.id == bucket_link.bucketItemID)
                    .first()
                )
                if bucket_item:
                    bucket_item.content = '1'

        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_couple_plan(plan_id):
    session = SessionLocal()
    try:
        plan = (
            session.query(CouplePlan)
            .filter(CouplePlan.id == plan_id)
            .first()
        )
        if not plan:
            return False

        session.query(CoupleBucketPlanLink).filter(
            CoupleBucketPlanLink.planID == plan_id
        ).delete()
        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceType == 'plan',
            CouplePlaceLink.sourceID == plan_id,
        ).delete(synchronize_session=False)

        session.delete(plan)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def set_couple_plan_chapter(plan_id, chapter_id):
    session = SessionLocal()
    try:
        plan = (
            session.query(CouplePlan)
            .filter(CouplePlan.id == plan_id)
            .first()
        )
        if not plan:
            return False
        plan.chapterID = chapter_id
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Bucketlist <-> Couple Plans

def get_couple_bucket_plan_map():
    """Return plans that originated from existing Bucket List Item rows."""
    session = SessionLocal()
    try:
        rows = (
            session.query(CoupleBucketPlanLink, CouplePlan)
            .join(CouplePlan, CoupleBucketPlanLink.planID == CouplePlan.id)
            .all()
        )
        return {
            link.bucketItemID: {
                'id': plan.id,
                'title': plan.title,
                'status': plan.status,
                'chapterID': plan.chapterID,
            }
            for link, plan in rows
        }
    finally:
        session.close()


def link_couple_bucket_plan(bucket_item_id, plan_id):
    session = SessionLocal()
    try:
        existing = (
            session.query(CoupleBucketPlanLink)
            .filter(CoupleBucketPlanLink.bucketItemID == bucket_item_id)
            .first()
        )
        if existing:
            return existing.planID

        link = CoupleBucketPlanLink(
            bucketItemID=bucket_item_id,
            planID=plan_id,
        )
        session.add(link)
        session.commit()
        return plan_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sync_bucket_item_to_plan(bucket_item_id, completed):
    """When a linked Bucketlist wish is checked, mark its plan experienced."""
    if not completed:
        return

    session = SessionLocal()
    try:
        link = (
            session.query(CoupleBucketPlanLink)
            .filter(CoupleBucketPlanLink.bucketItemID == bucket_item_id)
            .first()
        )
        if not link:
            return

        plan = (
            session.query(CouplePlan)
            .filter(CouplePlan.id == link.planID)
            .first()
        )
        if plan and plan.status != 'experienced':
            plan.status = 'experienced'
            session.commit()
    finally:
        session.close()


def return_couple_plan_to_bucketlist(plan_id):
    """Return a Bucketlist-derived active Plan to the open Bucketlist.

    The original Bucketlist Item is kept. The temporary execution Plan and its
    place links are removed so the wish becomes a normal open Bucketlist entry
    again. Experienced plans or plans already converted to a chapter are not
    reversible through this workflow.
    """
    session = SessionLocal()
    try:
        plan = (
            session.query(CouplePlan)
            .filter(CouplePlan.id == plan_id)
            .first()
        )
        if not plan:
            return None

        if plan.status == 'experienced' or plan.chapterID:
            raise ValueError('Experienced plans cannot be returned to the Bucketlist')

        link = (
            session.query(CoupleBucketPlanLink)
            .filter(CoupleBucketPlanLink.planID == plan_id)
            .first()
        )
        if not link:
            return None

        bucket_item = (
            session.query(Item)
            .filter(Item.id == link.bucketItemID)
            .first()
        )
        if not bucket_item:
            return None

        # Keep title changes made while the wish was a concrete plan.
        if plan.title:
            bucket_item.title = plan.title
        bucket_item.content = '0'

        bucket_item_id = bucket_item.id

        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceType == 'plan',
            CouplePlaceLink.sourceID == plan_id,
        ).delete(synchronize_session=False)
        session.delete(link)
        session.delete(plan)
        session.commit()
        return bucket_item_id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Couple Places

_ALLOWED_PLACE_SOURCE_TYPES = {
    'memory',
    'heart',
    'milestone',
    'plan',
    'chapter',
}


def _normalize_couple_place_name(value):
    return ' '.join(str(value or '').strip().casefold().split())


def _serialize_couple_place(place, creator=None):
    return {
        'id': place.id,
        'name': place.name,
        'normalizedName': place.normalizedName,
        'description': place.description or '',
        'addressLabel': place.addressLabel or '',
        'latitude': place.latitude,
        'longitude': place.longitude,
        'createdByUser': place.createdByUser,
        'dateCreated': place.dateCreated,
        'dateModified': place.dateModified,
        'creator': {
            'id': creator.id,
            'firstName': creator.firstName or '',
            'profilePicture': creator.profilePicture,
        } if creator else None,
    }


def get_couple_places():
    session = SessionLocal()
    try:
        rows = (
            session.query(CouplePlace, User)
            .join(User, CouplePlace.createdByUser == User.id)
            .order_by(CouplePlace.name.asc())
            .all()
        )
        return [
            _serialize_couple_place(place, creator)
            for place, creator in rows
        ]
    finally:
        session.close()


def get_couple_place(place_id):
    session = SessionLocal()
    try:
        row = (
            session.query(CouplePlace, User)
            .join(User, CouplePlace.createdByUser == User.id)
            .filter(CouplePlace.id == place_id)
            .first()
        )
        if not row:
            return None
        return _serialize_couple_place(row[0], row[1])
    finally:
        session.close()


# Zwei Orte gelten als derselbe, wenn sie naeher als das hier beieinander
# liegen. 0.002 Grad Breite sind rund 220 Meter - genug, um "Nieuwpoort" und
# "Nieuwpoort, Belgien" zusammenzufuehren, zu wenig, um zwei Restaurants in
# derselben Strasse zu verwechseln.
_PLACE_MATCH_DEGREES = 0.002


def _find_matching_place(session, normalized, latitude=None, longitude=None):
    """Sucht einen bestehenden Ort: erst ueber den Namen, dann ueber die Lage.

    Ohne die zweite Stufe entsteht bei jeder Schreibweise ein neuer Eintrag,
    und nach ein paar Reisen steht derselbe Ort mehrfach in der Liste.
    """
    place = (
        session.query(CouplePlace)
        .filter(CouplePlace.normalizedName == normalized)
        .order_by(CouplePlace.id.asc())
        .first()
    )
    if place or latitude is None or longitude is None:
        return place

    # Laengengrade ruecken zu den Polen hin zusammen.
    lon_span = _PLACE_MATCH_DEGREES / max(math.cos(math.radians(latitude)), 0.1)

    return (
        session.query(CouplePlace)
        .filter(
            CouplePlace.latitude.isnot(None),
            CouplePlace.longitude.isnot(None),
            CouplePlace.latitude.between(
                latitude - _PLACE_MATCH_DEGREES,
                latitude + _PLACE_MATCH_DEGREES,
            ),
            CouplePlace.longitude.between(
                longitude - lon_span,
                longitude + lon_span,
            ),
        )
        .order_by(CouplePlace.id.asc())
        .first()
    )


def _get_or_create_place_in_session(
    session,
    name,
    created_by_user,
    latitude=None,
    longitude=None,
    address_label='',
):
    normalized = _normalize_couple_place_name(name)
    if not normalized:
        return None

    place = _find_matching_place(session, normalized, latitude, longitude)

    if not place:
        place = CouplePlace(
            name=str(name).strip(),
            normalizedName=normalized,
            description='',
            addressLabel=address_label or '',
            latitude=latitude,
            longitude=longitude,
            createdByUser=created_by_user,
        )
        session.add(place)
        session.flush()
    else:
        if place.latitude is None and latitude is not None:
            place.latitude = latitude
        if place.longitude is None and longitude is not None:
            place.longitude = longitude
        if not place.addressLabel and address_label:
            place.addressLabel = address_label

    return place


def create_couple_place(
    name,
    description,
    latitude,
    longitude,
    address_label,
    created_by_user,
):
    session = SessionLocal()
    try:
        normalized = _normalize_couple_place_name(name)
        if not normalized:
            raise ValueError('Place name is required')

        existing = _find_matching_place(session, normalized, latitude, longitude)
        if existing:
            if description and not existing.description:
                existing.description = description
            if address_label and not existing.addressLabel:
                existing.addressLabel = address_label
            if latitude is not None and existing.latitude is None:
                existing.latitude = latitude
            if longitude is not None and existing.longitude is None:
                existing.longitude = longitude
            session.commit()
            return existing.id

        place = CouplePlace(
            name=str(name).strip(),
            normalizedName=normalized,
            description=description or '',
            addressLabel=address_label or '',
            latitude=latitude,
            longitude=longitude,
            createdByUser=created_by_user,
        )
        session.add(place)
        session.commit()
        session.refresh(place)
        return place.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_couple_place(
    place_id,
    name,
    description,
    latitude,
    longitude,
    address_label,
):
    session = SessionLocal()
    try:
        place = (
            session.query(CouplePlace)
            .filter(CouplePlace.id == place_id)
            .first()
        )
        if not place:
            return False

        place.name = str(name).strip()
        place.normalizedName = _normalize_couple_place_name(name)
        place.description = description or ''
        place.addressLabel = address_label or ''
        place.latitude = latitude
        place.longitude = longitude

        # Keep the legacy chapter coordinate fields useful for future
        # Dawarich integration when this place is the chapter's location.
        chapter_ids = {
            row[0]
            for row in session.query(CouplePlaceLink.sourceID).filter(
                CouplePlaceLink.placeID == place_id,
                CouplePlaceLink.sourceType == 'chapter',
                CouplePlaceLink.relationKind == 'location',
            ).all()
        }
        if chapter_ids:
            session.query(CoupleChapter).filter(
                CoupleChapter.id.in_(chapter_ids)
            ).update(
                {
                    CoupleChapter.latitude: latitude,
                    CoupleChapter.longitude: longitude,
                },
                synchronize_session=False,
            )

        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_couple_place(place_id):
    session = SessionLocal()
    try:
        place = (
            session.query(CouplePlace)
            .filter(CouplePlace.id == place_id)
            .first()
        )
        if not place:
            return False

        location_links = session.query(CouplePlaceLink).filter(
            CouplePlaceLink.placeID == place_id,
            CouplePlaceLink.relationKind == 'location',
        ).all()

        plan_ids = {
            link.sourceID for link in location_links
            if link.sourceType == 'plan'
        }
        chapter_ids = {
            link.sourceID for link in location_links
            if link.sourceType == 'chapter'
        }

        if plan_ids:
            session.query(CouplePlan).filter(
                CouplePlan.id.in_(plan_ids)
            ).update(
                {CouplePlan.locationName: ''},
                synchronize_session=False,
            )
        if chapter_ids:
            session.query(CoupleChapter).filter(
                CoupleChapter.id.in_(chapter_ids)
            ).update(
                {
                    CoupleChapter.locationName: '',
                    CoupleChapter.latitude: None,
                    CoupleChapter.longitude: None,
                },
                synchronize_session=False,
            )

        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.placeID == place_id
        ).delete(synchronize_session=False)
        session.delete(place)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sync_couple_source_location(
    source_type,
    source_id,
    location_name,
    created_by_user,
    latitude=None,
    longitude=None,
):
    """Mirror a Plan/Chapter locationName into the canonical place graph."""
    if source_type not in {'plan', 'chapter'}:
        raise ValueError('Unsupported location source type')

    session = SessionLocal()
    try:
        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceType == source_type,
            CouplePlaceLink.sourceID == source_id,
            CouplePlaceLink.relationKind == 'location',
        ).delete(synchronize_session=False)

        normalized = _normalize_couple_place_name(location_name)
        if not normalized:
            session.commit()
            return None

        place = _get_or_create_place_in_session(
            session,
            location_name,
            created_by_user,
            latitude=latitude,
            longitude=longitude,
        )

        existing = (
            session.query(CouplePlaceLink)
            .filter(
                CouplePlaceLink.placeID == place.id,
                CouplePlaceLink.sourceType == source_type,
                CouplePlaceLink.sourceID == source_id,
            )
            .first()
        )
        if existing:
            existing.relationKind = 'location'
        else:
            session.add(CouplePlaceLink(
                placeID=place.id,
                sourceType=source_type,
                sourceID=source_id,
                relationKind='location',
            ))

        if source_type == 'chapter':
            chapter = (
                session.query(CoupleChapter)
                .filter(CoupleChapter.id == source_id)
                .first()
            )
            if chapter and place.latitude is not None and place.longitude is not None:
                chapter.latitude = place.latitude
                chapter.longitude = place.longitude

        session.commit()
        return place.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Einmal je Prozess. Die Funktion wandert Altbestand in die Ortstabellen -
# das ist eine Migration, keine Seitenlogik. Sie hing an sieben Routen und
# hat damit bei jedem Seitenaufruf saemtliche Plaene und Kapitel gescannt.
_places_bootstrapped = False


def invalidate_place_bootstrap():
    """Nach einem Datenimport muss der Altbestand erneut geprueft werden."""
    global _places_bootstrapped
    _places_bootstrapped = False


def bootstrap_couple_places_from_existing_locations(force=False):
    """Idempotently preserve and connect existing Plan/Chapter location text.

    No existing row is rewritten or deleted. The legacy locationName remains the
    source text while the new place/link tables add map semantics on top.
    """
    global _places_bootstrapped
    if _places_bootstrapped and not force:
        return

    session = SessionLocal()
    try:
        sources = []

        for chapter in session.query(CoupleChapter).filter(
            CoupleChapter.locationName.isnot(None),
            CoupleChapter.locationName != '',
        ).all():
            sources.append((
                'chapter',
                chapter.id,
                chapter.locationName,
                chapter.createdByUser,
                chapter.latitude,
                chapter.longitude,
            ))

        for plan in session.query(CouplePlan).filter(
            CouplePlan.locationName.isnot(None),
            CouplePlan.locationName != '',
        ).all():
            sources.append((
                'plan',
                plan.id,
                plan.locationName,
                plan.createdByUser,
                None,
                None,
            ))

        for source_type, source_id, name, creator_id, lat, lon in sources:
            has_location_link = (
                session.query(CouplePlaceLink.id)
                .filter(
                    CouplePlaceLink.sourceType == source_type,
                    CouplePlaceLink.sourceID == source_id,
                    CouplePlaceLink.relationKind == 'location',
                )
                .first()
            )
            if has_location_link:
                continue

            place = _get_or_create_place_in_session(
                session,
                name,
                creator_id,
                latitude=lat,
                longitude=lon,
            )
            session.add(CouplePlaceLink(
                placeID=place.id,
                sourceType=source_type,
                sourceID=source_id,
                relationKind='location',
            ))

        session.commit()
        _places_bootstrapped = True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_couple_place_link_map():
    session = SessionLocal()
    try:
        places = {
            place.id: {
                'id': place.id,
                'name': place.name,
                'addressLabel': place.addressLabel or '',
                'latitude': place.latitude,
                'longitude': place.longitude,
            }
            for place in session.query(CouplePlace).all()
        }

        by_place = {place_id: [] for place_id in places}
        source_places = {}

        for link in session.query(CouplePlaceLink).all():
            place = places.get(link.placeID)
            if not place:
                continue

            source = {
                'source_type': link.sourceType,
                'source_id': link.sourceID,
                'relation_kind': link.relationKind,
            }
            by_place.setdefault(link.placeID, []).append(source)

            key = (link.sourceType, link.sourceID)
            source_places.setdefault(key, []).append({
                **place,
                'relation_kind': link.relationKind,
            })

        return {
            'places': places,
            'by_place': by_place,
            'source_places': source_places,
        }
    finally:
        session.close()


def replace_couple_place_manual_links(place_id, requested_links):
    """Replace only manually curated links; location-derived links stay intact."""
    session = SessionLocal()
    try:
        session.query(CouplePlaceLink).filter(
            CouplePlaceLink.placeID == place_id,
            CouplePlaceLink.relationKind == 'manual',
        ).delete(synchronize_session=False)

        seen = set()
        for source_type, source_id in requested_links:
            if source_type not in _ALLOWED_PLACE_SOURCE_TYPES:
                continue
            key = (source_type, int(source_id))
            if key in seen:
                continue
            seen.add(key)

            existing = (
                session.query(CouplePlaceLink.id)
                .filter(
                    CouplePlaceLink.placeID == place_id,
                    CouplePlaceLink.sourceType == source_type,
                    CouplePlaceLink.sourceID == source_id,
                )
                .first()
            )
            if existing:
                continue

            session.add(CouplePlaceLink(
                placeID=place_id,
                sourceType=source_type,
                sourceID=source_id,
                relationKind='manual',
            ))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def copy_couple_place_links(source_type, source_id, target_type, target_id):
    if source_type not in _ALLOWED_PLACE_SOURCE_TYPES:
        return
    if target_type not in _ALLOWED_PLACE_SOURCE_TYPES:
        return

    session = SessionLocal()
    try:
        source_links = session.query(CouplePlaceLink).filter(
            CouplePlaceLink.sourceType == source_type,
            CouplePlaceLink.sourceID == source_id,
        ).all()

        for link in source_links:
            existing = session.query(CouplePlaceLink.id).filter(
                CouplePlaceLink.placeID == link.placeID,
                CouplePlaceLink.sourceType == target_type,
                CouplePlaceLink.sourceID == target_id,
            ).first()
            if existing:
                continue
            session.add(CouplePlaceLink(
                placeID=link.placeID,
                sourceType=target_type,
                sourceID=target_id,
                relationKind=link.relationKind,
            ))

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Table ListType

def create_list_type(title, icon, contentURL, createdByUser, navbar, navbarOrder, routeID, mainTitle):
    session = SessionLocal()
    try:
        new_list_type = ListType(
            title=title,
            icon=icon,
            contentURL=contentURL,
            createdByUser=createdByUser,
            navbarOrder=navbarOrder,
            navbar=navbar,
            routeID=routeID,
            mainTitle=mainTitle,
        )
        session.add(new_list_type)
        session.commit()
        session.refresh(new_list_type)
        return new_list_type.id
    finally:
        session.close()

def get_list_type_by_id(list_type_id):
    session = SessionLocal()
    try:
        list_type = session.query(ListType).filter(ListType.id == list_type_id).first()
        return list_type
    finally:
        session.close()

def get_list_type_by_content_url(content_url):
    session = SessionLocal()
    try:
        list_type = session.query(ListType).filter(ListType.contentURL == content_url).first()
        return list_type
    finally:
        session.close()

def get_all_list_types():
    session = SessionLocal()
    try:
        list_types = session.query(ListType).order_by(ListType.navbarOrder.asc()).all()
        return list_types
    finally:
        session.close()

def update_list_type(list_type_id, title=None, icon=None, contentURL=None, navbar=None, navbarOrder=None, routeID=None, mainTitle=None):
    session = SessionLocal()
    try:
        list_type = session.query(ListType).filter(ListType.id == list_type_id).first()
        if list_type:
            if title is not None:
                list_type.title = title
            if icon is not None:
                list_type.icon = icon
            if contentURL is not None:
                list_type.contentURL = contentURL
            if navbar is not None:
                list_type.navbar = navbar
            if routeID is not None:
                list_type.routeID = routeID
            if mainTitle is not None:
                list_type.mainTitle = mainTitle
            if navbarOrder is not None:
                list_type.navbarOrder = navbarOrder
            session.commit()
    finally:
        session.close()

def delete_list_type(list_type_id):
    session = SessionLocal()
    try:
        list_type = session.query(ListType).filter(ListType.id == list_type_id).first()
        if list_type:
            session.delete(list_type)
            session.commit()
    finally:
        session.close()


def get_list_type_by_title(title):
    session = SessionLocal()
    try:
        list_type = session.query(ListType).filter(ListType.title == title).first()
        return list_type
    finally:
        session.close()


def ensure_banner_song_setting():
    """For existing databases: creates the banner_song setting if missing."""
    session = SessionLocal()
    try:
        existing = session.query(Setting).filter(Setting.name == 'banner_song').first()
        if existing:
            return
        session.add(Setting(name='banner_song', value='', icon='music_note', category='general', type='file'))
        session.commit()
    finally:
        session.close()


def ensure_countdown_list_type():
    """For existing databases: creates the Countdown ListType + permissions if missing."""
    session = SessionLocal()
    try:
        existing = session.query(ListType).filter(ListType.title == 'Countdown').first()
        if existing:
            return
        lt = ListType(title='Countdown', icon='timer', contentURL='', createdByUser=1, navbar=False, navbarOrder=0, routeID='', mainTitle='Countdown')
        session.add(lt)
        session.flush()
        admin_role = session.query(Role).filter(Role.roleName == 'Admin').first()
        for action in ('View', 'Create', 'Update', 'Delete'):
            perm = Permission(permissionName=f'{action} Countdown', listTypeID=lt.id)
            session.add(perm)
            session.flush()
            if admin_role:
                session.add(RolePermission(roleID=admin_role.id, permissionID=perm.id))
        # Seed translations
        for lang_code, text in [('en-US', 'Countdown'), ('de-DE', 'Countdown')]:
            exists = session.query(Translation).filter(
                Translation.entityType == 'ui', Translation.entityID == 0,
                Translation.languageCode == lang_code, Translation.fieldName == 'Countdown'
            ).first()
            if not exists:
                session.add(Translation(entityType='ui', entityID=0, languageCode=lang_code, fieldName='Countdown', translatedText=text))
        session.commit()
    finally:
        session.close()


# Per-list permission lifecycle functions

def _ensure_default_role_permissions_for_list_type(
    session,
    list_type_id,
    title,
):
    # Give a newly created shared list sensible default role access.
    # Admin and Adult receive CRUD. Child and any additional non-System role
    # receive View/Create so an admin-created shared list is visible and usable
    # by every normal SideBySide user by default.
    roles = (
        session.query(Role)
        .filter(Role.roleName != 'System')
        .all()
    )

    for action in ('View', 'Create', 'Update', 'Delete'):
        permission_name = f'{action} {title}'
        permission = (
            session.query(Permission)
            .filter(
                Permission.listTypeID == list_type_id,
                Permission.permissionName == permission_name,
            )
            .first()
        )

        if permission is None:
            permission = Permission(
                permissionName=permission_name,
                listTypeID=list_type_id,
            )
            session.add(permission)
            session.flush()

        for role in roles:
            allow = (
                role.roleName in {'Admin', 'Adult'}
                or action in {'View', 'Create'}
            )
            if not allow:
                continue

            existing = (
                session.query(RolePermission)
                .filter(
                    RolePermission.roleID == role.id,
                    RolePermission.permissionID == permission.id,
                )
                .first()
            )
            if existing is None:
                session.add(
                    RolePermission(
                        roleID=role.id,
                        permissionID=permission.id,
                    )
                )


def create_permissions_for_list_type(list_type_id, title):
    # Create per-list permissions with shared-list defaults.
    session = SessionLocal()
    try:
        _ensure_default_role_permissions_for_list_type(
            session,
            list_type_id,
            title,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_custom_list_role_permissions():
    # Backfill default permissions for existing admin/user-created lists.
    session = SessionLocal()
    try:
        custom_lists = (
            session.query(ListType)
            .filter(ListType.createdByUser != 1)
            .all()
        )

        for list_type in custom_lists:
            _ensure_default_role_permissions_for_list_type(
                session,
                list_type.id,
                list_type.title,
            )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def delete_permissions_for_list_type(list_type_id):
    """Deletes all permissions (and their RolePermissions) linked to a list type."""
    session = SessionLocal()
    try:
        perms = session.query(Permission).filter(Permission.listTypeID == list_type_id).all()
        for perm in perms:
            session.query(RolePermission).filter(RolePermission.permissionID == perm.id).delete()
            session.delete(perm)
        session.commit()
    finally:
        session.close()


def rename_list_type_permissions(list_type_id, new_title):
    """Renames all permissions linked to a list type to match the new title."""
    session = SessionLocal()
    try:
        perms = session.query(Permission).filter(Permission.listTypeID == list_type_id).all()
        for perm in perms:
            action = perm.permissionName.split(' ', 1)[0]
            perm.permissionName = f'{action} {new_title}'
        session.commit()
    finally:
        session.close()


# Table Translations

def get_supported_languages():
    session = SessionLocal()
    try:
        languages = session.query(Translation.languageCode).distinct().all()
        return [lang[0] for lang in languages]
    except Exception:
        return []
    finally:
        session.close()

def get_all_translations():
    session = SessionLocal()
    try:
        translations = session.query(Translation).all()
        return translations
    finally:
        session.close()

def get_field_name(entityType, entityID):
    session = SessionLocal()
    try:
        fieldNames = session.query(Translation.fieldName).filter(Translation.entityType == entityType, Translation.entityID == entityID).distinct().all()
        return [name[0] for name in fieldNames][0]
    finally:
        session.close()

def get_translation(fieldName, languageCode):
    session = SessionLocal()
    try:
        translation = session.query(Translation.translatedText).filter(Translation.fieldName == fieldName, Translation.languageCode == languageCode).first()
        return translation[0] if translation and translation[0] != "" else fieldName
    finally:
        session.close()

def get_translation_for_entity(entityType, entityID, languageCode):
    session = SessionLocal()
    try:
        # Normalize language code (e.g. "en_US.UTF-8" -> "en_US")
        lang = languageCode.split('.')[0] if languageCode else 'en-US'
        translation = session.query(Translation).filter(Translation.entityType == entityType, Translation.entityID == entityID, Translation.languageCode == lang).first()
        if translation:
            return translation.translatedText
        # Fallback to English
        if lang != 'en-US':
            translation = session.query(Translation).filter(Translation.entityType == entityType, Translation.entityID == entityID, Translation.languageCode == 'en-US').first()
            if translation:
                return translation.translatedText
        return f'{entityType}_{entityID}'
    finally:
        session.close()

def create_new_translations(new_translations_array):
    session = SessionLocal()
    try:
        # Deduplizieren nach (entityType, fieldName)
        seen = set()
        unique_translations = []
        for t in new_translations_array:
            key = (t['entityType'], t['fieldName'])
            if key not in seen:
                seen.add(key)
                unique_translations.append(t)

        for translation in unique_translations:
            existing = session.query(Translation).filter(
                Translation.entityType == translation['entityType'],
                Translation.entityID == 0,
                Translation.languageCode == 'en-US',
                Translation.fieldName == translation['fieldName']
            ).first()
            if not existing:
                new_translation = Translation(
                    entityType=translation['entityType'],
                    entityID=0,
                    languageCode='en-US',
                    fieldName=translation['fieldName'],
                    translatedText="",
                    helpText=""
                )
                session.add(new_translation)
                session.flush()
        session.commit()
    finally:
        session.close()


def create_new_language(languageCode):
    session = SessionLocal()
    try:
        fields = session.query(Translation).filter(Translation.languageCode == 'en-US').all()
        for field in fields:
            new_translation = Translation(
                entityType=field.entityType,
                entityID=field.entityID,
                languageCode=languageCode,
                fieldName=field.fieldName,
                translatedText="",
                helpText=field.helpText
            )
            session.add(new_translation)
        session.commit()
        return True
    finally:
        session.close()

def get_translations_by_language(languageCode):
    session = SessionLocal()
    try:
        translations = session.query(Translation).filter(Translation.languageCode == languageCode).all()
        return translations
    finally:
        session.close()

def update_translation(entityType, entityID, languageCode, fieldName, translatedText, helpText):
    session = SessionLocal()
    try:
        translation = session.query(Translation).filter(Translation.entityType == entityType, Translation.entityID == entityID, Translation.languageCode == languageCode, Translation.fieldName == fieldName).first()
        if translation:
            translation.translatedText = translatedText
            translation.helpText = helpText
            session.commit()
    finally:
        session.close()

def get_translation_progress():
    session = SessionLocal()
    try:
        languages = session.query(Translation.languageCode).distinct().all()
        progress = []
        for language in languages:
            total_entries = session.query(Translation).filter(Translation.languageCode == language[0]).count()
            translated_entries = session.query(Translation).filter(Translation.languageCode == language[0], Translation.translatedText != "").count()
            percentage = round((translated_entries / total_entries) * 100)
            progress.append({
                'language': language[0],
                'translated_entries': translated_entries,
                'total_entries': total_entries,
                'percentage': percentage
            })
        return progress
    finally:
        session.close()

# Table ItemShare

def generate_share_token(length=10):
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits
    session = SessionLocal()
    try:
        for _ in range(100):
            token = ''.join(secrets.choice(alphabet) for _ in range(length))
            existing = session.query(ItemShare).filter(ItemShare.token == token).first()
            if not existing:
                return token
        raise RuntimeError('Could not generate unique share token')
    finally:
        session.close()


def create_item_share(item_id, user_id, expires_at=None, password=None):
    from flask_bcrypt import generate_password_hash
    session = SessionLocal()
    try:
        token = generate_share_token()
        password_hash = None
        if password:
            password_hash = generate_password_hash(password).decode('utf-8')
        share = ItemShare(
            itemID=item_id,
            token=token,
            createdByUser=user_id,
            expiresAt=expires_at,
            passwordHash=password_hash,
            isActive=True
        )
        session.add(share)
        session.commit()
        session.refresh(share)
        return {
            'id': share.id,
            'token': share.token,
            'expiresAt': str(share.expiresAt) if share.expiresAt else None,
            'hasPassword': share.passwordHash is not None
        }
    finally:
        session.close()


def get_share_by_token(token):
    session = SessionLocal()
    try:
        share = session.query(ItemShare).filter(
            ItemShare.token == token,
            ItemShare.isActive == True
        ).first()
        if not share:
            return None, None
        item = session.query(Item).filter(Item.id == share.itemID).first()
        session.expunge(share)
        if item:
            session.expunge(item)
        return share, item
    finally:
        session.close()


def get_shares_for_item(item_id):
    session = SessionLocal()
    try:
        shares = session.query(ItemShare).filter(
            ItemShare.itemID == item_id,
            ItemShare.isActive == True
        ).all()
        return [{
            'id': share.id,
            'token': share.token,
            'createdAt': str(share.createdAt) if share.createdAt else None,
            'expiresAt': str(share.expiresAt) if share.expiresAt else None,
            'hasPassword': share.passwordHash is not None,
            'viewCount': share.viewCount or 0
        } for share in shares]
    finally:
        session.close()


def deactivate_share(share_id, user_id=None, admin=False):
    session = SessionLocal()
    try:
        if admin:
            share = session.query(ItemShare).filter(ItemShare.id == share_id).first()
        else:
            share = session.query(ItemShare).filter(
                ItemShare.id == share_id,
                ItemShare.createdByUser == user_id
            ).first()
        if share:
            share.isActive = False
            session.commit()
    finally:
        session.close()


def increment_share_view_count(share_id):
    session = SessionLocal()
    try:
        share = session.query(ItemShare).filter(ItemShare.id == share_id).first()
        if share:
            share.viewCount = (share.viewCount or 0) + 1
            session.commit()
    finally:
        session.close()


def get_shared_item_ids():
    from datetime import datetime
    session = SessionLocal()
    try:
        shares = session.query(ItemShare.itemID).filter(
            ItemShare.isActive == True,
            or_(ItemShare.expiresAt == None, ItemShare.expiresAt > datetime.utcnow())
        ).distinct().all()
        return {s[0] for s in shares}
    finally:
        session.close()


def get_all_active_shares():
    from datetime import datetime
    session = SessionLocal()
    try:
        shares = session.query(ItemShare, Item, User).join(
            Item, ItemShare.itemID == Item.id
        ).join(
            User, ItemShare.createdByUser == User.id
        ).filter(
            ItemShare.isActive == True
        ).order_by(ItemShare.createdAt.desc()).all()
        return [{
            'id': share.id,
            'token': share.token,
            'itemTitle': item.title,
            'itemID': item.id,
            'createdBy': f'{user.firstName} {user.lastName or ""}'.strip(),
            'createdAt': str(share.createdAt) if share.createdAt else None,
            'expiresAt': str(share.expiresAt) if share.expiresAt else None,
            'hasPassword': share.passwordHash is not None,
            'viewCount': share.viewCount or 0,
            'isExpired': share.expiresAt is not None and share.expiresAt < datetime.utcnow()
        } for share, item, user in shares]
    finally:
        session.close()


def verify_share_password(share, password):
    from flask_bcrypt import check_password_hash
    if not share.passwordHash:
        return True
    return check_password_hash(share.passwordHash, password)




def ensure_reminder_permissions():
    """For existing databases: creates reminder permissions if missing."""
    session = SessionLocal()
    try:
        existing = session.query(Permission).filter(Permission.permissionName == 'View Reminders').first()
        if existing:
            return
        admin_role = session.query(Role).filter(Role.roleName == 'Admin').first()
        adult_role = session.query(Role).filter(Role.roleName == 'Adult').first()
        child_role = session.query(Role).filter(Role.roleName == 'Child').first()
        for perm_name in ('View Reminders', 'Create Reminder', 'Update Reminder', 'Delete Reminder'):
            perm = Permission(permissionName=perm_name)
            session.add(perm)
            session.flush()
            if admin_role:
                session.add(RolePermission(roleID=admin_role.id, permissionID=perm.id))
            if perm_name in ('View Reminders', 'Create Reminder') and adult_role:
                session.add(RolePermission(roleID=adult_role.id, permissionID=perm.id))
            if perm_name == 'View Reminders' and child_role:
                session.add(RolePermission(roleID=child_role.id, permissionID=perm.id))
        session.commit()
    finally:
        session.close()


# Reminder CRUD

def get_all_reminders():
    session = SessionLocal()
    try:
        reminders = session.query(Reminder).filter(Reminder.active == True).order_by(Reminder.created_at.desc()).all()
        for r in reminders:
            session.expunge(r)
        return reminders
    finally:
        session.close()


def get_reminder_by_id(reminder_id):
    session = SessionLocal()
    try:
        reminder = session.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder:
            session.expunge(reminder)
        return reminder
    finally:
        session.close()


def create_reminder(title, description, reminder_type, created_by, month=None, day=None,
                    target_date=None, milestone_days=None, countdown_id=None,
                    notify_days_before='0', is_global=True, is_auto=False, auto_source=None):
    session = SessionLocal()
    try:
        reminder = Reminder(
            title=title, description=description or '', reminder_type=reminder_type,
            month=month, day=day, target_date=target_date,
            milestone_days=milestone_days, countdown_id=countdown_id,
            notify_days_before=notify_days_before, is_global=is_global,
            is_auto=is_auto, auto_source=auto_source, created_by=created_by, active=True
        )
        session.add(reminder)
        session.commit()
        session.refresh(reminder)
        return reminder.id
    finally:
        session.close()


def update_reminder(reminder_id, **kwargs):
    session = SessionLocal()
    try:
        reminder = session.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder:
            for key, value in kwargs.items():
                if hasattr(reminder, key) and value is not None:
                    setattr(reminder, key, value)
            session.commit()
    finally:
        session.close()


def delete_reminder(reminder_id):
    session = SessionLocal()
    try:
        session.query(ReminderMute).filter(ReminderMute.reminder_id == reminder_id).delete()
        reminder = session.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder:
            session.delete(reminder)
            session.commit()
    finally:
        session.close()


def get_user_muted_reminder_ids(user_id):
    session = SessionLocal()
    try:
        mutes = session.query(ReminderMute.reminder_id).filter(ReminderMute.user_id == user_id).all()
        return {m[0] for m in mutes}
    finally:
        session.close()


def mute_reminder(user_id, reminder_id):
    session = SessionLocal()
    try:
        existing = session.query(ReminderMute).filter(
            ReminderMute.user_id == user_id, ReminderMute.reminder_id == reminder_id
        ).first()
        if not existing:
            session.add(ReminderMute(user_id=user_id, reminder_id=reminder_id))
            session.commit()
    finally:
        session.close()


def unmute_reminder(user_id, reminder_id):
    session = SessionLocal()
    try:
        session.query(ReminderMute).filter(
            ReminderMute.user_id == user_id, ReminderMute.reminder_id == reminder_id
        ).delete()
        session.commit()
    finally:
        session.close()


def get_auto_reminder_by_source(auto_source):
    session = SessionLocal()
    try:
        reminder = session.query(Reminder).filter(
            Reminder.is_auto == True, Reminder.auto_source == auto_source
        ).first()
        if reminder:
            session.expunge(reminder)
        return reminder
    finally:
        session.close()


def delete_auto_reminders_by_source(auto_source):
    session = SessionLocal()
    try:
        reminders = session.query(Reminder).filter(
            Reminder.is_auto == True, Reminder.auto_source == auto_source
        ).all()
        for r in reminders:
            session.query(ReminderMute).filter(ReminderMute.reminder_id == r.id).delete()
            session.delete(r)
        session.commit()
    finally:
        session.close()


# Push Subscription CRUD

def save_push_subscription(user_id, endpoint, p256dh, auth):
    session = SessionLocal()
    try:
        existing = session.query(PushSubscription).filter(
            PushSubscription.endpoint == endpoint
        ).first()
        if existing:
            existing.user_id = user_id
            existing.p256dh = p256dh
            existing.auth = auth
        else:
            session.add(PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth))
        session.commit()
    finally:
        session.close()


def delete_push_subscription(endpoint):
    session = SessionLocal()
    try:
        session.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).delete()
        session.commit()
    finally:
        session.close()


def get_push_subscriptions_for_user(user_id):
    session = SessionLocal()
    try:
        subs = session.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        result = [{'endpoint': s.endpoint, 'p256dh': s.p256dh, 'auth': s.auth} for s in subs]
        return result
    finally:
        session.close()


# Notification Log

def check_notification_sent(notification_key):
    session = SessionLocal()
    try:
        existing = session.query(NotificationLog).filter(
            NotificationLog.notification_key == notification_key
        ).first()
        return existing is not None
    finally:
        session.close()


def log_notification(notification_key, reminder_id=None):
    session = SessionLocal()
    try:
        session.add(NotificationLog(notification_key=notification_key, reminder_id=reminder_id))
        session.commit()
    finally:
        session.close()


def approve_new_translations_to_all_languages():
    session = SessionLocal()
    try:
        all_translations = session.query(Translation).filter(Translation.languageCode == 'en-US').all()
        all_languages = [lang[0] for lang in session.query(Translation.languageCode).filter(Translation.languageCode != 'en-US').distinct().all()]

        for translation in all_translations:
            for lang_code in all_languages:
                existing = session.query(Translation).filter_by(
                    entityType=translation.entityType,
                    entityID=translation.entityID,
                    languageCode=lang_code,
                    fieldName=translation.fieldName
                ).first()
                if not existing:
                    session.add(Translation(
                        entityType=translation.entityType,
                        entityID=translation.entityID,
                        languageCode=lang_code,
                        fieldName=translation.fieldName,
                        translatedText="",
                        helpText=translation.helpText
                    ))
            if translation.translatedText == "":
                translation.translatedText = translation.fieldName

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Privater Bereich
#
# Jede Funktion nimmt die Nutzerkennung als erstes Argument und filtert
# damit. Es gibt bewusst kein get_private_entry(entry_id) ohne Nutzer:
# eine Abfrage, die man ohne Eigentuemer aufrufen kann, wird irgendwann
# auch ohne Eigentuemer aufgerufen.
# ---------------------------------------------------------------------------

PRIVATE_KINDS = ('note', 'gift')
PRIVATE_GIFT_STATUSES = ('idea', 'reserved', 'bought', 'given')


def _serialize_private_entry(entry):
    return {
        'id': entry.id,
        'userID': entry.userID,
        'kind': entry.kind,
        'title': entry.title,
        'content': entry.content or '',
        'recipient': entry.recipient or '',
        'occasion': entry.occasion or '',
        'targetDate': entry.targetDate,
        'price': entry.price or '',
        'link': entry.link or '',
        'status': entry.status,
        'pinned': bool(entry.pinned),
        'dateCreated': entry.dateCreated,
        'dateModified': entry.dateModified,
    }


def get_private_entries(user_id, kind=None):
    """Alle eigenen Eintraege, angeheftete zuerst."""
    session = SessionLocal()
    try:
        query = session.query(PrivateEntry).filter(PrivateEntry.userID == user_id)
        if kind in PRIVATE_KINDS:
            query = query.filter(PrivateEntry.kind == kind)

        rows = query.order_by(
            PrivateEntry.pinned.desc(),
            PrivateEntry.dateModified.desc(),
            PrivateEntry.id.desc(),
        ).all()
        return [_serialize_private_entry(row) for row in rows]
    finally:
        session.close()


def get_private_entry(user_id, entry_id):
    """Ein eigener Eintrag - oder None, auch wenn es ihn bei jemand anderem gibt."""
    session = SessionLocal()
    try:
        entry = (
            session.query(PrivateEntry)
            .filter(
                PrivateEntry.id == entry_id,
                PrivateEntry.userID == user_id,
            )
            .first()
        )
        return _serialize_private_entry(entry) if entry else None
    finally:
        session.close()


def create_private_entry(user_id, kind, title, content='', recipient=None,
                         occasion=None, target_date=None, price=None,
                         link=None, status='idea'):
    if kind not in PRIVATE_KINDS:
        raise ValueError('Invalid private entry kind')
    if status not in PRIVATE_GIFT_STATUSES:
        status = 'idea'

    session = SessionLocal()
    try:
        entry = PrivateEntry(
            userID=user_id,
            kind=kind,
            title=title,
            content=content or '',
            recipient=recipient or None,
            occasion=occasion or None,
            targetDate=target_date,
            price=price or None,
            link=link or None,
            status=status if kind == 'gift' else 'idea',
        )
        session.add(entry)
        session.commit()
        session.refresh(entry)
        return entry.id
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_private_entry(user_id, entry_id, **changes):
    """Aendert einen eigenen Eintrag. Fremde Eintraege bleiben unberuehrt."""
    allowed = {
        'title', 'content', 'recipient', 'occasion',
        'target_date', 'price', 'link', 'status', 'pinned',
    }
    columns = {
        'target_date': 'targetDate',
    }

    session = SessionLocal()
    try:
        entry = (
            session.query(PrivateEntry)
            .filter(
                PrivateEntry.id == entry_id,
                PrivateEntry.userID == user_id,
            )
            .first()
        )
        if not entry:
            return False

        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == 'status' and value not in PRIVATE_GIFT_STATUSES:
                continue
            setattr(entry, columns.get(key, key), value)

        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_private_entry(user_id, entry_id):
    session = SessionLocal()
    try:
        deleted = (
            session.query(PrivateEntry)
            .filter(
                PrivateEntry.id == entry_id,
                PrivateEntry.userID == user_id,
            )
            .delete()
        )
        session.commit()
        return bool(deleted)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def count_private_entries(user_id):
    """Zaehlt nach Art - fuer die Uebersicht auf der Startseite."""
    session = SessionLocal()
    try:
        counts = {kind: 0 for kind in PRIVATE_KINDS}
        rows = (
            session.query(PrivateEntry.kind, func.count(PrivateEntry.id))
            .filter(PrivateEntry.userID == user_id)
            .group_by(PrivateEntry.kind)
            .all()
        )
        for kind, total in rows:
            counts[kind] = total
        return counts
    finally:
        session.close()
