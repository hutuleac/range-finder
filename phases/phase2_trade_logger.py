"""Phase 2 — Trade logger + live P&L monitor.

TODO:
- Streamlit form: symbol, side, entry, SL, TP1, TP2, size, notes.
- Write to trade_logger.Trade.
- Loop over open trades on each rerun:
    * pull current price via data_fetcher
    * compute unrealised P&L
    * recommend CLOSE when: SL/TP hit OR structure flips OR score drops below 5.
- Show table with chips (OPEN / TP1 HIT / STOPPED / CLOSED).
"""
