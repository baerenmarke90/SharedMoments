from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, Text, TIMESTAMP, ForeignKey, LargeBinary, func, Index, UniqueConstraint, DateTime, Float, event
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from config import Config
from flask_bcrypt import generate_password_hash, check_password_hash
import os

Base = declarative_base()

# Definition der Tabellen

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    firstName = Column(String(255))
    lastName = Column(String(255))
    email = Column(String(255), index=True)
    birthDate = Column(Date)
    profilePicture = Column(String(255))
    passwordSalt = Column(String(255))
    passwordHash = Column(String(255))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    roles = relationship('UserRole', back_populates='user')
    settings = relationship('UserSetting', back_populates='user')
    items = relationship('Item', back_populates='creator')
    list_types = relationship('ListType', back_populates='creator')
    passkeys = relationship('Passkey', back_populates='user')

    def hash_password(self, password):
        # Generiere ein zufälliges Salt
        self.passwordSalt = os.urandom(16).hex()  # 16 Bytes random salt
        # Erstelle den Passwort-Hash mit Salt
        self.passwordHash = generate_password_hash(password + self.passwordSalt).decode('utf-8')
        return self.passwordHash, self.passwordSalt


    def check_password(self, password):
        return check_password_hash(self.passwordHash, password + self.passwordSalt)


    def get_id(self):
        return str(self.id)

class Passkey(Base):
    __tablename__ = 'passkeys'
    id = Column(Integer, primary_key=True, autoincrement=True)
    userID = Column(Integer, ForeignKey('users.id'))
    name = Column(String(255))  # Name des Schlüssels
    credential_id = Column(String(255), unique=True)  # Credential ID für WebAuthn
    public_key = Column(String(2048))  # Public key for FIDO2
    sign_count = Column(Integer, default=0)  # Sign Count für FIDO2
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    user = relationship('User', back_populates='passkeys')


class OIDCIdentity(Base):
    __tablename__ = 'oidcIdentities'

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    userID = Column(
        Integer,
        ForeignKey('users.id'),
        nullable=False,
        index=True
    )

    provider = Column(
        String(64),
        nullable=False,
        default='pocketid'
    )

    issuer = Column(
        String(512),
        nullable=False
    )

    subject = Column(
        String(512),
        nullable=False
    )

    email = Column(
        String(255),
        nullable=True
    )

    preferredUsername = Column(
        String(255),
        nullable=True
    )

    dateCreated = Column(
        TIMESTAMP,
        server_default=func.current_timestamp()
    )

    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    user = relationship(
        'User',
        foreign_keys=[userID]
    )

    __table_args__ = (
        UniqueConstraint(
            'issuer',
            'subject',
            name='uq_oidc_identity_issuer_subject'
        ),
        UniqueConstraint(
            'userID',
            'provider',
            name='uq_oidc_identity_user_provider'
        ),
    )


class AuthConfiguration(Base):
    __tablename__ = 'authConfiguration'

    id = Column(
        Integer,
        primary_key=True
    )

    localLoginEnabled = Column(
        Boolean,
        nullable=False,
        default=True
    )

    passkeyLoginEnabled = Column(
        Boolean,
        nullable=False,
        default=True
    )

    dateCreated = Column(
        TIMESTAMP,
        server_default=func.current_timestamp()
    )

    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )


class MobileOIDCCode(Base):
    """Short-lived one-time bridge from browser OIDC back to Android."""
    __tablename__ = 'mobileOidcCodes'

    codeHash = Column(
        String(64),
        primary_key=True
    )
    userID = Column(
        Integer,
        ForeignKey('users.id'),
        nullable=False,
        index=True
    )
    expiresAt = Column(
        DateTime,
        nullable=False,
        index=True
    )
    dateCreated = Column(
        TIMESTAMP,
        server_default=func.current_timestamp()
    )


class Role(Base):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True, autoincrement=True)
    roleName = Column(String(255))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    permissions = relationship('RolePermission', back_populates='role')
    users = relationship('UserRole', back_populates='role')

