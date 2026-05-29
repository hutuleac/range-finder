"""Pyonex persistence — SQLAlchemy models + helpers.

Phase 1: MetricsCache (cron writes, Streamlit reads).
Phase 2: SimulatedTrade + GridFill (grid bot simulation, ./trades.db).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

DB_PATH = os.getenv("PYONEX_DB_PATH", os.path.join(tempfile.gettempdir(), "pyonex.db"))
ENGINE_URL = f"sqlite:///{DB_PATH}"
_engine = create_engine(ENGINE_URL, future=True)


class Base(DeclarativeBase):
    pass


class MetricsCache(Base):
    __tablename__ = "metrics_cache"
    __table_args__ = (UniqueConstraint("symbol", name="uq_metrics_symbol"),)
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


class UserPair(Base):
    """User-added custom trading pair, persisted across sessions."""
    __tablename__ = "user_pairs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), unique=True, nullable=False, index=True)
    pair_type = Column(String(8), nullable=False, default="crypto")  # "crypto" | "stock"
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    Base.metadata.create_all(_engine)


# ── Trades DB (persists at ./trades.db, separate from metrics cache) ──────────
_TRADES_DB_PATH = os.getenv(
    "TRADES_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db"),
)
_trades_engine = create_engine(f"sqlite:///{_TRADES_DB_PATH}", future=True)


class TradesBase(DeclarativeBase):
    pass


class SimulatedTrade(TradesBase):
    __tablename__ = "simulated_trades"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    symbol       = Column(String(32), index=True, nullable=False)
    opened_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    closed_at    = Column(DateTime(timezone=True), nullable=True)
    status       = Column(String(16), default="ACTIVE", nullable=False)  # ACTIVE / CLOSED / SL_HIT / TP_HIT
    close_reason = Column(String(64), nullable=True)
    close_price  = Column(Float, nullable=True)

    # Grid parameters — snapshot at open
    entry_price = Column(Float, nullable=False)
    range_low   = Column(Float, nullable=False)
    range_high  = Column(Float, nullable=False)
    num_grids   = Column(Integer, nullable=False)
    direction   = Column(String(16), nullable=False, default="Neutral")
    grid_mode   = Column(String(16), nullable=False, default="Arithmetic")

    grid_score  = Column(Float, nullable=False, default=0.0)
    setup_score = Column(Float, nullable=True)

    stop_loss   = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    capital     = Column(Float, nullable=True)
    profile     = Column(String(16), nullable=False, default="moderate")

    # Simulation state
    last_simulated_at  = Column(DateTime(timezone=True), nullable=True)
    last_candle_ts     = Column(Float, nullable=True)   # epoch ms of last processed candle
    last_candle_close  = Column(Float, nullable=True)   # close price of last processed candle
    inventory          = Column(JSON, default=list)     # list of int level-indices currently held

    snapshot = Column(JSON, default=dict)   # full Range Finder payload at open


class GridFill(TradesBase):
    __tablename__ = "grid_fills"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    trade_id     = Column(Integer, nullable=False, index=True)
    filled_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    candle_ts    = Column(Float, nullable=False)    # epoch ms of the triggering candle
    action       = Column(String(8), nullable=False)  # BUY / SELL
    level_idx    = Column(Integer, nullable=True)   # index in the grid levels array
    level        = Column(Float, nullable=False)    # price level
    paired_level = Column(Float, nullable=True)     # SELL only: the buy level it closed
    pnl_pct      = Column(Float, nullable=True)     # net % for this cycle (after fees)
    pnl_usd      = Column(Float, nullable=True)     # dollar P&L if capital was provided


def init_trades_db() -> None:
    TradesBase.metadata.create_all(_trades_engine)


# ── Helpers — SimulatedTrade ────────────────────────────────────────────────────

def create_simulated_trade(trade: SimulatedTrade) -> int:
    with Session(_trades_engine) as s:
        s.add(trade)
        s.commit()
        s.refresh(trade)
        return trade.id


def get_simulated_trade(trade_id: int) -> SimulatedTrade | None:
    with Session(_trades_engine) as s:
        return s.get(SimulatedTrade, trade_id)


def get_active_trades() -> list[SimulatedTrade]:
    with Session(_trades_engine) as s:
        return s.execute(
            select(SimulatedTrade)
            .where(SimulatedTrade.status == "ACTIVE")
            .order_by(SimulatedTrade.opened_at.desc())
        ).scalars().all()


def get_all_simulated_trades() -> list[SimulatedTrade]:
    with Session(_trades_engine) as s:
        return s.execute(
            select(SimulatedTrade).order_by(SimulatedTrade.opened_at.desc())
        ).scalars().all()


def get_trade_fills(trade_id: int) -> list[GridFill]:
    with Session(_trades_engine) as s:
        return s.execute(
            select(GridFill)
            .where(GridFill.trade_id == trade_id)
            .order_by(GridFill.candle_ts)
        ).scalars().all()


def save_simulation_update(
    trade_id: int,
    inventory: list[int],
    last_candle_ts: float,
    last_candle_close: float,
    fills: list[dict],
    new_status: str = "ACTIVE",
    close_reason: str | None = None,
    close_price: float | None = None,
) -> None:
    """Atomically persist simulation state + new fills."""
    now = datetime.now(timezone.utc)
    with Session(_trades_engine) as s:
        trade = s.get(SimulatedTrade, trade_id)
        if trade is None:
            return
        trade.inventory = list(inventory)
        trade.last_candle_ts = last_candle_ts
        trade.last_candle_close = last_candle_close
        trade.last_simulated_at = now
        if new_status != "ACTIVE":
            trade.status = new_status
            trade.close_reason = close_reason
            trade.close_price = close_price
            trade.closed_at = now
        for f in fills:
            s.add(GridFill(
                trade_id=trade_id,
                filled_at=now,
                candle_ts=f["candle_ts"],
                action=f["action"],
                level_idx=f.get("level_idx"),
                level=f["level"],
                paired_level=f.get("paired_level"),
                pnl_pct=f.get("pnl_pct"),
                pnl_usd=f.get("pnl_usd"),
            ))
        s.commit()


def close_simulated_trade(trade_id: int, reason: str, price: float, status: str = "CLOSED") -> None:
    now = datetime.now(timezone.utc)
    with Session(_trades_engine) as s:
        trade = s.get(SimulatedTrade, trade_id)
        if trade is None:
            return
        trade.status = status
        trade.close_reason = reason
        trade.close_price = price
        trade.closed_at = now
        s.commit()


# Initialise schemas once at import time — no per-call overhead.
init_db()
init_trades_db()


def upsert_metrics(symbol: str, price: float, score: float, direction: str, payload: dict) -> None:
    with Session(_engine, future=True) as s:
        row = s.execute(
            select(MetricsCache).where(MetricsCache.symbol == symbol)
            .order_by(MetricsCache.updated_at.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = MetricsCache(symbol=symbol)
            s.add(row)
        row.price = price
        row.score = score
        row.direction = direction
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)
        s.commit()


def latest_metrics(symbol: str) -> MetricsCache | None:
    with Session(_engine, future=True) as s:
        return s.execute(
            select(MetricsCache).where(MetricsCache.symbol == symbol)
            .order_by(MetricsCache.updated_at.desc()).limit(1)
        ).scalar_one_or_none()


def all_latest() -> list[MetricsCache]:
    """One row per symbol — the latest."""
    with Session(_engine, future=True) as s:
        rows = s.execute(
            select(MetricsCache).order_by(MetricsCache.updated_at.desc())
        ).scalars().all()
        seen: dict[str, MetricsCache] = {}
        for r in rows:
            seen.setdefault(r.symbol, r)
        return list(seen.values())


# ── User-managed pairs ────────────────────────────────────────────────────────

def get_user_pairs() -> list[str]:
    """Return custom pair symbols ordered by when they were added."""
    with Session(_engine, future=True) as s:
        rows = s.execute(
            select(UserPair).order_by(UserPair.added_at)
        ).scalars().all()
        return [r.symbol for r in rows]


def add_user_pair(symbol: str, pair_type: str = "crypto") -> None:
    """Upsert a custom pair — no-op if it already exists."""
    with Session(_engine, future=True) as s:
        existing = s.execute(
            select(UserPair).where(UserPair.symbol == symbol)
        ).scalar_one_or_none()
        if existing is None:
            s.add(UserPair(symbol=symbol, pair_type=pair_type))
            s.commit()


def remove_user_pair(symbol: str) -> None:
    """Delete a custom pair. No-op if not found."""
    with Session(_engine, future=True) as s:
        row = s.execute(
            select(UserPair).where(UserPair.symbol == symbol)
        ).scalar_one_or_none()
        if row is not None:
            s.delete(row)
            s.commit()
