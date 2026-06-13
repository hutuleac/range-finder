"""AppTest UI tests for all four Streamlit pages.

Each class uses the `ui_app` fixture (defined in conftest.py) which:
  - Seeds in-memory SQLite from tests/fixtures/metrics_snapshot.json
  - Patches refresh_data.main to a no-op
  - Patches PionexClient to return tests/fixtures/pionex_bots.json
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone, timedelta
from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
TIMEOUT = 15  # seconds per AppTest run


class TestRangeFinder:
    """Default page — no radio selection needed."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass  # activates ui_app (seeds DB, patches scheduler + PionexClient) for every test

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_sidebar_multiselect_populated(self):
        at = self._run()
        assert len(at.sidebar.multiselect) > 0
        options = at.sidebar.multiselect[0].options
        assert any("USDT" in o for o in options)

    def test_markdown_renders(self):
        at = self._run()
        assert len(at.markdown) > 0

    def test_cache_age_shown_in_sidebar(self):
        at = self._run()
        sidebar_warnings = at.sidebar.warning
        cache_empty_warnings = [
            w for w in sidebar_warnings
            if "Cache empty" in (w.value or "")
        ]
        assert len(cache_empty_warnings) == 0

    def test_regime_badge_renders_when_present(self):
        """A payload carrying a resolved regime shows the REGIME badge + hint."""
        import json
        from pathlib import Path

        import trade_logger as tl

        snap = json.loads(
            (Path(__file__).parent / "fixtures" / "metrics_snapshot.json").read_text())
        row = snap[0]
        payload = row["payload"]
        payload["regime"] = {
            "er": {"er_value": 0.12, "er_regime": "RANGING"},
            "hurst": {"hurst_daily": 0.43, "regime": "MEAN_REVERTING"},
            "trendDaily": "Neutral",
            "confirmation": {
                "combined_regime": "CONFIRMED_RANGING", "conviction": "HIGH",
                "aligned": True, "trend_direction": "NEUTRAL",
                "strategy_hint": "GRID — fade extremes, mean reversion optimal",
            },
            "adxSlope": {"adx_slope": "FLAT", "adx_values": [], "adx_delta": 0.0},
        }
        payload["matrix"] = {
            "scores": {"GRID_NEUTRAL": 78.0, "GRID_LONG": 55.0,
                       "GRID_SHORT": 52.0, "DIRECTIONAL": 40.0},
            "winner": "GRID_NEUTRAL", "winnerScore": 78.0,
            "breakdown": {"GRID_NEUTRAL": [
                {"indicator": "BB_bandwidth", "weight": 16,
                 "normalized": 1.0, "contribution": 16.0},
            ]},
            "version": "1.0-heuristic",
        }
        tl.upsert_metrics(row["symbol"], row["price"], row["score"],
                          row["direction"], payload)
        at = self._run()
        assert not at.exception
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        assert "REGIME" in all_md
        assert "Confirmed Ranging" in all_md
        assert "STRATEGY MATRIX" in all_md
        assert "Grid·N" in all_md


class TestSignalScanner:
    """Signal Scanner page — routed via sidebar radio."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass  # activates ui_app for every test

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Signal Scanner")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_signal_content_renders(self):
        at = self._run()
        assert len(at.markdown) > 0 or len(at.dataframe) > 0

    def test_score_label_present(self):
        at = self._run()
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        assert any(
            kw in all_md
            for kw in ("SETUP", "DEVELOPING", "AVOID", "Score", "Setup")
        )


class TestBotMonitor:
    """Bot Monitor page — two fixture bots injected via monkeypatched PionexClient."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass  # activates ui_app for every test

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Bot Monitor")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_page_renders_content(self):
        at = self._run()
        assert len(at.markdown) > 0 or len(at.warning) > 0 or len(at.info) > 0

    def test_bot_card_or_portfolio_appears(self):
        at = self._run()
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        has_symbol  = "BTC" in all_md or "ETH" in all_md
        has_header  = "Bot Monitor" in all_md or "Portfolio" in all_md or "BOTS" in all_md
        has_warning = len(at.warning) > 0
        assert has_symbol or has_header or has_warning

    def test_recommendation_label_present_when_bots_matched(self):
        at = self._run()
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        rec_labels = ("HOLD", "CLOSE NOW", "TAKE PROFIT", "WARNING", "WATCH", "REVIEW")
        matched = any(lbl in all_md for lbl in rec_labels)
        assert matched or len(at.warning) > 0


