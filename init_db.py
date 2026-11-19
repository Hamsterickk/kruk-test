"""Создать таблицы, залить стартовую базу продуктов и клуб Kruk Team с расписанием.
Можно запускать повторно: ничего не дублирует. Печатает ссылки-приглашения."""
from sqlalchemy import text

from app import create_app
from app.models import db, User, Membership, Food, Pending, ATHLETE
from app.services.club import seed_kruk_team
from app.services.foods import seed_starter_foods
from app.services import profile

app = create_app()

NEW_COLUMNS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS kcal_manual BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS protein_manual BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS photo_id VARCHAR(200)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS photo_checked_at TIMESTAMP",
]

with app.app_context():
    db.create_all()
    for sql in NEW_COLUMNS:
        db.session.execute(text(sql))
    db.session.commit()
    added = seed_starter_foods()
    club = seed_kruk_team()
    # тренеры в группы не ставятся – убрать, если успели поставить
    trainers = [u.id for u in User.query.filter(User.role != ATHLETE).all()]
    if trainers:
        Membership.query.filter(Membership.user_id.in_(trainers)).delete(synchronize_session=False)
    # вопроса про цель больше нет: кто на нём застрял – анкета пройдена
    for u in User.query.filter_by(onboarding_step='goal').all():
        u.onboarding_step = None
        profile.compute_targets(u, profile.latest_weight(u.id))
    # мусор, который ИИ успел положить в личные базы: без букв в названии или с нулём калорий
    junk = [f for f in Food.query.filter(Food.user_id.isnot(None)).all()
            if sum(ch.isalpha() for ch in f.name) < 2 or not f.kcal]
    for f in junk:
        db.session.delete(f)
    Pending.query.delete()
    db.session.commit()
    username = app.config['BOT_USERNAME']
    print(f'Таблицы готовы. Новых продуктов в стартовой базе: {added}. Убрано мусора из баз: {len(junk)}')
    print(f'Ссылка для спортсменов: https://t.me/{username}?start={club.join_code}')
    print(f'Ссылка для тренеров:    https://t.me/{username}?start={club.trainer_code}')
