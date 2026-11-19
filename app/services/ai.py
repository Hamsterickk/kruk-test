"""ИИ через бесплатный Groq. У каждой модели свой дневной лимит: кончился у первой –
идём к следующей. У каждого человека свой дневной лимит сообщений к ИИ."""
import json
import logging
import time
from datetime import date, datetime, timedelta

import requests
from flask import current_app

from app.models import db, AiUsage
from app.services import foods, body, goals, club, profile

logger = logging.getLogger(__name__)
_exhausted: dict[str, date] = {}   # модель → день, когда кончился её дневной лимит
_cooldown: dict[str, datetime] = {}  # модель → до какого времени не трогать после минутного лимита


class AiUnavailable(Exception):
    pass


SYSTEM_PROMPT = (
    "Ты помощник спортсмена клуба Kruk Team в телеграме: питание, вес, сон, шаги, цели дня, тренировки "
    "клуба и его профиль. Отвечай коротко, по-русски, на «ты», без воды. Всё меняй только через "
    "инструменты, не делай вид, что записал. Всё, что человек просит поменять в своих данных, меняй сам: "
    "имя, норму калорий и белка, возраст, рост, записи еды, вес, сон, шаги, цели.\n"
    "Еда: не задавай вопросов. Граммы не указаны – бери обычную порцию сам. Незнакомое слово – скорее "
    "всего марка или блюдо: угадай, что это (например «Теос» – греческий йогурт), и запиши по обычным "
    "таблицам калорийности. Каждый продукт отдельным пунктом с граммами и КБЖУ на 100 г. Если продукт "
    "есть в блоке «Из базы», бери его название как есть. Блюдо из нескольких частей раскладывай на части.\n"
    "Человек поправляет запись («это был греческий йогурт», «там 200 г», «калорий больше») – исправь "
    "существующую запись через update_meal, новую не создавай. В интернет ты не ходишь, но таблицы "
    "калорийности знаешь – так и действуй.\n"
    "В личную базу продуктов (remember_food) – только когда человек сам прямо просит запомнить продукт.\n"
    "Норма: «мне надо 2400», «врач сказал 2400 ккал» – update_profile с kcal_target, это навсегда. "
    "«Посчитай норму заново» – reset_targets.\n"
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
        'name': 'update_meal',
        'description': 'Исправить уже записанную еду: название, граммы или КБЖУ на 100 г. '
                       'find – как запись называется сейчас, пусто – последняя запись.',
        'parameters': {'type': 'object', 'properties': {
            'find': {'type': 'string'}, 'new_name': {'type': 'string'}, 'grams': {'type': 'number'},
            'kcal_100': {'type': 'number'}, 'protein_100': {'type': 'number'},
            'fat_100': {'type': 'number'}, 'carbs_100': {'type': 'number'},
            'days_ago': {'type': 'integer'}}}}},
    {'type': 'function', 'function': {
        'name': 'update_profile',
        'description': 'Поменять профиль навсегда: имя, норму калорий, норму белка, возраст, рост, пол. '
                       'reset_targets – снова считать норму по анкете.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'kcal_target': {'type': 'integer'}, 'protein_target': {'type': 'integer'},
            'age': {'type': 'integer'}, 'height_cm': {'type': 'integer'}, 'sex': {'type': 'string', 'enum': ['m', 'f']},
            'reset_targets': {'type': 'boolean'}}}}},
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
        'name': 'remember_food',
        'description': 'Запомнить продукт в личную базу: КБЖУ на 100 г и обычная порция. Только если человек сам просит.',
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

class _Retry(Exception):
    """Ни одна модель не ответила, но похоже на временный сбой."""


def _post(payload: dict, deadline: float | None = None) -> dict:
    """Запрос с перебором моделей. AiUnavailable – ни одна не ответила.
    deadline – time.monotonic(), к которому надо успеть: дольше минуты сайт ответ не ждёт."""
    key = current_app.config.get('GROQ_API_KEY')
    if not key:
        raise AiUnavailable('нет ключа')
    deadline = deadline or time.monotonic() + 50
    last_error = 'нет доступных моделей'
    for attempt in range(2):
        if attempt:
            if deadline - time.monotonic() < 12:
                break
            time.sleep(2)  # все модели споткнулись разом – чаще всего это минутная заминка у Groq
        try:
            return _post_once(payload, key, deadline)
        except _Retry as e:
            last_error = str(e)
        except AiUnavailable as e:
            last_error = str(e)
            break
    logger.warning('ИИ недоступен: %s', last_error)
    raise AiUnavailable(last_error)


