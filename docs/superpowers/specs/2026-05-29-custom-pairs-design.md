# Custom Pair Management — Design Spec
**Date:** 2026-05-29
**Status:** Approved (updated to include Pionex stock pairs)

---

## Goal

Allow users to add arbitrary trading pairs beyond the 9 hard-coded `DEFAULT_PAIRS`, with persistence across browser refreshes via SQLite and exchange validation before saving. Supports two pair types:

- **Crypto pairs** — e.g. `LINK/USDT`, `AVAX/USDT` — validated against OKX/Bybit
- **Stock pairs** — e.g. `TSLAX/USD`, `AAPLX/USD` — Pionex-specific leveraged tokens, validated against Pionex API

---

## Pair Type Detection

A symbol is treated as a **stock pair** if its quote currency is `USD` (not `USDT`). Everything else is treated as a crypto pair.

| Input | Normalised | Type |
|---|---|---|
| `link` | `LINK/USDT` | crypto |
| `AVAX` | `AVAX/USDT` | crypto |
| `LINK/USDT` | `LINK/USDT` | crypto |
| `tslax` | `TSLAX/USD` | stock (ends in `X`) |
| `TSLAX/USD` | `TSLAX/USD` | stock |
| `AAPLX` | `AAPLX/USD` | stock (ends in `X`) |

**Normalisation rules (applied in order):**
1. Strip whitespace, uppercase
2. If `/` present → use as-is
3. If no `/` and token ends in `X` → append `/USD` (stock)
4. If no `/` and token does not end in `X` → append `/USDT` (crypto)

---

## Data Layer

### New model: `UserPair` in `trade_logger.py`

Added to the existing `Base` (same `pyonex.db`, same engine — no new DB file):

```python
class UserPair(Base):
    __tablename__ = "user_pairs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    symbol     = Column(String(32), unique=True, nullable=False, index=True)
    pair_type  = Column(String(8), nullable=False, default="crypto")  # "crypto" | "stock"
    added_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

### Helper functions added to `trade_logger.py`

| Function | Behaviour |
|---|---|
| `get_user_pairs() -> list[str]` | Returns list of symbol strings ordered by `added_at` |
| `add_user_pair(symbol: str, pair_type: str) -> None` | Upsert — insert if not exists, no-op if duplicate |
| `remove_user_pair(symbol: str) -> None` | Delete row where symbol matches; no-op if missing |

Schema is created at import time alongside existing tables (`init_db()` already calls `Base.metadata.create_all`).

---

## Validation

### Crypto pairs → `data_fetcher.validate_pair(symbol: str) -> bool`

New thin wrapper in `data_fetcher.py`:

```python
def validate_pair(symbol: str) -> bool:
    try:
        rows = fetch_klines(symbol, "4h", limit=1)
        return len(rows) > 0
    except Exception:
        return False
```

### Stock pairs → `PionexClient.validate_symbol(symbol: str) -> bool`

New method in `pionex_client.py`. Calls the Pionex public market endpoint to check if the symbol is listed.

> **Implementer note:** Verify the correct public endpoint against https://www.pionex.com/docs before coding. The likely candidate is `GET /api/v1/market/tickers` with `symbol=TSLAX_USD` (slash replaced by underscore), but confirm the response shape. If Pionex returns `result: true` and a non-empty `data` field, the symbol is valid.

```python
def validate_symbol(self, symbol: str) -> bool:
    """Check if a symbol is listed on Pionex (no auth required)."""
    try:
        data = requests.get(
            f"{_BASE}/api/v1/market/tickers",
            params={"symbol": symbol.replace("/", "_")},
            timeout=10,
        ).json()
        return bool(data.get("result") and data.get("data"))
    except Exception:
        return False
