"""ИИ через бесплатный Groq. У каждой модели свой дневной лимит: кончился у первой –
идём к следующей. У каждого человека свой дневной лимит сообщений к ИИ."""
import json
import logging
from datetime import date, datetime, timedelta

import requests
from flask import current_app

from app.models import db, AiUsage
from app.services import foods, body, goals, club

logger = logging.getLogger(__name__)
_exhausted: dict[str, date] = {}   # модель → день, когда кончился её дневной лимит
_cooldown: dict[str, datetime] = {}  # модель → до какого времени не трогать после минутного лимита


class AiUnavailable(Exception):
    pass


SYSTEM_PROMPT = (
    "Ты помощник спортсмена клуба Kruk Team в телеграме: питание, вес, сон, шаги, цели дня и тренировки "
    "клуба. Отвечай коротко, по-русски, на «ты», без воды. Всё записывай только через инструменты, "
    "не делай вид, что записал.\n"
    "Еда: каждый продукт отдельным пунктом с граммами и КБЖУ на 100 г. Если продукт есть в блоке «Из базы», "
    "бери его название как есть. Граммы не указаны – бери обычную порцию. КБЖУ оценивай по обычным "
    "таблицам калорийности, не завышай и не занижай. Блюдо из нескольких частей раскладывай на части. "
    "Если непонятно, что съедено или сколько, задай один короткий вопрос и ничего не записывай.\n"
    "Не давай медицинских советов: при болях и травмах – к врачу и тренеру. Группы и расписание "
    "меняет только тренер. Не выдумывай факты о человеке, опирайся на блок «Данные»."
)

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'log_meals', 'description': 'Записать съеденное.',
        'parameters': {'type': 'object', 'properties': {
            'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'name': {'type': 'string'}, 'grams': {'type': 'number'},
                'kcal_100': {'type': 'number'}, 'protein_100': {'type': 'number'},
                'fat_100': {'type': 'number'}, 'carbs_100': {'type': 'number'},
            }, 'required': ['name', 'grams', 'kcal_100', 'protein_100', 'fat_100', 'carbs_100']}},
            'days_ago': {'type': 'integer', 'description': '0 – сегодня, 1 – вчера'},
        }, 'required': ['items']}}},
    {'type': 'function', 'function': {
        'name': 'delete_meal', 'description': 'Удалить сегодняшнюю запись еды по названию.',
        'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}}},
    {'type': 'function', 'function': {
        'name': 'log_metrics', 'description': 'Записать вес в кг, сон в часах, шаги.',
        'parameters': {'type': 'object', 'properties': {
            'weight': {'type': 'number'}, 'sleep': {'type': 'number'}, 'steps': {'type': 'integer'},
            'days_ago': {'type': 'integer'}}}}},
    {'type': 'function', 'function': {
        'name': 'add_goal', 'description': 'Добавить цель: каждый день или только на сегодня.',
        'parameters': {'type': 'object', 'properties': {
            'title': {'type': 'string'}, 'daily': {'type': 'boolean'}}, 'required': ['title']}}},
    {'type': 'function', 'function': {
        'name': 'complete_goal', 'description': 'Отметить цель дня выполненной.',
        'parameters': {'type': 'object', 'properties': {'title': {'type': 'string'}}, 'required': ['title']}}},
    {'type': 'function', 'function': {
        'name': 'mark_training', 'description': 'Отметить, был ли на тренировке клуба, и что отрабатывал.',
        'parameters': {'type': 'object', 'properties': {
            'present': {'type': 'boolean'}, 'note': {'type': 'string'}, 'days_ago': {'type': 'integer'}},
            'required': ['present']}}},
    {'type': 'function', 'function': {
        'name': 'remember_food', 'description': 'Запомнить продукт в личную базу: КБЖУ на 100 г и обычная порция.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'kcal_100': {'type': 'number'}, 'protein_100': {'type': 'number'},
            'fat_100': {'type': 'number'}, 'carbs_100': {'type': 'number'}, 'portion': {'type': 'number'}},
            'required': ['name', 'kcal_100', 'protein_100', 'fat_100', 'carbs_100']}}},
]


# ===== ЛИМИТЫ =====

def usage_today(user_id: int) -> AiUsage:
    row = AiUsage.query.filter_by(user_id=user_id, on_date=date.today()).first()
    if not row:
        row = AiUsage(user_id=user_id, on_date=date.today(), requests=0, tokens=0)
        db.session.add(row)
        db.session.flush()
    return row


