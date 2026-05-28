# Custom Pair Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to add and persist arbitrary crypto pairs (`LINK/USDT`) and Pionex stock pairs (`TSLAX/USD`) beyond the 9 hard-coded defaults, with exchange validation before saving and SQLite persistence across browser refreshes.

**Architecture:** Four focused changes — DB model + helpers in `trade_logger.py`, a `validate_pair` thin wrapper in `data_fetcher.py`, a `validate_symbol` method in `pionex_client.py`, and sidebar UX replacement in `app.py`. A pure `_normalise_pair` helper lives in `app.py` and is unit-tested via direct import.

**Tech Stack:** SQLAlchemy 2.0 (existing), ccxt (existing), requests (existing), Streamlit 1.44 (existing), pytest.

---

## File Map

| Action | File | Change |
|--------|------|--------|
| Modify | `trade_logger.py` | Add `UserPair` model to `Base`; add `get_user_pairs`, `add_user_pair`, `remove_user_pair` |
| Modify | `data_fetcher.py` | Add `validate_pair(symbol) -> bool` |
| Modify | `pionex_client.py` | Add `validate_symbol(symbol) -> bool` |
| Modify | `app.py` | Add `_normalise_pair`; replace multiselect block with pair-management sidebar |
| Modify | `tests/test_trade_logger.py` | Add `UserPair` CRUD tests |
| Modify | `tests/test_data_fetcher.py` | Add `validate_pair` tests |
| Modify | `tests/test_pionex_client.py` | Add `validate_symbol` tests |
| Modify | `tests/test_ui_streamlit.py` | Add custom-pair AppTest |

---

## Task 1 — `UserPair` model and DB helpers

**Files:**
- Modify: `trade_logger.py` (after `class Trade`, before `def init_db`)
- Modify: `tests/test_trade_logger.py`

### Background

`trade_logger.py` already has a `Base` class, an `_engine`, and `init_db()` that calls `Base.metadata.create_all(_engine)`. Adding `UserPair` to `Base` is enough — `init_db()` will create the table automatically. The `in_memory_engines` fixture in `tests/test_trade_logger.py` calls `tl.Base.metadata.create_all(metrics_engine)`, so `UserPair` will be available in tests with no fixture changes.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_trade_logger.py` after the existing imports:

```python
from trade_logger import (
    add_user_pair,
    get_user_pairs,
    remove_user_pair,
)
```

Then add this class at the end of the file:

```python
class TestUserPairs:
    def test_get_user_pairs_empty(self):
        assert get_user_pairs() == []

    def test_add_and_get(self):
        add_user_pair("LINK/USDT", "crypto")
        pairs = get_user_pairs()
        assert "LINK/USDT" in pairs

    def test_add_stock_pair(self):
        add_user_pair("TSLAX/USD", "stock")
        assert "TSLAX/USD" in get_user_pairs()

    def test_add_is_idempotent(self):
        add_user_pair("LINK/USDT", "crypto")
        add_user_pair("LINK/USDT", "crypto")  # duplicate
        assert get_user_pairs().count("LINK/USDT") == 1

    def test_remove_existing(self):
        add_user_pair("AVAX/USDT", "crypto")
        remove_user_pair("AVAX/USDT")
        assert "AVAX/USDT" not in get_user_pairs()

    def test_remove_nonexistent_does_not_raise(self):
        remove_user_pair("DOES_NOT_EXIST/USDT")  # should not raise

    def test_get_returns_symbols_in_order(self):
        add_user_pair("LINK/USDT", "crypto")
        add_user_pair("AVAX/USDT", "crypto")
        pairs = get_user_pairs()
        assert pairs.index("LINK/USDT") < pairs.index("AVAX/USDT")
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_trade_logger.py::TestUserPairs -v --tb=short 2>&1
```

Expected: `ImportError: cannot import name 'add_user_pair'`

- [ ] **Step 3: Add `UserPair` model to `trade_logger.py`**

Insert after `class Trade` (around line 51) and before `def init_db()`:

```python
class UserPair(Base):
    """User-added custom trading pair, persisted across sessions."""
    __tablename__ = "user_pairs"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(32), unique=True, nullable=False, index=True)
    pair_type = Column(String(8),  nullable=False, default="crypto")  # "crypto" | "stock"
    added_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Add helper functions to `trade_logger.py`**

