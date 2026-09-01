from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    unionid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str] = mapped_column(String(40), default="好学的小万")
    completed_games: Mapped[int] = mapped_column(Integer, default=0)
    learned_points: Mapped[int] = mapped_column(Integer, default=0)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    vibration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class LearningSession(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    hearts: Mapped[int] = mapped_column(Integer, default=3)
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_type: Mapped[str] = mapped_column(
        String(20),
        default="keyword",
        server_default="keyword",
    )
    source_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sources: Mapped[list[dict]] = mapped_column(
        JSON,
        default=list,
    )
    generation_mode: Mapped[str] = mapped_column(String(20), default="legacy", server_default="legacy")
    verification_notice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    basic_fallback_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_sessions_user_status", "user_id", "status"),
        UniqueConstraint("basic_fallback_id", name="uq_sessions_basic_fallback_id"),
    )


class Level(Base):
    __tablename__ = "levels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(40))
    intro: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    correct_option: Mapped[int] = mapped_column(Integer)
    wrong_explanation: Mapped[str] = mapped_column(Text)
    praise: Mapped[str] = mapped_column(Text)
    takeaway: Mapped[str] = mapped_column(Text)
    source_ids: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
    )

    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_level_session_position"),
    )


class AnswerAttempt(Base):
    __tablename__ = "answer_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    level_position: Mapped[int] = mapped_column(Integer)
    selected_option: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    hearts_after: Mapped[int] = mapped_column(Integer)
    response_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviveEvent(Base):
    __tablename__ = "revive_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    method: Mapped[str] = mapped_column(String(20))
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistToken(Base):
    __tablename__ = "assist_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20), default="active")
    assisted_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BattleRoom(Base):
    __tablename__ = "battle_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    host_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(80))
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="generating",
        server_default="generating",
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BattleParticipant(Base):
    __tablename__ = "battle_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("battle_rooms.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(
        String(12),
        default="joined",
        server_default="joined",
    )
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    total_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_battle_participant_room_user"),
    )


class BattleAnswer(Base):
    __tablename__ = "battle_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    room_id: Mapped[str] = mapped_column(
        ForeignKey("battle_rooms.id", ondelete="CASCADE"),
        index=True,
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("battle_participants.id", ondelete="CASCADE"),
        index=True,
    )
    level_position: Mapped[int] = mapped_column(Integer)
    selected_option: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "level_position",
            name="uq_battle_answer_participant_level",
        ),
    )
