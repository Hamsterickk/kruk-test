"""Один чат на человека. Сначала всё, что можно, делает скрипт, ИИ – только для остального."""
import logging
import re
from datetime import date

from app.models import db, Message, Pending, Goal
from app.services import foods, body, goals, club, ai, profile

logger = logging.getLogger(__name__)

HELP = (
    "Пиши как обычно, я разберу:\n"
    "– еда: «гречка 200, курица 150, 2 яйца»\n"
    "– вес и сон: «74.5 7» или «вес 74.5», «спал 7»\n"
    "– шаги: «8000 шагов», задним числом – «вчера 9к шагов»\n"
    "– новый продукт в базу: «Сырок 407 8.5 27.8 32 порция 40» – ккал, Б, Ж, У на 100 г\n"
    "– тренировка: «был на тренировке, отрабатывали удушения»\n"
    "– поправить: «это был греческий йогурт», «там было 200 г», «моя норма 2400»\n"
    "Всё это видно и в приложении."
)


NAME_RE = re.compile(r'^(?:меня зовут|зови меня|называй меня|мо[её] имя)\s*[:–-]?\s*(?P<name>[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё -]{0,39}?)\s*[.!)]*$', re.I)
TRAIN_RE = re.compile(r'^(?P<neg>не\s+)?(был|была|ходил|ходила|сходил|сходила)\s+на\s+(тренировк\w*|трен\w*|занят\w*)', re.I)


def save(user_id: int, role: str, content: str) -> Message:
    m = Message(user_id=user_id, role=role, content=content)
    db.session.add(m)
    db.session.commit()
    return m


def history(user_id: int, limit: int = 100) -> list[Message]:
    rows = Message.query.filter_by(user_id=user_id).order_by(Message.id.desc()).limit(limit).all()
    return list(reversed(rows))


def handle(user, text: str) -> dict:
    """Сообщение человека → {'text', 'markup'}. Обе реплики сохраняются в историю."""
    text = (text or '').strip()[:2000]
    if not text:
        return {'text': 'Пустое сообщение', 'markup': None}
    prior = [{'role': m.role, 'content': m.content} for m in history(user.id, 8)]
    save(user.id, 'user', text)
    out = _script(user, text)
    if out is None:
        out = _ai(user, text, prior)
    save(user.id, 'assistant', out['text'])
    return out


def _script(user, text: str) -> dict | None:
    low = text.lower().strip()
    if low in ('/help', 'помощь', 'что умеешь', 'что ты умеешь'):
        return {'text': HELP, 'markup': None}
    m = NAME_RE.match(text.strip())
    if m and len(m.group('name').split()) <= 3:
        name = profile.clean_name(m.group('name'))
        if name:
            user.name = name
            db.session.commit()
            return {'text': f"Приятно познакомиться, {name} 👊 Имя поменял, тренер видит его так же.", 'markup': None}
    new_food = foods.parse_new_food(text)
    if new_food:
        f = foods.remember_food(user.id, new_food['name'], new_food['kcal'], new_food['protein'],
                                new_food['fat'], new_food['carbs'], new_food['portion'])
        portion = f" Порция {f.portion:g} г." if f.portion else ''
        return {'text': f"📒 Запомнил {f.name}: {f.kcal:g} ккал, Б {f.protein:g} Ж {f.fat:g} У {f.carbs:g} на 100 г.{portion}\n"
                        f"Теперь пиши «{f.name} 50» – запишу.", 'markup': None}
    m = TRAIN_RE.match(low)
    if m:
        present = not m.group('neg')
        note = text[m.end():].strip(' ,.:-–') or None
        sess = [s for s in club.sessions(club.user_groups(user.id), date.today(), date.today()) if not s['cancelled']]
        if not sess:
            return {'text': 'Сегодня у тебя нет занятий по расписанию. Если что-то не так – напиши тренеру.', 'markup': None}
        club.set_attendance(user.id, sess[0]['group'].id, date.today(), present, 'self', note if present else None)
        tail = f" Записал: {note}" if present and note else ''
        return {'text': f"{'💪 Отметил: был' if present else 'Отметил: не был'} – {club.session_text(sess[0], False)}.{tail}",
                'markup': None}
    metrics = body.apply_text(user.id, text)
    if metrics:
        return {'text': metrics, 'markup': None}
    res = foods.food_from_text(user.id, text)
    if res:
        meals, missing = res
        if meals:
            lines = '\n'.join(f"– {foods.meal_short(m)}" for m in meals)
            return {'text': f"✅ Записал:\n{lines}\n{foods.day_line(user)}", 'markup': None}
        if missing and ai.left_today(user.id) == 0:
            return {'text': f"Не нашёл в базе: {', '.join(missing)}. ИИ на сегодня закончился, поэтому "
                            "добавь продукт сам: «Название ккал Б Ж У» на 100 г, или в приложении в базе.",
                    'markup': None}
    return None


