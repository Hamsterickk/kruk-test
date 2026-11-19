import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_size': 5, 'max_overflow': 5}
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret')
    # аватарки из телеграма: кладёт бот, отдаёт сайт
    AVATAR_DIR = os.environ.get('AVATAR_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'avatars'))

    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    BOT_USERNAME = os.environ.get('BOT_USERNAME', 'test_kruk_team_bot')
    WEBAPP_URL = os.environ.get('WEBAPP_URL', '')
    ADMIN_TELEGRAM_ID = int(os.environ.get('ADMIN_TELEGRAM_ID', 0) or 0)

    GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
    GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
    # Бесплатный Groq: у каждой модели свой дневной лимит. Кончился у первой – берём следующую
    GROQ_MODELS = [m.strip() for m in os.environ.get(
        'GROQ_MODELS', 'llama-3.3-70b-versatile,openai/gpt-oss-20b,qwen/qwen3-32b').split(',') if m.strip()]
    # Сколько сообщений в день один человек может отдать ИИ. Записи скриптом лимит не тратят
    AI_DAILY_LIMIT = int(os.environ.get('AI_DAILY_LIMIT', 8))
