"""Вход в мини-апп через подпись телеграма. Человек = его telegram id, других логинов нет."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import parse_qsl

from flask import request, jsonify, current_app, g

from app.models import db, User

INIT_DATA_MAX_AGE = timedelta(days=1)


def validate_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data))
    received = parsed.pop('hash', None)
    if not received:
        return None
    check = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
    secret = hmac.new(b'WebAppData', current_app.config['TELEGRAM_BOT_TOKEN'].encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), received):
        return None
    try:
        if datetime.utcnow() - datetime.utcfromtimestamp(int(parsed.get('auth_date', 0))) > INIT_DATA_MAX_AGE:
            return None
    except ValueError:
        return None
    return parsed


def _tg_id() -> int | None:
    if current_app.config.get('TESTING') and request.headers.get('X-Test-User'):
        return int(request.headers['X-Test-User'])
    parsed = validate_init_data(request.headers.get('X-Telegram-Init-Data', ''))
    if not parsed:
        return None
    try:
        return int(json.loads(parsed.get('user', '{}')).get('id'))
    except (TypeError, ValueError):
        return None


def user_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        tg_id = _tg_id()
        if not tg_id:
            return jsonify({'error': 'unauthorized'}), 401
        user = User.query.filter_by(tg_id=tg_id).first()
        if not user or not user.is_active:
            return jsonify({'error': 'not_registered'}), 403
        if not user.onboarded:
            return jsonify({'error': 'onboarding'}), 403
        if not user.last_seen_at or datetime.utcnow() - user.last_seen_at > timedelta(minutes=5):
            user.last_seen_at = datetime.utcnow()
            db.session.commit()
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def trainer_required(f):
    @wraps(f)
    @user_required
    def wrapper(*args, **kwargs):
        if not g.user.is_trainer:
            return jsonify({'error': 'forbidden'}), 403
        return f(*args, **kwargs)
    return wrapper