def _ai(user, text: str, prior: list[dict]) -> dict:
    if ai.left_today(user.id) == 0:
        return {'text': "На сегодня лимит сообщений к ИИ закончился. Записи скриптом работают как обычно:\n\n" + HELP,
                'markup': None}
    try:
        result = ai.reply(user, text, prior)
    except ai.AiUnavailable:
        return {'text': "ИИ сейчас не отвечает. Записи скриптом работают:\n\n" + HELP, 'markup': None}
    except Exception:
        db.session.rollback()
        logger.exception('Ошибка ИИ')
        return {'text': 'Что-то пошло не так, попробуй ещё раз', 'markup': None}
    return {'text': result['text'], 'markup': None}


# ===== КНОПКИ =====

def callback(user, data: str) -> str:
    """Нажатие кнопки → текст ответа. Одинаково из телеграма и из приложения."""
    kind, _, rest = data.partition(':')
    if kind in ('rem', 'remno'):
        Pending.query.filter_by(user_id=user.id).delete()
        db.session.commit()
        return 'Кнопка устарела'
    if kind == 'att':
        group_id, day, present = rest.split(':')
        group_id, day = int(group_id), date.fromisoformat(day)
        if group_id not in [g.id for g in club.user_groups(user.id)]:
            return 'Эта группа у тебя больше не стоит'
        club.set_attendance(user.id, group_id, day, present == '1', 'self')
        if present == '1':
            return '💪 Отметил: был. Если хочешь, напиши, что отрабатывали – запишу в дневник.'
        return 'Отметил: не был.'
    if kind == 'rsvp':
        group_id, day, going = rest.split(':')
        group_id, day = int(group_id), date.fromisoformat(day)
        if group_id not in [g.id for g in club.user_groups(user.id)]:
            return 'Эта группа у тебя больше не стоит'
        club.set_rsvp(user.id, group_id, day, going == '1')
        return '✅ Записал: будешь. Тренер видит.' if going == '1' else 'Ок, отметил, что не сможешь. Тренер видит.'
    if kind == 'lead':
        from app.models import Group
        from app.services import reminders
        group_id, day = rest.split(':')
        grp = Group.query.filter_by(id=int(group_id), club_id=user.club_id).first()
        if user.role == 'admin':
            return 'Админ занятия не ведёт – так тебя никто не видит'
        if not user.is_trainer or not grp:
            return 'Это кнопка для тренеров'
        day = date.fromisoformat(day)
        ok, who = club.take_lead(grp.id, day, user.id)
        if not ok:
            return f"Уже ведёт {who}"
        reminders.notify_lead_taken(user, grp, day)
        s = {'group': grp, 'date': day, 'cancelled': False, 'note': None}
        return f"💪 Ты ведёшь: {club.session_text(s)}. Остальные тренеры в курсе."
    if kind == 'goal':
        g = Goal.query.filter_by(id=int(rest or 0), user_id=user.id, is_active=True).first()
        if not g:
            return 'Цели уже нет'
        done = g.id in goals.done_ids([g.id])
        goals.set_done(g, not done)
        a, b = goals.progress(user.id)
        return f"{'↩️ Снял' if done else '✅ Отметил'}: {g.title}. Целей сегодня: {a} из {b}"
    return 'Кнопка устарела'

