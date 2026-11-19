"""Всё, что бот присылает сам. Раз в минуту проверяем каждого: что пора отправить и что
ещё не отправляли. SentMark не даёт прислать одно и то же дважды после перезапуска."""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.models import db, User, SentMark
from app.services import foods, body, goals, club
from app.services.tg import send, buttons

logger = logging.getLogger(__name__)

TOMORROW_FROM, TOMORROW_TO = 20, 22    # «завтра тренировка» – с 20 до 22
SOON_BEFORE = timedelta(hours=2)       # в день занятия – за 2 часа, если оно не раньше 10:00
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
    return sent


def _user_tick(user: User, now: datetime) -> int:
    sent = 0
    today = now.date()
    groups = club.user_groups(user.id)
    # утро
    morning = datetime.combine(today, datetime.min.time()).replace(hour=user.morning_hour or 10)
    if morning <= now < morning + timedelta(hours=2) and mark(user.id, 'morning', today.isoformat()):
        text, markup = morning_message(user, today, groups)
        sent += send(user.tg_id, text, markup)
    # завтра тренировка
    if TOMORROW_FROM <= now.hour < TOMORROW_TO:
        tomorrow = today + timedelta(days=1)
        lines = []
        for s in club.sessions(groups, tomorrow, tomorrow):
            if not s['cancelled'] and mark(user.id, 'tomorrow', f"{s['group'].id}:{tomorrow}"):
                lines.append(club.session_text(s, with_day=False))
        if lines:
            sent += send(user.tg_id, '🥋 Завтра тренировка:\n' + '\n'.join(f"– {x}" for x in lines))
    for s in club.sessions(groups, today, today):
        if s['cancelled']:
            continue
        start, end = club.session_start(s), club.session_end(s)
        ref = f"{s['group'].id}:{today}"
        # скоро тренировка
        if start.hour >= 10 and start - SOON_BEFORE <= now < start and mark(user.id, 'soon', ref):
            minutes = int((start - now).total_seconds() // 60)
            when = f"через {minutes} мин" if minutes < 90 else f"в {s['group'].start_time}"
            sent += send(user.tg_id, f"⏰ Тренировка {when}: {club.session_text(s, with_day=False)}")
        # был?
        if end + ASK_AFTER <= now < end + ASK_UNTIL:
            marked = club.attendance_map(user.id, today, today).get((s['group'].id, today))
            if not marked and mark(user.id, 'ask', ref):
                g = s['group']
                kb = buttons([[('💪 Был', f"att:{g.id}:{today}:1"), ('Не был', f"att:{g.id}:{today}:0")]])
                sent += send(user.tg_id, f"Как тренировка – {g.name}, {g.start_time}? Отметь:", kb)
    # итог дня
    evening = datetime.combine(today, datetime.min.time()).replace(hour=EVENING_AT[0], minute=EVENING_AT[1])
    if evening <= now and mark(user.id, 'evening', today.isoformat()):
        sent += send(user.tg_id, evening_summary(user, today))
    return sent


def morning_message(user: User, day: date, groups: list) -> tuple[str, dict | None]:
    lines = [f"☀️ Доброе утро{', ' + user.name if user.name else ''}!"]
    todays = [s for s in club.sessions(groups, day, day) if not s['cancelled']]
    if todays:
        lines.append('🥋 Сегодня тренировка: ' + '; '.join(club.session_text(s, with_day=False) for s in todays))
    m = body.peek(user.id, day)
    ask = []
    if m.weight is None:
        ask.append('вес')
    if m.sleep is None:
        ask.append('сон')
    if ask:
        lines.append(f"Напиши {' и '.join(ask)}: например «74.5 7»")
    rows = []
    g = goals.as_json(user.id, day)
    if g:
        lines.append('🎯 Цели на сегодня – отмечай кнопками:')
        rows = [[(('✅ ' if x['done'] else '▫️ ') + x['title'][:40], f"goal:{x['id']}")] for x in g]
    return '\n'.join(lines), (buttons(rows) if rows else None)


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
