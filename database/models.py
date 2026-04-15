import json
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, Text, Float, Date, BigInteger, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), nullable=True)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=True)

    # Progression
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    sc_balance = Column(Integer, default=0)
    trust_rating = Column(Integer, default=100)  # 0-100
    branch = Column(String(20), nullable=True)   # 'butcher' | 'vegan'

    # Subscription
    is_subscribed = Column(Boolean, default=False)
    subscription_end = Column(DateTime, nullable=True)
    subscription_blocked = Column(Boolean, default=False)

    # Social
    referral_code = Column(String(12), unique=True, nullable=False)
    mentor_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    subscriptions = relationship(
        "Subscription", back_populates="user", foreign_keys="Subscription.user_id"
    )
    sc_transactions = relationship("SCTransaction", back_populates="user")
    photos = relationship("DailyPhoto", back_populates="user")
    quiz_attempts = relationship("UserQuizAttempt", back_populates="user")
    rewards = relationship("UserReward", back_populates="user")
    lottery_tickets = relationship("LotteryTicket", back_populates="user")
    referrals_made = relationship(
        "Referral", back_populates="referrer", foreign_keys="Referral.referrer_id"
    )
    referral_record = relationship(
        "Referral", back_populates="referred",
        foreign_keys="Referral.referred_id", uselist=False,
    )
    faction = relationship("UserFaction", back_populates="user", uselist=False)
    mentor = relationship("User", remote_side="User.id", foreign_keys=[mentor_id])


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_date = Column(DateTime, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=False)
    price_paid = Column(Float, default=0.0)
    sc_paid = Column(Integer, default=0)
    status = Column(String(20), default="active")  # active|expired|failed|blocked
    renewal_attempts = Column(Integer, default=0)
    last_attempt = Column(DateTime, nullable=True)
    telegram_payment_id = Column(String(256), nullable=True)

    user = relationship("User", back_populates="subscriptions", foreign_keys=[user_id])


class SCTransaction(Base):
    __tablename__ = "sc_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)        # + credit, - debit
    description = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sc_transactions")


class DailyPhoto(Base):
    __tablename__ = "daily_photos"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    photo_file_id = Column(String(256), nullable=False)
    photo_taken_at = Column(DateTime, nullable=True)   # from EXIF
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    # pending | p2p_pending | approved | rejected | control (fake inserted by admin)
    status = Column(String(20), default="pending")
    p2p_approve_count = Column(Integer, default=0)
    p2p_reject_count = Column(Integer, default=0)

    user = relationship("User", back_populates="photos")
    reviews = relationship("P2PReview", back_populates="photo")


class P2PReview(Base):
    __tablename__ = "p2p_reviews"

    id = Column(Integer, primary_key=True)
    photo_id = Column(Integer, ForeignKey("daily_photos.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_approved = Column(Boolean, nullable=True)  # None = assigned but not yet voted
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("photo_id", "reviewer_id"),)

    photo = relationship("DailyPhoto", back_populates="reviews")
    reviewer = relationship("User")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    _options = Column("options", Text, nullable=False)   # JSON list[str]
    correct_index = Column(Integer, nullable=False)      # 0-3
    scheduled_date = Column(Date, nullable=True)

    @property
    def options(self) -> list[str]:
        return json.loads(self._options)

    @options.setter
    def options(self, value: list[str]) -> None:
        self._options = json.dumps(value, ensure_ascii=False)

    attempts = relationship("UserQuizAttempt", back_populates="question")


class UserQuizAttempt(Base):
    __tablename__ = "user_quiz_attempts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("quiz_questions.id"), nullable=False)
    date = Column(Date, default=date.today)
    is_correct = Column(Boolean, default=False)
    sc_spent = Column(Integer, default=0)
    attempts = Column(Integer, default=1)

    __table_args__ = (UniqueConstraint("user_id", "question_id"),)

    user = relationship("User", back_populates="quiz_attempts")
    question = relationship("QuizQuestion", back_populates="attempts")


class BattlePassLevel(Base):
    __tablename__ = "battle_pass_levels"

    level = Column(Integer, primary_key=True)
    xp_required = Column(Integer, nullable=False)   # cumulative XP to reach this level
    reward_type = Column(String(20), nullable=False) # sc|guide|ticket
    reward_amount = Column(Integer, default=0)
    reward_description = Column(String(256), nullable=False)


class UserReward(Base):
    __tablename__ = "user_rewards"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level = Column(Integer, nullable=False)
    claimed = Column(Boolean, default=False)
    claimed_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "level"),)

    user = relationship("User", back_populates="rewards")


class LotteryTicket(Base):
    __tablename__ = "lottery_tickets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticket_number = Column(String(36), unique=True, nullable=False)  # UUID4
    lottery_month = Column(String(7), nullable=False)                # YYYY-MM
    is_winner = Column(Boolean, default=False)

    user = relationship("User", back_populates="lottery_tickets")


class AdminSetting(Base):
    __tablename__ = "admin_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)


class ControlPhoto(Base):
    __tablename__ = "control_photos"

    id = Column(Integer, primary_key=True)
    photo_file_id = Column(String(256), nullable=False)
    is_fake = Column(Boolean, default=True)
    added_by_admin = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    referred_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    referrer = relationship(
        "User", back_populates="referrals_made", foreign_keys=[referrer_id]
    )
    referred = relationship(
        "User", back_populates="referral_record", foreign_keys=[referred_id]
    )


class Faction(Base):
    __tablename__ = "factions"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    icon_emoji = Column(String(8), nullable=True)

    members = relationship("UserFaction", back_populates="faction")


class UserFaction(Base):
    __tablename__ = "user_factions"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    faction_id = Column(Integer, ForeignKey("factions.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="faction")
    faction = relationship("Faction", back_populates="members")