class TestTradeMonitor:
    """Trade Monitor page — empty state and seeded trade."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass  # activates ui_app for every test

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        at.sidebar.radio[0].set_value("Trade Monitor")
        at.run()
        return at

    def test_no_exception(self):
        at = self._run()
        assert not at.exception

    def test_no_error_widget(self):
        at = self._run()
        assert len(at.error) == 0

    def test_empty_state_renders(self):
        at = self._run()
        all_md  = " ".join(str(m.value) for m in at.markdown if m.value)
        all_inf = " ".join(str(i.value) for i in at.info  if i.value)
        combined = all_md + all_inf
        assert (
            "no" in combined.lower()
            or "empty" in combined.lower()
            or "trade" in combined.lower()
            or len(at.dataframe) > 0
        )

    def test_trade_table_renders_when_seeded(self):
        import trade_logger as tl
        from trade_logger import SimulatedTrade

        trade = SimulatedTrade(
            symbol="BTC/USDT",
            entry_price=100_000.0,
            range_low=90_000.0,
            range_high=110_000.0,
            num_grids=20,
            direction="Long",
            grid_mode="Arithmetic",
            grid_score=7.5,
            stop_loss=81_900.0,
            take_profit=115_500.0,
            profile="stable",
            inventory=[],
        )
        tl.create_simulated_trade(trade)

        at = self._run()
        assert not at.exception
        all_md = " ".join(str(m.value) for m in at.markdown if m.value)
        has_table = len(at.dataframe) > 0
        has_symbol_in_md = "BTC" in all_md
        assert has_table or has_symbol_in_md


# ─────────────────────────────────────────────────────────────────────
# Pure-function helper tests (no Streamlit context required)
# ─────────────────────────────────────────────────────────────────────

class TestBotMonitorHelpers:
    """Unit tests for pure helpers in bot_monitor — no Streamlit needed."""

    def test_chip_returns_html(self):
        from bot_monitor import _chip
        html = _chip("HOLD", "#fff", "#000")
        assert "HOLD" in html
        assert "bot-pill" in html

    def test_pnl_color_positive(self):
        from bot_monitor import _pnl_color
        assert _pnl_color(1.0)  == "#22c55e"

    def test_pnl_color_negative(self):
        from bot_monitor import _pnl_color
        assert _pnl_color(-1.0) == "#ef4444"

    def test_pnl_color_zero(self):
        from bot_monitor import _pnl_color
        assert _pnl_color(0.0) == "#94a3b8"

    def test_pionex_symbol_to_pair_with_underscore(self):
        from bot_monitor import _pionex_symbol_to_pair
        assert _pionex_symbol_to_pair("BTC_USDT") == "BTC/USDT"

    def test_pionex_symbol_to_pair_without_underscore(self):
        from bot_monitor import _pionex_symbol_to_pair
        assert _pionex_symbol_to_pair("BTCUSDT") == "BTCUSDT"


class TestTradeMonitorHelpers:
    """Unit tests for pure helpers in trade_monitor — no Streamlit needed."""

    def test_age_str_none(self):
        from trade_monitor import _age_str
        assert _age_str(None) == "—"

    def test_age_str_hours(self):
        from trade_monitor import _age_str
        dt = datetime.now(timezone.utc) - timedelta(hours=3, minutes=20)
        result = _age_str(dt)
        assert "h" in result

    def test_age_str_days(self):
        from trade_monitor import _age_str
        dt = datetime.now(timezone.utc) - timedelta(days=2, hours=5)
        result = _age_str(dt)
        assert "d" in result

    def test_pnl_color_positive(self):
        from trade_monitor import _pnl_color
        assert _pnl_color(1.0)  == "#22c55e"

    def test_pnl_color_negative(self):
        from trade_monitor import _pnl_color
        assert _pnl_color(-0.5) == "#ef4444"

    def test_pnl_color_zero(self):
        from trade_monitor import _pnl_color
        assert _pnl_color(0.0)  == "#94a3b8"

    def test_status_chip_active(self):
        from trade_monitor import _status_chip
        html = _status_chip("ACTIVE")
        assert "ACTIVE" in html
        assert "#22d3ee" in html

    def test_status_chip_tp_hit(self):
        from trade_monitor import _status_chip
        html = _status_chip("TP_HIT")
        assert "TP_HIT" in html

    def test_status_chip_unknown(self):
        from trade_monitor import _status_chip
        html = _status_chip("UNKNOWN")
        assert "UNKNOWN" in html

    def test_dir_color_long(self):
        from trade_monitor import _dir_color
        assert _dir_color("Long")  == "#22c55e"

    def test_dir_color_short(self):
        from trade_monitor import _dir_color
        assert _dir_color("Short") == "#ef4444"

    def test_dir_color_neutral(self):
        from trade_monitor import _dir_color
        assert _dir_color("Neutral") == "#fbbf24"

    def test_range_gauge_mid(self):
        from trade_monitor import _range_gauge
        html = _range_gauge(100.0, 90.0, 110.0)
        assert "50%" in html  # mid point

    def test_range_gauge_zero_range(self):
        from trade_monitor import _range_gauge
        html = _range_gauge(100.0, 100.0, 100.0)  # high == low → pct = 0.5
        assert "%" in html


class TestNormalisePair:
    """Unit tests for the pure _normalise_pair helper in app.py."""

    def _norm(self, raw: str):
        from app import _normalise_pair
        return _normalise_pair(raw)

    def test_plain_crypto_token_gets_usdt(self):
        sym, kind = self._norm("link")
        assert sym == "LINK/USDT"
        assert kind == "crypto"

    def test_explicit_crypto_pair_unchanged(self):
        sym, kind = self._norm("AVAX/USDT")
        assert sym == "AVAX/USDT"
        assert kind == "crypto"

    def test_stock_token_ending_x_gets_usd(self):
        sym, kind = self._norm("tslax")
        assert sym == "TSLAX/USD"
        assert kind == "stock"

    def test_explicit_stock_pair_unchanged(self):
        sym, kind = self._norm("AAPLX/USD")
        assert sym == "AAPLX/USD"
        assert kind == "stock"

    def test_strips_whitespace(self):
        sym, kind = self._norm("  avax  ")
        assert sym == "AVAX/USDT"

    def test_quote_usd_detected_as_stock(self):
        sym, kind = self._norm("MSFTX/USD")
        assert kind == "stock"


class TestCustomPairs:
    """Verify custom pairs appear in the sidebar multiselect."""

    @pytest.fixture(autouse=True)
    def _setup(self, ui_app):
        pass  # activates ui_app for every test

    def _run(self) -> AppTest:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
        at.run()
        return at

    def test_custom_crypto_pair_appears_in_options(self):
        import trade_logger as tl
        tl.add_user_pair("LINK/USDT", "crypto")

        at = self._run()
        assert not at.exception
        options = at.sidebar.multiselect[0].options
        assert "LINK/USDT" in options

    def test_custom_stock_pair_appears_in_options(self):
        import trade_logger as tl
        tl.add_user_pair("TSLAX/USD", "stock")

        at = self._run()
        assert not at.exception
        options = at.sidebar.multiselect[0].options
        assert "TSLAX/USD" in options

    def test_no_custom_pairs_shows_only_defaults(self):
        from config import DEFAULT_PAIRS
        at = self._run()
        assert not at.exception
        options = at.sidebar.multiselect[0].options
        for pair in DEFAULT_PAIRS:
            assert pair in options