def left_today(user_id: int) -> int:
    used = AiUsage.query.filter_by(user_id=user_id, on_date=date.today()).first()
    return max(0, current_app.config['AI_DAILY_LIMIT'] - (used.requests if used else 0))


# ===== ЗАПРОС =====

def _post(payload: dict) -> dict:
    """Запрос с перебором моделей. AiUnavailable – ни одна не ответила."""
    key = current_app.config.get('GROQ_API_KEY')
    if not key:
        raise AiUnavailable('нет ключа')
    last_error = 'нет доступных моделей'
    for model in current_app.config['GROQ_MODELS']:
        if _exhausted.get(model) == date.today():
            continue
        if _cooldown.get(model) and _cooldown[model] > datetime.now():
            continue
        try:
            r = requests.post(current_app.config['GROQ_API_URL'], json={**payload, 'model': model},
                              headers={'Authorization': f'Bearer {key}'}, timeout=(5, 25))
        except requests.RequestException as e:
            last_error = f'{model}: {e}'
            continue
        if r.status_code == 200:
            data = r.json()
            data['_model'] = model
            return data
        text = r.text[:500]
        last_error = f'{model}: {r.status_code} {text}'
        if r.status_code == 429:
            if 'per day' in text or 'TPD' in text or 'RPD' in text:
                _exhausted[model] = date.today()
            else:
                _cooldown[model] = datetime.now() + timedelta(seconds=60)
            continue
        if r.status_code >= 500 or r.status_code in (400, 404, 413):
            continue  # 400 бывает, если модель не умеет инструменты – пробуем следующую
        break
    logger.warning('ИИ недоступен: %s', last_error)
    raise AiUnavailable(last_error)


# ===== КОНТЕКСТ =====

def context(user, text: str) -> str:
    meals = foods.day_meals(user.id)
    t = foods.totals(meals)
    lines = [f"Данные. Сегодня {date.today():%d.%m.%Y}, {club.WD_SHORT[date.today().weekday()]}."]
    lines.append(f"Имя: {user.name or '–'}. Цель: {({'gain': 'набор', 'cut': 'сушка', 'keep': 'поддержание'}).get(user.goal, '–')}."
                 + (f" Норма {user.kcal_target} ккал, белок {user.protein_target} г." if user.kcal_target else ''))
    lines.append(f"Съедено сегодня: {t['kcal']} ккал, Б {t['protein']} Ж {t['fat']} У {t['carbs']}: "
                 + ('; '.join(foods.meal_short(m) for m in meals) or 'ничего'))
    m = body.peek(user.id, date.today())
    lines.append(f"Сегодня вес {m.weight or '–'}, сон {m.sleep or '–'}, шаги {m.steps or '–'}.")
    g = goals.as_json(user.id)
    lines.append('Цели дня: ' + ('; '.join(f"{x['title']} – {'да' if x['done'] else 'нет'}" for x in g) or 'нет'))
    groups = club.user_groups(user.id)
    upcoming = club.sessions(groups, date.today() - timedelta(days=1), date.today() + timedelta(days=1))
    lines.append('Тренировки вчера–завтра: ' + ('; '.join(
        club.session_text(s) + (' – отменена' if s['cancelled'] else '') for s in upcoming) or 'нет'))
    candidates = []
    for item in foods.parse_food_text(text) or [{'name': w} for w in text.split() if len(w) > 3][:8]:
        for f in foods.search(user.id, item['name'], limit=2):
            if f.name not in [c.name for c in candidates]:
                candidates.append(f)
    if candidates:
        lines.append('Из базы, КБЖУ на 100 г: ' + '; '.join(
            f"{f.name} {f.kcal:g}/{f.protein:g}/{f.fat:g}/{f.carbs:g}, порция {f.portion or 100:g} г" for f in candidates[:10]))
    return '\n'.join(lines)


# ===== ИНСТРУМЕНТЫ =====

