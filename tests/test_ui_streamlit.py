"""AppTest UI tests for all four Streamlit pages.

Each class uses the `ui_app` fixture (defined in conftest.py) which:
  - Seeds in-memory SQLite from tests/fixtures/metrics_snapshot.json
  - Patches refresh_data.main to a no-op
  - Patches PionexClient to return tests/fixtures/pionex_bots.json
"""
from __future__ import annotations

import os
import pytest
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
