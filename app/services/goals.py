"""Цели дня: ежедневные и разовые. Ставит сам человек или тренер."""
from datetime import date

from app.models import db, Goal, GoalDone
from app.services.foods import stems


def for_day(user_id: int, day: date | None = None) -> list[Goal]:
    day = day or date.today()
    rows = Goal.query.filter_by(user_id=user_id, is_active=True).order_by(Goal.created_at).all()
    return [g for g in rows if g.daily or g.on_date == day]


def done_ids(goal_ids: list[int], day: date | None = None) -> set[int]:
    if not goal_ids:
        return set()
    day = day or date.today()
    return {d.goal_id for d in GoalDone.query.filter(GoalDone.goal_id.in_(goal_ids), GoalDone.on_date == day).all()}


def as_json(user_id: int, day: date | None = None) -> list[dict]:
    goals = for_day(user_id, day)
    done = done_ids([g.id for g in goals], day)
    return [{'id': g.id, 'title': g.title, 'daily': g.daily, 'done': g.id in done,
             'by_trainer': bool(g.created_by and g.created_by != user_id)} for g in goals]


def add(user_id: int, title: str, daily: bool = True, created_by: int | None = None,
        on_date: date | None = None) -> Goal:
    goal = Goal(user_id=user_id, title=title.strip()[:200], daily=daily,
                on_date=None if daily else (on_date or date.today()), created_by=created_by or user_id)
    db.session.add(goal)
    db.session.commit()
    return goal


def set_done(goal: Goal, done: bool, day: date | None = None):
    day = day or date.today()
    row = GoalDone.query.filter_by(goal_id=goal.id, on_date=day).first()
    if done and not row:
        db.session.add(GoalDone(goal_id=goal.id, on_date=day))
    elif not done and row:
        db.session.delete(row)
    db.session.commit()


def remove(goal: Goal):
    goal.is_active = False
    db.session.commit()


def find(user_id: int, title: str) -> Goal | None:
    """Цель по словам из сообщения: «сделал зарядку» → «Зарядка 10 минут»."""
    q = set(stems(title))
    best, best_score = None, 0
    for g in for_day(user_id):
        score = len(q & set(stems(g.title)))
        if score > best_score:
            best, best_score = g, score
    return best


def progress(user_id: int, day: date | None = None) -> tuple[int, int]:
    goals = for_day(user_id, day)
    return len(done_ids([g.id for g in goals], day)), len(goals)
