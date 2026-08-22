"""Sicherung des privaten Bereichs fuer Export und Import.

Eigenes Modul nach dem Vorbild von daily_questions_backup: der private
Bereich haengt an Nutzern, nicht an Listen, und wuerde in der allgemeinen
Item-Schleife des Exports nicht auftauchen. Ohne diese Datei waeren Notizen
und Geschenkideen bei einem Umzug weg.

Zugeordnet wird ueber die E-Mail-Adresse, wie bei den Benutzereinstellungen:
IDs sind nach einem Import andere.
"""
from datetime import date

from app.models import PrivateEntry, SessionLocal, User


def _iso(value):
    return value.isoformat() if value is not None else None


def _parse_date(value):
    return date.fromisoformat(str(value)) if value else None


def export_private_entries_data():
    session = SessionLocal()
    try:
        users = {user.id: user for user in session.query(User).all()}
        result = {'version': 1, 'entries': []}

        for entry in session.query(PrivateEntry).order_by(PrivateEntry.id.asc()).all():
            owner = users.get(entry.userID)
            if not owner or not owner.email:
                # Ohne Zuordnung liesse sich der Eintrag beim Import keinem
                # Konto zuweisen - und ein privater Eintrag darf nicht bei
                # der falschen Person landen.
                continue

            result['entries'].append({
                'userEmail': owner.email,
                'kind': entry.kind,
                'title': entry.title,
                'content': entry.content or '',
                'recipient': entry.recipient,
                'occasion': entry.occasion,
                'targetDate': _iso(entry.targetDate),
                'price': entry.price,
                'link': entry.link,
                'status': entry.status,
                'pinned': bool(entry.pinned),
            })

        return result
    finally:
        session.close()


def import_private_entries_data(feature_data, user_email_to_id):
    """Spielt private Eintraege zurueck.

    Aeltere Sicherungen kennen den Bereich nicht - dann bleibt der aktuelle
    Bestand unangetastet, statt ihn zu leeren.
    """
    if not feature_data:
        return {'entries': 0, 'skipped': 0}

    session = SessionLocal()
    try:
        imported = 0
        skipped = 0

        for payload in feature_data.get('entries', []):
            email = str(payload.get('userEmail') or '').strip()
            user_id = (
                user_email_to_id.get(email)
                or user_email_to_id.get(email.lower())
            )
            title = str(payload.get('title') or '').strip()

            if not user_id or not title:
                skipped += 1
                continue

            kind = str(payload.get('kind') or 'note').strip().lower()
            if kind not in ('note', 'gift'):
                kind = 'note'

            status = str(payload.get('status') or 'idea').strip().lower()
            if status not in ('idea', 'reserved', 'bought', 'given'):
                status = 'idea'

            # Doppelte Eintraege beim erneuten Einspielen vermeiden.
            exists = (
                session.query(PrivateEntry)
                .filter(
                    PrivateEntry.userID == user_id,
                    PrivateEntry.kind == kind,
                    PrivateEntry.title == title,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            session.add(PrivateEntry(
                userID=user_id,
                kind=kind,
                title=title[:255],
                content=str(payload.get('content') or ''),
                recipient=payload.get('recipient') or None,
                occasion=payload.get('occasion') or None,
                targetDate=_parse_date(payload.get('targetDate')),
                price=payload.get('price') or None,
                link=payload.get('link') or None,
                status=status,
                pinned=bool(payload.get('pinned')),
            ))
            imported += 1

        session.commit()
        return {'entries': imported, 'skipped': skipped}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
