"""Клуб: локации, группы, кто в какой группе, отмены занятий и посещаемость."""
import secrets
from datetime import date, datetime, timedelta

from app.models import db, Club, Location, Group, Membership, SessionCancel, Attendance, SessionLead, Rsvp, User, ATHLETE

WD_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
WD_ACC = ['в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу', 'в воскресенье']

# Расписание с kruk-team.ru на момент запуска. Дальше его ведёт тренер в мини-аппе
KRUK_LOCATIONS = [
    ('Анохина', 'ул. Академика Анохина, 58', [
        ('Младшая группа', '0,2,4', '16:30', '18:00'),
        ('Старшая группа', '0,2,4', '18:00', '20:00'),
    ]),
    ('Белый Лотос', 'просп. Вернадского, 37, корп. 2', [
        ('Взрослые утро', '0,2,4', '07:30', '09:30'),
        ('Взрослые вечер', '0,2,4', '20:45', '22:15'),
    ]),
    ('Лотос', 'ул. Багрицкого, 61', [
        ('Совместная группа', '1,3,5', '16:15', '17:45'),
    ]),
]


def new_code() -> str:
    return secrets.token_urlsafe(6).replace('-', 'x').replace('_', 'z')


def seed_kruk_team() -> Club:
    club = Club.query.filter_by(name='Kruk Team').first()
    if club:
        return club
    club = Club(name='Kruk Team', join_code=new_code(), trainer_code=new_code())
    db.session.add(club)
    db.session.flush()
    for name, address, groups in KRUK_LOCATIONS:
        loc = Location(club_id=club.id, name=name, address=address)
        db.session.add(loc)
        db.session.flush()
        for g_name, days, start, end in groups:
            db.session.add(Group(club_id=club.id, location_id=loc.id, name=g_name, weekdays=days,
                                 start_time=start, end_time=end))
    db.session.commit()
    return club


def days_text(days: list[int]) -> str:
    return ', '.join(WD_SHORT[d] for d in sorted(days))


def group_json(g: Group) -> dict:
    loc = db.session.get(Location, g.location_id)
    return {'id': g.id, 'name': g.name, 'location_id': g.location_id, 'location': loc.name if loc else '',
            'address': loc.address if loc else '', 'days': g.days, 'days_text': days_text(g.days),
            'start': g.start_time, 'end': g.end_time, 'active': g.is_active}


def group_line(g: Group) -> str:
    loc = db.session.get(Location, g.location_id)
    where = f", {loc.name}" if loc else ''
    return f"{g.name}{where}. {days_text(g.days)}, {g.start_time}–{g.end_time}"


def user_groups(user_id: int) -> list[Group]:
    ids = [m.group_id for m in Membership.query.filter_by(user_id=user_id).all()]
    if not ids:
        return []
    return Group.query.filter(Group.id.in_(ids), Group.is_active == True).order_by(Group.start_time).all()  # noqa: E712


def group_members(group_id: int) -> list[int]:
    return [m.user_id for m in Membership.query.filter_by(group_id=group_id).all()]


def cancels(group_ids: list[int], start: date, end: date) -> dict:
    if not group_ids:
        return {}
    rows = SessionCancel.query.filter(SessionCancel.group_id.in_(group_ids), SessionCancel.on_date >= start,
                                      SessionCancel.on_date <= end).all()
    return {(r.group_id, r.on_date): r for r in rows}


def sessions(groups: list[Group], start: date, end: date) -> list[dict]:
    """Все занятия групп с start по end включительно, с отметкой об отмене."""
    cancelled = cancels([g.id for g in groups], start, end)
    out = []
    day = start
    while day <= end:
        for g in groups:
            if day.weekday() in g.days:
                c = cancelled.get((g.id, day))
                out.append({'group': g, 'date': day, 'cancelled': bool(c), 'note': c.note if c else None})
        day += timedelta(days=1)
    out.sort(key=lambda s: (s['date'], s['group'].start_time))
    return out


