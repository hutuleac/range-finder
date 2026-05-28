# Custom Pair Management — Design Spec
**Date:** 2026-05-29
**Status:** Approved

---

## Goal

Allow users to add arbitrary trading pairs (e.g. `LINK/USDT`, `AVAX/USDT`) beyond the 9 hard-coded `DEFAULT_PAIRS`, with persistence across browser refreshes via SQLite and exchange validation before saving.

---

## Data Layer

### New model: `UserPair` in `trade_logger.py`

Added to the existing `Base` (same `pyonex.db`, same engine — no new DB file):

```python
class UserPair(Base):
    __tablename__ = "user_pairs"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(32), unique=True, nullable=False, index=True)
    added_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

### Helper functions added to `trade_logger.py`

| Function | Behaviour |
|---|---|
| `get_user_pairs() -> list[str]` | Returns list of symbol strings ordered by `added_at` |
| `add_user_pair(symbol: str) -> None` | Upsert (insert if not exists, no-op if duplicate) |
| `remove_user_pair(symbol: str) -> None` | Delete row where symbol matches; no-op if missing |

Schema is created at import time alongside existing tables (`init_db()` extended to include `UserPair`).

---

## Validation

Before saving, the app confirms the pair trades on OKX/Bybit by calling the existing `data_fetcher` to fetch 1 candle (4H). If the fetch raises an exception or returns empty data, the pair is rejected and `st.error()` is shown in the sidebar. No new dependency — reuses `refresh_data.refresh_one` internals.

Specifically: call `data_fetcher.fetch_klines(symbol, "4h", limit=1)`. Wrap in try/except; any exception or empty result = invalid pair.

Input normalisation before validation: strip whitespace, uppercase, ensure `/USDT` suffix if user typed just a token name (e.g. `link` → `LINK/USDT`).

---

## Sidebar UX

**Replaces** the current `st.multiselect` block in `app.py`. Minimal diff — no new page, no new expander.

```
┌─────────────────────────────────────────┐
│ Watched pairs                           │
│ [multiselect: DEFAULT_PAIRS + custom]   │
│                                         │
│ [text_input: "Add pair (e.g. LINK)"] [Add] │
└─────────────────────────────────────────┘
```

### Render logic (runs on every sidebar render):

1. `custom = get_user_pairs()`
2. `options = DEFAULT_PAIRS + [p for p in custom if p not in DEFAULT_PAIRS]`
3. `selected = st.multiselect("Watched pairs", options, default=options, ...)`
4. **Removal detection:** `removed = set(custom) - set(selected)` → call `remove_user_pair(sym)` for each → if any removed: `st.rerun()`
5. **Add widget:**
   ```python
   col1, col2 = st.columns([3, 1])
   new_pair = col1.text_input("Add pair", placeholder="LINK / LINK/USDT", label_visibility="collapsed")
   add_clicked = col2.button("Add", use_container_width=True)
   ```
6. On `add_clicked` with non-empty `new_pair`:
   - Normalise: `sym = new_pair.strip().upper(); sym = sym if "/" in sym else f"{sym}/USDT"`
   - If `sym` already in `options`: show `st.info(f"{sym} is already in your list")`
   - Else: validate via `data_fetcher` (spinner: "Validating…") → success: `add_user_pair(sym)` + `st.rerun()` → failure: `st.error(f"{sym} not found on OKX/Bybit")`

---

## Files Changed

| File | Change |
|---|---|
| `trade_logger.py` | Add `UserPair` model to `Base`; add `get_user_pairs`, `add_user_pair`, `remove_user_pair`; extend `init_db()` |
| `app.py` | Replace multiselect block with new logic; import new helpers |
| `data_fetcher.py` | Expose a `validate_pair(symbol) -> bool` helper (thin wrapper around existing fetch logic) |

---

## Error Handling

| Scenario | Response |
|---|---|
| Invalid pair format | `st.error("Use format TOKEN/USDT")` — no DB write |
| Pair not on exchange | `st.error(f"{sym} not found on OKX/Bybit")` — no DB write |
| Pair already in list | `st.info(f"{sym} already watched")` — no DB write |
| DB error on save | Let exception propagate (SQLAlchemy logs it); user sees Streamlit traceback |

---

## Testing

- Unit tests in `tests/test_trade_logger.py`: `add_user_pair`, `remove_user_pair`, `get_user_pairs` (use existing in-memory engine fixture)
- Unit test in `tests/test_data_fetcher.py`: `validate_pair` returns True on valid symbol, False on invalid (mock the fetch)
- AppTest in `tests/test_ui_streamlit.py`: add a test that seeds a `UserPair` and confirms it appears in the multiselect options

---

## What This Does NOT Change

- `DEFAULT_PAIRS` in `config.py` — untouched, always available as options
- Refresh logic — custom pairs are refreshed by the same scheduler and "Refresh now" button (they're in `selected`, which drives the refresh loop)
- All other pages (Signal Scanner, Bot Monitor, Trade Monitor) — they receive `selected` and `payloads` unchanged
