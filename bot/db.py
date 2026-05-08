"""Модели БД и helpers на SQLAlchemy 2.0 async."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    requests: Mapped[list["Request"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )
    offers: Mapped[list["Offer"]] = relationship(
        back_populates="user", cascade="all,delete-orphan"
    )


class Request(Base):
    """Заявка пользователя (авто/запчасти/покупки)."""
    __tablename__ = "requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # car / parts / shop
    payload_json: Mapped[str] = mapped_column(Text)  # JSON-сериализация
    payment_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="requests")


class Offer(Base):
    """Офер (коммерческое предложение) от админа пользователю."""
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    price_rub: Mapped[int] = mapped_column(Integer)  # полная сумма в рублях
    # car / parts / shop — определяет правило предоплаты
    # (для car — 15% но не менее prepay_min_rub, для остальных — ровно 15%).
    kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="sent")
    # sent / accepted / paid_invoice / paid_sbp / declined
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="offers")


# --------------------------------------------------------------------------- #
# Engine / session helpers
# --------------------------------------------------------------------------- #
settings = get_settings()
settings.db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.db_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Создать таблицы, если отсутствуют, и применить простые миграции.

    Sqlite-миграции тут делаются «вручную» через PRAGMA table_info — идемпотентно.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # idempotent ALTER TABLE для уже существующих БД
        res = await conn.exec_driver_sql("PRAGMA table_info(offers)")
        existing = {row[1] for row in res.fetchall()}
        if "kind" not in existing:
            await conn.exec_driver_sql("ALTER TABLE offers ADD COLUMN kind VARCHAR(16)")


async def get_or_create_user(
    session: AsyncSession, tg_id: int, username: Optional[str]
) -> User:
    from sqlalchemy import select

    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(tg_id=tg_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif username and user.username != username:
        user.username = username
        await session.commit()
    return user