Add after `upsert_metrics` / `all_latest` at the bottom of the file:

```python
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
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_trade_logger.py::TestUserPairs -v --tb=short 2>&1
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Full regression check**

```bash
python3 -m pytest tests/test_trade_logger.py -q 2>&1
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add trade_logger.py tests/test_trade_logger.py
git commit -m "Add UserPair model and CRUD helpers to trade_logger"
```

---

## Task 2 — `validate_pair()` in `data_fetcher.py`

**Files:**
- Modify: `data_fetcher.py` (append at end)
- Modify: `tests/test_pionex_client.py` — no, wrong file. Use `tests/test_indicators.py`? No — create tests in `tests/test_data_fetcher.py` (new file).
- Create: `tests/test_data_fetcher.py`

### Background

`data_fetcher.fetch_klines(symbol, timeframe, limit)` returns a list of candles or `[]` on failure. `validate_pair` wraps it: returns `True` if at least one candle comes back, `False` otherwise. No new dependency.

- [ ] **Step 1: Create `tests/test_data_fetcher.py` with failing test**

```python
"""Tests for data_fetcher.py — validate_pair."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from data_fetcher import validate_pair


class TestValidatePair:
    def test_returns_true_when_klines_non_empty(self):
        fake_candle = [[1, "100", "101", "99", "100.5", "500", 0, 0, 0, "300", 0, 0]]
        with patch("data_fetcher.fetch_klines", return_value=fake_candle):
            assert validate_pair("LINK/USDT") is True

    def test_returns_false_when_klines_empty(self):
        with patch("data_fetcher.fetch_klines", return_value=[]):
            assert validate_pair("FAKE/USDT") is False

    def test_returns_false_on_exception(self):
        with patch("data_fetcher.fetch_klines", side_effect=Exception("network")):
            assert validate_pair("BAD/USDT") is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_data_fetcher.py -v --tb=short 2>&1
```

Expected: `ImportError: cannot import name 'validate_pair'`

- [ ] **Step 3: Add `validate_pair` to `data_fetcher.py`**

Append at the end of the file:

```python
def validate_pair(symbol: str) -> bool:
    """Return True if the exchange returns at least one candle for this symbol."""
    try:
        rows = fetch_klines(symbol, "4h", limit=1)
        return len(rows) > 0
    except Exception:
        return False
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_data_fetcher.py -v --tb=short 2>&1
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add data_fetcher.py tests/test_data_fetcher.py
git commit -m "Add validate_pair helper to data_fetcher"
```

---

## Task 3 — `validate_symbol()` in `pionex_client.py`

**Files:**
- Modify: `pionex_client.py`
- Modify: `tests/test_pionex_client.py`

### Background

Pionex exposes a public (no-auth) ticker endpoint. Based on the API pattern used by the existing `_get` method and documented at https://www.pionex.com/docs, the public ticker endpoint is:

```
GET https://api.pionex.com/api/v1/market/tickers?symbol=TSLAX_USD
```

The symbol format uses `_` instead of `/`. If `result: true` and `data` is non-empty, the symbol is valid. This endpoint requires no authentication — do **not** use `self._get()` (which adds auth headers). Use a raw `requests.get` call.

> **Before implementing:** Verify the endpoint by running:
> ```bash
> curl "https://api.pionex.com/api/v1/market/tickers?symbol=TSLAX_USD" | python3 -m json.tool
> ```
> Confirm the response shape. If the endpoint differs, adjust the implementation below accordingly but keep the same method signature and return semantics.

- [ ] **Step 1: Add failing tests to `tests/test_pionex_client.py`**

At the end of the file, add:

```python
class TestValidateSymbol:
    @patch("pionex_client.requests.get")
    def test_returns_true_when_symbol_found(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": True, "data": [{"symbol": "TSLAX_USD", "close": "25.0"}]},
        )
        client = PionexClient()
        assert client.validate_symbol("TSLAX/USD") is True

    @patch("pionex_client.requests.get")
    def test_returns_false_when_result_false(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": False, "data": []},
        )
        client = PionexClient()
        assert client.validate_symbol("FAKE/USD") is False

    @patch("pionex_client.requests.get")
    def test_returns_false_when_data_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"result": True, "data": []},
        )
        client = PionexClient()
        assert client.validate_symbol("UNKNOWN/USD") is False

    @patch("pionex_client.requests.get", side_effect=Exception("timeout"))
    def test_returns_false_on_network_error(self, mock_get):
        client = PionexClient()
        assert client.validate_symbol("TSLAX/USD") is False

    def test_works_without_api_keys(self):
        """validate_symbol does not require configured credentials."""
        client = PionexClient(api_key="", api_secret="")
        # We just verify the method exists and doesn't raise without keys
        # (actual network call mocked in other tests)
        assert hasattr(client, "validate_symbol")
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_pionex_client.py::TestValidateSymbol -v --tb=short 2>&1
```

Expected: `AttributeError: 'PionexClient' object has no attribute 'validate_symbol'`

- [ ] **Step 3: Add `validate_symbol` to `pionex_client.py`**

Add after `get_bot_detail` method (at the end of the class):

```python
    def validate_symbol(self, symbol: str) -> bool:
        """Check if a symbol is listed on Pionex. No authentication required.

        Uses the public market tickers endpoint. Falls back to False on any
        network error so callers can decide whether to save anyway.
        """
        try:
            resp = requests.get(
                f"{_BASE}/api/v1/market/tickers",
                params={"symbol": symbol.replace("/", "_")},
                timeout=10,
            )
            data = resp.json()
            return bool(data.get("result") and data.get("data"))
        except Exception:
            return False
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_pionex_client.py::TestValidateSymbol -v --tb=short 2>&1
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Full regression on pionex tests**

```bash
python3 -m pytest tests/test_pionex_client.py -q 2>&1
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pionex_client.py tests/test_pionex_client.py
git commit -m "Add validate_symbol to PionexClient for Pionex stock pair validation"
```

---

## Task 4 — `_normalise_pair` helper + sidebar UX in `app.py`

**Files:**
- Modify: `app.py` (add helper + replace sidebar multiselect block)
- Modify: `tests/test_ui_streamlit.py` (unit test for `_normalise_pair`)

### Background

The sidebar block to replace is lines 266–272 of `app.py` (the `st.multiselect` call):

```python
    selected = st.multiselect(
        "Watched pairs", DEFAULT_PAIRS, default=DEFAULT_PAIRS,
        help="USDT perpetuals. HYPE/SUI fall back to Bybit automatically.",
    )
```

The new block replaces those 5 lines with the pair-management logic. The `st.divider()` on line 282 and everything below stays unchanged.

The `_normalise_pair` function is a pure function — place it near the top of `app.py` with the other helpers (after the CSS block, before `chip()`).

- [ ] **Step 1: Write unit test for `_normalise_pair`**

Add at the end of `tests/test_ui_streamlit.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_ui_streamlit.py::TestNormalisePair -v --tb=short 2>&1
```

Expected: `ImportError: cannot import name '_normalise_pair' from 'app'`

- [ ] **Step 3: Add `_normalise_pair` to `app.py`**

Add after the `chip` helper function (around line 129), before the other render helpers:

```python
def _normalise_pair(raw: str) -> tuple[str, str]:
    """Normalise user input to a canonical symbol and detect pair type.

    Returns (symbol, pair_type) where pair_type is "crypto" or "stock".
    Rules:
      - Strip whitespace, uppercase
      - If already contains '/': use as-is, detect type from quote currency
      - If token ends in 'X' and no '/': append '/USD' → stock
      - Otherwise: append '/USDT' → crypto
    """
    sym = raw.strip().upper()
    if "/" in sym:
        pair_type = "stock" if sym.endswith("/USD") else "crypto"
        return sym, pair_type
    if sym.endswith("X"):
        return f"{sym}/USD", "stock"
    return f"{sym}/USDT", "crypto"
```

- [ ] **Step 4: Run `_normalise_pair` tests**

```bash
python3 -m pytest tests/test_ui_streamlit.py::TestNormalisePair -v --tb=short 2>&1
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Update `app.py` imports**

At the top of `app.py`, the existing trade_logger import reads:

```python
from trade_logger import all_latest, init_db, latest_metrics
```

Replace it with:

```python
from trade_logger import (
    add_user_pair,
    all_latest,
    get_user_pairs,
    init_db,
    latest_metrics,
    remove_user_pair,
)
```

Also add to the data_fetcher import line (find it near the top of `app.py`):

```python
from refresh_data import refresh_one
```

Leave that unchanged — `validate_pair` and `validate_symbol` are called inline in the sidebar block below.

- [ ] **Step 6: Replace the multiselect block in `app.py`**

Find and replace the existing multiselect (lines ~269–272):

**Old:**
```python
    selected = st.multiselect(
        "Watched pairs", DEFAULT_PAIRS, default=DEFAULT_PAIRS,
        help="USDT perpetuals. HYPE/SUI fall back to Bybit automatically.",
    )
```

**New** (replaces those 5 lines exactly — everything else in the sidebar stays):

```python
    # ── Pair selector ────────────────────────────────────────────────
    _custom = get_user_pairs()
    _options = DEFAULT_PAIRS + [p for p in _custom if p not in DEFAULT_PAIRS]
    selected = st.multiselect(
        "Watched pairs", _options, default=_options,
        help="USDT perpetuals. Deselect a custom pair to remove it permanently.",
    )
    # Remove any custom pair the user deselected
    _removed = set(_custom) - set(selected)
    if _removed:
        for _sym in _removed:
            remove_user_pair(_sym)
        st.rerun()

    # ── Add custom pair ──────────────────────────────────────────────
    _col1, _col2 = st.columns([3, 1])
    _new_raw = _col1.text_input(
        "Add pair",
        placeholder="LINK or TSLAX",
        label_visibility="collapsed",
        key="add_pair_input",
    )
    if _col2.button("Add", use_container_width=True, key="add_pair_btn"):
        if _new_raw.strip():
            _sym, _ptype = _normalise_pair(_new_raw)
            if _sym in _options:
                st.info(f"{_sym} is already in your list.")
            else:
                with st.spinner(f"Validating {_sym}…"):
                    if _ptype == "stock":
                        from pionex_client import PionexClient as _PC
                        _valid = _PC().validate_symbol(_sym)
                        _err_msg = f"{_sym} not found on Pionex."
                        _warn_msg = "Could not reach Pionex — saved anyway."
                    else:
                        from data_fetcher import validate_pair as _vp
                        _valid = _vp(_sym)
                        _err_msg = f"{_sym} not found on OKX/Bybit."
                        _warn_msg = None
                if _valid:
                    add_user_pair(_sym, _ptype)
                    st.rerun()
                elif _warn_msg and not _valid:
                    # Network unreachable — save with a warning (stock only)
                    st.warning(_warn_msg)
                    add_user_pair(_sym, _ptype)
                    st.rerun()
                else:
                    st.error(_err_msg)
```

> **Implementation note on the Pionex fallback:** The spec says to save with a warning when the Pionex API is unreachable (network error). `validate_symbol` returns `False` on network errors, so the sidebar can't distinguish "symbol not found" from "network down". To handle this, `validate_symbol` should return `None` on network error (instead of `False`) so the caller can show the warning and save anyway. Update `validate_symbol` in Task 3 if you haven't already — return `None` on `except Exception`, `True` on valid, `False` on confirmed-not-found.

**Update `pionex_client.validate_symbol` return type to `bool | None`:**

```python
    def validate_symbol(self, symbol: str) -> bool | None:
        """Check if a symbol is listed on Pionex. No authentication required.

        Returns:
            True  — symbol confirmed on Pionex
            False — symbol confirmed NOT on Pionex
            None  — network/API error; caller decides whether to save anyway
        """
        try:
            resp = requests.get(
                f"{_BASE}/api/v1/market/tickers",
                params={"symbol": symbol.replace("/", "_")},
                timeout=10,
            )
            data = resp.json()
            return bool(data.get("result") and data.get("data"))
        except Exception:
            return None
```

Update the sidebar block accordingly (replace `_valid = _PC().validate_symbol(_sym)` branch):

```python
                if _ptype == "stock":
                    from pionex_client import PionexClient as _PC
                    _result = _PC().validate_symbol(_sym)
                    if _result is True:
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    elif _result is None:
                        st.warning("Could not reach Pionex — saved anyway.")
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    else:
                        st.error(f"{_sym} not found on Pionex.")
                else:
                    from data_fetcher import validate_pair as _vp
                    if _vp(_sym):
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    else:
                        st.error(f"{_sym} not found on OKX/Bybit.")
```

**Final sidebar `Add` block (complete, no fragments):**

```python
    _col1, _col2 = st.columns([3, 1])
    _new_raw = _col1.text_input(
        "Add pair",
        placeholder="LINK or TSLAX",
        label_visibility="collapsed",
        key="add_pair_input",
    )
    if _col2.button("Add", use_container_width=True, key="add_pair_btn"):
        if _new_raw.strip():
            _sym, _ptype = _normalise_pair(_new_raw)
            if _sym in _options:
                st.info(f"{_sym} is already in your list.")
            else:
                with st.spinner(f"Validating {_sym}…"):
                    if _ptype == "stock":
                        from pionex_client import PionexClient as _PC
                        _result = _PC().validate_symbol(_sym)
                    else:
                        from data_fetcher import validate_pair as _vp
                        _result = True if _vp(_sym) else False
                if _ptype == "stock":
                    if _result is True:
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    elif _result is None:
                        st.warning("Could not reach Pionex — saved anyway.")
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    else:
                        st.error(f"{_sym} not found on Pionex.")
                else:
                    if _result:
                        add_user_pair(_sym, _ptype)
                        st.rerun()
                    else:
                        st.error(f"{_sym} not found on OKX/Bybit.")
```

Also update `validate_symbol` tests in `tests/test_pionex_client.py` to expect `None` on network error:

```python
    @patch("pionex_client.requests.get", side_effect=Exception("timeout"))
    def test_returns_none_on_network_error(self, mock_get):
        client = PionexClient()
        assert client.validate_symbol("TSLAX/USD") is None
```

(Rename the existing `test_returns_false_on_network_error` → `test_returns_none_on_network_error`.)

- [ ] **Step 7: Run full test suite**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1
```

Expected: all tests pass. Pay special attention to `TestNormalisePair` and `TestValidateSymbol`.

- [ ] **Step 8: Commit**

```bash
git add app.py pionex_client.py tests/test_ui_streamlit.py tests/test_pionex_client.py
git commit -m "Add custom pair management sidebar: add/remove crypto and stock pairs"
```

---

## Task 5 — AppTest for custom pair visibility

**Files:**
- Modify: `tests/test_ui_streamlit.py`
- Modify: `tests/conftest.py` (`ui_app` fixture — add `UserPair` table creation)

### Background

The `ui_app` fixture calls `_tl.Base.metadata.create_all(metrics_engine)`. Since `UserPair` is now part of `Base`, the table is created automatically — no fixture change needed.

To test that a custom pair appears in the multiselect options, seed a `UserPair` into the in-memory DB before running AppTest.

- [ ] **Step 1: Add the AppTest class to `tests/test_ui_streamlit.py`**

Append at the end of the file:

```python
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
```

- [ ] **Step 2: Run AppTest class**

```bash
cd /Users/peter/Desktop/Claude/range-finder
python3 -m pytest tests/test_ui_streamlit.py::TestCustomPairs -v --tb=short 2>&1
```

Expected: all 3 tests PASS.

- [ ] **Step 3: Full suite — no regressions**

```bash
python3 -m pytest tests/ -q --tb=short 2>&1
```

Expected: all tests pass.

- [ ] **Step 4: Commit and push**

```bash
git add tests/test_ui_streamlit.py
git commit -m "Add AppTest: custom pair visibility in sidebar multiselect"
git push origin main
```

---

## Verification Checklist (run after all tasks)

```bash
# All tests green
python3 -m pytest tests/ -q 2>&1 | tail -3

# Verify UserPair table exists in the live DB
python3 -c "
from trade_logger import get_user_pairs
print('user_pairs table OK, rows:', get_user_pairs())
"

# Smoke-test normalisation
python3 -c "
from app import _normalise_pair
cases = [('link', ('LINK/USDT', 'crypto')), ('tslax', ('TSLAX/USD', 'stock')),
         ('AAPLX/USD', ('AAPLX/USD', 'stock')), ('AVAX/USDT', ('AVAX/USDT', 'crypto'))]
for raw, expected in cases:
    result = _normalise_pair(raw)
    status = '✓' if result == expected else '✗'
    print(f'{status} {raw!r:15s} → {result}')
"
```
