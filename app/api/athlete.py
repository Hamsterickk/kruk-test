"""API спортсмена: профиль, еда, вес-сон-шаги, цели, клуб, чат. Всё – только своё."""
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, g

from app.auth import user_required
from app.models import db, Club, Food, Meal, Goal
from app.services import foods, body, goals, club, chat, profile, ai

bp = Blueprint('athlete', __name__)


def _num(value, lo, hi):
    try:
        v = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def _day(raw, back: int = 6):
    """Дата из запроса: сегодня или задним числом в пределах недели."""
    if not raw:
        return date.today()
    try:
        d = date.fromisoformat(str(raw))
    except ValueError:
        return None
    return d if date.today() - timedelta(days=back) <= d <= date.today() else None


# ===== ПРОФИЛЬ =====

@bp.route('/me')
@user_required
def me():
    u = g.user
    c = db.session.get(Club, u.club_id) if u.club_id else None
    return jsonify({
        'name': u.name, 'role': u.role, 'is_trainer': u.is_trainer, 'club': c.name if c else None,
        'goal': u.goal, 'goal_text': profile.GOALS.get(u.goal), 'kcal_target': u.kcal_target,
        'protein_target': u.protein_target, 'morning_hour': u.morning_hour, 'sex': u.sex, 'age': u.age,
        'height_cm': u.height_cm, 'ai_left': ai.left_today(u.id),
    })


@bp.route('/me', methods=['POST'])
@user_required
def update_me():
    u, data = g.user, request.json or {}
    if 'morning_hour' in data:
        h = _num(data['morning_hour'], 5, 12)
        if h is None:
            return jsonify({'error': 'Утро – с 5 до 12 часов'}), 400
        u.morning_hour = int(h)
    if data.get('goal') in profile.GOALS:
        u.goal = data['goal']
    if 'age' in data:
        a = _num(data['age'], 18, 90)
        if a is None:
            return jsonify({'error': 'Возраст от 18 до 90'}), 400
        u.age = int(a)
    if 'height_cm' in data:
        h = _num(data['height_cm'], 120, 230)
        if h is None:
            return jsonify({'error': 'Рост от 120 до 230 см'}), 400
        u.height_cm = int(h)
    if data.get('name'):
        u.name = str(data['name']).strip()[:40]
    profile.compute_targets(u, profile.latest_weight(u.id))
    db.session.commit()
    return me()


@bp.route('/today')
@user_required
def today():
    u = g.user
    t = foods.totals(foods.day_meals(u.id))
    m = body.peek(u.id, date.today())
    groups = club.user_groups(u.id)
    upcoming = [s for s in club.sessions(groups, date.today(), date.today() + timedelta(days=6))
                if club.session_end(s) > datetime.now()][:4]
    att = club.attendance_map(u.id, date.today(), date.today())
    return jsonify({
        'food': t, 'kcal_target': u.kcal_target, 'protein_target': u.protein_target,
        'weight': m.weight, 'sleep': m.sleep, 'steps': m.steps,
        'goals': goals.as_json(u.id),
        'sessions': [_session_json(s, att) for s in upcoming],
        'week': dict(zip(('present', 'total'), club.week_count(u.id))),
    })


def _session_json(s, att=None):
    a = (att or {}).get((s['group'].id, s['date']))
    return {'group_id': s['group'].id, 'group': s['group'].name, 'date': s['date'].isoformat(),
            'weekday': club.WD_SHORT[s['date'].weekday()], 'start': s['group'].start_time,
            'end': s['group'].end_time, 'location': club.group_json(s['group'])['location'],
            'address': club.group_json(s['group'])['address'], 'cancelled': s['cancelled'], 'note': s['note'],
            'present': a.present if a else None, 'started': club.session_start(s) <= datetime.now()}


# ===== ЕДА =====

def _meal_json(m: Meal) -> dict:
    return {'id': m.id, 'name': m.name, 'grams': round(m.grams), 'kcal': round(m.kcal),
            'protein': round(m.protein, 1), 'fat': round(m.fat, 1), 'carbs': round(m.carbs, 1),
            'estimated': m.estimated, 'time': m.created_at.strftime('%H:%M') if m.created_at else ''}


def _food_json(f: Food) -> dict:
    return {'id': f.id, 'name': f.name, 'kcal': f.kcal, 'protein': f.protein, 'fat': f.fat, 'carbs': f.carbs,
            'portion': f.portion, 'personal': f.user_id is not None}


@bp.route('/food/today')
@user_required
def food_today():
    u = g.user
    meals = foods.day_meals(u.id)
    return jsonify({'meals': [_meal_json(m) for m in meals], 'totals': foods.totals(meals),
                    'kcal_target': u.kcal_target, 'protein_target': u.protein_target})


@bp.route('/food/search')
@user_required
def food_search():
    return jsonify([_food_json(f) for f in foods.search(g.user.id, request.args.get('q', ''), limit=15)])


