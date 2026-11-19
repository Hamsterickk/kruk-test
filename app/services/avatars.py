"""Аватарки из телеграма. Бот раз в сутки проверяет каждого и кладёт картинку на диск,
мини-апп отдаёт её по подписанной ссылке: картинке в <img> не передать заголовок авторизации."""
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta

from flask import current_app

from app.models import db, User
from app.services import tg

logger = logging.getLogger(__name__)
RECHECK = timedelta(hours=24)        # аватарка есть – проверяем раз в сутки
RECHECK_EMPTY = timedelta(hours=1)   # не было – раз в час: вдруг человек открыл её боту


def folder() -> str:
    path = current_app.config['AVATAR_DIR']
    os.makedirs(path, exist_ok=True)
    return path


def file_path(user_id: int) -> str:
    return os.path.join(folder(), f'{int(user_id)}.jpg')


def sign(user_id: int) -> str:
    key = (current_app.config['SECRET_KEY'] + current_app.config['TELEGRAM_BOT_TOKEN']).encode()
    return hmac.new(key, f'avatar:{user_id}'.encode(), hashlib.sha256).hexdigest()[:16]


def check_sign(user_id: int, s: str) -> bool:
    return hmac.compare_digest(sign(user_id), s or '')


def url(user: User) -> str | None:
    if not user or not user.photo_id:
        return None
    return f'/api/avatar/{user.id}?v={user.photo_id[-8:]}&s={sign(user.id)}'


def refresh(user: User) -> bool:
    """Скачать свежую аватарку. True – что-то поменялось."""
    got = tg.fetch_avatar(user.tg_id)
    user.photo_checked_at = datetime.utcnow()
    if got is None:
        db.session.commit()
        return False
    photo_id, content = got
    changed = photo_id != (user.photo_id or '')
    if photo_id and (changed or not os.path.exists(file_path(user.id))):
        tmp = file_path(user.id) + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(content)
        os.replace(tmp, file_path(user.id))
    if not photo_id and os.path.exists(file_path(user.id)):
        os.remove(file_path(user.id))
    user.photo_id = photo_id
    db.session.commit()
    return changed


def refresh_due(limit: int = 5) -> int:
    """Несколько человек за раз, у кого давно не проверяли. Зовётся из минутного тика бота."""
    now = datetime.utcnow()
    users = User.query.filter(User.is_active == True,  # noqa: E712
                              (User.photo_checked_at.is_(None)) | (User.photo_checked_at < now - RECHECK)
                              | ((User.photo_id.is_(None) | (User.photo_id == '')) & (User.photo_checked_at < now - RECHECK_EMPTY))) \
        .order_by(User.photo_checked_at.asc().nullsfirst()).limit(limit).all()
    n = 0
    for u in users:
        try:
            n += refresh(u)
        except Exception:
            db.session.rollback()
            logger.exception('Аватарка %s', u.id)
    return n