class Permission(Base):
    __tablename__ = 'permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    permissionName = Column(String(255))
    listTypeID = Column(Integer, ForeignKey('listTypes.id'), nullable=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    roles = relationship('RolePermission', back_populates='permission')
    list_type = relationship('ListType', back_populates='permissions')

class RolePermission(Base):
    __tablename__ = 'rolePermissions'
    roleID = Column(Integer, ForeignKey('roles.id'), primary_key=True)
    permissionID = Column(Integer, ForeignKey('permissions.id'), primary_key=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    role = relationship('Role', back_populates='permissions')
    permission = relationship('Permission', back_populates='roles')

class UserRole(Base):
    __tablename__ = 'userRoles'
    userID = Column(Integer, ForeignKey('users.id'), primary_key=True)
    roleID = Column(Integer, ForeignKey('roles.id'), primary_key=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    user = relationship('User', back_populates='roles')
    role = relationship('Role', back_populates='users')

class Setting(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    value = Column(Text)
    icon = Column(String(255))
    category = Column(String(255))
    type = Column(String(255))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

class UserSetting(Base):
    __tablename__ = 'userSettings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    userID = Column(Integer, ForeignKey('users.id'))
    name = Column(String(255))
    value = Column(Text)
    icon = Column(String(255))
    category = Column(String(255))
    type = Column(String(255))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    user = relationship('User', back_populates='settings')

class Item(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255))
    content = Column(Text)
    contentType = Column(String(50))
    listType = Column(Integer, ForeignKey('listTypes.id'), index=True)
    contentURL = Column(Text)
    createdByUser = Column(Integer, ForeignKey('users.id'))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    blurPlaceholder = Column(Text, nullable=True)
    mediaWidth = Column(Integer, nullable=True)
    mediaHeight = Column(Integer, nullable=True)

    creator = relationship('User', back_populates='items')
    list_type = relationship('ListType', back_populates='items')

class ItemShare(Base):
    __tablename__ = 'itemShares'
    id = Column(Integer, primary_key=True, autoincrement=True)
    itemID = Column(Integer, ForeignKey('items.id'), nullable=False, index=True)
    token = Column(String(16), unique=True, nullable=False, index=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=False)
    createdAt = Column(TIMESTAMP, server_default=func.current_timestamp())
    expiresAt = Column(TIMESTAMP, nullable=True)
    passwordHash = Column(String(255), nullable=True)
    isActive = Column(Boolean, default=True, nullable=False)
    viewCount = Column(Integer, default=0, nullable=False)

    item = relationship('Item', backref='shares')
    creator = relationship('User', foreign_keys=[createdByUser])

class HeartMoment(Base):
    __tablename__ = 'heartMoments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    authorUserID = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    momentDate = Column(Date, nullable=False, index=True)
    description = Column(Text, nullable=False)
    feeling = Column(String(32), nullable=False, index=True)
    visibility = Column(String(16), nullable=False, default='shared', index=True)
    mediaFilename = Column(String(255), nullable=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    author = relationship('User', foreign_keys=[authorUserID])

class CoupleChapter(Base):
    __tablename__ = 'coupleChapters'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default='')
    startDate = Column(Date, nullable=True, index=True)
    endDate = Column(Date, nullable=True)
    locationName = Column(String(255), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    creator = relationship('User', foreign_keys=[createdByUser])


class CoupleChapterItem(Base):
    __tablename__ = 'coupleChapterItems'

    chapterID = Column(
        Integer,
        ForeignKey('coupleChapters.id'),
        primary_key=True,
    )
    itemID = Column(
        Integer,
        ForeignKey('items.id'),
        primary_key=True,
        index=True,
    )
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())


class CoupleChapterHeartMoment(Base):
    __tablename__ = 'coupleChapterHeartMoments'

    chapterID = Column(
        Integer,
        ForeignKey('coupleChapters.id'),
        primary_key=True,
    )
    heartMomentID = Column(
        Integer,
        ForeignKey('heartMoments.id'),
        primary_key=True,
        index=True,
    )
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())


class CouplePlan(Base):
    __tablename__ = 'couplePlans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default='')
    status = Column(String(20), nullable=False, default='idea', index=True)
    targetStartDate = Column(Date, nullable=True, index=True)
    targetEndDate = Column(Date, nullable=True)
    # Wann es tatsaechlich passiert ist. Ohne dieses Datum konnte ein Kapitel
    # aus einem erlebten Plan keinen Zeitraum uebernehmen.
    experiencedDate = Column(Date, nullable=True, index=True)
    locationName = Column(String(255), nullable=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    chapterID = Column(Integer, ForeignKey('coupleChapters.id'), nullable=True, index=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    creator = relationship('User', foreign_keys=[createdByUser])
    chapter = relationship('CoupleChapter', foreign_keys=[chapterID])


class CoupleBucketPlanLink(Base):
    __tablename__ = 'coupleBucketPlanLinks'

    bucketItemID = Column(
        Integer,
        ForeignKey('items.id'),
        primary_key=True,
    )
    planID = Column(
        Integer,
        ForeignKey('couplePlans.id'),
        nullable=False,
        unique=True,
        index=True,
    )
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())


class CouplePlace(Base):
    __tablename__ = 'couplePlaces'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    normalizedName = Column(String(255), nullable=False, index=True)
    description = Column(Text, default='')
    addressLabel = Column(Text, default='')
    latitude = Column(Float, nullable=True, index=True)
    longitude = Column(Float, nullable=True, index=True)
    createdByUser = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    creator = relationship('User', foreign_keys=[createdByUser])


class CouplePlaceLink(Base):
    __tablename__ = 'couplePlaceLinks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    placeID = Column(
        Integer,
        ForeignKey('couplePlaces.id'),
        nullable=False,
        index=True,
    )
    sourceType = Column(String(24), nullable=False, index=True)
    sourceID = Column(Integer, nullable=False, index=True)
    relationKind = Column(String(20), nullable=False, default='manual', index=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint(
            'placeID',
            'sourceType',
            'sourceID',
            name='uq_couple_place_source',
        ),
    )


class PrivateEntry(Base):
    """Eintraege, die ausschliesslich der eigenen Person gehoeren.

    Bewusst getrennt von HeartMoment: dort steuert `visibility`, ob der
    Partner mitliest, und der Standard ist "geteilt". Hier gibt es diesen
    Schalter nicht - ein Eintrag ohne passende userID wird nie geladen.
    Geschenkideen und Notizen teilen sich eine Tabelle, weil sie dieselbe
    Liste, dieselbe Suche und dieselben Rechte haben; `kind` trennt sie.
    """

    __tablename__ = 'privateEntries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userID = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default='note', index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, default='')

    # Nur fuer Geschenke gefuellt
    recipient = Column(String(255), nullable=True)
    occasion = Column(String(255), nullable=True)
    targetDate = Column(Date, nullable=True, index=True)
    price = Column(String(64), nullable=True)
    link = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default='idea', index=True)

    pinned = Column(Boolean, nullable=False, default=False, index=True)
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(
        TIMESTAMP,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    owner = relationship('User', foreign_keys=[userID])


class ListType(Base):
    __tablename__ = 'listTypes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255))
    icon = Column(String(255))
    contentURL = Column(Text)
    createdByUser = Column(Integer, ForeignKey('users.id'))
    navbarOrder = Column(Integer)
    navbar = Column(Boolean)
    routeID = Column(Integer, default=0)
    mainTitle = Column(String(255))
    dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    creator = relationship('User', back_populates='list_types')
    items = relationship('Item', back_populates='list_type')
    permissions = relationship('Permission', back_populates='list_type')

class Translation(Base):
    __tablename__ = 'translations'

    id = Column(Integer, primary_key=True)
    entityType = Column(String(50), nullable=False)  # Z.B. 'Role', 'Article'
    entityID = Column(Integer, nullable=False)       # ID der zugehörigen Entität
    languageCode = Column(String(5), nullable=False) # 'en-US', 'de-DE', etc.
    fieldName = Column(String(50), nullable=False)   # Z.B. 'description', 'title'
    translatedText = Column(Text, nullable=False)            # Der übersetzte Text
    helpText = Column(Text)
    #dateCreated = Column(TIMESTAMP, server_default=func.current_timestamp())
    #dateModified = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    __table_args__ = (
        Index('idx_translation_entity', 'entityType', 'entityID', 'languageCode', 'fieldName'),
        UniqueConstraint('entityType', 'entityID', 'languageCode', 'fieldName', name='uq_translation_entity')
    )


class Reminder(Base):
    __tablename__ = 'reminders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default='')
    reminder_type = Column(String(20), nullable=False)  # 'annual' | 'one_time' | 'milestone' | 'countdown'
    month = Column(Integer, nullable=True)              # für annual (1-12)
    day = Column(Integer, nullable=True)                # für annual (1-31)
    target_date = Column(Date, nullable=True)           # für one_time
    milestone_days = Column(Integer, nullable=True)     # für milestone (z.B. 1000)
    countdown_id = Column(Integer, nullable=True)       # FK → items.id für countdown
    notify_days_before = Column(String(50), default='0')  # kommasepariert: "0,1,3,7"
    is_global = Column(Boolean, default=True)
    is_auto = Column(Boolean, default=False)
    auto_source = Column(String(50), nullable=True)     # 'anniversary_date', 'wedding_date', 'user_birthday_2' etc.
    created_by = Column(Integer, ForeignKey('users.id'))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    mutes = relationship('ReminderMute', back_populates='reminder', cascade='all, delete-orphan')


class ReminderMute(Base):
    __tablename__ = 'reminder_mutes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    reminder_id = Column(Integer, ForeignKey('reminders.id'), nullable=False)

    reminder = relationship('Reminder', back_populates='mutes')

    __table_args__ = (
        UniqueConstraint('user_id', 'reminder_id', name='uq_reminder_mute'),
    )


class PushSubscription(Base):
    __tablename__ = 'push_subscriptions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())


class NotificationLog(Base):
    __tablename__ = 'notification_log'
    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_key = Column(String(200), unique=True, nullable=False)
    reminder_id = Column(Integer, nullable=True)
    sent_at = Column(DateTime, default=func.now())


# Database connection
_default_engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)

@event.listens_for(_default_engine, 'connect')
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute('PRAGMA busy_timeout=5000')
    cursor.close()

Base.metadata.create_all(_default_engine)

_DefaultSessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_default_engine)


class _DemoAwareSession:
    """Transparent wrapper — nutzt Demo-Engine wenn im Demo-Kontext."""
    def __call__(self):
        try:
            from flask import has_request_context, g
            if has_request_context() and hasattr(g, '_demo_session_factory'):
                return g._demo_session_factory()
        except (RuntimeError, ImportError):
            pass
        return _DefaultSessionFactory()


SessionLocal = _DemoAwareSession()
engine = _default_engine  # Backward-compat für run.py