```

If `PionexClient` is **not configured** (no API keys), stock pair validation still works because the ticker endpoint is public (no auth required). The `configured` check is only skipped for this method.

If the Pionex API call fails entirely (network error, endpoint changed), fall back gracefully: show `st.warning("Could not validate with Pionex — saved anyway")` and save the pair.

---

## Sidebar UX

**Replaces** the current `st.multiselect` block in `app.py`. Minimal diff — no new page.

```
┌──────────────────────────────────────────────┐
│ Watched pairs                                │
│ [multiselect: DEFAULT_PAIRS + custom pairs]  │
│                                              │
│ [text_input: "LINK or TSLAX"]   [Add]        │
└──────────────────────────────────────────────┘
```

Placeholder text: `"Crypto: LINK or LINK/USDT · Stock: TSLAX or TSLAX/USD"`

### Render logic (runs on every sidebar render):

1. `custom = get_user_pairs()`
2. `options = DEFAULT_PAIRS + [p for p in custom if p not in DEFAULT_PAIRS]`
3. `selected = st.multiselect("Watched pairs", options, default=options, ...)`
4. **Removal detection:** `removed = set(custom) - set(selected)` → call `remove_user_pair(sym)` for each → if any removed: `st.rerun()`
5. **Add widget:**
   ```python
   col1, col2 = st.columns([3, 1])
   new_pair = col1.text_input("Add pair", placeholder="LINK or TSLAX", label_visibility="collapsed")
   add_clicked = col2.button("Add", use_container_width=True)
   ```
6. On `add_clicked` with non-empty `new_pair`:
   - Normalise → detect `pair_type` ("crypto" or "stock")
   - If `sym` already in `options`: `st.info(f"{sym} is already in your list")`
   - Else validate with spinner "Validating {sym}…":
     - Crypto: `data_fetcher.validate_pair(sym)` → False → `st.error(f"{sym} not found on OKX/Bybit")`
     - Stock: `PionexClient().validate_symbol(sym)` → False → `st.error(f"{sym} not found on Pionex")` (with graceful fallback on network error)
   - On success: `add_user_pair(sym, pair_type)` + `st.rerun()`

---

## Files Changed

| File | Change |
|---|---|
| `trade_logger.py` | Add `UserPair` model; add `get_user_pairs`, `add_user_pair(symbol, pair_type)`, `remove_user_pair` |
| `data_fetcher.py` | Add `validate_pair(symbol) -> bool` |
| `pionex_client.py` | Add `validate_symbol(symbol) -> bool` (public endpoint, no auth required) |
| `app.py` | Replace multiselect block with new logic; import new helpers |

---

## Error Handling

| Scenario | Response |
|---|---|
| Unrecognised format | `st.error("Use TOKEN/USDT for crypto or TSLAX/USD for stocks")` |
| Crypto pair not found | `st.error(f"{sym} not found on OKX/Bybit")` — no DB write |
| Stock pair not found on Pionex | `st.error(f"{sym} not found on Pionex")` — no DB write |
| Pionex API unreachable (network) | `st.warning("Could not validate with Pionex — saved anyway")` — DB write proceeds |
| Pair already in list | `st.info(f"{sym} already watched")` — no DB write |
| DB error on save | Exception propagates; Streamlit shows traceback |

---

## Testing

- `tests/test_trade_logger.py`: `add_user_pair` (crypto + stock), `remove_user_pair`, `get_user_pairs` — use existing in-memory engine fixture
- `tests/test_data_fetcher.py`: `validate_pair` returns True on mocked valid fetch, False on exception
- `tests/test_pionex_client.py`: `validate_symbol` returns True on mocked 200 response, False on failure, True with warning on network error
- `tests/test_ui_streamlit.py`: seed a `UserPair` (both types) in `ui_app` fixture, confirm it appears in multiselect options

---

## What This Does NOT Change

- `DEFAULT_PAIRS` in `config.py` — untouched, always available as options
- Refresh logic — custom pairs are in `selected`, which drives the scheduler and "Refresh now" button. Stock pairs will fail to refresh via ccxt (expected) and surface an error in the sidebar — this is acceptable for now
- All other pages — receive `selected` and `payloads` unchanged
