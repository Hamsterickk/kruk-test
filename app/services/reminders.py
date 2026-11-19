"""Всё, что бот присылает сам. Раз в минуту проверяем каждого: что пора отправить и что
ещё не отправляли. SentMark не даёт прислать одно и то же дважды после перезапуска."""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from flask import current_app

from app.models import db, User, SentMark
from app.services import foods, body, goals, club, avatars
from app.services.tg import send, buttons

logger = logging.getLogger(__name__)

BEFORE = timedelta(minutes=90)        # тренировка – за полтора часа, с кнопками «буду / не смогу»
GOALS_AT = 12                          # цели в день без тренировки – в полдень
ASK_AFTER = timedelta(minutes=10)      # «был?» – через 10 минут после конца
ASK_UNTIL = timedelta(hours=4)
EVENING_AT = (22, 30)


def mark(user_id: int, kind: str, ref: str) -> bool:
    """True – отметили сейчас, можно отправлять. False – уже отправляли."""
    if SentMark.query.filter_by(user_id=user_id, kind=kind, ref=ref).first():
        return False
    db.session.add(SentMark(user_id=user_id, kind=kind, ref=ref))
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def active_users() -> list[User]:
    return User.query.filter(User.is_active == True, User.onboarding_step.is_(None)).all()  # noqa: E712


def tick(now: datetime | None = None) -> int:
    """Одна проверка для всех. Возвращает число отправленных сообщений."""
    now = now or datetime.now()
    sent = 0
    for user in active_users():
        try:
            sent += _user_tick(user, now)
        except Exception:
            db.session.rollback()
            logger.exception('Напоминания для %s упали', user.id)
    if not current_app.config.get('TESTING'):
        try:
            avatars.refresh_due()
        except Exception:
            db.session.rollback()
            logger.exception('Аватарки упали')
    return sent


def rsvp_row(group_id: int, day: date, going: bool | None) -> list:
    return [('✅ Буду' if going is True else 'Буду', f"rsvp:{group_id}:{day}:1"),
            ('✖️ Не смогу' if going is False else 'Не смогу', f"rsvp:{group_id}:{day}:0")]


def goal_rows(items: list[dict]) -> list:
    return [[(('✅ ' if x['done'] else '▫️ ') + x['title'][:40], f"goal:{x['id']}")] for x in items]


