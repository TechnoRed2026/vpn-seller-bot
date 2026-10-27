"""Notification helpers for admin log messages."""

from __future__ import annotations

import telebot

from config import LOG_GROUP_ID, log

_log_bot: telebot.TeleBot | None = None


def set_log_bot(bot: telebot.TeleBot) -> None:
    global _log_bot
    _log_bot = bot


def notify(text: str) -> None:
    """Send a log message to LOG_GROUP_ID, never raising to callers."""
    if _log_bot is None:
        return
    try:
        _log_bot.send_message(LOG_GROUP_ID, text)
    except Exception as exc:
        log.warning("_notify failed: %s", exc)


def notify_panel_login(host: str, user: str) -> None:
    """Notify about XUI panel login, never raising to callers."""
    if _log_bot is None:
        return
    try:
        text = f"🔐 ورود به پنل XUI\nمیزبان: <code>{host}</code>\nکاربر: <code>{user}</code>"
        _log_bot.send_message(LOG_GROUP_ID, text)
    except Exception as exc:
        log.warning("_notify_panel_login failed: %s", exc)