def session_start(s: dict) -> datetime:
    h, m = map(int, s['group'].start_time.split(':'))
    return datetime.combine(s['date'], datetime.min.time()).replace(hour=h, minute=m)


def session_end(s: dict) -> datetime:
    h, m = map(int, s['group'].end_time.split(':'))
    return datetime.combine(s['date'], datetime.min.time()).replace(hour=h, minute=m)


def day_word(day: date) -> str:
    """Сегодня / завтра / «в ср 21.11» – для сообщений."""
    delta = (day - date.today()).days
    if delta == 0:
        return 'сегодня'
    if delta == 1:
        return 'завтра'
    return f"{WD_SHORT[day.weekday()].lower()} {day:%d.%m}"


def session_text(s: dict, with_day: bool = True) -> str:
    """«Ср 21.11, 07:30 – Взрослые утро, Белый Лотос». Адрес – во вкладке «Клуб», в залах."""
    g = s['group']
    loc = db.session.get(Location, g.location_id)
    when = f"{WD_SHORT[s['date'].weekday()]} {s['date']:%d.%m}, " if with_day else ''
    where = f", {loc.name}" if loc else ''
    return f"{when}{g.start_time} – {g.name}{where}"


# ===== ПОСЕЩАЕМОСТЬ =====

def attendance_map(user_id: int, start: date, end: date) -> dict:
    rows = Attendance.query.filter(Attendance.user_id == user_id, Attendance.on_date >= start,
                                   Attendance.on_date <= end).all()
    return {(a.group_id, a.on_date): a for a in rows}


def set_attendance(user_id: int, group_id: int, day: date, present: bool | None, by: str = 'self',
                   note: str | None = None) -> Attendance | None:
    row = Attendance.query.filter_by(user_id=user_id, group_id=group_id, on_date=day).first()
    if present is None:
        if row:
            db.session.delete(row)
            db.session.commit()
        return None
    if not row:
        row = Attendance(user_id=user_id, group_id=group_id, on_date=day, present=present)
        db.session.add(row)
    row.present = present
    row.set_by = by
    if note is not None:
        row.note = note[:500] or None
    db.session.commit()
    return row


def history(user_id: int, days: int = 30) -> list[dict]:
    """Прошедшие занятия его групп за days дней с отметками, новые сверху."""
    end = date.today()
    start = end - timedelta(days=days)
    att = attendance_map(user_id, start, end)
    joined = {m.group_id: m.created_at.date() for m in Membership.query.filter_by(user_id=user_id).all()}
    # группы, где он сейчас, и те, откуда его убрали, но отметки остались
    group_ids = set(joined) | {gid for gid, _ in att}
    groups = Group.query.filter(Group.id.in_(group_ids)).all() if group_ids else []
    now = datetime.now()
    out = []
    for s in sessions(groups, start, end):
        if session_start(s) > now:
            continue
        a = att.get((s['group'].id, s['date']))
        # занятия до того, как тренер поставил группу, не считаются пропусками
        if not a and (s['group'].id not in joined or s['date'] < joined[s['group'].id] or not s['group'].is_active):
            continue
        out.append({'group_id': s['group'].id, 'group': s['group'].name, 'date': s['date'].isoformat(),
                    'time': s['group'].start_time, 'cancelled': s['cancelled'],
                    'present': a.present if a else None, 'note': a.note if a else None,
                    'by_trainer': bool(a and a.set_by == 'trainer')})
    out.reverse()
    return out


def attendance_stats(user_id: int, days: int = 30) -> dict:
    rows = [r for r in history(user_id, days) if not r['cancelled']]
    marked = [r for r in rows if r['present'] is not None]
    present = sum(1 for r in marked if r['present'])
    return {'sessions': len(rows), 'present': present, 'marked': len(marked),
            'percent': round(present * 100 / len(rows)) if rows else None}


def week_count(user_id: int) -> tuple[int, int]:
    """Был / всего занятий на этой неделе, по прошедшим."""
    monday = date.today() - timedelta(days=date.today().weekday())
    rows = [r for r in history(user_id, 7) if r['date'] >= monday.isoformat() and not r['cancelled']]
    return sum(1 for r in rows if r['present']), len(rows)


