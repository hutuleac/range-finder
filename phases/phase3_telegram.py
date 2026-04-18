"""Phase 3 — Telegram alerts on trade recommendations.

TODO:
- Use python-telegram-bot (already pinned in requirements.txt).
- Keep a last-sent snapshot per symbol in MetricsCache payload ({"last_alert": ...}).
- Emit an alert when:
    * score crosses SCORE_BOT_MIN (7.5) upward, OR
    * direction flips Long <-> Short, OR
    * squeeze starts (detect_squeeze flips True).
- Hook point: add `maybe_alert(payload)` call at the end of refresh_data.refresh_one().
"""
