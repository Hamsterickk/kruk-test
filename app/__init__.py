import logging
import os
import time

# Клуб в Москве: «сегодня» и время напоминаний – московские
os.environ['TZ'] = 'Europe/Moscow'
time.tzset()

from flask import Flask  # noqa: E402

from app.config import Config  # noqa: E402
from app.models import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def create_app(config: dict | None = None):
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    db.init_app(app)

    from app.api.athlete import bp as athlete_bp
    from app.api.trainer import bp as trainer_bp
    app.register_blueprint(athlete_bp, url_prefix='/api')
    app.register_blueprint(trainer_bp, url_prefix='/api/trainer')

    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    @app.after_request
    def no_cache_html(resp):
        if resp.mimetype == 'text/html':
            resp.headers['Cache-Control'] = 'no-store'
        return resp

    return app