def _post_once(payload: dict, key: str, deadline: float) -> dict:
    last_error, transient = 'нет доступных моделей', False
    for model in current_app.config['GROQ_MODELS']:
        if _exhausted.get(model) == date.today():
            continue
        if _cooldown.get(model) and _cooldown[model] > datetime.now():
            continue
        r = None
        for _ in range(2):  # кривой вызов инструмента: та же модель со второй попытки обычно справляется
            left = deadline - time.monotonic()
            if left < 4:
                raise AiUnavailable(f'не успели: {last_error}')
            try:
                r = requests.post(current_app.config['GROQ_API_URL'], json={**payload, 'model': model},
                                  headers={'Authorization': f'Bearer {key}'}, timeout=(5, min(35, left)))
            except requests.RequestException as e:
                last_error, transient, r = f'{model}: {e}', True, None
                break
            if r.status_code == 200:
                data = r.json()
                data['_model'] = model
                return data
            last_error = f'{model}: {r.status_code} {r.text[:400]}'
            logger.info('Groq %s', last_error)
            if not (r.status_code == 400 and 'tool_use_failed' in r.text):
                break
        if r is None:
            continue
        if r.status_code in (401, 403):
            raise AiUnavailable(last_error)  # ключ не тот – перебирать модели бессмысленно
        if r.status_code == 429:
            if 'per day' in r.text or 'TPD' in r.text or 'RPD' in r.text:
                _exhausted[model] = date.today()
            else:
                _cooldown[model] = datetime.now() + timedelta(seconds=60)
                transient = True
        elif r.status_code >= 500:
            transient = True
        # 400 – модель не справилась с инструментами, 404 – модель убрали: берём следующую
    if transient:
        raise _Retry(last_error)
    raise AiUnavailable(last_error)


# ===== КОНТЕКСТ =====

def context(user, text: str) -> str:
    meals = foods.day_meals(user.id)
    t = foods.totals(meals)
    lines = [f"Данные. Сегодня {date.today():%d.%m.%Y}, {club.WD_SHORT[date.today().weekday()]}."]
    lines.append(f"Имя: {user.name or '–'}. Возраст {user.age or '–'}, рост {user.height_cm or '–'}."
                 + (f" Норма {user.kcal_target} ккал{' (поставил сам)' if user.kcal_manual else ' (по анкете)'},"
                    f" белок {user.protein_target} г." if user.kcal_target else ' Нормы пока нет.'))
    lines.append(f"Съедено сегодня: {t['kcal']} ккал, Б {t['protein']} Ж {t['fat']} У {t['carbs']}. Записи по порядку: "
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


def _per100(args: dict) -> dict | None:
    """КБЖУ на 100 г от ИИ. Калорий меньше, чем дают сами Б, Ж и У, – ИИ ошибся: считаем по ним."""
    kcal = _num(args.get('kcal_100'), 0, 950)
    p, f, c = (_num(args.get(k) or 0, 0, 100) for k in ('protein_100', 'fat_100', 'carbs_100'))
    if None in (p, f, c) or p + f + c > 100.5:
        return None
    calc = 4 * p + 9 * f + 4 * c
    if kcal is None or (calc > 20 and kcal < calc * 0.6):
        kcal = round(calc)
    return {'kcal': kcal, 'protein': p, 'fat': f, 'carbs': c}


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text or '')


def _update_meal(user, args: dict, day) -> str:
    meals = foods.day_meals(user.id, day)
    if not meals:
        return 'Записей за этот день нет'
    find = str(args.get('find') or '').strip()
    hits = [m for m in reversed(meals) if find and set(foods.stems(find)) & set(foods.stems(m.name))]
    meal = hits[0] if hits else meals[-1]
    grams = _num(args.get('grams'), 1, 3000) or meal.grams
    new_name = str(args.get('new_name') or '').strip()
    if new_name and _letters(new_name) < 2:
        new_name = ''
    if args.get('kcal_100') is not None or args.get('protein_100') is not None:
        per = _per100(args)
        if not per:
            return 'Не исправил: проверь цифры'
        estimated = True
    else:
        known = foods.best_match(user.id, new_name) if new_name else None
        if known and set(foods.stems(new_name)) <= set(foods.stems(known.name + ' ' + (known.keywords or ''))):
            per, estimated, new_name = {'kcal': known.kcal, 'protein': known.protein, 'fat': known.fat,
                                        'carbs': known.carbs}, False, known.name
        else:
            k = 100 / meal.grams if meal.grams else 1
            per = {'kcal': meal.kcal * k, 'protein': meal.protein * k, 'fat': meal.fat * k, 'carbs': meal.carbs * k}
            estimated = meal.estimated
    before = foods.meal_short(meal)
    k = grams / 100
    meal.name = (new_name or meal.name)[:120]
    meal.grams = round(grams)
    meal.kcal, meal.protein, meal.fat, meal.carbs = (round(per[x] * k, 1) for x in ('kcal', 'protein', 'fat', 'carbs'))
    meal.estimated = estimated
    db.session.commit()
    return f"Исправлено: было {before}, стало {foods.meal_short(meal)}"


