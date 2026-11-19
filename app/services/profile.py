"""Анкета при первом входе и норма калорий по ней."""
import re

from app.models import db, User
from app.services import body
from datetime import date

GOALS = {'gain': 'Набор массы', 'cut': 'Сушка', 'keep': 'Поддержание'}
STEPS = ['name', 'sex', 'age', 'height', 'weight', 'goal']
QUESTIONS = {
    'name': 'Как тебя зовут?',
    'sex': 'Пол?',
    'age': 'Сколько тебе лет? Напиши числом',
    'height': 'Рост в сантиметрах?',
    'weight': 'Вес сейчас, кг? Например 74.5',
    'goal': 'Какая цель?',
}


def compute_targets(user: User, weight: float | None) -> None:
    """Миффлин – Сан Жеор, активность 1,55: тренировки 3 раза в неделю.
    Набор +10%, сушка −15%. Белок 1,8 г на кг, на сушке 2 г."""
    if not (weight and user.age and user.height_cm and user.sex):
        return
    bmr = 10 * weight + 6.25 * user.height_cm - 5 * user.age + (5 if user.sex == 'm' else -161)
    kcal = bmr * 1.55 * {'gain': 1.10, 'cut': 0.85}.get(user.goal, 1.0)
    user.kcal_target = int(round(kcal / 50) * 50)
    user.protein_target = int(round(weight * (2.0 if user.goal == 'cut' else 1.8)))


def latest_weight(user_id: int) -> float | None:
    return body.summary(user_id).get('weight')


def answer(user: User, text: str) -> str | None:
    """Ответ на текущий вопрос анкеты. Возвращает ошибку или None, если принято."""
    step = user.onboarding_step
    text = (text or '').strip()
    if step == 'name':
        if not 1 <= len(text) <= 40:
            return 'Имя покороче, до 40 букв'
        user.name = text
    elif step == 'sex':
        low = text.lower()
        if low.startswith(('м', 'm')):
            user.sex = 'm'
        elif low.startswith(('ж', 'f', 'w')):
            user.sex = 'f'
        else:
            return 'Выбери кнопкой: мужской или женский'
    elif step == 'age':
        if not re.fullmatch(r'\d{1,2}', text) or not 18 <= int(text) <= 90:
            return 'Нужен возраст числом, от 18 лет'
        user.age = int(text)
    elif step == 'height':
        if not re.fullmatch(r'\d{3}', text) or not 120 <= int(text) <= 230:
            return 'Рост числом в сантиметрах, например 178'
        user.height_cm = int(text)
    elif step == 'weight':
        try:
            w = float(text.replace(',', '.'))
        except ValueError:
            return 'Вес числом, например 74.5'
        if not 30 <= w <= 250:
            return 'Вес числом, например 74.5'
        body.save(user.id, date.today(), weight=w)
    elif step == 'goal':
        key = next((k for k, v in GOALS.items() if text.lower() in (k, v.lower())), None)
        if not key:
            return 'Выбери цель кнопкой'
        user.goal = key
    nxt = STEPS.index(step) + 1
    user.onboarding_step = STEPS[nxt] if nxt < len(STEPS) else None
    if user.onboarding_step is None:
        compute_targets(user, latest_weight(user.id))
    db.session.commit()
    return None


def skip(user: User):
    """Тренер может не заполнять анкету: трекер ему не обязателен."""
    user.onboarding_step = None
    db.session.commit()


def norm_text(user: User) -> str:
    if not user.kcal_target:
        return 'Норму посчитаю, когда будут рост, вес, возраст и цель'
    return f"Твоя норма: {user.kcal_target} ккал в день, белок {user.protein_target} г"
