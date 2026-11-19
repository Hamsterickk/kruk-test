"""Отправка в телеграм обычным HTTP-запросом. Так пишут и мини-апп (тренер поставил
группу – спортсмену сразу сообщение), и напоминания."""
import html
import logging
import re

import requests
from flask import current_app

logger = logging.getLogger(__name__)
MAX_LEN = 3900


def md_to_html(text: str) -> str:
    """Ответы в markdown, телеграм понимает HTML."""
    lines = []
    for line in (text or '').split('\n'):
        stripped = line.lstrip()
        heading = re.match(r'^#{1,6}\s+(.*)', stripped)
        if heading:
            line = f"**{heading.group(1).strip('*')}**"
        elif re.match(r'^[-*]\s+', stripped):
            line = '• ' + re.sub(r'^[-*]\s+', '', stripped)
        lines.append(line)
    t = html.escape('\n'.join(lines), quote=False)
    t = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'(?<![\w*])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', t)
    t = re.sub(r'(?<!\w)_(?![\s_])([^_\n]+?)(?<!\s)_(?!\w)', r'<i>\1</i>', t)
    return t


def buttons(rows: list[list[tuple[str, str]]]) -> dict:
    """[[('Был', 'att:1:2026-11-20:1')]] → inline_keyboard."""
    return {'inline_keyboard': [[{'text': t, 'callback_data': d} for t, d in row] for row in rows]}


def webapp_button(text: str = 'Открыть приложение') -> dict | None:
    url = current_app.config.get('WEBAPP_URL')
    return {'inline_keyboard': [[{'text': text, 'web_app': {'url': url}}]]} if url else None


def send(tg_id: int, text: str, markup: dict | None = None, markdown: bool = True) -> bool:
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.warning('Нет токена бота, сообщение не отправлено')
        return False
    body = {'chat_id': tg_id, 'text': md_to_html(text)[:MAX_LEN] if markdown else text[:MAX_LEN],
            'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if markup:
        body['reply_markup'] = markup
    try:
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json=body, timeout=8)
        if r.status_code != 200:
            logger.warning('Телеграм не принял сообщение для %s: %s', tg_id, r.text[:300])
            return False
        return True
    except requests.RequestException:
        logger.warning('Телеграм недоступен', exc_info=True)
        return False