def _update_profile(user, args: dict) -> str:
    done = []
    if args.get('name'):
        name = profile.clean_name(str(args['name']))
        if not name:
            return 'Имя – только буквы, до 40 символов'
        user.name = name
        done.append(f"имя {name}")
    age, height = _num(args.get('age'), 18, 90), _num(args.get('height_cm'), 120, 230)
    if args.get('age') is not None and age is None:
        return 'Возраст – от 18 до 90'
    if args.get('height_cm') is not None and height is None:
        return 'Рост – от 120 до 230 см'
    if age:
        user.age = int(age)
        done.append(f"возраст {int(age)}")
    if height:
        user.height_cm = int(height)
        done.append(f"рост {int(height)}")
    if args.get('sex') in ('m', 'f'):
        user.sex = args['sex']
        done.append('пол')
    kcal = _num(args.get('kcal_target'), 0, 100000) if args.get('kcal_target') is not None else None
    protein = _num(args.get('protein_target'), 0, 10000) if args.get('protein_target') is not None else None
    err = profile.set_targets(user, kcal, protein, reset=bool(args.get('reset_targets')))
    if err:
        db.session.rollback()
        return err
    profile.compute_targets(user, profile.latest_weight(user.id))
    if args.get('reset_targets'):
        done.append('норма снова по анкете')
    elif kcal is not None or protein is not None:
        done.append('норма')
    db.session.commit()
    if not done:
        return 'Нечего менять'
    norm = f" Норма сейчас {user.kcal_target} ккал, белок {user.protein_target} г." if user.kcal_target else ''
    return 'Сохранено: ' + ', '.join(done) + '.' + norm


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
                per100 = _per100(it)
                if not per100 or _letters(it['name']) < 2:
                    bad.append(it['name'])
                    continue
                meal = foods.add_meal(user.id, it['name'], grams, per100, day, estimated=True)
            logged.append(foods.meal_short(meal))
        db.session.commit()
        out = ('Записано: ' + '; '.join(logged)) if logged else ''
        return out + (f" Не записано: {', '.join(bad)}" if bad else '') or 'Нечего записывать'
    if name == 'update_meal':
        return _update_meal(user, args, day)
    if name == 'update_profile':
        return _update_profile(user, args)
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
        per = _per100(args)
        fname = str(args.get('name') or '').strip()
        if not per or per['kcal'] <= 0 or _letters(fname) < 2:
            return 'Не запомнил: нужно понятное название продукта и КБЖУ'
        food = foods.remember_food(user.id, fname, per['kcal'], per['protein'], per['fat'], per['carbs'],
                                   _num(args.get('portion'), 1, 3000))
        return f"Запомнил: {food.name}"
    return 'Неизвестное действие'


# ===== ОТВЕТ =====

def reply(user, text: str, history: list[dict]) -> dict:
    """{'text'}. AiUnavailable – ИИ не ответил."""
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'system', 'content': context(user, text)}]
    messages += history[-6:]
    messages.append({'role': 'user', 'content': text})
    usage = usage_today(user.id)
    usage.requests += 1
    db.session.commit()
    state, results = {}, []
    deadline = time.monotonic() + 50
    for _ in range(3):
        try:
            data = _post({'messages': messages, 'tools': TOOLS, 'tool_choice': 'auto', 'temperature': 0.3,
                          'max_tokens': 900}, deadline)
        except AiUnavailable:
            if results:  # записать успели, не дали только финальный текст
                return {'text': '✅ ' + ' · '.join(results)}
            raise
        usage.tokens += (data.get('usage') or {}).get('total_tokens', 0)
        db.session.commit()
        msg = data['choices'][0]['message']
        calls = msg.get('tool_calls') or []
        if not calls:
            content = (msg.get('content') or '').strip()
            if not content and results:
                content = '✅ ' + ' · '.join(results)
            return {'text': content or 'Готово'}
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
    return {'text': '✅ ' + ' · '.join(results)}
