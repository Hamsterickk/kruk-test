"""Бот и напоминания. Запуск: .venv/bin/python bot_run.py"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import create_app
from app.bot import handlers

flask_app = create_app()


async def post_init(application):
    await handlers.setup_menu(application)
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
    scheduler.add_job(handlers.tick_job, 'interval', seconds=60, id='tick', max_instances=1, coalesce=True)
    scheduler.start()
    application.bot_data['scheduler'] = scheduler


if __name__ == '__main__':
    app = handlers.build(flask_app)
    app.post_init = post_init
    app.run_polling(drop_pending_updates=False)
