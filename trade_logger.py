"""Pyonex persistence — SQLAlchemy models + helpers.

Phase 1 uses MetricsCache only (cron writes, Streamlit reads).
Trade model is scaffolded for Phase 2.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

DB_PATH = os.getenv("PYONEX_DB_PATH", "pyonex.db")
ENGINE_URL = f"sqlite:///{DB_PATH}"
_engine = create_engine(ENGINE_URL, future=True)


class Base(DeclarativeBase):
    pass


class MetricsCache(Base):
    __tablename__ = "metrics_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), index=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    price = Column(Float, nullable=False, default=0.0)
    score = Column(Float, nullable=False, default=0.0)
    direction = Column(String(16), nullable=False, default="Neutral")
    payload = Column(JSON, nullable=False, default=dict)


class Trade(Base):
    """Phase 2 — not used in Phase 1 but schema is stable."""
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), index=True, nullable=False)
    opened_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime(timezone=True), nullable=True)
    side = Column(String(8), nullable=False)
    entry = Column(Float, nullable=False)
    sl = Column(Float, nullable=True)
    tp1 = Column(Float, nullable=True)
    tp2 = Column(Float, nullable=True)
    size = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), default="open")
    notes = Column(String, default="")


def init_db() -> None:
    Base.metadata.create_all(_engine)


def upsert_metrics(symbol: str, price: float, score: float, direction: str, payload: dict) -> None:
    init_db()
    with Session(_engine, future=True) as s:
        row = MetricsCache(
            symbol=symbol,
            price=price,
            score=score,
            direction=direction,
            payload=json.loads(json.dumps(payload, default=str)),
        )
        s.add(row)
        s.commit()


def latest_metrics(symbol: str) -> MetricsCache | None:
    init_db()
    with Session(_engine, future=True) as s:
        stmt = select(MetricsCache).where(MetricsCache.symbol == symbol) \
                                    .order_by(MetricsCache.updated_at.desc()).limit(1)
        return s.execute(stmt).scalar_one_or_none()


def all_latest() -> list[MetricsCache]:
    """One row per symbol — the latest. Uses a grouped subquery."""
    init_db()
    with Session(_engine, future=True) as s:
        # simple path: fetch all, pick newest per symbol in Python (Phase 1 volume trivial)
        rows = s.execute(select(MetricsCache).order_by(MetricsCache.updated_at.desc())).scalars().all()
        seen: dict[str, MetricsCache] = {}
        for r in rows:
            seen.setdefault(r.symbol, r)
        return list(seen.values())
