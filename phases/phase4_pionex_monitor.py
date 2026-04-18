"""Phase 4 — Pionex active-trade monitor (read-only API).

TODO:
- Pionex REST signing: HMAC-SHA256 on concatenated query string; docs: https://pionex-doc.gitbook.io/apidocs/.
- Poll /api/v1/account/balances and /api/v1/grid/openOrders every cron tick.
- For each running bot:
    * compare its range + direction to fresh recommendation from refresh_data.refresh_one()
    * if recommendation flipped or viability blocked, emit "re-recommend" alert via phase3_telegram.
- Surface the bot table in app.py (new sidebar section) with status chips.
"""