def _num(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def run_tool(user, name: str, args: dict, state: dict) -> str:
    day = date.today() - timedelta(days=max(0, min(6, int(args.get('days_ago') or 0))))
    if name == 'log_meals':
        logged, bad = [], []
        for it in args.get('items') or []:
            grams = _num(it.get('grams'), 1, 3000)
            if not it.get('name') or not grams:
                bad.append(str(it.get('name') or '?'))
                continue
            known = foods.best_match(user.id, it['name'])
            if known and set(foods.stems(it['name'])) <= set(foods.stems(known.name + ' ' + (known.keywords or ''))):
                meal = foods.log_from_food(user.id, known, grams=grams, on_date=day)
            else:
                kcal = _num(it.get('kcal_100'), 0, 950)
                p, f, c = (_num(it.get(k), 0, 100) for k in ('protein_100', 'fat_100', 'carbs_100'))
                if None in (kcal, p, f, c) or p + f + c > 100.5:
                    bad.append(it['name'])
                    continue
                per100 = {'kcal': kcal, 'protein': p, 'fat': f, 'carbs': c}
                meal = foods.add_meal(user.id, it['name'], grams, per100, day, estimated=True)
                state.setdefault('estimated', []).append({**per100, 'name': it['name'], 'portion': grams})
            logged.append(foods.meal_short(meal))
        db.session.commit()
        out = ('Записано: ' + '; '.join(logged)) if logged else ''
        return out + (f" Не записано: {', '.join(bad)}" if bad else '') or 'Нечего записывать'
    if name == 'delete_meal':
        meals = [m for m in reversed(foods.day_meals(user.id)) if set(foods.stems(args.get('name', ''))) & set(foods.stems(m.name))]
        if not meals:
            return 'Такой записи сегодня нет'
        db.session.delete(meals[0])
        db.session.commit()
        return f"Удалено: {foods.meal_short(meals[0])}"
    if name == 'log_metrics':
        w, s, st = _num(args.get('weight'), 30, 250), _num(args.get('sleep'), 0.5, 16), _num(args.get('steps'), 0, 100000)
        if w is None and s is None and st is None:
            return 'Нечего записывать'
        body.save(user.id, day, w, s, int(st) if st is not None else None)
        return 'Записано' + (f" за {day:%d.%m}" if day != date.today() else '')
    if name == 'add_goal':
        g = goals.add(user.id, args.get('title', ''), daily=bool(args.get('daily', True)))
        return f"Цель добавлена: {g.title}"
    if name == 'complete_goal':
        g = goals.find(user.id, args.get('title', ''))
        if not g:
            return 'Такой цели нет'
        goals.set_done(g, True)
        return f"Отмечено: {g.title}"
    if name == 'mark_training':
        sess = [s for s in club.sessions(club.user_groups(user.id), day, day) if not s['cancelled']]
        if not sess:
            return 'В этот день у тебя нет занятий по расписанию'
        s = sess[0]
        club.set_attendance(user.id, s['group'].id, day, bool(args.get('present')), 'self', args.get('note'))
        return f"Отмечено: {club.session_text(s)} – {'был' if args.get('present') else 'не был'}"
    if name == 'remember_food':
        kcal = _num(args.get('kcal_100'), 0, 950)
        p, f, c = (_num(args.get(k), 0, 100) for k in ('protein_100', 'fat_100', 'carbs_100'))
        if None in (kcal, p, f, c) or not args.get('name'):
            return 'Не запомнил: проверь цифры'
        food = foods.remember_food(user.id, args['name'], kcal, p, f, c, _num(args.get('portion'), 1, 3000))
        return f"Запомнил: {food.name}"
    return 'Неизвестное действие'


# ===== ОТВЕТ =====

def reply(user, text: str, history: list[dict]) -> dict:
    """{'text', 'estimated'}. AiUnavailable – ИИ не ответил."""
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'system', 'content': context(user, text)}]
    messages += history[-6:]
    messages.append({'role': 'user', 'content': text})
    usage = usage_today(user.id)
    usage.requests += 1
    db.session.commit()
    state, results = {}, []
    for _ in range(3):
        data = _post({'messages': messages, 'tools': TOOLS, 'tool_choice': 'auto', 'temperature': 0.3,
                      'max_tokens': 900})
        usage.tokens += (data.get('usage') or {}).get('total_tokens', 0)
        db.session.commit()
        msg = data['choices'][0]['message']
        calls = msg.get('tool_calls') or []
        if not calls:
            content = (msg.get('content') or '').strip()
            if not content and results:
                content = '✅ ' + ' · '.join(results)
            return {'text': content or 'Готово', 'estimated': state.get('estimated', [])}
        messages.append({'role': 'assistant', 'content': msg.get('content') or '', 'tool_calls': calls})
        for call in calls:
            try:
                args = json.loads(call['function'].get('arguments') or '{}')
            except json.JSONDecodeError:
                args = {}
            try:
                result = run_tool(user, call['function']['name'], args, state)
            except Exception:
                db.session.rollback()
                logger.exception('Инструмент %s упал', call['function']['name'])
                result = 'Ошибка при записи'
            results.append(result)
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result})
    return {'text': '✅ ' + ' · '.join(results), 'estimated': state.get('estimated', [])}
