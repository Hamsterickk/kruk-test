"""Все личные данные привязаны к user_id. Чужие записи через API не достаются: каждый
запрос фильтрует по текущему пользователю, а тренер видит только спортсменов своего клуба."""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

ATHLETE, TRAINER, ADMIN = 'athlete', 'trainer', 'admin'


class Club(db.Model):
    __tablename__ = 'clubs'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    join_code = db.Column(db.String(32), unique=True, nullable=False)     # для спортсменов
    trainer_code = db.Column(db.String(32), unique=True, nullable=False)  # для тренеров


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    tg_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'))
    role = db.Column(db.String(16), default=ATHLETE, nullable=False)
    name = db.Column(db.String(80))
    username = db.Column(db.String(64))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime)
    # анкета
    onboarding_step = db.Column(db.String(24))  # шаг анкеты, None – пройдена
    sex = db.Column(db.String(1))
    age = db.Column(db.Integer)
    height_cm = db.Column(db.Integer)
    goal = db.Column(db.String(8))  # gain / cut / keep
    kcal_target = db.Column(db.Integer)
    protein_target = db.Column(db.Integer)
    morning_hour = db.Column(db.Integer, default=10)

    @property
    def is_trainer(self) -> bool:
        return self.role in (TRAINER, ADMIN)

    @property
    def onboarded(self) -> bool:
        return self.onboarding_step is None


class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))


class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    weekdays = db.Column(db.String(20), nullable=False)  # «0,2,4» – пн, ср, пт
    start_time = db.Column(db.String(5), nullable=False)  # «18:00»
    end_time = db.Column(db.String(5), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    @property
    def days(self) -> list[int]:
        return [int(d) for d in (self.weekdays or '').split(',') if d.strip().isdigit()]


class Membership(db.Model):
    """Спортсмен ходит в группу. Ставит и снимает тренер."""
    __tablename__ = 'memberships'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id'),)


class SessionCancel(db.Model):
    """Тренер отменил занятие группы в конкретный день."""
    __tablename__ = 'session_cancels'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(200))
    __table_args__ = (db.UniqueConstraint('group_id', 'on_date'),)


class SessionLead(db.Model):
    """Кто из тренеров ведёт занятие группы в конкретный день."""
    __tablename__ = 'session_leads'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    trainer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('group_id', 'on_date'),)


class Rsvp(db.Model):
    """Спортсмен заранее ответил: буду или не смогу."""
    __tablename__ = 'rsvp'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    going = db.Column(db.Boolean, nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id', 'on_date'),)


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    present = db.Column(db.Boolean, nullable=False)
    note = db.Column(db.String(500))   # что отрабатывал
    set_by = db.Column(db.String(8), default='self')  # self / trainer
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'group_id', 'on_date'),)


class Food(db.Model):
    """Продукт: user_id пустой – общая стартовая база, иначе личный продукт."""
    __tablename__ = 'foods'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    name = db.Column(db.String(120), nullable=False)
    kcal = db.Column(db.Float, nullable=False)
    protein = db.Column(db.Float, default=0)
    fat = db.Column(db.Float, default=0)
    carbs = db.Column(db.Float, default=0)
    portion = db.Column(db.Float)  # обычная порция, г
    priority = db.Column(db.Integer, default=0)  # 0 – брать первым, если подходит несколько
    keywords = db.Column(db.String(200), default='')  # другие слова для поиска


class Meal(db.Model):
    __tablename__ = 'meals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    on_date = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    grams = db.Column(db.Float, nullable=False)
    kcal = db.Column(db.Float, default=0)
    protein = db.Column(db.Float, default=0)
    fat = db.Column(db.Float, default=0)
    carbs = db.Column(db.Float, default=0)
    estimated = db.Column(db.Boolean, default=False)  # КБЖУ оценил ИИ
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class DayMetrics(db.Model):
    """Вес, сон и шаги за день – одна строка на человека и день."""
    __tablename__ = 'day_metrics'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    on_date = db.Column(db.Date, nullable=False)
    weight = db.Column(db.Float)
    sleep = db.Column(db.Float)
    steps = db.Column(db.Integer)
    __table_args__ = (db.UniqueConstraint('user_id', 'on_date'),)


class Goal(db.Model):
    """Цель: каждый день или разовая на дату. Ставит сам человек или тренер."""
    __tablename__ = 'goals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    daily = db.Column(db.Boolean, default=True)
    on_date = db.Column(db.Date)        # для разовой
    in_morning = db.Column(db.Boolean, default=True)  # показывать в утреннем сообщении
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GoalDone(db.Model):
    __tablename__ = 'goal_done'
    id = db.Column(db.Integer, primary_key=True)
    goal_id = db.Column(db.Integer, db.ForeignKey('goals.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    __table_args__ = (db.UniqueConstraint('goal_id', 'on_date'),)


class Message(db.Model):
    """Один чат на человека – тот же, что в телеграме."""
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # user / assistant
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AiUsage(db.Model):
    __tablename__ = 'ai_usage'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    on_date = db.Column(db.Date, nullable=False)
    requests = db.Column(db.Integer, default=0)
    tokens = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'on_date'),)


class SentMark(db.Model):
    """Что уже отправлено – чтобы напоминание не пришло дважды после перезапуска."""
    __tablename__ = 'sent_marks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    ref = db.Column(db.String(64), nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'kind', 'ref'),)


class Pending(db.Model):
    """Вопрос бота, ждущий кнопки: «запомнить продукт?»."""
    __tablename__ = 'pending'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(24), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
