"""Telegram alerts for bot events and signal transitions.

Sends a message when a bot's recommendation changes to an actionable state.
Deduplicates using a simple in-memory cache (resets on app restart).
"""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger("pyonex.telegram")

_ALERT_ACTIONS = {"CLOSE_NOW", "TAKE_PROFIT", "WARNING"}
_COOLDOWN_SEC = 1800  # don't re-alert same bot+action within 30 min
_sent_cache: dict[str, float] = {}


def _get_config() -> tuple[str, str]:
    token, chat_id = "", ""
    try:
        import streamlit as st
        token = str(st.secrets.get("TELEGRAM_BOT_TOKEN", ""))
        chat_id = str(st.secrets.get("TELEGRAM_CHAT_ID", ""))
    except Exception:
        pass
    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def is_configured() -> bool:
    token, chat_id = _get_config()
    return bool(token and chat_id)


def _send_message(text: str) -> bool:
    token, chat_id = _get_config()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        log.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("Telegram request failed: %s", e)
    return False


def _cache_key(symbol: str, action: str) -> str:
    return f"{symbol}:{action}"


def _should_send(symbol: str, action: str) -> bool:
    key = _cache_key(symbol, action)
    last = _sent_cache.get(key, 0)
    return (time.time() - last) > _COOLDOWN_SEC


def _mark_sent(symbol: str, action: str) -> None:
    _sent_cache[_cache_key(symbol, action)] = time.time()


_ACTION_EMOJI = {
    "CLOSE_NOW": "[!]",
    "TAKE_PROFIT": "[OK]",
    "WARNING": "[!!]",
}


def send_bot_alert(symbol: str, advice: dict) -> bool:
    rec = advice.get("recommendation", {})
    action = rec.get("action", "")
    if action not in _ALERT_ACTIONS:
        return False
    if not _should_send(symbol, action):
        return False

    emoji = _ACTION_EMOJI.get(action, "[i]")
    pos = advice.get("position", {})
    profit = advice.get("profit", {})
    restart = advice.get("restart")

    lines = [
        f"{emoji} <b>{action.replace('_', ' ')}</b> -- {symbol}",
        f"{rec.get('reason', '')}",
        f"Price at {pos.get('pct', 0):.0f}% of range",
        f"Grid P&L: {profit.get('gridProfitPct', 0):+.1f}%  Realized: {profit.get('realizedPct', 0):+.1f}%",
    ]

    if restart:
        lines.append("")
        lines.append(f">> <b>Restart:</b> {restart['direction']} Grid")
        lines.append(f"{restart['rangeLow']:,.4f} - {restart['rangeHigh']:,.4f} ({restart['rangeWidthPct']:.1f}%)")
        lines.append(f"{restart['grids']}g / {restart['mode']} / ~{restart['duration']}")

    text = "\n".join(lines)
    sent = _send_message(text)
    if sent:
        _mark_sent(symbol, action)
        log.info("Telegram alert sent: %s %s", symbol, action)
    return sent


def send_signal_alert(symbol: str, signal_info: dict) -> bool:
    """Alert when Signal Scanner detects a high-urgency setup."""
    urgency = signal_info.get("urgency", {})
    if urgency.get("level") not in ("URGENT",):
        return False
    sig = signal_info.get("signal_type", {})
    if not _should_send(symbol, f"signal:{sig.get('type', '')}"):
        return False

    lines = [
        f"!! <b>SIGNAL: {sig.get('type', '').replace('_', ' ')}</b> -- {symbol}",
        f"Setup Score: {signal_info.get('score', 0):.1f} ({signal_info.get('label', '')})",
        f"Direction: {sig.get('direction', '')}",
        f"ETA: {signal_info.get('eta', {}).get('label', 'Unknown')}",
        f"{sig.get('reason', '')}",
    ]

    text = "\n".join(lines)
    sent = _send_message(text)
    if sent:
        _mark_sent(symbol, f"signal:{sig.get('type', '')}")
    return sent
