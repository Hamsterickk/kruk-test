"""Создать таблицы, залить стартовую базу продуктов и клуб Kruk Team с расписанием.
Можно запускать повторно: ничего не дублирует. Печатает ссылки-приглашения."""
from app import create_app
from app.models import db
from app.services.club import seed_kruk_team
from app.services.foods import seed_starter_foods

app = create_app()

with app.app_context():
    db.create_all()
    added = seed_starter_foods()
    club = seed_kruk_team()
    username = app.config['BOT_USERNAME']
    print(f'Таблицы готовы. Новых продуктов в стартовой базе: {added}')
    print(f'Ссылка для спортсменов: https://t.me/{username}?start={club.join_code}')
    print(f'Ссылка для тренеров:    https://t.me/{username}?start={club.trainer_code}')
