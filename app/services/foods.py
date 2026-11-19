"""Еда без внешних API: общая стартовая база, личная база каждого и запись скриптом.
ИИ подключается, только когда продукта нет ни в одной базе."""
import re
from datetime import date, timedelta

from app.models import db, Food, Meal
from app.services.food_data import STARTER_FOODS

WORD_RE = re.compile(r'[a-zа-я0-9%]+')


def norm(text: str) -> str:
    return (text or '').lower().replace('ё', 'е').strip()


def stem(word: str) -> str:
    """Грубая основа слова: «яйца» и «яйцо» → «яйц», «жареные» и «жареное» → «жарен»."""
    if len(word) <= 3:
        return word
    return word[:max(3, min(5, len(word) - 1))]


def stems(text: str) -> list[str]:
    return [stem(w) for w in WORD_RE.findall(norm(text)) if not w.isdigit()]


def seed_starter_foods() -> int:
    """Залить стартовую базу. Повторный запуск не дублирует и обновляет цифры."""
    existing = {norm(f.name): f for f in Food.query.filter(Food.user_id.is_(None)).all()}
    added = 0
    for name, kcal, p, f, c, portion, priority, keywords in STARTER_FOODS:
        food = existing.get(norm(name))
        if not food:
            food = Food(name=name, user_id=None)
            db.session.add(food)
            added += 1
        food.kcal, food.protein, food.fat, food.carbs = kcal, p, f, c
        food.portion, food.priority, food.keywords = portion, priority, keywords
    db.session.commit()
    return added


def _score(query_stems: list[str], food: Food) -> int | None:
    """Сколько очков даёт продукт под запрос. None – подходит не по всем словам."""
    name_stems = stems(food.name)
    all_stems = name_stems + stems(food.keywords or '')
    score = 0
    for q in query_stems:
        if q in name_stems:
            score += 3
        elif q in all_stems:
            score += 2
        elif any(s.startswith(q) or q.startswith(s) for s in all_stems if min(len(s), len(q)) >= 3):
            score += 1
        else:
            return None
    return score


def search(user_id: int, query: str, limit: int = 20) -> list[Food]:
    """Поиск по личной и общей базе. Личные продукты – первыми."""
    q = stems(query)
    if not q:
        return []
    pool = Food.query.filter((Food.user_id == user_id) | (Food.user_id.is_(None))).all()
    scored = []
    for food in pool:
        s = _score(q, food)
        if s is not None:
            if stems(food.name)[:1] == q[:1]:
                s += 1  # «овсянка» – это «Овсянка на воде», а не «Печенье овсяное»
            personal = 1 if food.user_id else 0
            scored.append((-personal, -s, food.priority or 0, len(stems(food.name)), food.name, food))
    scored.sort(key=lambda t: t[:5])
    return [t[-1] for t in scored[:limit]]


def best_match(user_id: int, name: str) -> Food | None:
    found = search(user_id, name, limit=1)
    return found[0] if found else None


# ===== РАЗБОР ТЕКСТА =====

# В сообщении есть что-то кроме «что съел» – это не простой список еды
NOT_FOOD_RE = re.compile(
    r'(\?|\b(не|нет|удали\w*|убери|убрать|поменя\w*|замени\w*|исправ\w*|вчера|позавчера|завтра|сколько|'
    r'что|как|почему|зачем|запомни|забудь|норм\w*|вместо|отмени\w*|верни|без|было|лишн\w*|вес|сон|спал|'
    r'шаг\w*|трениров\w*|цел\w*|это|там|был\w?|поправ\w*|ошиб\w*|неправильн\w*|меня|зовут)\b)', re.I)
SPLIT_RE = re.compile(r'\s*(?:[,;\n+]|\s\bи\b\s|\sплюс\s|\sещ[её]\s)\s*', re.I)
UNITS = r'грамм\w*|гр|г|мл|кг|л|штук\w*|шт'
NUM_AFTER = re.compile(rf'^(?P<name>.*?[^\d\s].*?)\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>{UNITS})?\.?$', re.I)
NUM_BEFORE = re.compile(rf'^(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>{UNITS})?\.?\s+(?P<name>.+)$', re.I)
EATEN_PREFIX = re.compile(r'^(я\s+)?(съел\w*|поел\w*|ел|выпил\w*|скушал\w*|на завтрак|на обед|на ужин|перекус\w*)\s*:?\s*', re.I)
WORD_NUMS = {'один': 1, 'одна': 1, 'одно': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
             'пол': 0.5, 'половина': 0.5, 'половину': 0.5}


def parse_food_text(text: str) -> list[dict] | None:
    """«круассан 65, молоко 300 мл, 2 банана» → [{name, grams, pieces}].
    None – это не простой список еды."""
    text = (text or '').strip()
    if not text or len(text) > 300 or NOT_FOOD_RE.search(text):
        return None
    text = EATEN_PREFIX.sub('', text)
    items = []
    for part in SPLIT_RE.split(text):
        part = part.strip(' .!')
        if not part:
            continue
        first, _, rest = part.partition(' ')
        if first.lower() in WORD_NUMS and rest:
            part = f"{WORD_NUMS[first.lower()]} {rest}"
        match = NUM_BEFORE.match(part) or NUM_AFTER.match(part)
        name, grams, pieces = part, None, None
        if match:
            name = match.group('name').strip(' .')
            value = float(match.group('num').replace(',', '.'))
            unit = (match.group('unit') or '').lower()
            if unit.startswith('кг') or unit == 'л':
                grams = value * 1000
            elif unit.startswith(('г', 'мл')):
                grams = value
            elif unit.startswith('шт') or value <= 10:
                pieces = value  # «2 банана», «банан 2» – штуки
            else:
                grams = value
        if not re.search(r'[а-яёa-z]', name, re.I):
            return None
        items.append({'name': name, 'grams': grams, 'pieces': pieces})
    return items or None


