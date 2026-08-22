"""Sicherung des privaten Bereichs fuer Export und Import.

Private Daten haengen an Nutzern, nicht an den gemeinsamen Listen. Die Zuordnung
beim Import erfolgt deshalb ueber die E-Mail-Adresse statt ueber alte IDs.
"""
from datetime import date
from app.models import PrivateEntry, PrivateList, PrivateListItem, SessionLocal, User


def _iso(value):
    return value.isoformat() if value is not None else None


def _parse_date(value):
    return date.fromisoformat(str(value)) if value else None


def export_private_entries_data():
    session = SessionLocal()
    try:
        users = {user.id: user for user in session.query(User).all()}
        result = {'version': 2, 'entries': [], 'lists': []}

        for entry in session.query(PrivateEntry).order_by(PrivateEntry.id.asc()).all():
            owner = users.get(entry.userID)
            if not owner or not owner.email:
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

        lists = session.query(PrivateList).order_by(PrivateList.id.asc()).all()
        for private_list in lists:
            owner = users.get(private_list.userID)
            if not owner or not owner.email:
                continue
            items = (
                session.query(PrivateListItem)
                .filter(PrivateListItem.listID == private_list.id)
                .order_by(PrivateListItem.position.asc(), PrivateListItem.id.asc())
                .all()
            )
            result['lists'].append({
                'userEmail': owner.email,
                'title': private_list.title,
                'icon': private_list.icon or 'checklist',
                'items': [
                    {
                        'title': item.title,
                        'completed': bool(item.completed),
                        'position': item.position,
                    }
                    for item in items
                ],
            })
        return result
    finally:
        session.close()


def import_private_entries_data(feature_data, user_email_to_id):
    """Spielt private Eintraege und Listen zurueck.

    Aeltere Sicherungen kennen Listen nicht. Dann werden nur die vorhandenen
    Bereiche importiert und bestehende Daten nicht geloescht.
    """
    if not feature_data:
        return {'entries': 0, 'lists': 0, 'items': 0, 'skipped': 0}

    session = SessionLocal()
    try:
        imported = 0
        lists_imported = 0
        items_imported = 0
        skipped = 0

        for payload in feature_data.get('entries', []):
            email = str(payload.get('userEmail') or '').strip()
            user_id = user_email_to_id.get(email) or user_email_to_id.get(email.lower())
            title = str(payload.get('title') or '').strip()
            if not user_id or not title:
                skipped += 1
                continue

            kind = str(payload.get('kind') or 'note').strip().lower()
            if kind not in ('note', 'gift', 'birthday'):
                kind = 'note'
            status = str(payload.get('status') or 'idea').strip().lower()
            if status not in ('idea', 'reserved', 'bought', 'given'):
                status = 'idea'

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

        for payload in feature_data.get('lists', []):
            email = str(payload.get('userEmail') or '').strip()
            user_id = user_email_to_id.get(email) or user_email_to_id.get(email.lower())
            title = str(payload.get('title') or '').strip()
            if not user_id or not title:
                skipped += 1
                continue

            private_list = (
                session.query(PrivateList)
                .filter(PrivateList.userID == user_id, PrivateList.title == title[:255])
                .first()
            )
            if not private_list:
                private_list = PrivateList(
                    userID=user_id,
                    title=title[:255],
                    icon=str(payload.get('icon') or 'checklist')[:64],
                )
                session.add(private_list)
                session.flush()
                lists_imported += 1

            existing_titles = {
                row[0]
                for row in session.query(PrivateListItem.title)
                .filter(PrivateListItem.listID == private_list.id)
                .all()
            }
            for index, item_payload in enumerate(payload.get('items', []), start=1):
                item_title = str(item_payload.get('title') or '').strip()
                if not item_title or item_title in existing_titles:
                    if not item_title:
                        skipped += 1
                    continue
                position = item_payload.get('position')
                try:
                    position = int(position)
                except (TypeError, ValueError):
                    position = index
                session.add(PrivateListItem(
                    listID=private_list.id,
                    title=item_title[:255],
                    completed=bool(item_payload.get('completed')),
                    position=position,
                ))
                existing_titles.add(item_title)
                items_imported += 1

        session.commit()
        return {
            'entries': imported,
            'lists': lists_imported,
            'items': items_imported,
            'skipped': skipped,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