# ===== КТО ВЕДЁТ И КТО ПРИДЁТ =====

def leads(group_ids: list[int], start: date, end: date) -> dict:
    if not group_ids:
        return {}
    rows = SessionLead.query.filter(SessionLead.group_id.in_(group_ids), SessionLead.on_date >= start,
                                    SessionLead.on_date <= end).all()
    return {(r.group_id, r.on_date): r for r in rows}


def take_lead(group_id: int, day: date, trainer_id: int) -> tuple[bool, str | None]:
    """(взял, кто уже ведёт). Уже ведёт другой – не перебиваем."""
    row = SessionLead.query.filter_by(group_id=group_id, on_date=day).first()
    if row and row.trainer_id != trainer_id:
        other = db.session.get(User, row.trainer_id)
        return False, other.name if other else 'другой тренер'
    if not row:
        db.session.add(SessionLead(group_id=group_id, on_date=day, trainer_id=trainer_id))
        db.session.commit()
    return True, None


def release_lead(group_id: int, day: date, trainer_id: int) -> bool:
    row = SessionLead.query.filter_by(group_id=group_id, on_date=day, trainer_id=trainer_id).first()
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def set_rsvp(user_id: int, group_id: int, day: date, going: bool):
    row = Rsvp.query.filter_by(user_id=user_id, group_id=group_id, on_date=day).first()
    if not row:
        row = Rsvp(user_id=user_id, group_id=group_id, on_date=day, going=going)
        db.session.add(row)
    row.going = going
    db.session.commit()


def rsvp_map(user_id: int, start: date, end: date) -> dict:
    rows = Rsvp.query.filter(Rsvp.user_id == user_id, Rsvp.on_date >= start, Rsvp.on_date <= end).all()
    return {(r.group_id, r.on_date): r.going for r in rows}


def roster(group: Group, day: date) -> dict:
    """Занятие: кто ведёт и кто из группы придёт или пришёл. Одинаково для тренера и спортсмена."""
    from app.services.avatars import url as avatar
    lead = SessionLead.query.filter_by(group_id=group.id, on_date=day).first()
    lead_user = db.session.get(User, lead.trainer_id) if lead else None
    members = User.query.filter(User.id.in_(group_members(group.id) or [0]), User.is_active == True,  # noqa: E712
                                User.role == ATHLETE).order_by(User.name).all()
    ids = [m.id for m in members] or [0]
    rs = {r.user_id: r.going for r in Rsvp.query.filter(Rsvp.group_id == group.id, Rsvp.on_date == day, Rsvp.user_id.in_(ids)).all()}
    att = {a.user_id: a.present for a in Attendance.query.filter(Attendance.group_id == group.id, Attendance.on_date == day,
                                                                 Attendance.user_id.in_(ids)).all()}
    cancel = SessionCancel.query.filter_by(group_id=group.id, on_date=day).first()
    s = {'group': group, 'date': day, 'cancelled': bool(cancel), 'note': cancel.note if cancel else None}
    loc = db.session.get(Location, group.location_id)
    return {
        'group_id': group.id, 'group': group.name, 'location': loc.name if loc else '',
        'date': day.isoformat(), 'weekday': WD_SHORT[day.weekday()],
        'start': group.start_time, 'end': group.end_time, 'cancelled': bool(cancel), 'note': s['note'],
        'started': session_start(s) <= datetime.now(),
        'lead': {'id': lead_user.id, 'name': lead_user.name, 'avatar': avatar(lead_user)} if lead_user else None,
        'members': [{'id': m.id, 'name': m.name, 'avatar': avatar(m), 'going': rs.get(m.id), 'present': att.get(m.id)}
                    for m in members],
        'members_count': len(members),
        'going': sum(1 for v in rs.values() if v), 'not_going': sum(1 for v in rs.values() if v is False),
    }


def club_sessions(club_id: int, start: date, end: date) -> list[dict]:
    groups = Group.query.filter_by(club_id=club_id, is_active=True).all()
    return sessions(groups, start, end)