# ===== ЗАПИСЬ =====

def nutrients(food: Food, grams: float) -> dict:
    k = grams / 100
    return {'kcal': food.kcal * k, 'protein': (food.protein or 0) * k,
            'fat': (food.fat or 0) * k, 'carbs': (food.carbs or 0) * k}


def add_meal(user_id: int, name: str, grams: float, per100: dict, on_date: date | None = None,
             estimated: bool = False) -> Meal:
    k = grams / 100
    meal = Meal(user_id=user_id, on_date=on_date or date.today(), name=name[:120], grams=round(grams),
                kcal=round(per100['kcal'] * k, 1), protein=round(per100.get('protein', 0) * k, 1),
                fat=round(per100.get('fat', 0) * k, 1), carbs=round(per100.get('carbs', 0) * k, 1),
                estimated=estimated)
    db.session.add(meal)
    return meal


def log_from_food(user_id: int, food: Food, grams: float | None = None, pieces: float | None = None,
                  on_date: date | None = None) -> Meal:
    portion = food.portion or 100
    grams = grams or (portion * pieces if pieces else portion)
    per100 = {'kcal': food.kcal, 'protein': food.protein, 'fat': food.fat, 'carbs': food.carbs}
    return add_meal(user_id, food.name, grams, per100, on_date)


def food_from_text(user_id: int, text: str) -> tuple[list[Meal], list[str]] | None:
    """Скриптом: всё нашлось в базах – записываем. Возвращает (записано, не найдено).
    None – это не список еды. Если чего-то нет, ничего не пишем: пусть разберётся ИИ."""
    items = parse_food_text(text)
    if not items:
        return None
    if not any(i['grams'] or i['pieces'] for i in items) and not any(best_match(user_id, i['name']) for i in items):
        return None  # ни цифр, ни знакомых продуктов – это не еда, а просто фраза
    found, missing = [], []
    for item in items:
        food = best_match(user_id, item['name'])
        if food:
            found.append((food, item))
        else:
            missing.append(item['name'])
    if missing:
        return [], missing
    meals = [log_from_food(user_id, food, item['grams'], item['pieces']) for food, item in found]
    db.session.commit()
    return meals, []


def remember_food(user_id: int, name: str, kcal: float, protein: float, fat: float, carbs: float,
                  portion: float | None = None) -> Food:
    """В личную базу. Тот же продукт ещё раз – обновить цифры."""
    name = name.strip()[:120]
    food = next((f for f in Food.query.filter_by(user_id=user_id).all() if norm(f.name) == norm(name)), None)
    if not food:
        food = Food(user_id=user_id, name=name)
        db.session.add(food)
    food.kcal, food.protein, food.fat, food.carbs = kcal, protein, fat, carbs
    if portion:
        food.portion = portion
    db.session.commit()
    return food


# «Протеин Ваниль 380 75 5 8» или «запомни сырок 400/8/28/32 порция 40» – новый продукт без ИИ
ADD_FOOD_RE = re.compile(
    r'^(?:запомни|добавь в базу|в базу)?\s*(?P<name>[^\d]+?)\s+(?P<kcal>\d+(?:[.,]\d+)?)\s*(?:ккал)?[\s/]+'
    r'(?P<p>\d+(?:[.,]\d+)?)[\s/]+(?P<f>\d+(?:[.,]\d+)?)[\s/]+(?P<c>\d+(?:[.,]\d+)?)'
    r'(?:\s*(?:порция|по)?\s*(?P<portion>\d+(?:[.,]\d+)?)\s*(?:г|гр|грамм)?)?\s*$', re.I)


def parse_new_food(text: str) -> dict | None:
    m = ADD_FOOD_RE.match((text or '').strip())
    if not m:
        return None
    num = lambda k: float(m.group(k).replace(',', '.')) if m.group(k) else None  # noqa: E731
    data = {'name': m.group('name').strip(' :-'), 'kcal': num('kcal'), 'protein': num('p'),
            'fat': num('f'), 'carbs': num('c'), 'portion': num('portion')}
    if not data['name'] or data['kcal'] > 950 or data['protein'] + data['fat'] + data['carbs'] > 100.5:
        return None
    return data


# ===== СВОДКИ =====

def day_meals(user_id: int, day: date | None = None) -> list[Meal]:
    return Meal.query.filter_by(user_id=user_id, on_date=day or date.today()).order_by(Meal.created_at).all()


def totals(meals: list[Meal]) -> dict:
    return {k: round(sum(getattr(m, k) or 0 for m in meals)) for k in ('kcal', 'protein', 'fat', 'carbs')}


def day_line(user) -> str:
    t = totals(day_meals(user.id))
    norm_kcal = user.kcal_target
    head = f"{t['kcal']}" + (f" из {norm_kcal}" if norm_kcal else '') + ' ккал'
    protein = f"белок {t['protein']}" + (f" из {user.protein_target}" if user.protein_target else '') + ' г'
    return f"За сегодня: {head}, {protein}"


def meal_short(m: Meal) -> str:
    return f"{m.name} {round(m.grams)} г – {round(m.kcal)} ккал"


def average_kcal(user_id: int, days: int = 7) -> int | None:
    start = date.today() - timedelta(days=days)
    rows = Meal.query.filter(Meal.user_id == user_id, Meal.on_date >= start, Meal.on_date < date.today()).all()
    by_day = {}
    for m in rows:
        by_day[m.on_date] = by_day.get(m.on_date, 0) + (m.kcal or 0)
    return round(sum(by_day.values()) / len(by_day)) if by_day else None