@bp.route('/food/log', methods=['POST'])
@user_required
def food_log():
    data = request.json or {}
    food = db.session.get(Food, int(data.get('food_id') or 0))
    if not food or (food.user_id not in (None, g.user.id)):
        return jsonify({'error': 'Продукт не найден'}), 404
    grams = _num(data.get('grams') or food.portion or 100, 1, 3000)
    if grams is None:
        return jsonify({'error': 'Вес порции от 1 до 3000 г'}), 400
    meal = foods.log_from_food(g.user.id, food, grams=grams)
    db.session.commit()
    return jsonify(_meal_json(meal))


@bp.route('/food/meal/<int:meal_id>', methods=['POST', 'DELETE'])
@user_required
def food_meal(meal_id):
    meal = Meal.query.filter_by(id=meal_id, user_id=g.user.id).first()
    if not meal:
        return jsonify({'error': 'Запись не найдена'}), 404
    if request.method == 'DELETE':
        db.session.delete(meal)
        db.session.commit()
        return jsonify({'ok': True})
    grams = _num((request.json or {}).get('grams'), 1, 3000)
    if grams is None:
        return jsonify({'error': 'Вес от 1 до 3000 г'}), 400
    k = grams / meal.grams if meal.grams else 1
    meal.kcal, meal.protein, meal.fat, meal.carbs = (round(v * k, 1) for v in (meal.kcal, meal.protein, meal.fat, meal.carbs))
    meal.grams = round(grams)
    db.session.commit()
    return jsonify(_meal_json(meal))


@bp.route('/food/base')
@user_required
def food_base():
    rows = Food.query.filter_by(user_id=g.user.id).order_by(Food.name).all()
    return jsonify([_food_json(f) for f in rows])


@bp.route('/food/base', methods=['POST'])
@user_required
def food_base_add():
    data = request.json or {}
    name = str(data.get('name') or '').strip()
    kcal = _num(data.get('kcal'), 0, 950)
    p, f, c = (_num(data.get(k) or 0, 0, 100) for k in ('protein', 'fat', 'carbs'))
    portion = _num(data.get('portion'), 1, 3000) if data.get('portion') not in (None, '') else None
    if not name or kcal is None or None in (p, f, c) or p + f + c > 100.5:
        return jsonify({'error': 'Нужны название и КБЖУ на 100 г: белки + жиры + углеводы не больше 100'}), 400
    food = foods.remember_food(g.user.id, name, kcal, p, f, c, portion)
    return jsonify(_food_json(food))


@bp.route('/food/base/<int:food_id>', methods=['DELETE'])
@user_required
def food_base_delete(food_id):
    food = Food.query.filter_by(id=food_id, user_id=g.user.id).first()
    if not food:
        return jsonify({'error': 'Продукт не найден'}), 404
    db.session.delete(food)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/food/yesterday')
@user_required
def food_yesterday():
    y = date.today() - timedelta(days=1)
    meals = foods.day_meals(g.user.id, y)
    today_keys = {(foods.norm(m.name), round(m.grams)) for m in foods.day_meals(g.user.id)}
    return jsonify({'meals': [_meal_json(m) for m in meals], 'kcal': foods.totals(meals)['kcal'],
                    'done': bool(meals) and all((foods.norm(m.name), round(m.grams)) in today_keys for m in meals)})


@bp.route('/food/repeat', methods=['POST'])
@user_required
def food_repeat():
    """Повторить вчерашние записи: все или выбранные id."""
    ids = set((request.json or {}).get('ids') or [])
    y = date.today() - timedelta(days=1)
    meals = [m for m in foods.day_meals(g.user.id, y) if not ids or m.id in ids]
    if not meals:
        return jsonify({'error': 'Вчера ничего не записано'}), 404
    for m in meals:
        per100 = {k: getattr(m, k) * 100 / m.grams if m.grams else 0 for k in ('kcal', 'protein', 'fat', 'carbs')}
        foods.add_meal(g.user.id, m.name, m.grams, per100, estimated=m.estimated)
    db.session.commit()
    return jsonify({'ok': True, 'count': len(meals)})


# ===== ВЕС, СОН, ШАГИ =====

@bp.route('/body')
@user_required
def body_week():
    offset = max(0, min(52, request.args.get('week', 0, type=int)))
    return jsonify({'days': body.week(g.user.id, offset), 'summary': body.summary(g.user.id), 'week': offset})


