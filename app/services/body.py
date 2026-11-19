"""Вес, сон, шаги: запись, разбор фраз скриптом и данные для графиков."""
import re
from datetime import date, timedelta

from app.models import db, DayMetrics

BACKFILL_DAYS = 6
NUM = r'(\d{1,3}(?:[.,]\d{1,2})?)'
DAY_RE = re.compile(r'(?<![а-яё])(позавчера|вчера)(?![а-яё])', re.I)
PAIR_RE = re.compile(rf'^\s*{NUM}\s+{NUM}\s*$')
WEIGHT_RE = re.compile(rf'(?:вес\w*\s*:?\s*{NUM}|{NUM}\s*кг)', re.I)
SLEEP_RE = re.compile(rf'(?:(?:сон|спал\w*|поспал\w*)\s*:?\s*{NUM}|{NUM}\s*(?:ч\b|час\w*)\s*(?:сна|спал\w*)?)', re.I)
STEPS_RE = re.compile(r'(?:шаг\w*\s*:?\s*(\d[\d\s]*(?:[.,]\d)?\s*(?:к|k|тыс\w*)?)|'
                      r'(\d[\d\s]*(?:[.,]\d)?\s*(?:к|k|тыс\w*)?)\s*шаг\w*)', re.I)
OTHER_WORDS_RE = re.compile(r'(съел|ел\b|выпил|трениров|цел|запомни|удали|\?)', re.I)


def metrics(user_id: int, day: date) -> DayMetrics:
    row = DayMetrics.query.filter_by(user_id=user_id, on_date=day).first()
    if not row:
        row = DayMetrics(user_id=user_id, on_date=day)
        db.session.add(row)
    return row


def peek(user_id: int, day: date):
    """Строка дня без создания: для чтения."""
    row = DayMetrics.query.filter_by(user_id=user_id, on_date=day).first()
    return row or DayMetrics(user_id=user_id, on_date=day)


def save(user_id: int, day: date, weight=None, sleep=None, steps=None) -> DayMetrics:
    row = metrics(user_id, day)
    if weight is not None:
        row.weight = round(float(weight), 1)
    if sleep is not None:
        row.sleep = round(float(sleep), 1)
    if steps is not None:
        row.steps = int(steps)
    db.session.commit()
    return row


def _f(v: str) -> float:
    return float(v.replace(',', '.'))


def parse_steps(raw: str) -> int | None:
    raw = (raw or '').lower().replace(' ', '')
    m = re.match(r'^(\d+(?:[.,]\d)?)(к|k|тыс\w*)?$', raw)
    if not m:
        return None
    value = float(m.group(1).replace(',', '.'))
    return int(value * 1000) if m.group(2) else int(value)


def parse(text: str) -> dict | None:
    """Фраза про вес, сон, шаги → {day, weight, sleep, steps}. None – не про это."""
    low = (text or '').lower().strip()
    if not low or len(low) > 80 or OTHER_WORDS_RE.search(low):
        return None
    day_word = DAY_RE.search(low)
    day = date.today() - timedelta(days=2 if day_word and day_word.group(1) == 'позавчера' else 1 if day_word else 0)
    rest = DAY_RE.sub(' ', low)
    out = {'day': day, 'weight': None, 'sleep': None, 'steps': None}
    pair = PAIR_RE.match(rest)
    if pair:
        w, s = _f(pair.group(1)), _f(pair.group(2))
        if 30 <= w <= 250 and 0 < s <= 16:
            out.update(weight=w, sleep=s)
            return out
        return None
    m = STEPS_RE.search(rest)
    if m:
        steps = parse_steps(m.group(1) or m.group(2))
        if steps and 100 <= steps <= 100000:
            out['steps'] = steps
        rest = rest[:m.start()] + ' ' + rest[m.end():]
    m = SLEEP_RE.search(rest)
    if m:
        s = _f(m.group(1) or m.group(2))
        if 0 < s <= 16:
            out['sleep'] = s
        rest = rest[:m.start()] + ' ' + rest[m.end():]
    m = WEIGHT_RE.search(rest)
    if m:
        w = _f(m.group(1) or m.group(2))
        if 30 <= w <= 250:
            out['weight'] = w
        rest = rest[:m.start()] + ' ' + rest[m.end():]
    # остались посторонние слова – это не простая запись, пусть разбирается ИИ
    if re.search(r'[а-яa-z]{3,}', re.sub(r'\b(и|а|был\w*|было|часов|часа|ч|сна|кг|по)\b', ' ', rest)):
        return None
    if out['weight'] is None and out['sleep'] is None and out['steps'] is None:
        return None
    return out


def apply_text(user_id: int, text: str) -> str | None:
    """Скриптом записать вес, сон, шаги. Ответ для чата или None."""
    data = parse(text)
    if not data:
        return None
    save(user_id, data['day'], data['weight'], data['sleep'], data['steps'])
    parts = []
    if data['weight'] is not None:
        parts.append(f"вес {data['weight']:g} кг")
    if data['sleep'] is not None:
        parts.append(f"сон {data['sleep']:g} ч")
    if data['steps'] is not None:
        parts.append(f"шаги {data['steps']}")
    when = '' if data['day'] == date.today() else f" за {data['day']:%d.%m}"
    return f"✅ Записал{when}: " + ', '.join(parts)


def week(user_id: int, offset: int = 0) -> list[dict]:
    """Неделя пн–вс: offset 0 – текущая, 1 – прошлая."""
    monday = date.today() - timedelta(days=date.today().weekday()) - timedelta(weeks=offset)
    days = [monday + timedelta(days=i) for i in range(7)]
    rows = {r.on_date: r for r in DayMetrics.query.filter(
        DayMetrics.user_id == user_id, DayMetrics.on_date >= days[0], DayMetrics.on_date <= days[-1]).all()}
    return [{'date': d.isoformat(), 'weight': getattr(rows.get(d), 'weight', None),
             'sleep': getattr(rows.get(d), 'sleep', None), 'steps': getattr(rows.get(d), 'steps', None),
             'future': d > date.today()} for d in days]


def summary(user_id: int, days: int = 7) -> dict:
    start = date.today() - timedelta(days=days - 1)
    rows = DayMetrics.query.filter(DayMetrics.user_id == user_id, DayMetrics.on_date >= start).order_by(DayMetrics.on_date).all()
    weights = [r.weight for r in rows if r.weight]
    sleeps = [r.sleep for r in rows if r.sleep]
    steps = [r.steps for r in rows if r.steps]
    last_weight = DayMetrics.query.filter(DayMetrics.user_id == user_id, DayMetrics.weight.isnot(None)) \
        .order_by(DayMetrics.on_date.desc()).first()
    return {
        'weight': last_weight.weight if last_weight else None,
        'weight_date': last_weight.on_date.isoformat() if last_weight else None,
        'weight_change': round(weights[-1] - weights[0], 1) if len(weights) > 1 else None,
        'sleep_avg': round(sum(sleeps) / len(sleeps), 1) if sleeps else None,
        'steps_avg': round(sum(steps) / len(steps)) if steps else None,
    }
