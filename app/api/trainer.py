"""API тренера: спортсмены своего клуба, их группы, посещаемость и цели, расписание.
Питание тренер видит только итогами и не меняет."""
import re
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, g, current_app

from app.auth import trainer_required
from app.models import db, User, Club, Group, Location, Membership, SessionCancel, Goal, ADMIN, ATHLETE, TRAINER
from app.services import club, goals, body, foods, reminders, avatars

bp = Blueprint('trainer', __name__)
TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _athlete(user_id: int) -> User | None:
    """Только спортсмены своего клуба. Тренеры в группы не ставятся и не правятся."""
    u = db.session.get(User, user_id)
    return u if u and u.club_id == g.user.club_id and u.is_active and u.role == ATHLETE else None


def _group(group_id: int) -> Group | None:
    grp = db.session.get(Group, group_id)
    return grp if grp and grp.club_id == g.user.club_id else None


def _link(code: str) -> str:
    return f"https://t.me/{current_app.config['BOT_USERNAME']}?start={code}"


@bp.route('/overview')
@trainer_required
def overview():
    c = db.session.get(Club, g.user.club_id)
    people = User.query.filter_by(club_id=c.id, is_active=True).order_by(User.name).all()
    athletes = []
    for u in people:
        if u.onboarding_step is not None or u.role != ATHLETE:
            continue
        stats = club.attendance_stats(u.id, 30)
        s = body.summary(u.id)
        athletes.append({'id': u.id, 'name': u.name or u.username or str(u.tg_id), 'role': u.role, 'avatar': avatars.url(u),
                         'groups': [x.name for x in club.user_groups(u.id)], 'attendance': stats['percent'],
                         'weight': s['weight'], 'weight_change': s['weight_change'],
                         'last_seen': u.last_seen_at.isoformat() if u.last_seen_at else None})
    pending = [{'id': u.id, 'name': u.name or u.username or str(u.tg_id)} for u in people
               if u.onboarding_step is not None and u.role != ADMIN]
    groups = Group.query.filter_by(club_id=c.id, is_active=True).order_by(Group.location_id, Group.start_time).all()
    return jsonify({
        'club': c.name, 'athlete_link': _link(c.join_code),
        'trainer_link': _link(c.trainer_code) if g.user.role == ADMIN else None,
        'athletes': athletes, 'registering': pending, 'me': g.user.id,
        'trainers': [{'id': u.id, 'name': u.name, 'avatar': avatars.url(u)} for u in people if u.role == TRAINER],
        'groups': [{**club.group_json(x), 'members': len(club.group_members(x.id))} for x in groups],
        'locations': [{'id': l.id, 'name': l.name, 'address': l.address}
                      for l in Location.query.filter_by(club_id=c.id).order_by(Location.id).all()],
    })


@bp.route('/links')
@trainer_required
def links():
    """Свежие ссылки: после каждого входа по ссылке она меняется."""
    c = db.session.get(Club, g.user.club_id)
    return jsonify({'athlete_link': _link(c.join_code),
                    'trainer_link': _link(c.trainer_code) if g.user.role == ADMIN else None})


@bp.route('/athlete/<int:user_id>')
@trainer_required
def athlete_card(user_id):
    u = _athlete(user_id)
    if not u:
        return jsonify({'error': 'Спортсмен не найден'}), 404
    s = body.summary(u.id)
    weights = [d for d in body.week(u.id, 0) + body.week(u.id, 1) if d['weight']]
    return jsonify({
        'id': u.id, 'name': u.name, 'role': u.role, 'age': u.age, 'height_cm': u.height_cm, 'avatar': avatars.url(u),
        'kcal_manual': bool(u.kcal_manual),
        'goal': u.goal, 'kcal_target': u.kcal_target,
        'group_ids': [x.id for x in club.user_groups(u.id)],
        'history': club.history(u.id, 30), 'stats': club.attendance_stats(u.id, 30),
        'goals': goals.as_json(u.id), 'summary': s,
        'kcal_avg': foods.average_kcal(u.id, 7), 'weights': sorted(weights, key=lambda d: d['date']),
    })