@bp.route('/body', methods=['POST'])
@user_required
def body_save():
    data = request.json or {}
    day = _day(data.get('date'))
    if not day:
        return jsonify({'error': 'Задним числом – только за последнюю неделю'}), 400
    w = _num(data['weight'], 30, 250) if data.get('weight') not in (None, '') else None
    s = _num(data['sleep'], 0.5, 16) if data.get('sleep') not in (None, '') else None
    st = body.parse_steps(str(data['steps'])) if data.get('steps') not in (None, '') else None
    if data.get('weight') not in (None, '') and w is None:
        return jsonify({'error': 'Вес от 30 до 250 кг'}), 400
    if data.get('sleep') not in (None, '') and s is None:
        return jsonify({'error': 'Сон от 0.5 до 16 часов'}), 400
    if data.get('steps') not in (None, '') and (st is None or st > 100000):
        return jsonify({'error': 'Шаги числом, например 8000 или 8к'}), 400
    if w is None and s is None and st is None:
        return jsonify({'error': 'Нечего записывать'}), 400
    body.save(g.user.id, day, w, s, st)
    if w is not None and day == date.today():
        profile.compute_targets(g.user, w)
        db.session.commit()
    return jsonify({'ok': True})


# ===== ЦЕЛИ =====

@bp.route('/goals')
@user_required
def goals_list():
    return jsonify(goals.as_json(g.user.id))


@bp.route('/goals', methods=['POST'])
@user_required
def goals_add():
    data = request.json or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'error': 'Напиши цель'}), 400
    goal = goals.add(g.user.id, title, daily=bool(data.get('daily', True)))
    return jsonify({'id': goal.id})


@bp.route('/goals/<int:goal_id>/toggle', methods=['POST'])
@user_required
def goals_toggle(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=g.user.id, is_active=True).first()
    if not goal:
        return jsonify({'error': 'Цель не найдена'}), 404
    done = goal.id in goals.done_ids([goal.id])
    goals.set_done(goal, not done)
    return jsonify({'done': not done})


@bp.route('/goals/<int:goal_id>', methods=['DELETE'])
@user_required
def goals_delete(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=g.user.id, is_active=True).first()
    if not goal:
        return jsonify({'error': 'Цель не найдена'}), 404
    if goal.created_by and goal.created_by != g.user.id:
        return jsonify({'error': 'Эту цель поставил тренер, убрать её может только он'}), 403
    goals.remove(goal)
    return jsonify({'ok': True})


# ===== КЛУБ =====

@bp.route('/club')
@user_required
def club_my():
    u = g.user
    groups = club.user_groups(u.id)
    start = date.today()
    sess = [s for s in club.sessions(groups, start, start + timedelta(days=7)) if club.session_end(s) > datetime.now()]
    att = club.attendance_map(u.id, start, start)
    return jsonify({'groups': [club.group_json(x) for x in groups],
                    'upcoming': [_session_json(s, att) for s in sess],
                    'history': club.history(u.id, 30), 'stats': club.attendance_stats(u.id, 30)})


@bp.route('/club/attendance', methods=['POST'])
@user_required
def club_attendance():
    data = request.json or {}
    day = _day(data.get('date'), back=30)
    group_id = int(data.get('group_id') or 0)
    if not day or group_id not in [x.id for x in club.user_groups(g.user.id)]:
        return jsonify({'error': 'Такого занятия у тебя нет'}), 400
    if not any(s['date'] == day and not s['cancelled'] for s in club.sessions([db.session.get(club.Group, group_id)], day, day)):
        return jsonify({'error': 'В этот день занятия не было'}), 400
    existing = club.attendance_map(g.user.id, day, day).get((group_id, day))
    if existing and existing.set_by == 'trainer' and 'present' in data:
        return jsonify({'error': 'Посещение уже отметил тренер, поменять может только он'}), 403
    present = data.get('present') if 'present' in data else (existing.present if existing else True)
    club.set_attendance(g.user.id, group_id, day, present, 'self' if not existing or existing.set_by == 'self' else 'trainer',
                        data.get('note') if 'note' in data else None)
    return jsonify({'ok': True})


# ===== ЧАТ =====

@bp.route('/chat')
@user_required
def chat_history():
    return jsonify([{'id': m.id, 'role': m.role, 'content': m.content} for m in chat.history(g.user.id, 100)])


@bp.route('/chat', methods=['POST'])
@user_required
def chat_send():
    text = str((request.json or {}).get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Пустое сообщение'}), 400
    out = chat.handle(g.user, text)
    actions = []
    for row in (out.get('markup') or {}).get('inline_keyboard', []):
        actions += [{'label': b['text'], 'data': b['callback_data']} for b in row if 'callback_data' in b]
    last = chat.history(g.user.id, 1)
    return jsonify({'reply': out['text'], 'actions': actions, 'id': last[0].id if last else None})


@bp.route('/chat/action', methods=['POST'])
@user_required
def chat_action():
    data = str((request.json or {}).get('data') or '')
    text = chat.callback(g.user, data)
    m = chat.save(g.user.id, 'assistant', text)
    return jsonify({'reply': text, 'id': m.id})


@bp.route('/chat/<int:msg_id>', methods=['DELETE'])
@user_required
def chat_delete(msg_id):
    m = chat.Message.query.filter_by(id=msg_id, user_id=g.user.id).first()
    if not m:
        return jsonify({'error': 'Сообщение не найдено'}), 404
    db.session.delete(m)
    db.session.commit()
    return jsonify({'ok': True})
