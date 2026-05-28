"""Shared pytest fixtures for range-finder tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(closes: np.ndarray, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(closes)
    spread = closes * 0.005
    return pd.DataFrame({
        "Time": np.arange(n, dtype=np.int64) * 14_400_000,
        "Open":   closes + rng.uniform(-spread, spread),
        "High":   closes + np.abs(rng.normal(0, spread)),
        "Low":    closes - np.abs(rng.normal(0, spread)),
        "Close":  closes,
        "Volume": np.abs(rng.normal(1000, 200, n)),
        "BuyVol": np.abs(rng.normal(500, 100, n)),
    })


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """50-candle OHLCV with slight random walk — enough for all period-14 indicators."""
    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.randn(50) * 0.3)
    return _make_ohlcv(prices)


@pytest.fixture
def trending_ohlcv() -> pd.DataFrame:
    """60-candle monotone uptrend — drives high RSI and Bullish structure."""
    prices = np.linspace(80.0, 130.0, 60)
    df = _make_ohlcv(prices)
    # Guarantee strictly ascending OHLC so structure tests are deterministic
    df["High"]  = prices + 1.0
    df["Low"]   = prices - 0.5
    df["Close"] = prices + 0.3
    df["Open"]  = prices
    return df


@pytest.fixture
def bearish_ohlcv() -> pd.DataFrame:
    """60-candle monotone downtrend — drives Bearish structure."""
    prices = np.linspace(130.0, 80.0, 60)
    df = _make_ohlcv(prices)
    df["High"]  = prices + 0.5
    df["Low"]   = prices - 1.0
    df["Close"] = prices - 0.3
    df["Open"]  = prices
    return df


@pytest.fixture
def flat_ohlcv() -> pd.DataFrame:
    """50-candle flat range — drives squeeze / low ADX."""
    prices = np.ones(50) * 100.0 + np.random.default_rng(0).uniform(-0.1, 0.1, 50)
    df = _make_ohlcv(prices)
    df["High"]  = prices + 0.5
    df["Low"]   = prices - 0.5
    df["Close"] = prices
    return df


@pytest.fixture
def empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["Time", "Open", "High", "Low", "Close", "Volume", "BuyVol"])


@pytest.fixture
def mock_metrics() -> dict:
    """Metrics dict matching the shape returned by get_advanced_metrics / calc_grid_score."""
    return {
        "currClose": 100.0,
        "rsi": 52.0,
        "atr": 2.5,
        "atrPct": 2.5,
        "ema_fast": 99.0,
        "ema_slow": 95.0,
        "poc5d": 100.0,
        "poc14d": 99.5,
        "cvd5d": 50.0,
        "volume5d": 800.0,
        "structure4h": "Neutral",
        "fvgList": [],
        "adx": {"adx": 15.0, "plusDI": 20.0, "minusDI": 14.0},
        "bb": {"upper": 105.0, "lower": 95.0, "mid": 100.0, "bw": 10.0, "label": "normal"},
        "bbBw": 10.0,
        "macd": {"macd": 0.1, "signal": 0.05, "histogram": 0.05, "trend": "bull"},
        "obv": {"obv": 50000.0, "trend": "UP"},
        "change24h": 0.5,
        "oi_change_pct": -3.0,
        "funding": -0.005,
        "squeeze": {"squeeze": False, "bbTight": False, "dcTight": False, "bbBw": 10.0, "dcAtrRatio": 1.2},
        "gridRange": {"rangeLow": 92.0, "rangeHigh": 108.0},
        "_grid_score": 7.0,
    }


@pytest.fixture
def mock_bot() -> dict:
    """Realistic Pionex spot-grid bot payload."""
    import time
    return {
        "buOrderId": "bot-123",
        "symbol": "BTCUSDT",
        "buOrderType": "spot_grid",
        "status": "running",
        "lowerPrice": "90.0",
        "upperPrice": "110.0",
        "gridNum": 20,
        "quoteInvestment": "500.0",
        "baseInvestment": "0.0",
        "gridProfit": "10.0",
        "realizedProfit": "2.0",
        "createTime": int(time.time() * 1000) - 3 * 86_400_000,  # 3 days ago
    }


# ── Streamlit AppTest shared fixture ─────────────────────────────────

import json as _json
from pathlib import Path as _Path

import trade_logger as _tl
from sqlalchemy import create_engine as _create_engine
from sqlalchemy.pool import StaticPool as _StaticPool


@pytest.fixture()
def ui_app(monkeypatch):
    """Full-integration fixture for AppTest UI tests.

    Seeds in-memory SQLite from captured snapshot, patches refresh_data.main
    to a no-op, and patches PionexClient to return fixture bots.

    Uses StaticPool so all SQLAlchemy sessions (including those opened by
    AppTest inside the same process) share a single SQLite connection and
    therefore see the seeded data.
    """
    # 1. Single-connection in-memory engines (StaticPool keeps one connection
    #    alive and reuses it for every Session — avoids :memory: isolation).
    connect_args = {"check_same_thread": False}
    metrics_engine = _create_engine(
        "sqlite:///:memory:",
        connect_args=connect_args,
        poolclass=_StaticPool,
        future=True,
    )
    trades_engine = _create_engine(
        "sqlite:///:memory:",
        connect_args=connect_args,
        poolclass=_StaticPool,
        future=True,
    )
    _tl.Base.metadata.create_all(metrics_engine)
    _tl.TradesBase.metadata.create_all(trades_engine)
    monkeypatch.setattr(_tl, "_engine",        metrics_engine)
    monkeypatch.setattr(_tl, "_trades_engine", trades_engine)

    # 2. Seed metrics from snapshot
    snapshot_path = _Path(__file__).parent / "fixtures" / "metrics_snapshot.json"
    snapshot = _json.loads(snapshot_path.read_text())
    for row in snapshot:
        _tl.upsert_metrics(
            row["symbol"], row["price"], row["score"],
            row["direction"], row["payload"],
        )

    # 3. Patch refresh_data.main to no-op
    import refresh_data as _rd
    monkeypatch.setattr(_rd, "main", lambda *a, **kw: None)

    # 4. Patch PionexClient
    import pionex_client as _pc
    bots_path = _Path(__file__).parent / "fixtures" / "pionex_bots.json"
    fixture_bots = _json.loads(bots_path.read_text())

    monkeypatch.setattr(_pc.PionexClient, "api_key",    "test-key",    raising=False)
    monkeypatch.setattr(_pc.PionexClient, "api_secret", "test-secret", raising=False)
    monkeypatch.setattr(_pc.PionexClient, "list_running_bots",
                        lambda self: fixture_bots)
    monkeypatch.setattr(_pc.PionexClient, "get_bot_detail",
                        lambda self, order_id: fixture_bots[0])

    yield