@bp.route('/athlete/<int:user_id>/groups', methods=['POST'])
@trainer_required
def athlete_groups(user_id):
    u = _athlete(user_id)
    data = request.json or {}
    grp = _group(int(data.get('group_id') or 0))
    if not u or not grp:
        return jsonify({'error': 'Не найдено'}), 404
    row = Membership.query.filter_by(user_id=u.id, group_id=grp.id).first()
    on = bool(data.get('on'))
    if on and not row:
        db.session.add(Membership(user_id=u.id, group_id=grp.id))
        db.session.commit()
        reminders.notify_group_added(u, grp)
    elif not on and row:
        db.session.delete(row)
        db.session.commit()
        reminders.notify_group_removed(u, grp)
    return jsonify({'group_ids': [x.id for x in club.user_groups(u.id)]})


@bp.route('/athlete/<int:user_id>/attendance', methods=['POST'])
@trainer_required
def athlete_attendance(user_id):
    u = _athlete(user_id)
    data = request.json or {}
    grp = _group(int(data.get('group_id') or 0))
    try:
        day = date.fromisoformat(str(data.get('date')))
    except ValueError:
        day = None
    if not u or not grp or not day or day > date.today():
        return jsonify({'error': 'Не найдено'}), 404
    present = data.get('present')
    club.set_attendance(u.id, grp.id, day, None if present is None else bool(present), 'trainer')
    return jsonify({'history': club.history(u.id, 30), 'stats': club.attendance_stats(u.id, 30)})


@bp.route('/athlete/<int:user_id>/goals', methods=['POST'])
@trainer_required
def athlete_goal_add(user_id):
    u = _athlete(user_id)
    title = str((request.json or {}).get('title') or '').strip()
    if not u or not title:
        return jsonify({'error': 'Напиши цель'}), 400
    goal = goals.add(u.id, title, daily=bool((request.json or {}).get('daily', True)), created_by=g.user.id)
    from app.services.tg import send
    send(u.tg_id, f"🎯 Тренер добавил тебе цель: {goal.title}" + (' – каждый день' if goal.daily else ' – на сегодня'))
    return jsonify({'goals': goals.as_json(u.id)})


@bp.route('/goal/<int:goal_id>', methods=['DELETE'])
@trainer_required
def athlete_goal_delete(goal_id):
    goal = db.session.get(Goal, goal_id)
    if not goal or not _athlete(goal.user_id) or not goal.is_active:
        return jsonify({'error': 'Цель не найдена'}), 404
    goals.remove(goal)
    return jsonify({'goals': goals.as_json(goal.user_id)})


@bp.route('/athlete/<int:user_id>/remove', methods=['POST'])
@trainer_required
def athlete_remove(user_id):
    u = _athlete(user_id)
    if not u or u.id == g.user.id or u.role == ADMIN:
        return jsonify({'error': 'Нельзя'}), 400
    u.is_active = False
    Membership.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return jsonify({'ok': True})


# ===== ГРУППЫ И РАСПИСАНИЕ =====

def _group_from(data: dict, grp: Group | None = None):
    name = str(data.get('name') or '').strip()
    days = sorted({int(d) for d in data.get('days') or [] if str(d).isdigit() and 0 <= int(d) <= 6})
    start, end = str(data.get('start') or ''), str(data.get('end') or '')
    loc = db.session.get(Location, int(data.get('location_id') or 0))
    if not name or not days or not TIME_RE.match(start) or not TIME_RE.match(end) or start >= end:
        return None, 'Нужны название, дни и время в виде 18:00, конец позже начала'
    if not loc or loc.club_id != g.user.club_id:
        return None, 'Выбери зал'
    grp = grp or Group(club_id=g.user.club_id)
    grp.name, grp.weekdays, grp.start_time, grp.end_time, grp.location_id = name[:120], ','.join(map(str, days)), start, end, loc.id
    return grp, None


@bp.route('/group', methods=['POST'])
@trainer_required
def group_create():
    grp, err = _group_from(request.json or {})
    if err:
        return jsonify({'error': err}), 400
    db.session.add(grp)
    db.session.commit()
    return jsonify(club.group_json(grp))


