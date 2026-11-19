"""Телеграм-бот: вход по приглашению, анкета, один чат и кнопки. Всё, что трогает базу,
выполняется в отдельном потоке внутри контекста Flask."""
import asyncio
import logging
from datetime import date, datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from app.models import db, User, Club, Message, AiUsage, Goal, ATHLETE, TRAINER, ADMIN
from app.services import chat, profile, goals, reminders, club, avatars
from app.services.tg import md_to_html, send
from app.services.club import new_code

logger = logging.getLogger(__name__)
INVITE_ONLY = ('Это тестовый бот клуба Kruk Team. Вход только по приглашению – попроси ссылку у тренера.')


class Ctx:
    flask_app = None


async def run(fn, *args):
    """Синхронную работу с базой – в поток, внутри контекста приложения."""
    def wrapped():
        with Ctx.flask_app.app_context():
            try:
                return fn(*args)
            finally:
                db.session.remove()
    return await asyncio.to_thread(wrapped)


def _kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows]) if rows else None


def _app_kb(text='Открыть приложение'):
    url = Ctx.flask_app.config.get('WEBAPP_URL')
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, web_app=WebAppInfo(url=url))]]) if url else None


def _markup_from_dict(markup: dict | None):
    if not markup:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b['text'], callback_data=b['callback_data']) for b in row]
                                 for row in markup.get('inline_keyboard', [])])


async def _reply(update: Update, text: str, markup=None):
    msg = update.effective_message
    try:
        await msg.reply_text(md_to_html(text)[:3900], parse_mode=ParseMode.HTML, reply_markup=markup,
                             disable_web_page_preview=True)
    except BadRequest:
        await msg.reply_text(text[:3900], reply_markup=markup)


# ===== АНКЕТА =====

def question(user_id: int) -> tuple[str, list]:
    u = db.session.get(User, user_id)
    step = u.onboarding_step
    rows = []
    if step == 'name' and u.name:
        rows = [[(f"Оставить: {u.name}"[:40], 'ob:name_keep')]]
    elif step == 'sex':
        rows = [[('Мужской', 'ob:sex:m'), ('Женский', 'ob:sex:f')]]
    if u.is_trainer:
        rows.append([('Пропустить анкету', 'ob:skip')])
    n = profile.STEPS.index(step) + 1
    return f"Анкета {n}/{len(profile.STEPS)}. {profile.QUESTIONS[step]}", rows


def finish_text(user_id: int) -> str:
    u = db.session.get(User, user_id)
    lines = ['Готово 🔥', profile.norm_text(u), '']
    if u.role == ATHLETE:
        lines.append('Группы и расписание тебе поставит тренер – я сразу напишу.')
    else:
        lines.append('Ты тренер: в приложении есть вкладка «Тренер» – спортсмены, группы, посещаемость.')
    lines += ['', chat.HELP]
    return '\n'.join(lines)


def notify_trainers_new(user_id: int):
    u = db.session.get(User, user_id)
    if u.role != ATHLETE:
        return
    trainers = User.query.filter(User.club_id == u.club_id, User.role == TRAINER, User.is_active == True).all()  # noqa: E712
    for t in trainers:
        send(t.tg_id, f"👋 Новый спортсмен: {u.name}. Поставь ему группы в приложении, вкладка «Тренер».")


def use_code(club, code: str | None):
    """Ссылка одноразовая: по ней вошли – выдаём клубу новую, старая больше не пускает."""
    if not club or not code:
        return
    if club.join_code == code:
        club.join_code = new_code()
    elif club.trainer_code == code:
        club.trainer_code = new_code()


def register(tg_id: int, first_name: str, username: str | None, code: str | None) -> dict:
    """Вход по /start. {'status': new|exists|inactive|invite, 'user_id'}"""
    admin_id = Ctx.flask_app.config['ADMIN_TELEGRAM_ID']
    user = User.query.filter_by(tg_id=tg_id).first()
    club = None
    role = None
    if code:
        club = Club.query.filter_by(join_code=code).first()
        role = ATHLETE if club else None
        if not club:
            club = Club.query.filter_by(trainer_code=code).first()
            role = TRAINER if club else None
    if tg_id == admin_id:
        club = club or Club.query.order_by(Club.id).first()
        role = ADMIN
    if user:
        changed = False
        if club and (not user.is_active or user.club_id != club.id):
            user.is_active, user.club_id = True, club.id
            changed = True
        if role and user.role != role and (role == ADMIN or (role == TRAINER and user.role == ATHLETE)):
            user.role = role
            changed = True
        if changed:
            use_code(club, code)
        db.session.commit()
        if not user.is_active:
            return {'status': 'inactive', 'user_id': user.id}
        return {'status': 'exists', 'user_id': user.id}
    if not club:
        return {'status': 'invite'}
    user = User(tg_id=tg_id, club_id=club.id, role=role, name=(first_name or '')[:40] or None,
                username=username, onboarding_step='name')
    db.session.add(user)
    use_code(club, code)
    db.session.commit()
    return {'status': 'new', 'user_id': user.id}


