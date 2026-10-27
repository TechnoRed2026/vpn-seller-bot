"""
Entry point — initialise bot + xui client, then start polling.
"""

import atexit
import os
import sys
import threading
import time


import telebot
from telebot import apihelper

import handlers
from config import BACKUP_CHAT_ID as _BACKUP_CHAT_ID
from config import BOT_TOKEN, PROXIES, XUI_BASE_PATH, XUI_URL, log
from xui_api import XUIClient

# ── single-instance lock (prevents Telegram 409 from two local copies) ────────
_LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")


def _acquire_single_instance_lock() -> None:
    """Refuse to start if another copy is already running on this machine."""
    if os.path.exists(_LOCK_PATH):
        try:
            with open(_LOCK_PATH, "r", encoding="utf-8") as f:
                old_pid = int((f.read() or "0").strip() or 0)
        except Exception:
            old_pid = 0

        if old_pid and _pid_alive(old_pid):
            log.error(
                "Another bot instance is already running (PID %s). "
                "Refusing to start to avoid Telegram 409 conflicts. "
                "Stop the other process or delete %s if it's stale.",
                old_pid,
                _LOCK_PATH,
            )
            sys.exit(1)
        else:
            log.warning(
                "Stale lock file found (PID %s not alive) — overwriting.", old_pid
            )

    with open(_LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(_release_lock)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            exit_code = ctypes.c_ulong()
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not h:
                return False
            try:
                if not ctypes.windll.kernel32.GetExitCodeProcess(
                    h, ctypes.byref(exit_code)
                ):
                    return False
                return exit_code.value == STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _release_lock() -> None:
    try:
        if os.path.exists(_LOCK_PATH):
            with open(_LOCK_PATH, "r", encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
            if pid == os.getpid():
                os.remove(_LOCK_PATH)
    except Exception:
        pass


if PROXIES:
    apihelper.proxy = PROXIES

apihelper.SESSION_TIME_TO_LIVE = 5 * 60

# Track startup phase to filter out panel login logs during bot initialization
_startup_complete = False


def _on_panel_login_callback(host: str, user: str) -> None:
    """Notify about XUI panel login events (skip during startup)."""
    if not _startup_complete:
        return
    handlers._notify_panel_login(host, user)


bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
xui = XUIClient(on_panel_login=_on_panel_login_callback)

if __name__ == "__main__":
    _acquire_single_instance_lock()
    handlers.register(bot, xui)
    log.info("Vpn Seller Bot starting")
    log.info("XUI API target: %s%s", XUI_URL, XUI_BASE_PATH)

    try:
        _inbounds = xui.get_inbounds()
        if _inbounds is None:
            log.warning(
                "Initial x-ui API check failed. Verify XUI_URL/XUI_BASE_PATH/XUI_API_KEY settings."
            )
        else:
            log.info("Initial x-ui API check OK (inbounds=%d)", len(_inbounds))
    except Exception as exc:
        log.warning("Initial x-ui API check exception: %s", exc)

    # ── Hourly auto-backup thread ─────────────────────────────────────
    _BACKUP_INTERVAL = 3600  # 1 hour in seconds

    def _auto_backup_loop() -> None:
        """Send an automatic backup every hour to the backup group."""
        import datetime
        import io

        while True:
            time.sleep(_BACKUP_INTERVAL)
            try:
                now = datetime.datetime.now()
                ts = now.strftime("%Y-%m-%d %H:%M:%S")
                stamp = now.strftime("%Y%m%d_%H%M%S")

                # ── 1. x-ui database backup ───────────────────────────────────
                xui_data = xui.get_db_backup()
                if xui_data:
                    bot.send_document(
                        _BACKUP_CHAT_ID,
                        telebot.types.InputFile(
                            io.BytesIO(xui_data),
                            file_name=f"x-ui_backup_{stamp}.db",
                        ),
                        caption=(
                            "💾 <b>بکاپ خودکار — پایگاه داده پنل</b>\n"
                            f"🗓 تاریخ: <code>{ts}</code>"
                        ),
                    )
                else:
                    log.warning("Auto-backup: failed to retrieve x-ui database.")

                # ── 2. data.json (wallet / purchases / referrals …) ───────────
                _DATA_PATH = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "data.json"
                )
                if os.path.exists(_DATA_PATH):
                    with open(_DATA_PATH, "rb") as f:
                        json_bytes = f.read()
                    bot.send_document(
                        _BACKUP_CHAT_ID,
                        telebot.types.InputFile(
                            io.BytesIO(json_bytes),
                            file_name=f"data_{stamp}.json",
                        ),
                        caption=(
                            "🗂 <b>بکاپ خودکار — data.json</b>\n"
                            f"🗓 تاریخ: <code>{ts}</code>"
                        ),
                    )
                else:
                    log.warning("Auto-backup: data.json not found.")

                log.info("Auto-backup sent to %s at %s", _BACKUP_CHAT_ID, ts)
            except Exception as exc:
                log.error("Auto-backup error: %s", exc)

    threading.Thread(target=_auto_backup_loop, daemon=True, name="auto-backup").start()
    log.info(
        "Auto-backup scheduled every %d seconds → chat %s",
        _BACKUP_INTERVAL,
        _BACKUP_CHAT_ID,
    )
    # ─────────────────────────────────────────────────────────────────────────

    # Ensure no webhook is set, and drop any pending updates lingering from a previous run.
    try:
        bot.remove_webhook()
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:
        log.warning("remove_webhook failed (non-fatal): %s", exc)

    # Startup complete — now handle panel login notifications
    _startup_complete = True

    conflict_backoff = 15  # seconds — used when another poller is detected
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=20)
            # infinity_polling returned without exception → proxy dropped, restart
            log.warning("Polling ended — restarting in 3 seconds…")
            time.sleep(3)
        except apihelper.ApiTelegramException as exc:
            if getattr(exc, "error_code", None) == 409:
                log.error(
                    "Telegram 409 Conflict: another getUpdates poller is active "
                    "(likely on another machine/VPS). Waiting %ss before retry.",
                    conflict_backoff,
                )
                time.sleep(conflict_backoff)
                conflict_backoff = min(conflict_backoff * 2, 300)
            else:
                log.error("Telegram API error: %s — restarting in 5 seconds…", exc)
                time.sleep(5)
        except Exception as exc:
            log.error("Bot crashed: %s — restarting in 5 seconds…", exc)
            time.sleep(5)