@bp.route('/group/<int:group_id>', methods=['POST', 'DELETE'])
@trainer_required
def group_edit(group_id):
    grp = _group(group_id)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    if request.method == 'DELETE':
        grp.is_active = False
        Membership.query.filter_by(group_id=grp.id).delete()
        db.session.commit()
        return jsonify({'ok': True})
    grp, err = _group_from(request.json or {}, grp)
    if err:
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify(club.group_json(grp))


@bp.route('/group/<int:group_id>/sessions')
@trainer_required
def group_sessions(group_id):
    grp = _group(group_id)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    out = []
    for s in club.sessions([grp], date.today(), date.today() + timedelta(days=21)):
        if club.session_end(s) > datetime.now():
            out.append({'date': s['date'].isoformat(), 'weekday': club.WD_SHORT[s['date'].weekday()],
                        'start': grp.start_time, 'cancelled': s['cancelled'], 'note': s['note']})
    return jsonify(out)


@bp.route('/group/<int:group_id>/roster')
@trainer_required
def group_roster(group_id):
    """Ближайшие занятия группы: кто ведёт, кто придёт. Сегодняшнее – с отметками, кто был."""
    grp = _group(group_id)
    if not grp:
        return jsonify({'error': 'Группа не найдена'}), 404
    out = []
    for s in club.sessions([grp], date.today(), date.today() + timedelta(days=14)):
        if club.session_end(s) + timedelta(hours=4) > datetime.now():
            out.append(club.roster(grp, s['date']))
        if len(out) == 3:
            break
    return jsonify(out)


@bp.route('/group/<int:group_id>/lead', methods=['POST'])
@trainer_required
def group_lead(group_id):
    grp = _group(group_id)
    data = request.json or {}
    try:
        day = date.fromisoformat(str(data.get('date')))
    except ValueError:
        day = None
    if not grp or not day or day.weekday() not in grp.days or day < date.today():
        return jsonify({'error': 'Такого занятия нет'}), 400
    if data.get('take', True):
        if g.user.role == ADMIN:
            return jsonify({'error': 'Админ занятия не ведёт – так тебя никто не видит'}), 403
        ok, who = club.take_lead(grp.id, day, g.user.id)
        if not ok:
            return jsonify({'error': f'Уже ведёт {who}'}), 409
        reminders.notify_lead_taken(g.user, grp, day)
    elif club.release_lead(grp.id, day, g.user.id):
        reminders.notify_lead_released(g.user, grp, day)
    return jsonify(club.roster(grp, day))


@bp.route('/group/<int:group_id>/cancel', methods=['POST'])
@trainer_required
def group_cancel(group_id):
    grp = _group(group_id)
    data = request.json or {}
    try:
        day = date.fromisoformat(str(data.get('date')))
    except ValueError:
        day = None
    if not grp or not day or day.weekday() not in grp.days or day < date.today():
        return jsonify({'error': 'Такого занятия нет'}), 400
    row = SessionCancel.query.filter_by(group_id=grp.id, on_date=day).first()
    if data.get('cancel', True):
        if not row:
            db.session.add(SessionCancel(group_id=grp.id, on_date=day, note=(str(data.get('note') or '')[:200] or None)))
            db.session.commit()
            sent = reminders.notify_cancel(grp, day, data.get('note'))
        else:
            sent = 0
    else:
        if row:
            db.session.delete(row)
            db.session.commit()
            sent = reminders.notify_cancel(grp, day, None, restored=True)
        else:
            sent = 0
    return jsonify({'ok': True, 'notified': sent})


@bp.route('/location', methods=['POST'])
@trainer_required
def location_add():
    data = request.json or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Напиши название зала'}), 400
    loc = Location(club_id=g.user.club_id, name=name[:120], address=str(data.get('address') or '').strip()[:200] or None)
    db.session.add(loc)
    db.session.commit()
    return jsonify({'id': loc.id, 'name': loc.name, 'address': loc.address})