def _refresh_avatar(user_id: int):
    """На /start аватарку берём сразу, не ждём ночной проверки."""
    if Ctx.flask_app.config.get('TESTING'):
        return
    try:
        avatars.refresh(db.session.get(User, user_id))
    except Exception:
        db.session.rollback()
        logger.warning('Аватарка не обновилась', exc_info=True)


def user_state(tg_id: int) -> dict | None:
    u = User.query.filter_by(tg_id=tg_id).first()
    if not u:
        return None
    return {'id': u.id, 'active': u.is_active, 'step': u.onboarding_step}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    code = context.args[0] if context.args else None
    res = await run(register, tg.id, tg.first_name, tg.username, code)
    if res['status'] == 'invite':
        await _reply(update, INVITE_ONLY)
        return
    if res['status'] == 'inactive':
        await _reply(update, 'Тренер убрал тебя из клуба. Чтобы вернуться – попроси у него новую ссылку.')
        return
    state = await run(user_state, tg.id)
    await run(_refresh_avatar, state['id'])
    if state['step']:
        if res['status'] == 'new':
            await _reply(update, 'Привет! Это тестовый бот Kruk Team: питание, вес, сон, шаги, цели и тренировки клуба. '
                                 'Сначала короткая анкета – 5 вопросов, по ней посчитаю норму калорий.')
        text, rows = await run(question, state['id'])
        await _reply(update, text, _kb(rows))
        return
    await _reply(update, 'На месте 👊 Пиши, что съел, вес, сон, шаги – или открой приложение.', _app_kb())


async def _after_answer(update: Update, user_id: int):
    state = await run(lambda: db.session.get(User, user_id).onboarding_step)
    if state:
        text, rows = await run(question, user_id)
        await _reply(update, text, _kb(rows))
        return
    await _reply(update, await run(finish_text, user_id), _app_kb())
    await run(notify_trainers_new, user_id)


def _answer(user_id: int, value: str) -> str | None:
    return profile.answer(db.session.get(User, user_id), value)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg = update.effective_user
    state = await run(user_state, tg.id)
    if not state:
        await _reply(update, INVITE_ONLY)
        return
    if not state['active']:
        await _reply(update, 'Тренер убрал тебя из клуба. Чтобы вернуться – попроси у него новую ссылку.')
        return
    text = update.effective_message.text or ''
    if state['step']:
        err = await run(_answer, state['id'], text)
        if err:
            q, rows = await run(question, state['id'])
            await _reply(update, f"{err}\n\n{q}", _kb(rows))
            return
        await _after_answer(update, state['id'])
        return
    stop = asyncio.Event()
    typing = asyncio.create_task(_typing(context.bot, update.effective_chat.id, stop))
    try:
        out = await run(_handle, state['id'], text)
    finally:
        stop.set()
        await typing
    await _reply(update, out['text'], _markup_from_dict(out.get('markup')))


