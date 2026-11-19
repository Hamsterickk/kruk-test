"""Анкета при первом входе и норма калорий по ней."""
import re

from app.models import db, User
from app.services import body
from datetime import date

STEPS = ['name', 'sex', 'age', 'height', 'weight']
QUESTIONS = {
    'name': 'Как тебя зовут?',
    'sex': 'Пол?',
    'age': 'Сколько тебе лет? Напиши числом',
    'height': 'Рост в сантиметрах?',
    'weight': 'Вес сейчас, кг? Например 74.5',
}


def compute_targets(user: User, weight: float | None) -> None:
    """Миффлин – Сан Жеор на поддержание, активность 1,55: тренировки 3 раза в неделю.
    Белок 1,8 г на кг. Что человек поставил сам, не трогаем."""
    if not (weight and user.age and user.height_cm and user.sex):
        return
    bmr = 10 * weight + 6.25 * user.height_cm - 5 * user.age + (5 if user.sex == 'm' else -161)
    if not user.kcal_manual:
        user.kcal_target = int(round(bmr * 1.55 / 50) * 50)
    if not user.protein_manual:
        user.protein_target = int(round(weight * 1.8))


def set_targets(user: User, kcal=None, protein=None, reset: bool = False) -> str | None:
    """Норма вручную: из чата или приложения. reset – снова считать по анкете. Ошибка или None."""
    if reset:
        user.kcal_manual = user.protein_manual = False
        compute_targets(user, latest_weight(user.id))
        return None
    if kcal is not None:
        if not 1000 <= kcal <= 6000:
            return 'Норма калорий – от 1000 до 6000'
        user.kcal_target, user.kcal_manual = int(round(kcal)), True
    if protein is not None:
        if not 30 <= protein <= 400:
            return 'Белок – от 30 до 400 г'
        user.protein_target, user.protein_manual = int(round(protein)), True
    return None


NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё' -]{0,39}$")


def clean_name(text: str) -> str | None:
    text = re.sub(r'\s+', ' ', (text or '').strip(' .,!'))
    if not NAME_RE.match(text):
        return None
    return text[:1].upper() + text[1:]


def latest_weight(user_id: int) -> float | None:
    return body.summary(user_id).get('weight')


def answer(user: User, text: str) -> str | None:
    """Ответ на текущий вопрос анкеты. Возвращает ошибку или None, если принято."""
    step = user.onboarding_step
    text = (text or '').strip()
    if step == 'name':
        name = clean_name(text)
        if not name:
            return 'Напиши имя буквами, до 40 символов'
        user.name = name
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
        return 'Норму посчитаю, когда будут рост, вес и возраст'
    return f"Твоя норма: {user.kcal_target} ккал в день, белок {user.protein_target} г"