def before_message(s: dict, going: bool | None, now: datetime, goal_items: list | None = None) -> tuple[str, dict]:
    g = s['group']
    r = club.roster(g, s['date'])
    minutes = int((club.session_start(s) - now).total_seconds() // 60)
    when = 'через полтора часа' if minutes >= 80 else f"через {max(minutes, 1)} мин"
    lines = [f"🥋 Тренировка {when}, в {g.start_time} – {g.name}, {r['location']}"]
    who = f"Ведёт {r['lead']['name']} · " if r['lead'] else ''
    lines.append(f"{who}будут {r['going']} из {r['members_count']}")
    lines.append('Ты отметил, что будешь 💪' if going else 'Придёшь?')
    rows = [rsvp_row(g.id, s['date'], going)]
    if goal_items:
        lines.append('\n🎯 Цели на сегодня – отмечай кнопками:')
        rows += goal_rows(goal_items)
    return '\n'.join(lines), buttons(rows)


def _user_tick(user: User, now: datetime) -> int:
    sent = 0
    today = now.date()
    groups = club.user_groups(user.id)
    todays = [s for s in club.sessions(groups, today, today) if not s['cancelled']]
    rsvp = club.rsvp_map(user.id, today, today)
    going_today = [s for s in todays if rsvp.get((s['group'].id, today)) is not False]
    goal_items = goals.as_json(user.id, today)
    open_goals = [x for x in goal_items if not x['done']]
    for s in going_today:
        start, ref = club.session_start(s), f"{s['group'].id}:{today}"
        # за полтора часа – с кнопками и целями дня
        if start - BEFORE <= now < start and mark(user.id, 'before', ref):
            with_goals = bool(open_goals) and mark(user.id, 'goals', today.isoformat())
            text, markup = before_message(s, rsvp.get((s['group'].id, today)), now, goal_items if with_goals else None)
            sent += send(user.tg_id, text, markup)
    # день без тренировки – цели в полдень, если они есть
    noon = datetime.combine(today, datetime.min.time()).replace(hour=GOALS_AT)
    if not going_today and open_goals and noon <= now < noon + timedelta(hours=3) \
            and mark(user.id, 'goals', today.isoformat()):
        sent += send(user.tg_id, '🎯 Цели на сегодня – отмечай кнопками:', buttons(goal_rows(goal_items)))
    # был?
    for s in going_today:
        end, ref = club.session_end(s), f"{s['group'].id}:{today}"
        if end + ASK_AFTER <= now < end + ASK_UNTIL:
            marked = club.attendance_map(user.id, today, today).get((s['group'].id, today))
            if not marked and mark(user.id, 'ask', ref):
                g = s['group']
                kb = buttons([[('💪 Был', f"att:{g.id}:{today}:1"), ('Не был', f"att:{g.id}:{today}:0")]])
                sent += send(user.tg_id, f"Как тренировка – {g.name}, {g.start_time}? Отметь:", kb)
    if user.role == 'trainer' and user.club_id:  # админ тренерских уведомлений не получает
        sent += _trainer_tick(user, now)
    # итог дня
    evening = datetime.combine(today, datetime.min.time()).replace(hour=EVENING_AT[0], minute=EVENING_AT[1])
    if evening <= now and mark(user.id, 'evening', today.isoformat()):
        sent += send(user.tg_id, evening_summary(user, today))
    return sent


def _ask_time(s: dict) -> datetime:
    """Когда спрашивать тренеров «кто берёт»: утренние занятия – накануне в 20:00,
    остальные – в 9:00 того же дня."""
    start = club.session_start(s)
    if start.hour < 11:
        return datetime.combine(s['date'] - timedelta(days=1), datetime.min.time()).replace(hour=20)
    return datetime.combine(s['date'], datetime.min.time()).replace(hour=9)


def _trainer_tick(user: User, now: datetime) -> int:
    sent = 0
    today = now.date()
    sessions = [s for s in club.club_sessions(user.club_id, today, today + timedelta(days=1)) if not s['cancelled']]
    leads = club.leads([s['group'].id for s in sessions], today, today + timedelta(days=1))
    for s in sessions:
        g, start = s['group'], club.session_start(s)
        ref = f"{g.id}:{s['date']}"
        lead = leads.get((g.id, s['date']))
        if not lead and _ask_time(s) <= now < start and mark(user.id, 'whotakes', ref):
            day = 'Сегодня' if s['date'] == today else 'Завтра'
            kb = buttons([[('🙋 Беру', f"lead:{g.id}:{s['date']}")]])
            sent += send(user.tg_id, f"🥋 {day} {club.session_text(s, with_day=False)}\nКто ведёт?", kb)
        if lead and lead.trainer_id == user.id and s['date'] == today and start - BEFORE <= now < start \
                and mark(user.id, 'lead_soon', ref):
            r = club.roster(g, s['date'])
            sent += send(user.tg_id, f"⏰ Ты ведёшь в {g.start_time}: {club.session_text(s, with_day=False)}\n"
                                     f"В группе {len(r['members'])}, будут {r['going']}, не смогут {r['not_going']}")
    return sent


def _trainers(club_id: int, except_id: int) -> list[User]:
    return User.query.filter(User.club_id == club_id, User.id != except_id, User.is_active == True,  # noqa: E712
                             User.role == 'trainer').all()  # админ невидим – ему не пишем


def notify_lead_taken(trainer: User, group, day: date) -> int:
    """Тренерам – кто взял, спортсменам группы – кто у них ведёт."""
    s = {'group': group, 'date': day, 'cancelled': False, 'note': None}
    if club.session_start(s) <= datetime.now():
        return 0
    n = sum(send(o.tg_id, f"✅ {trainer.name} ведёт: {club.session_text(s)}") for o in _trainers(trainer.club_id, trainer.id))
    when = club.day_word(day)
    text = f"🥋 {when[:1].upper() + when[1:]} в {group.start_time} {group.name} ведёт {trainer.name}"
    for uid in club.group_members(group.id):
        u = db.session.get(User, uid)
        if u and u.is_active and u.onboarded:
            n += send(u.tg_id, text)
    return n


def notify_lead_released(trainer: User, group, day: date) -> int:
    """Тренер отказался – остальным снова «кто ведёт?» с кнопкой."""
    s = {'group': group, 'date': day, 'cancelled': False, 'note': None}
    if club.session_start(s) <= datetime.now():
        return 0
    kb = buttons([[('🙋 Беру', f"lead:{group.id}:{day}")]])
    return sum(send(o.tg_id, f"⚠️ {trainer.name} не сможет вести: {club.session_text(s)}\nКто ведёт?", kb)
               for o in _trainers(trainer.club_id, trainer.id))


def evening_summary(user: User, day: date) -> str:
    meals = foods.day_meals(user.id, day)
    t = foods.totals(meals)
    lines = ['🌙 Итог дня']
    if not meals:
        lines.append('🍽 Еду сегодня не записывал')
    elif user.kcal_target:
        diff = t['kcal'] - user.kcal_target
        verdict = 'в норме' if abs(diff) <= user.kcal_target * 0.1 else (f"недобор {-diff}" if diff < 0 else f"перебор {diff}")
        lines.append(f"🍽 {t['kcal']} из {user.kcal_target} ккал – {verdict}, белок {t['protein']} из {user.protein_target} г")
    else:
        lines.append(f"🍽 {t['kcal']} ккал, белок {t['protein']} г")
    m = body.peek(user.id, day)
    lines.append(f"👟 Шаги: {m.steps if m.steps is not None else 'не записаны'}")
    lines.append(f"😴 Сон: {f'{m.sleep:g} ч' if m.sleep is not None else 'не записан'}")
    a, b = goals.progress(user.id, day)
    if b:
        lines.append(f"🎯 Цели: {a} из {b}")
    todays = [s for s in club.sessions(club.user_groups(user.id), day, day) if not s['cancelled']]
    if todays:
        att = club.attendance_map(user.id, day, day)
        for s in todays:
            a_ = att.get((s['group'].id, day))
            mark_ = 'был 💪' if a_ and a_.present else 'не был' if a_ else 'не отмечено'
            lines.append(f"🥋 {s['group'].name}: {mark_}")
    if m.steps is None:
        lines.append('\nНапиши шаги за сегодня, например «8500 шагов»')
    return '\n'.join(lines)


# ===== СООБЩЕНИЯ ОТ ДЕЙСТВИЙ ТРЕНЕРА =====

def notify_group_added(athlete: User, group) -> bool:
    nxt = next((s for s in club.sessions([group], date.today(), date.today() + timedelta(days=7))
                if not s['cancelled'] and club.session_start(s) > datetime.now()), None)
    text = f"🥋 Тренер поставил тебе занятия: {club.group_line(group)}"
    if nxt:
        text += f"\nБлижайшее – {club.session_text(nxt)}"
    return send(athlete.tg_id, text)


def notify_group_removed(athlete: User, group) -> bool:
    return send(athlete.tg_id, f"Тренер убрал у тебя группу: {group.name}")


def notify_cancel(group, day: date, note: str | None, restored: bool = False) -> int:
    s = {'group': group, 'date': day, 'cancelled': False, 'note': None}
    if restored:
        text = f"✅ Занятие состоится: {club.session_text(s)}"
    else:
        text = f"❌ Тренер отменил занятие: {club.session_text(s)}" + (f"\n{note}" if note else '')
    n = 0
    for uid in club.group_members(group.id):
        u = db.session.get(User, uid)
        if u and u.is_active:
            n += send(u.tg_id, text)
    return n
