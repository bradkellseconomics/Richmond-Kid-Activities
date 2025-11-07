from __future__ import annotations
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, Text, JSON, UniqueConstraint
from .db import Base


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # "schema_org" | "rss" | "ics" | "html"
    active: Mapped[int] = mapped_column(Integer, default=1)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(200), unique=True)  # fingerprint
    source_id: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), default="general")
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_dt: Mapped[str] = mapped_column(String(40))  # ISO
    end_dt: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tz: Mapped[str] = mapped_column(String(50), default="America/New_York")
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    registration_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")

    __table_args__ = (UniqueConstraint("uid", name="uq_event_uid"),)

