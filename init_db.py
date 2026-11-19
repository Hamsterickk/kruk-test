"""Создать таблицы, залить стартовую базу продуктов и клуб Kruk Team с расписанием.
Можно запускать повторно: ничего не дублирует. Печатает ссылки-приглашения."""
from app import create_app
from app.models import db, User, Membership, ATHLETE
from app.services.club import seed_kruk_team
from app.services.foods import seed_starter_foods

app = create_app()

with app.app_context():
    db.create_all()
    added = seed_starter_foods()
    club = seed_kruk_team()
    # тренеры в группы не ставятся – убрать, если успели поставить
    trainers = [u.id for u in User.query.filter(User.role != ATHLETE).all()]
    if trainers:
        Membership.query.filter(Membership.user_id.in_(trainers)).delete(synchronize_session=False)
        db.session.commit()
    username = app.config['BOT_USERNAME']
    print(f'Таблицы готовы. Новых продуктов в стартовой базе: {added}')
    print(f'Ссылка для спортсменов: https://t.me/{username}?start={club.join_code}')
    print(f'Ссылка для тренеров:    https://t.me/{username}?start={club.trainer_code}')