async def _typing(bot, chat_id: int, stop: asyncio.Event):
    """«печатает…» держится 5 секунд – обновляем, пока ИИ думает."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), 4.5)
        except asyncio.TimeoutError:
            pass


def _handle(user_id: int, text: str) -> dict:
    u = db.session.get(User, user_id)
    u.last_seen_at = datetime.utcnow()
    db.session.commit()
    return chat.handle(u, text)


async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, 'Я понимаю только текст. Напиши словами, что съел или что нужно.')


def _callback(user_id: int, data: str, rows: list) -> dict:
    u = db.session.get(User, user_id)
    out = {'text': chat.callback(u, data)}
    if data.split(':')[0] in ('goal', 'rsvp') and rows:
        out['rows'] = refresh_rows(u, rows)  # кнопки остаются, на них видно, что выбрано
    else:
        chat.save(u.id, 'assistant', out['text'])
    return out


def refresh_rows(u: User, rows: list) -> list:
    """Те же кнопки сообщения с новыми подписями: цели – ✅, «буду / не смогу» – выбранное."""
    out = []
    for row in rows:
        new = []
        for text, data in row:
            kind, _, rest = data.partition(':')
            if kind == 'goal':
                g = Goal.query.filter_by(id=int(rest or 0), user_id=u.id, is_active=True).first()
                if not g:
                    continue
                text = ('✅ ' if g.id in goals.done_ids([g.id]) else '▫️ ') + g.title[:40]
            elif kind == 'rsvp':
                gid, day, val = rest.split(':')
                day = date.fromisoformat(day)
                cur = club.rsvp_map(u.id, day, day).get((int(gid), day))
                text = reminders.rsvp_row(int(gid), day, cur)[0 if val == '1' else 1][0]
            new.append((text, data))
        if new:
            out.append(new)
    return out


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    tg = update.effective_user
    state = await run(user_state, tg.id)
    if not state or not state['active']:
        await q.answer('Нет доступа')
        return
    data = q.data or ''
    if data.startswith('ob:'):
        await q.answer()
        if not state['step']:
            return
        if data == 'ob:skip':
            await run(lambda: profile.skip(db.session.get(User, state['id'])) if db.session.get(User, state['id']).is_trainer else None)
        else:
            value = {'ob:name_keep': None}.get(data)
            if data == 'ob:name_keep':
                value = await run(lambda: db.session.get(User, state['id']).name)
            elif data.startswith('ob:sex:'):
                value = data.split(':')[2]
            err = await run(_answer, state['id'], value or '')
            if err:
                await _reply(update, err)
                return
        try:
            await q.edit_message_reply_markup(None)
        except BadRequest:
            pass
        await _after_answer(update, state['id'])
        return
    if state['step']:
        await q.answer('Сначала закончи анкету')
        return
    rows = [[(b.text, b.callback_data) for b in row if b.callback_data]
            for row in (q.message.reply_markup.inline_keyboard if q.message and q.message.reply_markup else [])]
    out = await run(_callback, state['id'], data, rows)
    if 'rows' in out:
        await q.answer(out['text'][:190])
        try:
            await q.edit_message_reply_markup(_kb(out['rows']))
        except BadRequest:
            pass
        return
    await q.answer()
    try:
        await q.edit_message_reply_markup(None)
    except BadRequest:
        pass
    await _reply(update, out['text'])


async def cmd_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, 'Приложение:', _app_kb())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, chat.HELP)


def admin_stats(tg_id: int) -> str | None:
    u = User.query.filter_by(tg_id=tg_id).first()
    if not u or u.role != ADMIN:
        return None
    users = User.query.filter_by(is_active=True).all()
    week = datetime.utcnow() - timedelta(days=7)
    day = datetime.utcnow() - timedelta(days=1)
    active7 = sum(1 for x in users if x.last_seen_at and x.last_seen_at >= week)
    active1 = sum(1 for x in users if x.last_seen_at and x.last_seen_at >= day)
    msgs = Message.query.filter(Message.role == 'user', Message.created_at >= day).count()
    ai = AiUsage.query.filter_by(on_date=date.today()).all()
    c = db.session.get(Club, u.club_id)
    name = Ctx.flask_app.config['BOT_USERNAME']
    return (f"Пользователей: {len(users)}, из них анкету прошли {sum(1 for x in users if x.onboarded)}\n"
            f"Активны за сутки: {active1}, за 7 дней: {active7}\n"
            f"Сообщений за сутки: {msgs}\n"
            f"ИИ сегодня: {sum(a.requests for a in ai)} запросов, {sum(a.tokens for a in ai)} токенов\n\n"
            f"Ссылка спортсменам: https://t.me/{name}?start={c.join_code}\n"
            f"Ссылка тренерам: https://t.me/{name}?start={c.trainer_code}")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await run(admin_stats, update.effective_user.id)
    if text:
        await update.effective_message.reply_text(text, disable_web_page_preview=True)


# ===== ЗАПУСК =====

async def tick_job():
    try:
        await run(reminders.tick)
    except Exception:
        logger.exception('Напоминания упали')


async def setup_menu(app: Application):
    url = Ctx.flask_app.config.get('WEBAPP_URL')
    if url:
        try:
            await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Приложение', web_app=WebAppInfo(url=url)))
        except Exception:
            logger.warning('Не получилось поставить кнопку приложения', exc_info=True)


def build(flask_app) -> Application:
    Ctx.flask_app = flask_app
    application = Application.builder().token(flask_app.config['TELEGRAM_BOT_TOKEN']).post_init(setup_menu).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('app', cmd_app))
    application.add_handler(CommandHandler('help', cmd_help))
    application.add_handler(CommandHandler('admin', cmd_admin))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(~filters.TEXT & ~filters.COMMAND, on_other))
    return application
