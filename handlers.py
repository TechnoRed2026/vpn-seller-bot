"""
All Telegram bot handlers for the 3x-ui management bot.

Conversation states
───────────────────
S_TRAFFIC_EMAIL  – waiting for client email (traffic check)
S_CREATE_EMAIL   – waiting for new client email
S_CREATE_USER_ID – waiting for optional Telegram user_id to assign the config
S_CREATE_GB      – waiting for GB limit
S_CREATE_DAYS    – waiting for expiry days (text fallback)
S_ASK_INSECURE   – waiting for yes/no on allowInsecure
"""

from __future__ import annotations

import datetime
import io
import json
import re
import secrets
import string
import threading
import time
import uuid as _uuid_mod
from html import escape
from urllib.parse import urlparse

import telebot

from config import (
    ADMIN_IDS,
    BACKUP_CHAT_ID,
    CARD_NUMBER,
    FORCE_JOIN_CHANNEL_ID,
    FORCE_JOIN_CHANNEL_URL,
    PAYMENT_GROUP_ID,
    PRICE_PER_GB,
    REFERRAL_CONFIG_DAYS,
    REFERRAL_CONFIG_MB,
    REFERRAL_CONFIG_REQUIRED_REFERRALS,
    REFERRAL_ENABLED,
    SHOP_INBOUNDS,
    SUPPORT_URL,
    TEST_ACCOUNT_LIMIT,
    TEST_ACCOUNT_MB,
    TEST_ACCOUNT_MINUTES,
    TUTORIAL_TEXT,
    WG_XUI_URL,
    XUI_SUB_BASE_URL,
    XUI_URL,
    calculate_price,
    log,
)
from handler_format import (
    fmt_bytes as _fmt_bytes,
)
from handler_format import (
    fmt_expiry as _fmt_expiry,
)
from handler_format import (
    fmt_toman as _fmt_toman,
)
from handler_format import (
    fmt_uptime as _fmt_uptime,
)
from handler_format import (
    parse_toman_to_k as _parse_toman_to_k,
)
from handler_links import add_insecure_to_link as _add_insecure_to_link
from handler_notify import (
    notify as _notify,
)
from handler_notify import (
    notify_panel_login as _notify_panel_login,
)
from handler_notify import (
    set_log_bot,
)
from handler_state import (
    S_ADD_TRAFFIC,
    S_ASK_INSECURE,
    S_BL_IDENTIFIER,
    S_BL_REMOVE_USER_ID,
    S_BL_REASON,
    S_BL_USER_ID,
    S_CREATE_DAYS,
    S_CREATE_EMAIL,
    S_CREATE_GB,
    S_CREATE_USER_ID,
    S_EDIT_DAYS,
    S_EDIT_GB,
    S_RENEW_CUSTOM_GB,
    S_RENEW_GB,
    S_SHOP_CUSTOM_GB,
    S_SHOP_DAYS,
    S_SHOP_GB,
    S_SHOP_NAME,
    S_TRAFFIC_EMAIL,
    S_WALLET_AMOUNT,
    S_WALLET_PHOTO,
    S_WG_GB,
    S_WG_NAME,
    S_WG_USER_ID,
)
from handler_state import (
    clear_state as _clear_state,
)
from handler_state import (
    data as _data,
)
from handler_state import (
    states as _states,
)
from keyboards import (
    BTN_BACKUP,
    BTN_BLACKLIST_ADMIN,
    BTN_BLACKLIST_LIST,
    # customer menu
    BTN_BUY_NEW,
    BTN_CHARGE,
    BTN_CLEANUP,
    BTN_CREATE,
    BTN_MONITOR,
    BTN_MY_CFGS,
    BTN_MY_CREDIT,
    BTN_MY_SERVICES,
    BTN_MY_USAGE,
    BTN_PRICING,
    BTN_REFERRAL,
    BTN_RENEW,
    BTN_RESTART_P,
    BTN_RESTART_X,
    BTN_SERVER_STATUS,
    BTN_SHOP,
    BTN_STARTED_USERS,
    BTN_STATS,
    BTN_STATUS,
    BTN_STOP_MON,
    BTN_SUPPORT_IDS,
    BTN_TEST_ACC,
    BTN_TEST_ACC_ADMIN,
    BTN_TOGGLE_TRIAL,
    BTN_TRAFFIC,
    BTN_TUTORIAL,
    BTN_USAGE,
    BTN_WALLET,
    BTN_WIREGUARD,
    PAGE_SIZE,
    blacklist_admin_keyboard,
    blacklist_list_keyboard,
    blacklist_reason_keyboard,
    cancel_keyboard,
    cleanup_manual_list_keyboard,
    cleanup_menu_keyboard,
    client_actions_keyboard,
    client_delete_confirm_keyboard,
    clients_list_keyboard,
    config_detail_keyboard,
    create_user_target_keyboard,
    customer_menu,
    expiry_keyboard,
    force_join_keyboard,
    inbounds_keyboard,
    insecure_keyboard,
    live_monitor_keyboard,
    main_menu,
    my_configs_keyboard,
    nodes_monitor_keyboard,
    payment_admin_keyboard,
    referral_keyboard,
    renew_confirm_keyboard,
    renew_gb_keyboard,
    restart_panel_keyboard,
    services_keyboard,
    shop_confirm_keyboard,
    shop_days_keyboard,
    shop_gb_keyboard,
    shop_inbounds_keyboard,
    shop_name_keyboard,
    stats_keyboard,
    trial_toggle_keyboard,
    user_menu,
    wallet_keyboard,
)
from storage import (
    add_balance,
    deduct_balance,
    get_all_known_user_ids,
    get_all_purchases,
    get_balance,
    get_blacklist_entries,
    get_pending_payment,
    get_purchases,
    get_referral_stats,
    get_started_users,
    get_trial_enabled,
    get_trial_limit,
    get_trials_count,
    has_claimed_referral_config,
    has_used_trial,
    increase_trial_limit,
    is_user_blacklisted,
    mark_user_started,
    register_referral,
    release_referral_config,
    release_trial_slot,
    remove_pending_payment,
    remove_blacklist,
    remove_purchase,
    reserve_referral_config,
    reserve_trial_slot,
    save_pending_payment,
    save_purchase,
    set_blacklist,
    set_trial_enabled,
    set_trial_limit,
    update_purchase_fields,
)

# ── runtime monitor state ─────────────────────────────────────────────────────
_live_monitors: dict[int, threading.Event] = {}  # chat_id -> stop event
_live_monitor_msg: dict[
    int, int
] = {}  # chat_id -> last monitor message_id (persisted across restarts)
_live_monitor_last_text: dict[int, str] = {}  # chat_id -> last rendered text

# ── server status cache — refreshed by a background poller every 10s ──────────
_SERVER_STATUS_INTERVAL = 10  # seconds
_server_status_cache: dict[str, str] = {}  # outbound tag -> formatted status text
_server_status_lock = threading.Lock()


def _classify_outbound_test(obj: dict | None) -> str:
    """Map the panel's outbound-test result to one of the 3 customer-facing states."""
    if not isinstance(obj, dict):
        return "Unkown / Unkown"
    status_code = obj.get("statusCode")
    if obj.get("success") and isinstance(status_code, int) and 200 <= status_code < 300:
        return f"{status_code} - OK"
    if status_code == -1 or obj.get("success") is False:
        return "-1 / Failed"
    return "Unkown / Unkown"


def _refresh_server_status_once(xui) -> None:
    all_outbounds = (xui.get_xray_config() or {}).get("xraySetting", {}).get(
        "outbounds"
    ) or []
    visible = [
        ob
        for ob in all_outbounds
        if isinstance(ob, dict)
        and str(ob.get("tag", "")).strip().lower() not in {"direct", "blackhole", "blocked"}
    ]
    results = {}
    for ob in visible:
        tag = str(ob.get("tag", "")).strip() or "—"
        test_obj = xui.test_outbound(ob, all_outbounds, mode="http")
        results[tag] = _classify_outbound_test(test_obj)
    with _server_status_lock:
        _server_status_cache.clear()
        _server_status_cache.update(results)


def _server_status_poller_loop(xui) -> None:
    while True:
        try:
            _refresh_server_status_once(xui)
        except Exception as exc:
            log.error("Server status poller error: %s", exc)
        time.sleep(_SERVER_STATUS_INTERVAL)


def _start_server_status_poller(xui) -> None:
    threading.Thread(
        target=_server_status_poller_loop,
        args=(xui,),
        daemon=True,
        name="server-status-poller",
    ).start()


def _format_server_status_message() -> str:
    with _server_status_lock:
        snapshot = dict(_server_status_cache)
    lines = ["📡 <b>لیست و وضعیت سرورها</b>", "━━━━━━━━━━━━━━━━━━"]
    if not snapshot:
        lines.append("⏳ اطلاعات سرورها هنوز آماده نشده. چند لحظه دیگر دوباره تلاش کنید.")
    else:
        for tag, status in snapshot.items():
            lines.append(f"🌍 <b>{tag}</b>\n   ● Status : {status}")
    return "\n".join(lines)

_CLEANUP_PAGE_SIZE = 5

# ── All reply-keyboard menu button labels in one set for fast lookup ──────────
# (BTN_* constants are imported from keyboards.py — single source of truth)
_ALL_MENU_BTNS = {
    BTN_TRAFFIC,
    BTN_CREATE,
    BTN_WIREGUARD,
    BTN_STATUS,
    BTN_BACKUP,
    BTN_RESTART_X,
    BTN_RESTART_P,
    BTN_STATS,
    BTN_STARTED_USERS,
    BTN_CLEANUP,
    BTN_MONITOR,
    BTN_STOP_MON,
    BTN_TOGGLE_TRIAL,
    BTN_SHOP,
    BTN_WALLET,
    BTN_MY_CFGS,
    BTN_CHARGE,
    BTN_USAGE,
    BTN_BLACKLIST_ADMIN,
    BTN_BLACKLIST_LIST,
    # customer menu
    BTN_BUY_NEW,
    BTN_TEST_ACC,
    BTN_PRICING,
    BTN_TEST_ACC_ADMIN,
    BTN_RENEW,
    BTN_MY_USAGE,
    BTN_MY_CREDIT,
    BTN_MY_SERVICES,
    BTN_REFERRAL,
    BTN_SERVER_STATUS,
    BTN_TUTORIAL,
    BTN_SUPPORT_IDS,
}


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


_bot_username_cache: str | None = None


def _online_set(xui) -> set[str]:
    """Return casefolded online identifiers for robust matching."""
    return {
        str(item).strip().casefold()
        for item in (xui.get_online_clients() or [])
        if str(item).strip()
    }


def _is_blocked(uid: int) -> bool:
    return is_user_blacklisted(uid)


def _send_blacklist_denied(bot: telebot.TeleBot, chat_id: int) -> None:
    bot.send_message(
        chat_id,
        "⛔️ شما در لیست بلک‌لیست قرار گرفتین و امکان استفاده از ربات را ندارید.",
    )


def _is_force_join_member(bot: telebot.TeleBot, uid: int) -> bool:
    if not FORCE_JOIN_CHANNEL_ID or _is_admin(uid):
        return True
    try:
        member = bot.get_chat_member(FORCE_JOIN_CHANNEL_ID, uid)
    except Exception as exc:
        log.warning("Force-join membership check failed for %s: %s", uid, exc)
        return False

    status = getattr(member, "status", "")
    if status == "restricted":
        return bool(getattr(member, "is_member", False))
    return status in ("creator", "administrator", "member")


def _send_force_join(bot: telebot.TeleBot, chat_id: int) -> None:
    bot.send_message(
        chat_id,
        "برای استفاده از ربات، ابتدا عضو کانال زیر شوید و بعد دکمه بررسی عضویت را بزنید:",
        reply_markup=force_join_keyboard(FORCE_JOIN_CHANNEL_URL),
    )


def _ensure_force_join(bot: telebot.TeleBot, uid: int, chat_id: int) -> bool:
    if _is_force_join_member(bot, uid):
        return True
    _send_force_join(bot, chat_id)
    return False


def _show_blacklist_page(
    bot: telebot.TeleBot,
    chat_id: int,
    page: int = 0,
    admin_mode: bool = False,
) -> None:
    rows = get_blacklist_entries()
    total = len(rows)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    lines = [
        f"🚫 <b>لیست کاربران بلک‌لیست</b> — صفحه {page + 1} از {total_pages}",
        "━━━━━━━━━━━━━━━━━━",
        f"📦 تعداد کل: <b>{total}</b>",
        "",
    ]
    if not page_rows:
        lines.append("لیست بلک‌لیست خالی است.")
    else:
        for i, row in enumerate(page_rows, start=page * PAGE_SIZE + 1):
            identifier = row.get("identifier") or "—"
            reason = row.get("reason") or "—"
            lines.append(
                f"{i}. 👤 <code>{identifier}</code> | 🆔 <code>{row['user_id']}</code>\n"
                f"   • دلیل: {reason}"
            )

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=blacklist_list_keyboard(page, total_pages, admin_mode=admin_mode),
    )


def _apply_blacklist(
    bot: telebot.TeleBot,
    chat_id: int,
    target_uid: int,
    identifier: str,
    reason: str,
    actor_uid: int,
) -> None:
    set_blacklist(target_uid, identifier, reason, actor_uid)
    bot.send_message(
        chat_id,
        "✅ کاربر با موفقیت به بلک‌لیست اضافه شد.\n"
        f"👤 آیدی: <code>{identifier}</code>\n"
        f"🆔 یوزر آیدی: <code>{target_uid}</code>\n"
        f"📌 دلیل: {reason}",
        reply_markup=main_menu(),
    )
    try:
        bot.send_message(
            target_uid,
            "⛔️ شما در لیست بلک‌لیست قرار گرفتین و امکان استفاده از ربات را ندارید."
            f"\n📌 دلیل: {reason}",
        )
    except Exception:
        pass


def _current_trial_limit() -> int:
    """Current runtime trial limit (0 = unlimited)."""
    return get_trial_limit(TEST_ACCOUNT_LIMIT)


def _is_client_addable_inbound(inbound: dict) -> bool:
    """Return True when inbound supports addClient flow for normal users."""
    proto = str((inbound or {}).get("protocol") or "").strip().lower()
    if not proto or proto in {"wireguard", "dokodemo-door"}:
        return False

    allowed = {"vmess", "vless", "trojan", "shadowsocks", "socks", "http"}
    if proto in allowed:
        return True

    try:
        settings = json.loads((inbound or {}).get("settings", "{}") or "{}")
    except Exception:
        return False
    clients = settings.get("clients")
    return isinstance(clients, list)


def _client_create_inbounds(xui) -> list:
    """List inbounds suitable for admin create-user wizard."""
    return [
        inb for inb in (xui.get_inbounds() or []) if _is_client_addable_inbound(inb)
    ]


def _panel_client_exists(xui, inbound_id: int, email: str) -> bool:
    """Robust existence check using email/comment (not remark)."""
    target = str(email or "").strip().casefold()
    if not target:
        return False

    inbound = xui.get_inbound(inbound_id)
    if isinstance(inbound, dict):
        try:
            settings = json.loads(inbound.get("settings", "{}") or "{}")
        except Exception:
            settings = {}

        has_lists = isinstance(settings.get("clients"), list) or isinstance(
            settings.get("peers"), list
        )

        for c in settings.get("clients") or []:
            if not isinstance(c, dict):
                continue
            c_email = str(c.get("email") or "").strip().casefold()
            c_comment = str(c.get("comment") or "").strip().casefold()
            if target in {c_email, c_comment}:
                return True

        for p in settings.get("peers") or []:
            if not isinstance(p, dict):
                continue
            p_email = str(p.get("email") or "").strip().casefold()
            p_comment = str(p.get("comment") or "").strip().casefold()
            if target in {p_email, p_comment}:
                return True

        if has_lists:
            # Settings contains explicit client/peer lists and no match was found.
            # Treat as deleted to avoid stale traffic endpoint false-positives.
            return False

    # Fallback for uncommon panels that don't expose clients/peers in settings.
    for item in xui.get_client_traffics_by_inbound(inbound_id):
        if not isinstance(item, dict):
            continue
        c_email = str(item.get("email") or "").strip().casefold()
        c_comment = str(item.get("comment") or "").strip().casefold()
        if target in {c_email, c_comment}:
            return True

    return False


def _sync_deleted_panel_configs(xui) -> int:
    """Delete Telegram purchase records for configs removed from panel."""
    inbounds = xui.get_inbounds() or []
    if not inbounds:
        return 0

    known_inbound_ids = {
        int(inb.get("id"))
        for inb in inbounds
        if isinstance(inb, dict) and inb.get("id") is not None
    }

    removed_count = 0
    for p in get_all_purchases():
        uid = p.get("user_id")
        email = str(p.get("email") or "").strip()
        iid_raw = p.get("inbound_id")
        if uid is None or not email or iid_raw is None:
            continue
        try:
            user_id = int(uid)
            inbound_id = int(iid_raw)
        except Exception:
            continue

        exists = inbound_id in known_inbound_ids and _panel_client_exists(
            xui, inbound_id, email
        )
        if exists:
            continue

        if remove_purchase(user_id, inbound_id, email):
            removed_count += 1

    return removed_count


def _sync_deleted_panel_configs_for_user(xui, user_id: int) -> int:
    """Delete one user's purchase records that were removed from panel."""
    inbounds = xui.get_inbounds() or []
    if not inbounds:
        return 0

    known_inbound_ids = {
        int(inb.get("id"))
        for inb in inbounds
        if isinstance(inb, dict) and inb.get("id") is not None
    }

    removed_count = 0
    for p in get_purchases(user_id):
        email = str(p.get("email") or "").strip()
        iid_raw = p.get("inbound_id")
        if not email or iid_raw is None:
            continue
        try:
            inbound_id = int(iid_raw)
        except Exception:
            continue

        exists = inbound_id in known_inbound_ids and _panel_client_exists(
            xui, inbound_id, email
        )
        if exists:
            continue

        if remove_purchase(user_id, inbound_id, email):
            removed_count += 1

    return removed_count


def _is_test_config_email(email: str) -> bool:
    e = str(email or "").strip().casefold()
    return e.startswith("trial_") or e.startswith("admin_")


def _is_referral_config_email(email: str) -> bool:
    return str(email or "").strip().casefold().startswith("referral_")


def _collect_ended_clients(xui, kind: str = "all") -> list[dict]:
    """Collect ended clients from panel by usage/expiry/disabled, optionally filtered by kind."""
    inbounds = xui.get_inbounds() or []
    now_ms = int(time.time() * 1000)
    rows: list[dict] = []
    seen: set[tuple[int, str]] = set()

    for inb in inbounds:
        iid_raw = inb.get("id")
        if iid_raw is None:
            continue
        try:
            inbound_id = int(iid_raw)
        except Exception:
            continue

        for c in inb.get("clientStats") or []:
            email = str(c.get("email") or "").strip()
            if not email:
                continue

            key = (inbound_id, email.casefold())
            if key in seen:
                continue
            seen.add(key)

            up = int(c.get("up", 0) or 0)
            down = int(c.get("down", 0) or 0)
            total = int(c.get("total", 0) or 0)
            expiry = int(c.get("expiryTime", 0) or 0)
            enabled = c.get("enable", True)
            used = up + down

            depleted = total > 0 and used >= total
            expired = expiry > 0 and expiry <= now_ms
            disabled = enabled is False
            ended = depleted or expired or disabled
            if not ended:
                continue

            is_test = _is_test_config_email(email)
            is_ref = _is_referral_config_email(email)
            if kind == "test" and not is_test:
                continue
            if kind == "ref" and not is_ref:
                continue

            reasons = []
            if depleted:
                reasons.append("اتمام حجم")
            if expired:
                reasons.append("اتمام زمان")
            if disabled:
                reasons.append("غیرفعال")

            rows.append(
                {
                    "inbound_id": inbound_id,
                    "email": email,
                    "used": used,
                    "total": total,
                    "expiry": expiry,
                    "is_test": is_test,
                    "is_ref": is_ref,
                    "reason": " / ".join(reasons) or "نامشخص",
                }
            )

    rows.sort(
        key=lambda x: (
            x["expiry"] if int(x.get("expiry", 0) or 0) > 0 else 10**18,
            x["email"].casefold(),
        )
    )
    return rows


def _remove_purchase_records_for_client(inbound_id: int, email: str) -> int:
    removed = 0
    target_email = str(email or "").strip()
    try:
        target_inbound = int(inbound_id)
    except Exception:
        return 0

    for p in get_all_purchases():
        try:
            uid = int(p.get("user_id"))
            iid = int(p.get("inbound_id"))
        except Exception:
            continue
        if iid != target_inbound:
            continue
        if str(p.get("email") or "").strip() != target_email:
            continue
        if remove_purchase(uid, iid, target_email):
            removed += 1
    return removed


def _delete_ended_entries(xui, entries: list[dict]) -> tuple[int, int, int, list[str]]:
    """Delete selected ended entries from panel and cleanup purchase records."""
    ok_count = 0
    fail_count = 0
    removed_records = 0
    failed_emails: list[str] = []

    for e in entries:
        email = str(e.get("email") or "").strip()
        iid = e.get("inbound_id")
        if not email or iid is None:
            continue
        try:
            inbound_id = int(iid)
        except Exception:
            continue

        if xui.delete_client(inbound_id, email):
            ok_count += 1
            removed_records += _remove_purchase_records_for_client(inbound_id, email)
        else:
            fail_count += 1
            failed_emails.append(email)

    return ok_count, fail_count, removed_records, failed_emails


def _show_cleanup_manual_page(
    bot: telebot.TeleBot,
    xui,
    uid: int,
    chat_id: int,
    page: int = 0,
) -> None:
    entries = _collect_ended_clients(xui, kind="all")
    _data.setdefault(uid, {})["cleanup_manual_entries"] = entries

    total = len(entries)
    total_pages = max(1, (total + _CLEANUP_PAGE_SIZE - 1) // _CLEANUP_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_entries = entries[page * _CLEANUP_PAGE_SIZE : (page + 1) * _CLEANUP_PAGE_SIZE]

    if not entries:
        bot.send_message(
            chat_id,
            "✅ کانفیگ تمام‌شده‌ای برای حذف دستی پیدا نشد.",
            reply_markup=cleanup_menu_keyboard(),
        )
        return

    view_entries = []
    start_idx = page * _CLEANUP_PAGE_SIZE
    for i, e in enumerate(page_entries, start=start_idx):
        badges = []
        if e.get("is_test"):
            badges.append("🧪")
        if e.get("is_ref"):
            badges.append("🎁")
        badge = "".join(badges) if badges else "📦"
        label = f"{badge} {e['email']} | {e['reason']}"
        if len(label) > 58:
            label = label[:57] + "…"
        view_entries.append({"idx": i, "label": label})

    bot.send_message(
        chat_id,
        "🛠 <b>حذف دستی کانفیگ‌های تمام‌شده</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 تعداد کل: <b>{total}</b>\n"
        "(هر صفحه ۵ مورد)",
        reply_markup=cleanup_manual_list_keyboard(view_entries, page, total_pages),
    )


# ── action helpers (called from multiple places) ──────────────────────────────


def _do_create(
    bot: telebot.TeleBot,
    xui,
    uid: int,
    chat_id: int,
    days: int,
) -> None:
    d = _data.get(uid, {})
    inbound_id = d.get("inbound_id")
    protocol = d.get("protocol", "vless")
    email = d.get("email", "")
    gb = d.get("gb", 0.0)
    assigned_user_id = d.get("assign_user_id")

    if not inbound_id or not email:
        _clear_state(uid)
        bot.send_message(
            chat_id,
            "❌ اطلاعات ناقص است. لطفاً دوباره تلاش کنید.",
            reply_markup=main_menu(),
        )
        return

    bot.send_chat_action(chat_id, "typing")
    ok, cid, sub_id = xui.add_client(inbound_id, protocol, email, gb, days)

    if not ok:
        _clear_state(uid)
        bot.send_message(
            chat_id,
            f"❌ خطا در ساخت کاربر <code>{email}</code>.\n"
            "احتمالاً این ایمیل قبلاً ثبت شده یا اینباند پیدا نشد.",
            reply_markup=main_menu(),
        )
        return

    # Fetch config links from panel API
    links = xui.get_client_links(inbound_id, email)

    if assigned_user_id is not None:
        try:
            assigned_user_id = int(assigned_user_id)
            save_purchase(
                assigned_user_id,
                email,
                inbound_id,
                protocol,
                gb,
                days,
                sub_id or "",
                extra={"source": "admin_create", "assigned_by": uid},
            )
        except Exception as exc:
            log.warning(
                "Failed to assign admin-created config to user_id=%s: %s",
                assigned_user_id,
                exc,
            )

    # Save everything for the insecure step
    _data[uid] = {
        "pending_links": links,
        "pending_email": email,
        "pending_protocol": protocol,
        "pending_gb": gb,
        "pending_days": days,
        "pending_sub_id": sub_id or "",
        "pending_cid": cid or "",
        "pending_inbound_id": inbound_id,
        "pending_assigned_user_id": assigned_user_id,
    }
    _states[uid] = S_ASK_INSECURE

    bot.send_message(
        chat_id,
        "⚠️ کاربر ساخته شد. اکنون بگویید:\n\n"
        "🔒 آیا می‌خواهید <b>allowInsecure</b> به کانفیگ اضافه شود?\n"
        "<i>(برای سرورهایی که گواهینامه معتبر TLS ندارند)</i>",
        reply_markup=insecure_keyboard(),
    )


def _send_client_result(
    bot: telebot.TeleBot,
    uid: int,
    chat_id: int,
    add_insecure: bool,
) -> None:
    d = _data.get(uid, {})
    links = list(d.get("pending_links") or [])
    email = d.get("pending_email", "")
    protocol = d.get("pending_protocol", "?")
    gb = d.get("pending_gb", 0)
    days = d.get("pending_days", 0)
    sub_id = d.get("pending_sub_id", "")
    cid = d.get("pending_cid", "")
    assigned_user_id = d.get("pending_assigned_user_id")
    _clear_state(uid)

    if add_insecure:
        links = [_add_insecure_to_link(lnk) for lnk in links]

    gb_str = "نامحدود" if gb == 0 else f"{gb} GB"
    expiry_str = "بدون محدودیت" if days == 0 else f"{days} روز"
    insecure_badge = (
        "🔓 AllowInsecure: فعال" if add_insecure else "🔒 AllowInsecure: غیرفعال"
    )

    summary = (
        "✅ <b>کاربر با موفقیت ساخته شد</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 ایمیل:      <code>{email}</code>\n"
        f"🔌 پروتکل:    {protocol.upper()}\n"
        f"💾 حجم:       {gb_str}\n"
        f"📅 اعتبار:    {expiry_str}\n"
        f"🔑 UUID:      <code>{cid}</code>\n"
        + (
            f"🧾 تعلق به کاربر: <code>{assigned_user_id}</code>\n"
            if assigned_user_id is not None
            else ""
        )
        + f"{insecure_badge}"
    )
    bot.send_message(chat_id, summary)

    _notify(
        "➕ <b>اکانت جدید ساخته شد (ادمین)</b>\n"
        f"👤 ایمیل: <code>{email}</code>\n"
        f"🔌 پروتکل: {protocol.upper()}\n"
        f"💾 حجم: {gb_str}  |  📅 {expiry_str}"
        + (
            f"\n🧾 تعلق به کاربر: <code>{assigned_user_id}</code>"
            if assigned_user_id is not None
            else ""
        )
    )

    if assigned_user_id is not None and assigned_user_id != uid:
        try:
            bot.send_message(
                int(assigned_user_id),
                "✅ یک کانفیگ جدید توسط ادمین برای شما ثبت شد.\n"
                f"👤 نام: <code>{email}</code>\n"
                f"🔌 پروتکل: {protocol.upper()}\n"
                f"💾 حجم: {gb_str}\n"
                f"📅 اعتبار: {expiry_str}",
                reply_markup=user_menu(get_balance(int(assigned_user_id))),
            )
        except Exception:
            pass

    if links:
        bot.send_message(chat_id, f"📋 <b>کانفیگ‌ها ({len(links)}):</b>")
        for lnk in links:
            bot.send_message(chat_id, f"<code>{lnk}</code>")
    else:
        bot.send_message(
            chat_id,
            "⚠️ کانفیگ لینک از پنل دریافت نشد. از UUID بالا استفاده کنید.",
        )

    if sub_id and XUI_SUB_BASE_URL:
        sub_link = f"{XUI_SUB_BASE_URL}/sub/{sub_id}"
        bot.send_message(
            chat_id,
            f"🔗 <b>لینک اشتراک (Subscription):</b>\n<code>{sub_link}</code>",
        )

    bot.send_message(chat_id, "منوی اصلی:", reply_markup=main_menu())


def _restart_xray(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    bot.send_chat_action(chat_id, "typing")
    ok = xui.restart_xray()
    bot.send_message(
        chat_id,
        "✅ Xray با موفقیت ریستارت شد." if ok else "❌ ریستارت Xray ناموفق بود.",
        reply_markup=main_menu(),
    )
    if ok:
        _notify("🔄 <b>Xray ریستارت شد</b> (توسط ادمین)")


def _restart_panel(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    bot.send_chat_action(chat_id, "typing")
    ok = xui.restart_panel()
    bot.send_message(
        chat_id,
        "✅ پنل با موفقیت ریستارت شد. اگر چند ثانیه قطع شد، طبیعیه 🙂"
        if ok
        else "❌ ریستارت پنل ناموفق بود.",
        reply_markup=main_menu(),
    )


def _show_status(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    bot.send_chat_action(chat_id, "typing")
    status = xui.get_server_status()
    if not status:
        bot.send_message(
            chat_id, "❌ خطا در دریافت وضعیت سرور.", reply_markup=main_menu()
        )
        return

    cpu = status.get("cpu", 0)
    mem = status.get("mem", {})
    disk = status.get("disk", {})
    xray_info = status.get("xray", {})
    uptime = status.get("uptime", 0)
    net_traffic = status.get("netTraffic", {})
    net_io = status.get("netIO", {})
    public_ip = status.get("publicIP", {})
    tcp_count = status.get("tcpCount", 0)
    udp_count = status.get("udpCount", 0)

    mem_used = mem.get("current", 0)
    mem_total = mem.get("total", 0)
    mem_pct = (mem_used / mem_total * 100) if mem_total else 0

    disk_used = disk.get("current", 0)
    disk_total = disk.get("total", 0)
    disk_pct = (disk_used / disk_total * 100) if disk_total else 0

    xray_state = xray_info.get("state", "?")
    xray_ver = xray_info.get("version", "?")

    msg = (
        "🖥 <b>وضعیت سرور</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🌐 IP:       <code>{public_ip.get('ipv4', '?')}</code>\n"
        f"⏱ آپتایم:   {_fmt_uptime(uptime)}\n"
        f"⚡️ CPU:      {cpu:.1f}%\n"
        f"🧠 RAM:      {_fmt_bytes(mem_used)} / {_fmt_bytes(mem_total)} ({mem_pct:.1f}%)\n"
        f"💿 دیسک:    {_fmt_bytes(disk_used)} / {_fmt_bytes(disk_total)} ({disk_pct:.1f}%)\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔷 Xray:    {xray_state}  |  v{xray_ver}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📤 ارسال کل:   {_fmt_bytes(net_traffic.get('sent', 0))}\n"
        f"📥 دریافت کل:  {_fmt_bytes(net_traffic.get('recv', 0))}\n"
        f"⬆️ I/O up:   {_fmt_bytes(net_io.get('up', 0))}/s\n"
        f"⬇️ I/O down: {_fmt_bytes(net_io.get('down', 0))}/s\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔌 TCP:      {tcp_count}\n"
        f"📡 UDP:      {udp_count}"
    )
    bot.send_message(chat_id, msg, reply_markup=main_menu())


def _send_backup(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    bot.send_chat_action(chat_id, "upload_document")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ts_display = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    any_sent = False
    errors = []

    # ── 1. x-ui database ───────────────────────────────────────────────
    xui_data = xui.get_db_backup()
    if xui_data:
        db_caption = f"💾 <b>بکاپ پایگاه داده پنل</b>\n🗓 <code>{ts_display}</code>"
        bot.send_document(
            chat_id,
            telebot.types.InputFile(
                io.BytesIO(xui_data), file_name=f"x-ui_backup_{ts}.db"
            ),
            caption=db_caption,
        )
        if chat_id != BACKUP_CHAT_ID:
            bot.send_document(
                BACKUP_CHAT_ID,
                telebot.types.InputFile(
                    io.BytesIO(xui_data), file_name=f"x-ui_backup_{ts}.db"
                ),
                caption=db_caption,
            )
        any_sent = True
    else:
        errors.append("پایگاه داده پنل")

    # ── 2. data.json ────────────────────────────────────────────────────
    import os as _os

    _data_path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "data.json"
    )
    if _os.path.exists(_data_path):
        with open(_data_path, "rb") as f:
            json_bytes = f.read()
        json_caption = f"🗂 <b>data.json</b>\n🗓 <code>{ts_display}</code>"
        bot.send_document(
            chat_id,
            telebot.types.InputFile(
                io.BytesIO(json_bytes), file_name=f"data_{ts}.json"
            ),
            caption=json_caption,
        )
        if chat_id != BACKUP_CHAT_ID:
            bot.send_document(
                BACKUP_CHAT_ID,
                telebot.types.InputFile(
                    io.BytesIO(json_bytes), file_name=f"data_{ts}.json"
                ),
                caption=json_caption,
            )
        any_sent = True
    else:
        errors.append("data.json")

    if errors:
        bot.send_message(
            chat_id,
            "⚠️ خطا در دریافت: " + "، ".join(errors),
            reply_markup=main_menu(),
        )
    if any_sent:
        msg = "✅ بکاپ ارسال شد."
        if chat_id != BACKUP_CHAT_ID:
            msg += f" (کانال بکاپ <code>{BACKUP_CHAT_ID}</code> هم فوروارد شد)"
        bot.send_message(chat_id, msg, reply_markup=main_menu())


def _show_users_stats(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    bot.send_chat_action(chat_id, "typing")
    inbounds = xui.get_inbounds() or []
    onlines = _online_set(xui)
    now_ms = int(time.time() * 1000)

    total_users = 0
    ended_users: list[str] = []

    for inb in inbounds:
        client_stats = inb.get("clientStats") or []
        total_users += len(client_stats)

        for c in client_stats:
            email = (c.get("email") or "").strip()
            if not email:
                continue
            up = int(c.get("up", 0) or 0)
            down = int(c.get("down", 0) or 0)
            total = int(c.get("total", 0) or 0)
            expiry = int(c.get("expiryTime", 0) or 0)
            disabled = c.get("enable") is False

            depleted = total > 0 and (up + down) >= total
            expired = expiry > 0 and expiry <= now_ms

            if depleted or expired or disabled:
                reasons = []
                if depleted:
                    reasons.append("حجم")
                if expired:
                    reasons.append("انقضا")
                if disabled:
                    reasons.append("غیرفعال")
                ended_users.append(f"{email} ({' / '.join(reasons)})")

    online_count = len(onlines)
    ended_count = len(ended_users)

    msg = (
        "👥 <b>آمار کاربران</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 کل کاربران: <b>{total_users}</b>\n"
        f"🟢 کاربران آنلاین: <b>{online_count}</b>\n"
        f"⛔ کاربران تمام‌شده: <b>{ended_count}</b>\n"
    )

    if onlines:
        sample_online = list(onlines)[:20]
        msg += "\n🟢 <b>نمونه آنلاین‌ها:</b>\n" + "\n".join(
            f"• <code>{e}</code>" for e in sample_online
        )
        if online_count > 20:
            msg += f"\n... و {online_count - 20} کاربر دیگر"

    if ended_users:
        sample_ended = ended_users[:30]
        msg += "\n\n⛔ <b>نمونه کاربران تمام‌شده:</b>\n" + "\n".join(
            f"• <code>{e}</code>" for e in sample_ended
        )
        if ended_count > 30:
            msg += f"\n... و {ended_count - 30} کاربر دیگر"

    bot.send_message(chat_id, msg, reply_markup=stats_keyboard())


def _show_started_users(bot: telebot.TeleBot, chat_id: int) -> None:
    users = get_started_users()
    total = len(users)
    if total == 0:
        bot.send_message(
            chat_id,
            "👥 <b>کاربران استارت‌زده</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "تاکنون هیچ کاربری ربات را استارت نکرده است.",
            reply_markup=main_menu(),
        )
        return

    lines = []
    for i, u in enumerate(users, start=1):
        uid = u["user_id"]
        uname = f"@{u['username']}" if u["username"] else "—"
        full_name = (
            " ".join(x for x in [u["first_name"], u["last_name"]] if x).strip() or "—"
        )
        lines.append(f"{i}. <code>{uid}</code> | {uname} | {full_name}")

    title = (
        f"👥 <b>کاربران استارت‌زده</b>\n━━━━━━━━━━━━━━━━━━\nتعداد کل: <b>{total}</b>\n\n"
    )
    chunk = title
    for line in lines:
        if len(chunk) + len(line) + 1 > 3800:
            bot.send_message(chat_id, chunk)
            chunk = line
        else:
            chunk = f"{chunk}\n{line}" if chunk else line

    bot.send_message(chat_id, chunk, reply_markup=main_menu())


def _build_live_monitor_text(status: dict) -> str:
    net_io = status.get("netIO", {})
    cpu = status.get("cpu", 0)
    mem = status.get("mem", {})
    uptime = status.get("uptime", 0)
    tcp_count = status.get("tcpCount", 0)
    udp_count = status.get("udpCount", 0)
    ts = datetime.datetime.now().strftime("%H:%M:%S")

    return (
        "📡 <b>TRAFFIC LIVE MONITOR</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕒 {ts}\n"
        f"⏱ آپتایم: {_fmt_uptime(uptime)}\n"
        f"⚡ CPU: {cpu:.1f}%\n"
        f"🧠 RAM: {_fmt_bytes(mem.get('current', 0))} / {_fmt_bytes(mem.get('total', 0))}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⬆️ UP/s: {_fmt_bytes(net_io.get('up', 0))}\n"
        f"⬇️ DOWN/s: {_fmt_bytes(net_io.get('down', 0))}\n"
        f"🔌 TCP: {tcp_count}   📡 UDP: {udp_count}\n"
        "\n<i>هر 2 ثانیه آپدیت می‌شود... برای توقف، دکمه ⏹ توقف مانیتور را بزنید.</i>"
    )


def _build_nodes_monitor_text(xui) -> str:
    inbounds = xui.get_inbounds() or []
    onlines = _online_set(xui)
    now_ms = int(time.time() * 1000)
    ts = datetime.datetime.now().strftime("%H:%M:%S")

    if not inbounds:
        return "❌ هیچ نودی (inbound) برای مانیتور پیدا نشد."

    lines = [
        "🧩 <b>مانیتور نودها</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🕒 {ts}",
    ]

    total_clients = 0
    total_online = 0

    for inb in inbounds:
        iid = inb.get("id", "?")
        remark = (inb.get("remark") or "بدون نام").strip()
        proto = (inb.get("protocol") or "?").upper()
        port = inb.get("port", "?")
        client_stats = inb.get("clientStats") or []

        valid_clients = [c for c in client_stats if (c.get("email") or "").strip()]
        c_total = len(valid_clients)
        c_online = 0
        c_depleted = 0
        c_expired = 0
        used_sum = 0

        for c in valid_clients:
            email = (c.get("email") or "").strip()
            up = int(c.get("up", 0) or 0)
            down = int(c.get("down", 0) or 0)
            total = int(c.get("total", 0) or 0)
            expiry = int(c.get("expiryTime", 0) or 0)

            used_sum += up + down
            email_cf = email.casefold()
            if email_cf in onlines or any(
                email_cf and email_cf in tok for tok in onlines
            ):
                c_online += 1
            if total > 0 and (up + down) >= total:
                c_depleted += 1
            if expiry > 0 and expiry <= now_ms:
                c_expired += 1

        total_clients += c_total
        total_online += c_online

        lines.append(
            f"\n🔹 <b>{remark}</b>  (<code>ID:{iid}</code>)\n"
            f"🔌 {proto} :{port}\n"
            f"👥 کاربران: {c_total}  |  🟢 آنلاین: {c_online}\n"
            f"📦 مصرف مجموع: {_fmt_bytes(used_sum)}\n"
            f"⛔ اتمام‌حجم: {c_depleted}  |  ⏳ منقضی: {c_expired}"
        )

    lines.insert(
        3,
        f"📊 مجموع کاربران: <b>{total_clients}</b>  |  🟢 آنلاین: <b>{total_online}</b>",
    )
    lines.append("\n<i>برای آپدیت، دکمه «رفرش نودها» را بزنید.</i>")
    return "\n".join(lines)


def _start_live_monitor(bot: telebot.TeleBot, xui, chat_id: int) -> None:
    # If a monitor is already running in this chat, do NOT start a second one
    # (prevents sending a fresh message on every button press).
    prev = _live_monitors.get(chat_id)
    if prev and not prev.is_set():
        log.info("Live monitor already running for chat %s; ignoring restart", chat_id)
        return

    stop_event = threading.Event()
    _live_monitors[chat_id] = stop_event

    def _worker() -> None:
        # Reuse the previous monitor message_id if we still have one,
        # so re-pressing the button after stop continues editing the same message.
        msg_id = _live_monitor_msg.get(chat_id)
        base_interval = 2.0
        while not stop_event.is_set():
            wait_seconds = base_interval
            try:
                status = xui.get_server_status()
            except Exception as _exc:
                log.debug("Live monitor: status fetch failed: %s", _exc)
                status = None
            if not status:
                text = "❌ خطا در دریافت وضعیت سرور برای مانیتور زنده."
            else:
                text = _build_live_monitor_text(status)

            try:
                if msg_id is None:
                    # Keep this message editable: do not attach reply keyboard markup.
                    sent = bot.send_message(chat_id, text, parse_mode="HTML")
                    msg_id = sent.message_id
                    _live_monitor_msg[chat_id] = msg_id
                    _live_monitor_last_text[chat_id] = text
                else:
                    # Skip API call entirely if text is identical to last render
                    if _live_monitor_last_text.get(chat_id) == text:
                        stop_event.wait(wait_seconds)
                        continue
                    bot.edit_message_text(
                        text,
                        chat_id,
                        msg_id,
                        parse_mode="HTML",
                    )
                    _live_monitor_last_text[chat_id] = text
            except Exception as exc:
                err = str(exc).lower()
                if "message is not modified" in err:
                    pass  # harmless — content unchanged
                elif "retry after" in err or "too many requests" in err:
                    # Telegram rate limit: keep same message_id and back off.
                    m = re.search(r"retry after\s*(\d+)", err)
                    retry_after = int(m.group(1)) if m else 2
                    wait_seconds = max(base_interval, float(retry_after) + 0.2)
                    log.info(
                        "Live monitor rate-limited; backing off %.1fs", wait_seconds
                    )
                elif (
                    "message to edit not found" in err
                    or "message_id_invalid" in err
                    or "message can't be edited" in err
                    or "message can not be edited" in err
                ):
                    # Message was removed or became non-editable: recreate once.
                    log.info("Live monitor target message lost/uneditable; recreating")
                    msg_id = None
                    _live_monitor_msg.pop(chat_id, None)
                    _live_monitor_last_text.pop(chat_id, None)
                else:
                    # Transient issue: keep same message_id to avoid spam.
                    log.warning(
                        "Live monitor update issue (kept same message): %s", exc
                    )

            stop_event.wait(wait_seconds)
        # thread exits silently; the stop callback already notified the user

    threading.Thread(target=_worker, daemon=True).start()


def _stop_live_monitor(chat_id: int) -> bool:
    ev = _live_monitors.get(chat_id)
    if not ev:
        return False
    ev.set()
    return True


# ── client list helpers ───────────────────────────────────────────────────────


def _build_clients_list(xui) -> list:
    """Return flat list of all clients across inbounds with status emoji."""
    inbounds = xui.get_inbounds() or []
    onlines = _online_set(xui)
    now_ms = int(time.time() * 1000)
    result = []
    for inb in inbounds:
        iid = inb.get("id")
        if not iid:
            continue
        for c in inb.get("clientStats") or []:
            email = (c.get("email") or "").strip()
            if not email:
                continue
            up = int(c.get("up", 0) or 0)
            down = int(c.get("down", 0) or 0)
            total = int(c.get("total", 0) or 0)
            expiry = int(c.get("expiryTime", 0) or 0)
            enabled = c.get("enable", True)
            depleted = total > 0 and (up + down) >= total
            expired = expiry > 0 and expiry <= now_ms
            if not enabled or depleted or expired:
                emoji = "🔴"
            elif email.casefold() in onlines or any(
                email and email.casefold() in tok for tok in onlines
            ):
                emoji = "🟢"
            else:
                emoji = "⚪"
            result.append(
                {
                    "email": email,
                    "inbound_id": int(iid),
                    "up": up,
                    "down": down,
                    "total": total,
                    "expiry": expiry,
                    "enable": enabled,
                    "emoji": emoji,
                }
            )
    return result


def _show_clients_list_page(
    bot: telebot.TeleBot, xui, chat_id: int, page: int = 0
) -> None:
    entries = _build_clients_list(xui)
    total = len(entries)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_entries = entries[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    msg = (
        f"👥 <b>لیست کاربران</b> — صفحه {page + 1} از {total_pages}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📦 مجموع: <b>{total}</b> کاربر\n"
        "🟢 آنلاین  ⚪ معمولی  🔴 غیرفعال/تمام‌شده"
    )
    bot.send_message(
        chat_id,
        msg,
        reply_markup=clients_list_keyboard(page_entries, page, total_pages),
    )


def _show_client_info(
    bot: telebot.TeleBot, xui, chat_id: int, inbound_id: int, email: str
) -> None:
    traffic = xui.get_client_traffic(email)
    if not traffic:
        bot.send_message(
            chat_id,
            f"❌ کاربر <code>{email}</code> پیدا نشد.",
            reply_markup=main_menu(),
        )
        return
    up = int(traffic.get("up", 0) or 0)
    down = int(traffic.get("down", 0) or 0)
    total = int(traffic.get("total", 0) or 0)
    expiry = int(traffic.get("expiryTime", 0) or 0)
    enabled = traffic.get("enable", True)
    used = up + down
    remain = (total - used) if total > 0 else None
    status = "✅ فعال" if enabled else "❌ غیرفعال"
    msg = (
        "👤 <b>اطلاعات کاربر</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📧 ایمیل:        <code>{email}</code>\n"
        f"📶 وضعیت:       {status}\n"
        f"⬆️ آپلود:         {_fmt_bytes(up)}\n"
        f"⬇️ دانلود:        {_fmt_bytes(down)}\n"
        f"📦 مجموع مصرف: {_fmt_bytes(used)}\n"
        f"💾 حجم کل:      {'♾ نامحدود' if total == 0 else _fmt_bytes(total)}\n"
        + (f"📉 باقیمانده:   {_fmt_bytes(remain)}\n" if remain is not None else "")
        + f"⏳ انقضا:        {_fmt_expiry(expiry)}"
    )
    bot.send_message(
        chat_id, msg, reply_markup=client_actions_keyboard(inbound_id, email)
    )


# ── wallet / shop helpers ─────────────────────────────────────────────────────


def _auto_select_inbound(xui) -> dict | None:
    """
    Return the inbound with the fewest current clients among allowed inbounds.
    Filtered by SHOP_INBOUNDS remark names (case-insensitive); if empty, all inbounds allowed.
    """
    inbounds = xui.get_inbounds() or []
    allowed = [s.lower() for s in SHOP_INBOUNDS]
    filtered = [
        inb
        for inb in inbounds
        if not allowed or (inb.get("remark") or "").lower() in allowed
    ]
    if not filtered:
        filtered = inbounds  # fallback: use all
    return min(
        filtered, key=lambda inb: len(inb.get("clientStats") or []), default=None
    )


def _wireguard_peers_count(inbound: dict) -> int:
    """Return number of peers in a WireGuard inbound settings payload."""
    try:
        settings = json.loads((inbound or {}).get("settings", "{}") or "{}")
        peers = settings.get("peers") or []
        return len(peers) if isinstance(peers, list) else 0
    except Exception:
        return 0


def _build_wg_config_text(peer: dict, server_host: str, inbound_port: int) -> str:
    """Build a WireGuard .conf file content from peer data."""
    private_key = peer.get("privateKey", "")
    address = (peer.get("allowedIPs") or ["10.0.0.2/32"])[0]
    server_pubkey = peer.get("_server_public_key", "")
    mtu = int(peer.get("_mtu") or 1420)
    keepalive = int(peer.get("keepAlive") or 0) or 25
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {address}\n"
        "DNS = 1.1.1.1, 1.0.0.1\n"
        f"MTU = {mtu}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_pubkey}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"Endpoint = {server_host}:{inbound_port}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )


def _auto_select_wireguard_inbound(xui) -> dict | None:
    """Pick a WireGuard inbound (prefers SHOP_INBOUNDS filter, then least peers)."""
    all_inbounds = xui.get_inbounds() or []
    wg_inbounds = [
        inb
        for inb in all_inbounds
        if str(inb.get("protocol", "")).lower() == "wireguard"
    ]
    if not wg_inbounds:
        return None

    if SHOP_INBOUNDS:
        allowed_set = set(SHOP_INBOUNDS)
        filtered = [
            inb for inb in wg_inbounds if (inb.get("remark") or "") in allowed_set
        ]
        if filtered:
            wg_inbounds = filtered

    return min(
        wg_inbounds,
        key=lambda inb: (_wireguard_peers_count(inb), int(inb.get("id", 0))),
    )


def _register_referral_from_start(
    bot: telebot.TeleBot, uid: int, text: str | None
) -> None:
    referrer_id = _parse_referrer_id(text)
    if referrer_id is None:
        return

    ok_ref, ref_reason, ref_balance = register_referral(uid, referrer_id, 0)
    if ok_ref:
        try:
            bot.send_message(
                referrer_id,
                "🎉 <b>دعوت موفق!</b>\n"
                "یک کاربر جدید با لینک شما عضو شد و یک دعوت موفق برای شما ثبت شد.\n"
                f"🎁 با {REFERRAL_CONFIG_REQUIRED_REFERRALS} دعوت موفق می‌توانید کانفیگ رفرال بگیرید.",
                reply_markup=user_menu(ref_balance),
            )
        except Exception:
            pass
        _notify(
            "🎁 <b>دعوت موفق</b>\n"
            f"👤 دعوت‌کننده: <code>{referrer_id}</code>\n"
            f"🆕 کاربر جدید: <code>{uid}</code>"
        )
    elif ref_reason not in ("already_started", "already_referred", "self"):
        log.info("Referral ignored for %s from %s: %s", uid, referrer_id, ref_reason)


def _send_user_menu(bot: telebot.TeleBot, chat_id: int, uid: int) -> None:
    balance = get_balance(uid)
    bot.send_message(
        chat_id,
        f"👤 <b>پنل کاربری</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی کیف پول: <b>{_fmt_toman(balance)}</b>\n\n"
        "از منوی پایین یک گزینه را انتخاب کنید:",
        reply_markup=customer_menu(REFERRAL_ENABLED),
    )


def _parse_referrer_id(text: str | None) -> int | None:
    """Extract referrer ID from /start ref_<id> payload."""
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("ref_"):
        payload = payload[4:]
    elif payload.startswith("ref-"):
        payload = payload[4:]
    else:
        return None
    return int(payload) if payload.lstrip("-").isdigit() else None


def _get_bot_username(bot: telebot.TeleBot) -> str | None:
    """Return bot username with a small in-memory cache."""
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    try:
        username = (bot.get_me().username or "").strip()
    except Exception as exc:
        log.warning("Failed to fetch bot username for referral link: %s", exc)
        return None
    _bot_username_cache = username or None
    return _bot_username_cache


def _referral_link(bot: telebot.TeleBot, uid: int) -> str:
    username = _get_bot_username(bot)
    if not username:
        return f"/start ref_{uid}"
    return f"https://t.me/{username}?start=ref_{uid}"


def _show_referral(bot: telebot.TeleBot, chat_id: int, uid: int) -> None:
    stats = get_referral_stats(uid)
    link = _referral_link(bot, uid)
    reward_remaining = max(0, REFERRAL_CONFIG_REQUIRED_REFERRALS - int(stats["count"]))
    claimed_referral_config = has_claimed_referral_config(uid)
    referral_config_line = (
        "🎁 کانفیگ رفرال: <b>دریافت شده</b>"
        if claimed_referral_config
        else (
            f"🎁 جایزه {REFERRAL_CONFIG_REQUIRED_REFERRALS} دعوت: "
            f"<b>{REFERRAL_CONFIG_MB:.0f} MB</b> / <b>{REFERRAL_CONFIG_DAYS}</b> روز"
        )
    )
    referral_config_progress = (
        ""
        if claimed_referral_config
        else (
            "✅ شما می‌توانید کانفیگ رفرال را دریافت کنید."
            if reward_remaining == 0
            else f"⏳ تا کانفیگ رفرال: <b>{reward_remaining}</b> دعوت موفق دیگر"
        )
    )
    bot.send_message(
        chat_id,
        "🎁 <b>دعوت دوستان</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔗 لینک اختصاصی شما:\n<code>{link}</code>\n\n"
        f"👥 تعداد دعوت‌های موفق: <b>{stats['count']}</b>\n"
        "🧪 اکانت تست: <b>بدون نیاز به دعوت</b>\n"
        f"{referral_config_line}\n"
        f"{referral_config_progress}\n\n"
        "هر کاربر جدید که با لینک شما ربات را برای اولین بار استارت کند، یک دعوت موفق برای شما ثبت می‌شود.",
        reply_markup=referral_keyboard(get_balance(uid)),
    )


def _pick_reward_inbound(xui) -> dict | None:
    """Pick the first configured shop inbound, falling back to the first inbound."""
    all_inbounds = xui.get_inbounds() or []
    if SHOP_INBOUNDS:
        return next(
            (inb for inb in all_inbounds if inb.get("remark") in SHOP_INBOUNDS),
            all_inbounds[0] if all_inbounds else None,
        )
    return all_inbounds[0] if all_inbounds else None


def _claim_referral_config(
    bot: telebot.TeleBot, xui, uid: int, chat_id: int, username: str | None
) -> None:
    stats = get_referral_stats(uid)
    referral_count = int(stats["count"])
    if has_claimed_referral_config(uid):
        bot.send_message(
            chat_id,
            "⚠️ شما قبلاً کانفیگ رفرال را دریافت کرده‌اید.\n"
            "این جایزه برای هر کاربر فقط یک بار قابل دریافت است.",
            reply_markup=referral_keyboard(get_balance(uid)),
        )
        return
    if referral_count < REFERRAL_CONFIG_REQUIRED_REFERRALS:
        remaining = REFERRAL_CONFIG_REQUIRED_REFERRALS - referral_count
        link = _referral_link(bot, uid)
        bot.send_message(
            chat_id,
            "🎁 <b>کانفیگ رفرال هنوز فعال نشده</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"برای دریافت این کانفیگ باید <b>{REFERRAL_CONFIG_REQUIRED_REFERRALS}</b> دعوت موفق داشته باشید.\n"
            f"دعوت‌های موفق شما: <b>{referral_count}</b>\n"
            f"باقی‌مانده: <b>{remaining}</b>\n\n"
            f"🔗 لینک دعوت شما:\n<code>{link}</code>",
            reply_markup=referral_keyboard(get_balance(uid)),
        )
        return

    bot.send_chat_action(chat_id, "typing")
    inbound = _pick_reward_inbound(xui)
    if not inbound:
        bot.send_message(
            chat_id,
            "❌ در حال حاضر امکان ساخت کانفیگ رفرال نیست. با پشتیبانی تماس بگیرید.",
            reply_markup=referral_keyboard(get_balance(uid)),
        )
        return

    email = f"referral_{uid}"
    ok_reserve, reason = reserve_referral_config(uid, email)
    if not ok_reserve:
        bot.send_message(
            chat_id,
            "⚠️ شما قبلاً کانفیگ رفرال را دریافت کرده‌اید.",
            reply_markup=referral_keyboard(get_balance(uid)),
        )
        return

    protocol = inbound.get("protocol", "vless")
    total_gb = REFERRAL_CONFIG_MB / 1024
    ok, cid, sub_id = xui.add_client(
        inbound["id"],
        protocol,
        email,
        total_gb,
        REFERRAL_CONFIG_DAYS,
    )
    if not ok:
        release_referral_config(uid)
        bot.send_message(
            chat_id,
            "❌ خطا در ساخت کانفیگ رفرال. لطفاً دوباره تلاش کنید.",
            reply_markup=referral_keyboard(get_balance(uid)),
        )
        return

    save_purchase(
        uid,
        email,
        inbound["id"],
        protocol,
        total_gb,
        REFERRAL_CONFIG_DAYS,
        sub_id or "",
        extra={"source": "referral_reward", "referrals": referral_count},
    )

    user_tag = f"@{username}" if username else "—"
    _notify(
        "🎁 <b>کانفیگ رفرال ساخته شد</b>\n"
        f"🆔 کاربر: <code>{uid}</code>\n"
        f"👤 یوزرنیم: <code>{user_tag}</code>\n"
        f"👥 دعوت موفق: <b>{referral_count}</b>\n"
        f"👤 ایمیل: <code>{email}</code>\n"
        f"💾 حجم: {REFERRAL_CONFIG_MB:.0f} MB  |  📅 {REFERRAL_CONFIG_DAYS} روز"
    )

    links = [
        _add_insecure_to_link(lnk) for lnk in xui.get_client_links(inbound["id"], email)
    ]
    bot.send_message(
        chat_id,
        "✅ <b>کانفیگ رفرال ساخته شد!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 نام: <code>{email}</code>\n"
        f"💾 حجم: {REFERRAL_CONFIG_MB:.0f} MB\n"
        f"📅 مدت زمان: {REFERRAL_CONFIG_DAYS} روز\n\n"
        "این جایزه برای هر کاربر فقط یک بار قابل دریافت است.",
        reply_markup=referral_keyboard(get_balance(uid)),
    )
    if links:
        for lnk in links:
            bot.send_message(chat_id, f"<code>{lnk}</code>")
    if sub_id and XUI_SUB_BASE_URL:
        bot.send_message(
            chat_id,
            f"🔗 <b>لینک اشتراک:</b>\n<code>{XUI_SUB_BASE_URL}/sub/{sub_id}</code>",
        )


def _gen_shop_name(user_identity: str | int | None, gb: float | int | None) -> str:
    """Nam-e config ra az ID, hajm va pasvand-e tasadofi misazad."""
    raw_id = str(user_identity or "").strip().lstrip("@")
    safe_id = re.sub(r"[^A-Za-z0-9_]", "", raw_id)[:32] or "USER"
    if gb and float(gb) > 0:
        gbf = float(gb)
        volume = f"{int(gbf)}G" if gbf.is_integer() else f"{gbf:g}G".replace(".", "_")
    else:
        volume = "NA"
    rnd = "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8)
    )
    return f"@{safe_id} | 🪶 {volume} | {rnd}"


def _ask_shop_name(bot: telebot.TeleBot, chat_id: int) -> None:
    """Hide reply menu and ask for config name with one random button."""
    bot.send_message(
        chat_id,
        "⌨️ منوی پایینی موقتاً بسته شد؛ نام کانفیگ را وارد کنید یا دکمه رندوم را بزنید.",
        reply_markup=telebot.types.ReplyKeyboardRemove(),
    )
    bot.send_message(
        chat_id,
        "👤 نام کانفیگ (ایمیل) را وارد کنید:\n"
        "<i>(حداقل ۳ کاراکتر)</i>\n"
        "یا از دکمه زیر نام رندوم با فرمت <code>@ID | 🪶 GB | randomprefix</code> بسازید.",
        reply_markup=shop_name_keyboard(),
    )


def _set_shop_email_and_continue(
    bot: telebot.TeleBot, xui, uid: int, chat_id: int, email: str
) -> None:
    """Validate/set shop name then continue purchase flow."""
    email = (email or "").strip()
    if not email or len(email) < 3:
        bot.send_message(
            chat_id,
            "⚠️ نام نامعتبر. حداقل ۳ کاراکتر وارد کنید.",
            reply_markup=shop_name_keyboard(),
        )
        return

    _data.setdefault(uid, {})["shop_email"] = email
    inbound = _auto_select_inbound(xui)
    if not inbound:
        _clear_state(uid)
        bot.send_message(
            chat_id,
            "❌ هیچ سروری در دسترس نیست.",
            reply_markup=user_menu(get_balance(uid)),
        )
        return

    _data[uid]["shop_inbound_id"] = int(inbound["id"])
    _data[uid]["shop_protocol"] = inbound.get("protocol", "vless")
    if _data[uid].get("shop_gb"):
        _data[uid].setdefault("shop_days", 0)
        _states[uid] = None
        _show_shop_confirm(bot, uid, chat_id)
    else:
        _states[uid] = S_SHOP_GB
        bot.send_message(
            chat_id,
            "💾 حجم اینترنت را انتخاب کنید:"
            f"\n<i>هر GB = {_fmt_toman(PRICE_PER_GB)}</i>",
            reply_markup=shop_gb_keyboard(),
        )


def _show_shop_confirm(bot: telebot.TeleBot, uid: int, chat_id: int) -> None:
    d = _data.get(uid, {})
    email = d.get("shop_email", "")
    gb = float(d.get("shop_gb", 0))
    days = int(d.get("shop_days", 0))
    protocol = d.get("shop_protocol", "vless")
    price = calculate_price(gb)
    balance = get_balance(uid)

    sufficient = balance >= price
    msg = (
        "🛒 <b>تأیید سفارش</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 نام کانفیگ:    <code>{email}</code>\n"
        f"🔌 پروتکل:       {protocol.upper()}\n"
        f"💾 حجم:         {gb:.0f} GB\n"
        f"📅 اعتبار:       {'♾ بدون محدودیت' if days == 0 else f'{days} روز'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت:        <b>{_fmt_toman(price)}</b>\n"
        f"👛 موجودی:      <b>{_fmt_toman(balance)}</b>\n"
        + (
            "✅ موجودی کافی است"
            if sufficient
            else f"❌ موجودی ناکافی  (کمبود: {_fmt_toman(price - balance)})"
        )
    )
    if sufficient:
        bot.send_message(chat_id, msg, reply_markup=shop_confirm_keyboard())
    else:
        bot.send_message(
            chat_id,
            msg + "\n\n⚠️ ابتدا کیف پول خود را شارژ کنید.",
            reply_markup=wallet_keyboard(),
        )


def _do_shop_purchase(
    bot: telebot.TeleBot,
    xui,
    uid: int,
    chat_id: int,
    username: str | None = None,
) -> None:
    d = _data.get(uid, {})
    email = d.get("shop_email", "")
    gb = float(d.get("shop_gb", 0))
    days = int(d.get("shop_days", 0))
    inbound_id = d.get("shop_inbound_id")
    protocol = d.get("shop_protocol", "vless")
    price = calculate_price(gb)

    if not inbound_id or not email or gb <= 0:
        _clear_state(uid)
        _send_user_menu(bot, chat_id, uid)
        return

    ok_deduct, new_balance = deduct_balance(uid, price)
    if not ok_deduct:
        _clear_state(uid)
        balance = get_balance(uid)
        bot.send_message(
            chat_id,
            f"❌ موجودی ناکافی!\n"
            f"💰 موجودی: {_fmt_toman(balance)}\n"
            f"💳 قیمت: {_fmt_toman(price)}",
            reply_markup=user_menu(balance),
        )
        return

    bot.send_chat_action(chat_id, "typing")
    ok_create, cid, sub_id = xui.add_client(inbound_id, protocol, email, gb, days)
    if not ok_create:
        add_balance(uid, price)  # refund
        _clear_state(uid)
        bot.send_message(
            chat_id,
            "❌ خطا در ساخت کانفیگ. مبلغ به کیف پول برگشت داده شد.",
            reply_markup=user_menu(get_balance(uid)),
        )
        return

    links = [
        _add_insecure_to_link(lnk) for lnk in xui.get_client_links(inbound_id, email)
    ]
    _clear_state(uid)

    save_purchase(uid, email, inbound_id, protocol, gb, days, sub_id or "")

    user_tag = f"@{username}" if username else "—"
    _notify(
        "🛒 <b>خرید سرویس جدید</b>\n"
        f"🆔 کاربر: <code>{uid}</code>\n"
        f"👤 یوزرنیم: <code>{user_tag}</code>\n"
        f"👤 ایمیل: <code>{email}</code>\n"
        f"🔌 پروتکل: {protocol.upper()}\n"
        f"💾 حجم: {gb:.0f} GB  |  📅 {'♾' if days == 0 else f'{days} روز'}\n"
        f"💰 مبلغ: {_fmt_toman(price)}"
    )

    bot.send_message(
        chat_id,
        "✅ <b>خرید موفق!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 نام کانفیگ:    <code>{email}</code>\n"
        f"🔌 پروتکل:       {protocol.upper()}\n"
        f"💾 حجم:         {gb:.0f} GB\n"
        f"📅 اعتبار:       {'♾ بدون محدودیت' if days == 0 else f'{days} روز'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 مبلغ پرداختی:  {_fmt_toman(price)}\n"
        f"👛 موجودی جدید:   {_fmt_toman(new_balance)}",
    )
    if links:
        bot.send_message(chat_id, f"📋 <b>کانفیگ‌ها ({len(links)}):</b>")
        for lnk in links:
            bot.send_message(chat_id, f"<code>{lnk}</code>")
    else:
        bot.send_message(chat_id, "⚠️ کانفیگ لینک از پنل دریافت نشد.")
    if sub_id and XUI_SUB_BASE_URL:
        bot.send_message(
            chat_id,
            f"🔗 <b>لینک اشتراک:</b>\n<code>{XUI_SUB_BASE_URL}/sub/{sub_id}</code>",
        )
    bot.send_message(chat_id, "منوی کاربری:", reply_markup=user_menu(new_balance))


# ── renewal helpers ───────────────────────────────────────────────────────────


def _show_renew_confirm(bot: telebot.TeleBot, uid: int, chat_id: int) -> None:
    d = _data.get(uid, {})
    idx = d.get("renew_idx")
    gb = float(d.get("renew_gb", 0))
    purchases = get_purchases(uid)
    if idx is None or idx >= len(purchases):
        _clear_state(uid)
        _send_user_menu(bot, chat_id, uid)
        return
    p = purchases[idx]
    price = calculate_price(gb)
    balance = get_balance(uid)
    sufficient = balance >= price
    msg = (
        "🔄 <b>تأیید تمدید سرویس</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 نام کانفیگ:  <code>{p['email']}</code>\n"
        f"➕ حجم اضافه:  {gb:.0f} GB\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 قیمت:       {_fmt_toman(price)}\n"
        f"👛 موجودی:     {_fmt_toman(balance)}\n"
        + (
            "✅ موجودی کافی است"
            if sufficient
            else f"❌ موجودی ناکافی  (کمبود: {_fmt_toman(price - balance)})"
        )
    )
    if sufficient:
        bot.send_message(chat_id, msg, reply_markup=renew_confirm_keyboard())
    else:
        bot.send_message(
            chat_id,
            msg + "\n\n⚠️ ابتدا کیف پول خود را شارژ کنید.",
            reply_markup=wallet_keyboard(),
        )


def _do_renew_purchase(bot: telebot.TeleBot, xui, uid: int, chat_id: int) -> None:
    d = _data.get(uid, {})
    idx = d.get("renew_idx")
    gb = float(d.get("renew_gb", 0))
    purchases = get_purchases(uid)
    if idx is None or idx >= len(purchases) or gb <= 0:
        _clear_state(uid)
        _send_user_menu(bot, chat_id, uid)
        return
    p = purchases[idx]
    price = calculate_price(gb)

    ok_deduct, new_balance = deduct_balance(uid, price)
    if not ok_deduct:
        _clear_state(uid)
        balance = get_balance(uid)
        bot.send_message(
            chat_id,
            f"❌ موجودی ناکافی!\n"
            f"💰 موجودی: {_fmt_toman(balance)}\n"
            f"💳 قیمت: {_fmt_toman(price)}",
            reply_markup=user_menu(balance),
        )
        return

    bot.send_chat_action(chat_id, "typing")
    traffic = xui.get_client_traffic(p["email"], p.get("inbound_id"))
    cur_bytes = int((traffic or {}).get("total", 0) or 0)
    new_gb = (cur_bytes + int(gb * 1_073_741_824)) / 1_073_741_824

    ok_update = xui.update_client(
        p["inbound_id"], p["email"], total_gb=new_gb, enable=True
    )
    if not ok_update:
        add_balance(uid, price)  # refund
        _clear_state(uid)
        bot.send_message(
            chat_id,
            "❌ خطا در تمدید سرویس. مبلغ به کیف پول برگشت داده شد.",
            reply_markup=user_menu(get_balance(uid)),
        )
        return

    _clear_state(uid)
    _notify(
        "🔄 <b>تمدید سرویس</b>\n"
        f"👤 ایمیل: <code>{p['email']}</code>\n"
        f"🆔 کاربر: <code>{uid}</code>\n"
        f"➕ حجم اضافه: {gb:.0f} GB\n"
        f"💰 مبلغ: {_fmt_toman(price)}"
    )
    bot.send_message(
        chat_id,
        "✅ <b>تمدید موفق!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 نام کانفیگ:      <code>{p['email']}</code>\n"
        f"➕ حجم اضافه شده:  {gb:.0f} GB\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 مبلغ پرداختی:    {_fmt_toman(price)}\n"
        f"👛 موجودی جدید:     {_fmt_toman(new_balance)}",
        reply_markup=user_menu(new_balance),
    )


# ── register ──────────────────────────────────────────────────────────────────


def register(bot: telebot.TeleBot, xui) -> None:
    set_log_bot(bot)
    _start_server_status_poller(xui)

    # ── /start ───────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["start"])
    def cmd_start(m: telebot.types.Message) -> None:
        uid = m.from_user.id
        if _is_blocked(uid):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(uid) and not _is_force_join_member(bot, uid):
            _data.setdefault(uid, {})["pending_start_text"] = m.text
            _send_force_join(bot, m.chat.id)
            return
        user_tag = f"@{m.from_user.username}" if m.from_user.username else "—"
        full_name = (
            " ".join(
                x
                for x in [m.from_user.first_name or "", m.from_user.last_name or ""]
                if x
            ).strip()
            or "—"
        )
        role = "ادمین" if _is_admin(uid) else "کاربر"

        _register_referral_from_start(bot, uid, m.text)
        mark_user_started(
            uid,
            m.from_user.username,
            m.from_user.first_name,
            m.from_user.last_name,
        )
        if _is_admin(uid):
            _notify(
                "🚪 <b>ورود به پنل</b>\n"
                f"👥 نقش: <b>{role}</b>\n"
                f"🆔 کاربر: <code>{uid}</code>\n"
                f"👤 یوزرنیم: <code>{user_tag}</code>\n"
                f"📛 نام: <code>{full_name}</code>\n"
                f"💬 چت: <code>{m.chat.id}</code>"
            )
        _clear_state(uid)
        if _is_admin(uid):
            bot.send_message(
                m.chat.id,
                "👋 <b>خوش آمدید به پنل مدیریت 3x-ui</b>\n\nیک گزینه را انتخاب کنید:",
                reply_markup=main_menu(),
            )
        else:
            _send_user_menu(bot, m.chat.id, uid)

    # ── /status ──────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["status"])
    def cmd_status(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        _show_status(bot, xui, m.chat.id)

    # ── /backup ──────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["backup"])
    def cmd_backup(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        _send_backup(bot, xui, m.chat.id)

    # ── /help ────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["help"])
    def cmd_help(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        bot.send_message(
            m.chat.id,
            "📋 <b>دستورات</b>\n\n"
            "/start — منوی اصلی\n"
            "/status — وضعیت سرور\n"
            "/backup — دریافت بکاپ\n"
            "/addbalance &lt;user_id&gt; &lt;amount_toman&gt; — افزودن موجودی کاربر (تومان)\n"
            "/settriallimit &lt;count&gt; — تنظیم سقف کل تست (0=نامحدود)\n"
            "/addtriallimit &lt;count&gt; — افزایش سقف تست\n"
            "/broadcast &lt;message&gt; — ارسال پیام به همه کاربران\n"
            "/help — این پیام\n\n"
            "از دکمه‌های منو می‌توانید ترافیک کاربر، آمار کاربران، و مانیتور زنده را ببینید.",
            reply_markup=main_menu(),
        )

    # ── /broadcast ─────────────────────────────────────────────────────────
    @bot.message_handler(commands=["broadcast"])
    def cmd_broadcast(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return

        parts = (m.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.send_message(
                m.chat.id,
                "❌ فرمت صحیح:\n<code>/broadcast &lt;message&gt;</code>",
                reply_markup=main_menu(),
            )
            return

        payload = parts[1].strip()
        targets = get_all_known_user_ids()
        if not targets:
            bot.send_message(
                m.chat.id,
                "⚠️ هیچ کاربری برای ارسال همگانی پیدا نشد.",
                reply_markup=main_menu(),
            )
            return

        sent = 0
        failed = 0
        for uid in targets:
            try:
                bot.send_message(uid, payload)
                sent += 1
            except Exception:
                failed += 1

        bot.send_message(
            m.chat.id,
            "📣 <b>نتیجه برودکست</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 مخاطب کل: <b>{len(targets)}</b>\n"
            f"✅ موفق: <b>{sent}</b>\n"
            f"❌ ناموفق: <b>{failed}</b>",
            reply_markup=main_menu(),
        )

    # ── /settriallimit ─────────────────────────────────────────────────────
    @bot.message_handler(commands=["settriallimit"])
    def cmd_settriallimit(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        parts = m.text.split()
        if len(parts) != 2:
            bot.send_message(
                m.chat.id,
                "❌ فرمت صحیح:\n<code>/settriallimit &lt;count&gt;</code>\n"
                "<i>count=0 یعنی نامحدود</i>",
            )
            return
        try:
            count = int(parts[1])
            if count < 0:
                raise ValueError
        except ValueError:
            bot.send_message(m.chat.id, "❌ count باید عدد صحیحِ صفر یا مثبت باشد.")
            return

        new_limit = set_trial_limit(count)
        used = get_trials_count()
        cap = f"{used}/{new_limit}" if new_limit > 0 else f"{used}/∞"
        bot.send_message(
            m.chat.id,
            f"✅ سقف تست با موفقیت تنظیم شد.\n👥 ظرفیت فعلی: <b>{cap}</b>",
            reply_markup=main_menu(),
        )

    # ── /addtriallimit ─────────────────────────────────────────────────────
    @bot.message_handler(commands=["addtriallimit"])
    def cmd_addtriallimit(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        parts = m.text.split()
        if len(parts) != 2:
            bot.send_message(
                m.chat.id,
                "❌ فرمت صحیح:\n<code>/addtriallimit &lt;count&gt;</code>",
            )
            return
        try:
            delta = int(parts[1])
            if delta <= 0:
                raise ValueError
        except ValueError:
            bot.send_message(m.chat.id, "❌ count باید عدد صحیحِ مثبت باشد.")
            return

        cur_limit = _current_trial_limit()
        if cur_limit == 0:
            used = get_trials_count()
            bot.send_message(
                m.chat.id,
                "ℹ️ سقف تست هم‌اکنون نامحدود است (∞) و افزایش عددی معنی ندارد.\n"
                "اگر سقف عددی می‌خواهید، اول با /settriallimit مقدار بدهید.",
            )
            bot.send_message(
                m.chat.id,
                f"👥 ظرفیت فعلی: <b>{used}/∞</b>",
                reply_markup=main_menu(),
            )
            return

        new_limit = increase_trial_limit(delta, TEST_ACCOUNT_LIMIT)
        used = get_trials_count()
        bot.send_message(
            m.chat.id,
            f"✅ سقف تست به اندازه <b>{delta}</b> نفر افزایش یافت.\n"
            f"👥 ظرفیت فعلی: <b>{used}/{new_limit}</b>",
            reply_markup=main_menu(),
        )

    # ── /addbalance ──────────────────────────────────────────────────────────
    @bot.message_handler(commands=["addbalance"])
    def cmd_addbalance(m: telebot.types.Message) -> None:
        if _is_blocked(m.from_user.id):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _is_admin(m.from_user.id):
            return
        parts = m.text.split()
        if len(parts) != 3:
            bot.send_message(
                m.chat.id,
                "❌ فرمت صحیح:\n<code>/addbalance &lt;user_id&gt; &lt;amount_toman&gt;</code>",
            )
            return
        try:
            target_uid = int(parts[1])
            amount_toman = int(parts[2].replace(",", "").replace(".", ""))
            if amount_toman <= 0:
                raise ValueError
        except ValueError:
            bot.send_message(
                m.chat.id, "❌ user_id و amount_toman باید عدد صحیح مثبت باشند."
            )
            return
        if amount_toman % 1000 != 0:
            bot.send_message(m.chat.id, "❌ مبلغ باید مضرب ۱۰۰۰ تومان باشد.")
            return
        amount = amount_toman // 1000
        new_bal = add_balance(target_uid, amount)
        bot.send_message(
            m.chat.id,
            f"✅ <b>{_fmt_toman(amount)}</b> به کاربر <code>{target_uid}</code> اضافه شد.\n"
            f"💰 موجودی جدید: <b>{_fmt_toman(new_bal)}</b>",
        )
        try:
            bot.send_message(
                target_uid,
                f"✅ <b>{_fmt_toman(amount)}</b> توسط ادمین به کیف پول شما اضافه شد.\n"
                f"💰 موجودی فعلی: <b>{_fmt_toman(new_bal)}</b>",
                reply_markup=user_menu(new_bal),
            )
        except Exception:
            pass  # user may have not started the bot

    # ── photo handler (payment receipts) ────────────────────────────────────
    @bot.message_handler(content_types=["photo"])
    def handle_photo(m: telebot.types.Message) -> None:
        uid = m.from_user.id
        if _is_blocked(uid):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _ensure_force_join(bot, uid, m.chat.id):
            return
        state = _states.get(uid)
        if state != S_WALLET_PHOTO:
            return
        d = _data.get(uid, {})
        amount = int(d.get("wallet_amount", 0))
        if amount <= 0:
            _clear_state(uid)
            _send_user_menu(bot, m.chat.id, uid)
            return

        file_id = m.photo[-1].file_id
        username = m.from_user.username or m.from_user.first_name or str(uid)
        pay_id = _uuid_mod.uuid4().hex[:12]

        save_pending_payment(pay_id, uid, amount, file_id, username)
        _clear_state(uid)

        caption = (
            "💳 <b>درخواست شارژ کیف پول</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 کاربر: @{username}\n"
            f"🆔 یوزر آیدی: <code>{uid}</code>\n"
            f"💰 مبلغ: <b>{_fmt_toman(amount)}</b>"
        )
        try:
            bot.send_photo(
                PAYMENT_GROUP_ID,
                file_id,
                caption=caption,
                reply_markup=payment_admin_keyboard(pay_id),
            )
        except Exception as exc:
            log.error("Failed to send payment receipt to group: %s", exc)
            remove_pending_payment(pay_id)
            bot.send_message(
                m.chat.id,
                "❌ خطا در ارسال رسید. لطفاً دوباره تلاش کنید.",
                reply_markup=user_menu(get_balance(uid)),
            )
            return

        bot.send_message(
            m.chat.id,
            "✅ رسید شما ارسال شد.\nپس از تأیید ادمین، مبلغ به کیف پولتان اضافه می‌شود.",
            reply_markup=user_menu(get_balance(uid)),
        )

    # ── Reply-keyboard menu button handler (must be registered before handle_text) ─
    @bot.message_handler(
        func=lambda m: m.content_type == "text" and m.text in _ALL_MENU_BTNS
    )
    def handle_menu_button(m: telebot.types.Message) -> None:
        uid = m.from_user.id
        if _is_blocked(uid):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _ensure_force_join(bot, uid, m.chat.id):
            return
        _clear_state(uid)
        t = m.text

        # ── Buttons accessible by all users ──────────────────────────────────
        if t == BTN_WALLET:
            balance = get_balance(uid)
            bot.send_message(
                m.chat.id,
                f"💰 <b>کیف پول</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"موجودی: <b>{_fmt_toman(balance)}</b>\n\n"
                f"💳 شماره کارت جهت شارژ:\n<code>{CARD_NUMBER}</code>",
                reply_markup=wallet_keyboard(),
            )
            return

        if t == BTN_CHARGE:
            # Jump straight to deposit flow
            _states[uid] = S_WALLET_AMOUNT
            balance = get_balance(uid)
            bot.send_message(
                m.chat.id,
                f"💳 <b>شارژ کیف پول</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"موجودی فعلی: <b>{_fmt_toman(balance)}</b>\n\n"
                f"💳 شماره کارت:\n<code>{CARD_NUMBER}</code>\n\n"
                "💵 مبلغ موردنظر برای شارژ را به <b>تومان</b> وارد کنید (مثال: 300000):",
                reply_markup=cancel_keyboard(),
            )
            return

        if t == BTN_USAGE:
            # Show live traffic summary for all of user's purchased configs
            _sync_deleted_panel_configs_for_user(xui, uid)
            purchases = get_purchases(uid)
            if not purchases:
                bot.send_message(
                    m.chat.id,
                    "📊 شما هنوز کانفیگی خریداری نکرده‌اید.",
                )
                return
            bot.send_chat_action(m.chat.id, "typing")
            lines = ["📊 <b>میزان مصرف کانفیگ‌ها</b>\n━━━━━━━━━━━━━━━━━━"]
            for p in purchases:
                traffic = xui.get_client_traffic(p["email"], p.get("inbound_id"))
                if traffic:
                    up = int(traffic.get("up", 0) or 0)
                    down = int(traffic.get("down", 0) or 0)
                    total = int(traffic.get("total", 0) or 0)
                    used = up + down
                    rem = max(0, total - used) if total > 0 else -1
                    rem_s = "♾" if rem < 0 else _fmt_bytes(rem)
                    expiry = int(traffic.get("expiryTime", 0) or 0)
                    if expiry > 0:
                        import datetime as _dt

                        days_left = (
                            _dt.datetime.fromtimestamp(expiry / 1000)
                            - _dt.datetime.now()
                        ).days
                        exp_s = f"{days_left}d" if days_left > 0 else "منقضی"
                    else:
                        exp_s = "♾"
                    lines.append(
                        f"⚙️ <code>{p['email']}</code>\n"
                        f"  📦 {_fmt_bytes(used)} / {'♾' if total == 0 else _fmt_bytes(total)}"
                        f"  |  🔋 {rem_s}  |  📅 {exp_s}"
                    )
                else:
                    lines.append(f"⚙️ <code>{p['email']}</code>  —  اطلاعات دریافت نشد")
            bot.send_message(m.chat.id, "\n".join(lines))
            return

        if t == BTN_BLACKLIST_LIST:
            _show_blacklist_page(bot, m.chat.id, page=0, admin_mode=_is_admin(uid))
            return

        if t == BTN_SHOP:
            _data[uid] = {}
            _states[uid] = S_SHOP_NAME
            balance = get_balance(uid)
            bot.send_message(
                m.chat.id,
                f"🛒 <b>پنل فروش کانفیگ (حجم دلخواه)</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"💰 قیمت: <b>{_fmt_toman(PRICE_PER_GB)} / هر GB</b>\n"
                f"👛 موجودی شما: <b>{_fmt_toman(balance)}</b>\n\n"
                "💡 برای حجم‌های استاندارد (۲۰ تا ۱۰۰ گیگ) از «📦 سرویس‌ها» با قیمت ثابت و مقرون‌به‌صرفه‌تر استفاده کنید.\n\n"
                "در مرحله بعد باید نام کانفیگ را مشخص کنید.",
            )
            _ask_shop_name(bot, m.chat.id)
            return

        if t == BTN_MY_CFGS:
            _sync_deleted_panel_configs_for_user(xui, uid)
            purchases = get_purchases(uid)
            if not purchases:
                bot.send_message(
                    m.chat.id,
                    "📋 شما هنوز کانفیگی خریداری نکرده‌اید.",
                    reply_markup=user_menu(),
                )
            else:
                bot.send_message(
                    m.chat.id,
                    f"📋 <b>کانفیگ‌های من ({len(purchases)}):</b>\n"
                    "یک کانفیگ را انتخاب کنید:",
                    reply_markup=my_configs_keyboard(purchases),
                )
            return

        # ── New customer-menu buttons ─────────────────────────────────────────

        if t == BTN_BUY_NEW:
            balance = get_balance(uid)
            bot.send_message(
                m.chat.id,
                f"🚀 <b>خرید سرویس جدید</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👛 موجودی شما: <b>{_fmt_toman(balance)}</b>\n\n"
                "یک بسته را انتخاب کنید:",
                reply_markup=services_keyboard(),
            )
            return

        if t in (BTN_TEST_ACC, BTN_TEST_ACC_ADMIN):
            is_admin_user = _is_admin(uid)
            trial_limit = _current_trial_limit()
            trial_minutes = 60 if is_admin_user else TEST_ACCOUNT_MINUTES
            if not is_admin_user and not get_trial_enabled():
                bot.send_message(
                    m.chat.id,
                    "⚠️ اکانت تست در حال حاضر فعال نیست.",
                )
                return
            if not is_admin_user and has_used_trial(uid):
                bot.send_message(
                    m.chat.id,
                    "⚠️ شما قبلاً اکانت تست دریافت کرده‌اید.\n"
                    "هر کاربر تنها یک بار می‌تواند اکانت تست بگیرد.",
                )
                return
            bot.send_chat_action(m.chat.id, "typing")
            # Pick first available shop inbound
            all_inbounds = xui.get_inbounds() or []
            if SHOP_INBOUNDS:
                inbound = next(
                    (inb for inb in all_inbounds if inb.get("remark") in SHOP_INBOUNDS),
                    all_inbounds[0] if all_inbounds else None,
                )
            else:
                inbound = all_inbounds[0] if all_inbounds else None

            if not inbound:
                bot.send_message(
                    m.chat.id,
                    "❌ در حال حاضر سرویس تست موجود نیست. با پشتیبانی تماس بگیرید.",
                )
                return

            if is_admin_user:
                trial_email = f"admin_{uid}_{secrets.token_hex(3)}"
                ok_slot, reason, used_count = True, "", get_trials_count()
            else:
                trial_email = f"trial_{uid}"
                ok_slot, reason, used_count = reserve_trial_slot(
                    uid, trial_email, trial_limit
                )

            if not ok_slot:
                if reason == "already":
                    bot.send_message(
                        m.chat.id,
                        "⚠️ شما قبلاً اکانت تست دریافت کرده‌اید.\n"
                        "هر کاربر تنها یک بار می‌تواند اکانت تست بگیرد.",
                    )
                    return
                if reason == "limit":
                    bot.send_message(
                        m.chat.id,
                        f"⛔️ ظرفیت اکانت تست تکمیل شده است.\n"
                        f"ظرفیت کل: <b>{trial_limit}</b> نفر\n"
                        f"مصرف‌شده: <b>{used_count}</b> نفر",
                    )
                    return

            protocol = inbound.get("protocol", "vless")
            total_gb = TEST_ACCOUNT_MB / 1024
            expiry_days = trial_minutes / 1440
            ok, cid, sub_id = xui.add_client(
                inbound["id"],
                protocol,
                trial_email,
                total_gb,
                expiry_days,
            )
            if not ok:
                # rollback reserved slot if panel client creation failed
                if not is_admin_user:
                    release_trial_slot(uid)
                bot.send_message(
                    m.chat.id,
                    "❌ خطا در ساخت اکانت ادمین. لطفاً دوباره تلاش کنید."
                    if is_admin_user
                    else "❌ خطا در ساخت اکانت تست. احتمالاً قبلاً یک اکانت با این مشخصات ساخته شده.",
                )
                return

            user_tag = f"@{m.from_user.username}" if m.from_user.username else "—"
            if is_admin_user:
                _notify(
                    "👑 <b>اکانت ویژه ادمین ساخته شد</b>\n"
                    f"🆔 ادمین: <code>{uid}</code>\n"
                    f"👤 یوزرنیم: <code>{user_tag}</code>\n"
                    f"👤 ایمیل: <code>{trial_email}</code>\n"
                    f"💾 حجم: {TEST_ACCOUNT_MB:.0f} MB  |  ⏱ {trial_minutes} دقیقه"
                )
            else:
                _notify(
                    "🧪 <b>اکانت تست دریافت شد</b>\n"
                    f"🆔 کاربر: <code>{uid}</code>\n"
                    f"👤 یوزرنیم: <code>{user_tag}</code>\n"
                    f"👤 ایمیل: <code>{trial_email}</code>\n"
                    f"💾 حجم: {TEST_ACCOUNT_MB:.0f} MB  |  ⏱ {TEST_ACCOUNT_MINUTES} دقیقه"
                )
            links = [
                _add_insecure_to_link(lnk)
                for lnk in xui.get_client_links(inbound["id"], trial_email)
            ]
            if is_admin_user:
                bot.send_message(
                    m.chat.id,
                    "✅ <b>اکانت ویژه ادمین ساخته شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"👤 نام: <code>{trial_email}</code>\n"
                    f"💾 حجم: {TEST_ACCOUNT_MB:.0f} MB\n"
                    f"⏱ مدت زمان: فقط {trial_minutes} دقیقه\n\n"
                    "👑 این اکانت مخصوص ادمین است و بدون محدودیت تعداد قابل دریافت است.",
                )
            else:
                trial_time_str = f"{TEST_ACCOUNT_MINUTES} دقیقه"
                bot.send_message(
                    m.chat.id,
                    "✅ <b>اکانت تست ساخته شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"👤 نام: <code>{trial_email}</code>\n"
                    f"💾 حجم: {TEST_ACCOUNT_MB:.0f} MB\n"
                    f"⏱ مدت زمان: فقط {trial_time_str}\n\n"
                    f"⚠️ این اکانت یک‌بار مصرف است و مدت زمان آن فقط {trial_time_str} است.\n"
                    + (
                        f"📈 ظرفیت تست: <b>{used_count}/{trial_limit}</b>"
                        if trial_limit > 0
                        else f"📈 تعداد تست‌های گرفته‌شده: <b>{used_count}</b>"
                    ),
                )
            if links:
                for lnk in links:
                    bot.send_message(m.chat.id, f"<code>{lnk}</code>")
            if sub_id and XUI_SUB_BASE_URL:
                bot.send_message(
                    m.chat.id,
                    f"🔗 <b>لینک اشتراک:</b>\n<code>{XUI_SUB_BASE_URL}/sub/{sub_id}</code>",
                )
            return

        if t == BTN_PRICING:
            bot.send_message(
                m.chat.id,
                "📦 <b>سرویس‌های موجود</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "برای خرید مستقیم روی بسته موردنظر بزنید:",
                reply_markup=services_keyboard(),
            )
            return

        if t == BTN_RENEW:
            purchases = get_purchases(uid)
            if not purchases:
                bot.send_message(
                    m.chat.id,
                    "🔄 <b>تمدید سرویس</b>\n\n"
                    "⚠️ شما هنوز سرویسی خریداری نکرده‌اید.\n"
                    "برای تمدید ابتدا یک سرویس بخرید.",
                )
            else:
                bot.send_message(
                    m.chat.id,
                    f"🔄 <b>تمدید سرویس</b>\n\nسرویس موردنظر خود را انتخاب کنید:",
                    reply_markup=my_configs_keyboard(purchases),
                )
            return

        if t == BTN_MY_USAGE:
            # Same as BTN_USAGE
            _sync_deleted_panel_configs_for_user(xui, uid)
            purchases = get_purchases(uid)
            if not purchases:
                bot.send_message(
                    m.chat.id,
                    "📊 شما هنوز کانفیگی خریداری نکرده‌اید.",
                )
                return
            bot.send_chat_action(m.chat.id, "typing")
            lines = ["📊 <b>میزان مصرف کانفیگ‌ها</b>\n━━━━━━━━━━━━━━━━━━"]
            for p in purchases:
                traffic = xui.get_client_traffic(p["email"], p.get("inbound_id"))
                if traffic:
                    up = int(traffic.get("up", 0) or 0)
                    down = int(traffic.get("down", 0) or 0)
                    total = int(traffic.get("total", 0) or 0)
                    used = up + down
                    rem = max(0, total - used) if total > 0 else -1
                    rem_s = "♾" if rem < 0 else _fmt_bytes(rem)
                    expiry = int(traffic.get("expiryTime", 0) or 0)
                    if expiry > 0:
                        import datetime as _dt

                        days_left = (
                            _dt.datetime.fromtimestamp(expiry / 1000)
                            - _dt.datetime.now()
                        ).days
                        exp_s = f"{days_left}d" if days_left > 0 else "منقضی"
                    else:
                        exp_s = "♾"
                    lines.append(
                        f"⚙️ <code>{p['email']}</code>\n"
                        f"  📦 {_fmt_bytes(used)} / {'♾' if total == 0 else _fmt_bytes(total)}"
                        f"  |  🔋 {rem_s}  |  📅 {exp_s}"
                    )
                else:
                    lines.append(f"⚙️ <code>{p['email']}</code>  —  اطلاعات دریافت نشد")
            bot.send_message(m.chat.id, "\n".join(lines))
            return

        if t == BTN_MY_CREDIT:
            # Same as BTN_WALLET
            balance = get_balance(uid)
            bot.send_message(
                m.chat.id,
                f"💳 <b>اعتبار من</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"موجودی: <b>{_fmt_toman(balance)}</b>\n\n"
                f"💳 شماره کارت جهت شارژ:\n<code>{CARD_NUMBER}</code>",
                reply_markup=wallet_keyboard(),
            )
            return

        if t == BTN_REFERRAL:
            if REFERRAL_ENABLED:
                _show_referral(bot, m.chat.id, uid)
            else:
                bot.send_message(m.chat.id, "⚠️ قابلیت دعوت دوستان موقتاً غیرفعال است.")
            return

        if t == BTN_SERVER_STATUS:
            bot.send_message(m.chat.id, _format_server_status_message())
            return

        if t == BTN_TUTORIAL:
            bot.send_message(m.chat.id, TUTORIAL_TEXT)
            return

        if t == BTN_SUPPORT_IDS:
            lines = ["<b>Vpn Seller Bot</b>"]
            if FORCE_JOIN_CHANNEL_URL:
                lines.append(f'<a href="{escape(FORCE_JOIN_CHANNEL_URL, quote=True)}">Channel</a>')
            if SUPPORT_URL:
                lines.append(f'<a href="{escape(SUPPORT_URL, quote=True)}">Support</a>')
            if not FORCE_JOIN_CHANNEL_URL and not SUPPORT_URL:
                lines.append("Contact links are not configured.")
            bot.send_message(m.chat.id, "\n\n".join(lines), parse_mode="HTML")
            return

        if t == BTN_MY_SERVICES:
            _sync_deleted_panel_configs_for_user(xui, uid)
            purchases = get_purchases(uid)
            if not purchases:
                bot.send_message(
                    m.chat.id,
                    "📋 شما هنوز سرویسی خریداری نکرده‌اید.\n"
                    "برای خرید روی «خرید سرویس جدید» بزنید.",
                )
            else:
                bot.send_message(
                    m.chat.id,
                    f"📋 <b>سرویس‌های من ({len(purchases)}):</b>\n"
                    "یک سرویس را انتخاب کنید:",
                    reply_markup=my_configs_keyboard(purchases),
                )
            return

        # ── Admin-only buttons ────────────────────────────────────────────────
        if not _is_admin(uid):
            return

        if t == BTN_TRAFFIC:
            _states[uid] = S_TRAFFIC_EMAIL
            bot.send_message(
                m.chat.id,
                "📧 ایمیل کاربر را وارد کنید:",
                reply_markup=cancel_keyboard(),
            )

        elif t == BTN_CREATE:
            inbounds = _client_create_inbounds(xui)
            if not inbounds:
                bot.send_message(
                    m.chat.id,
                    "❌ اینباند قابل استفاده برای ساخت کاربر پیدا نشد.\n"
                    "(مثل WireGuard و موارد غیرقابل addClient نادیده گرفته شدند)",
                    reply_markup=main_menu(),
                )
                return
            _data[uid] = {}
            bot.send_message(
                m.chat.id,
                "🔌 اینباند (outbound) مورد نظر را انتخاب کنید:",
                reply_markup=inbounds_keyboard(inbounds),
            )

        elif t == BTN_WIREGUARD:
            _clear_state(uid)
            _states[uid] = S_WG_NAME
            bot.send_message(
                m.chat.id,
                "🛡 <b>ساخت سرویس WireGuard</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "مرحله 1/3: نام سرویس (email) را وارد کنید.",
                reply_markup=cancel_keyboard(),
            )

        elif t == BTN_STATUS:
            _show_status(bot, xui, m.chat.id)

        elif t == BTN_BACKUP:
            _send_backup(bot, xui, m.chat.id)

        elif t == BTN_RESTART_X:
            _restart_xray(bot, xui, m.chat.id)

        elif t == BTN_RESTART_P:
            bot.send_message(
                m.chat.id,
                "⚠️ آیا مطمئن هستید که می‌خواهید پنل را ریستارت کنید؟",
                reply_markup=restart_panel_keyboard(),
            )

        elif t == BTN_STATS:
            _show_users_stats(bot, xui, m.chat.id)

        elif t == BTN_STARTED_USERS:
            _show_started_users(bot, m.chat.id)

        elif t == BTN_MONITOR:
            bot.send_message(
                m.chat.id,
                "🎛 <b>پنل مانیتور</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "از دکمه‌های زیر مانیتور زنده سرور یا مانیتور نودها را اجرا کنید:",
                reply_markup=live_monitor_keyboard(),
            )

        elif t == BTN_STOP_MON:
            stopped = _stop_live_monitor(m.chat.id)
            bot.send_message(
                m.chat.id,
                "⏹ مانیتور متوقف شد." if stopped else "⚠️ مانیتور فعالی وجود ندارد.",
                reply_markup=main_menu(),
            )

        elif t == BTN_TOGGLE_TRIAL:
            enabled = get_trial_enabled()
            status = "🟢 فعال" if enabled else "🔴 غیرفعال"
            trials_used = get_trials_count()
            trial_limit = _current_trial_limit()
            trials_cap = (
                f"{trials_used}/{trial_limit}"
                if trial_limit > 0
                else f"{trials_used}/∞"
            )
            bot.send_message(
                m.chat.id,
                f"🧪 <b>اکانت تست</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"وضعیت فعلی: {status}\n"
                f"💾 حجم: <b>{TEST_ACCOUNT_MB:.0f} MB</b>\n"
                f"⏱ مدت تست: <b>{TEST_ACCOUNT_MINUTES} دقیقه</b>\n"
                f"👥 ظرفیت تست: <b>{trials_cap}</b>\n"
                "🎁 شرط رفرال: <b>ندارد</b>",
                reply_markup=trial_toggle_keyboard(enabled),
            )

        elif t == BTN_CLEANUP:
            bot.send_message(
                m.chat.id,
                "🧹 <b>پاکسازی کانفیگ‌های تمام‌شده</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "از گزینه‌های زیر انتخاب کنید:",
                reply_markup=cleanup_menu_keyboard(),
            )

        elif t == BTN_BLACKLIST_ADMIN:
            _clear_state(uid)
            bot.send_message(
                m.chat.id,
                "🚫 <b>مدیریت بلک‌لیست</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "یک گزینه را انتخاب کنید:",
                reply_markup=blacklist_admin_keyboard(),
            )

    # ── text message state machine ───────────────────────────────────────────
    @bot.message_handler(
        func=lambda m: m.content_type == "text" and not m.text.startswith("/")
    )
    def handle_text(m: telebot.types.Message) -> None:
        uid = m.from_user.id
        if _is_blocked(uid):
            _send_blacklist_denied(bot, m.chat.id)
            return
        if not _ensure_force_join(bot, uid, m.chat.id):
            return
        state = _states.get(uid)

        # ── wallet: waiting for deposit amount (all users) ────────────────────
        if state == S_WALLET_AMOUNT:
            try:
                amount = _parse_toman_to_k(m.text)
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ مبلغ نامعتبر. لطفاً مبلغ را به تومان و به‌صورت مضرب ۱۰۰۰ وارد کنید (مثال: 300000):",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data.setdefault(uid, {})["wallet_amount"] = amount
            _states[uid] = S_WALLET_PHOTO
            bot.send_message(
                m.chat.id,
                f"💳 مبلغ <b>{_fmt_toman(amount)}</b> را به شماره کارت زیر واریز کنید:\n\n"
                f"<code>{CARD_NUMBER}</code>\n\n"
                "📸 سپس تصویر رسید پرداخت را ارسال کنید:",
                reply_markup=cancel_keyboard(),
            )
            return

        # ── shop: waiting for config name (all users) ─────────────────────────
        elif state == S_SHOP_NAME:
            _set_shop_email_and_continue(bot, xui, uid, m.chat.id, m.text)
            return

        # ── shop: waiting for GB (typed manually, either S_SHOP_GB or custom) ──
        elif state in (S_SHOP_GB, S_SHOP_CUSTOM_GB):
            try:
                gb = float(m.text.strip().replace(",", "."))
                if gb <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً حجم را به گیگابایت وارد کنید:",
                    reply_markup=shop_gb_keyboard(),
                )
                return
            _data.setdefault(uid, {})["shop_gb"] = gb
            _data[uid]["shop_days"] = 0  # always unlimited
            _states[uid] = None
            _show_shop_confirm(bot, uid, m.chat.id)
            return

        # ── renew: waiting for GB (typed manually) ────────────────────────────
        elif state in (S_RENEW_GB, S_RENEW_CUSTOM_GB):
            try:
                gb = float(m.text.strip().replace(",", "."))
                if gb <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً حجم را به گیگابایت وارد کنید:",
                    reply_markup=renew_gb_keyboard(),
                )
                return
            _data.setdefault(uid, {})["renew_gb"] = gb
            _states[uid] = None
            _show_renew_confirm(bot, uid, m.chat.id)
            return

        # ── admin wireguard wizard: service name then target user_id ────────
        elif state == S_WG_NAME:
            if not _is_admin(uid):
                return
            wg_name = (m.text or "").strip()
            if not wg_name or " " in wg_name:
                bot.send_message(
                    m.chat.id,
                    "⚠️ نام سرویس نامعتبر است. بدون فاصله وارد کنید (مثال: wg_user01).",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data.setdefault(uid, {})["wg_name"] = wg_name
            _states[uid] = S_WG_USER_ID
            bot.send_message(
                m.chat.id,
                "مرحله 2/3: یوزر آیدی عددی کاربری که می‌خواهید سرویس به او تخصیص داده شود را وارد کنید.",
                reply_markup=cancel_keyboard(),
            )
            return

        elif state == S_WG_USER_ID:
            if not _is_admin(uid):
                return
            try:
                target_uid = int((m.text or "").strip())
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ یوزر آیدی باید عددی باشد. دوباره وارد کنید.",
                    reply_markup=cancel_keyboard(),
                )
                return

            _data.setdefault(uid, {})["wg_target_uid"] = target_uid
            _states[uid] = S_WG_GB
            bot.send_message(
                m.chat.id,
                "مرحله 3/3: حجم سرویس را به گیگابایت وارد کنید (مثال: 10).",
                reply_markup=cancel_keyboard(),
            )
            return

        elif state == S_WG_GB:
            if not _is_admin(uid):
                return
            try:
                wg_gb = float((m.text or "").strip().replace(",", "."))
                if wg_gb <= 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ حجم نامعتبر است. لطفاً یک عدد مثبت (GB) وارد کنید.",
                    reply_markup=cancel_keyboard(),
                )
                return

            d_wg = _data.get(uid, {})
            wg_name = (d_wg.get("wg_name") or "").strip()
            target_uid_raw = d_wg.get("wg_target_uid")
            try:
                target_uid = int(target_uid_raw)
            except Exception:
                target_uid = None
            if not wg_name:
                _clear_state(uid)
                bot.send_message(
                    m.chat.id,
                    "❌ اطلاعات ساخت WireGuard ناقص شد. دوباره تلاش کنید.",
                    reply_markup=main_menu(),
                )
                return
            if target_uid is None:
                _clear_state(uid)
                bot.send_message(
                    m.chat.id,
                    "❌ یوزر آیدی مقصد نامعتبر است. دوباره تلاش کنید.",
                    reply_markup=main_menu(),
                )
                return

            protocol = "wireguard"
            days = 0  # unlimited time

            bot.send_chat_action(m.chat.id, "typing")
            ok, wg_inbound, peer, err_msg = xui.add_wireguard_inbound(
                wg_name,
                total_gb=wg_gb,
                expiry_days=days,
                tg_id=target_uid,
            )
            if not ok:
                _clear_state(uid)
                bot.send_message(
                    m.chat.id,
                    "❌ خطا در ساخت سرویس WireGuard.\n"
                    f"جزئیات: <code>{err_msg or 'unknown_error'}</code>\n"
                    "ℹ️ این خطا الزاماً به معنی تکراری بودن نام نیست و می‌تواند از تنظیمات inbound باشد.",
                    reply_markup=main_menu(),
                )
                return

            inbound_id = int(wg_inbound.get("id") or 0)
            if not inbound_id:
                _clear_state(uid)
                bot.send_message(
                    m.chat.id,
                    "❌ سرویس در پنل ساخته شد اما ID آن دریافت نشد. لطفاً پنل را بررسی کنید.",
                    reply_markup=main_menu(),
                )
                return

            # Build WireGuard config file
            server_host = ((peer or {}).get("_server_host") or "").strip()
            if not server_host:
                parsed_url = urlparse(XUI_URL)
                server_host = parsed_url.hostname or XUI_URL
            wg_panel_url = ((peer or {}).get("_panel_url") or WG_XUI_URL or "").strip()
            wg_panel_base = ((peer or {}).get("_panel_base_path") or "").strip()
            inbound_port = int(wg_inbound.get("port") or 51820)
            wg_conf = _build_wg_config_text(peer, server_host, inbound_port)
            wg_conf_bytes = wg_conf.encode("utf-8")
            safe_name = re.sub(r"[^\w\-]", "_", wg_name)
            peer_ip = ((peer or {}).get("allowedIPs") or ["—"])[0]

            save_purchase(
                target_uid,
                wg_name,
                inbound_id,
                protocol,
                wg_gb,
                days,
                "",
                {
                    "wg_conf": wg_conf,
                    "peer_ip": peer_ip,
                    "inbound_port": inbound_port,
                    "inbound_remark": wg_inbound.get("remark") or wg_name,
                },
            )
            _clear_state(uid)

            admin_tag = f"@{m.from_user.username}" if m.from_user.username else "—"
            _notify(
                "🛡 <b>سرویس WireGuard توسط ادمین ساخته شد</b>\n"
                f"👮 ادمین: <code>{admin_tag}</code> | <code>{uid}</code>\n"
                f"🆔 کاربر مقصد: <code>{target_uid}</code>\n"
                f"👤 نام سرویس: <code>{wg_name}</code>\n"
                f"🔌 پروتکل: {protocol.upper()}\n"
                f"💾 حجم ثبت‌شده: {wg_gb:g} GB\n"
                f"🏷 IP Peer: <code>{peer_ip}</code>\n"
                f"🖥 پنل WireGuard: <code>{wg_panel_url}{wg_panel_base}</code>"
            )

            bot.send_message(
                m.chat.id,
                "✅ <b>سرویس WireGuard ساخته و تخصیص داده شد.</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 نام سرویس: <code>{wg_name}</code>\n"
                f"🆔 یوزر مقصد: <code>{target_uid}</code>\n"
                f"🧩 آیدی پنل: <code>{inbound_id}</code>\n"
                f"🔌 پروتکل: {protocol.upper()}\n"
                f"💾 حجم ثبت‌شده: <b>{wg_gb:g} GB</b>\n"
                f"🔢 پورت: <code>{inbound_port}</code>\n"
                f"🏷 IP Peer: <code>{peer_ip}</code>\n"
                f"🖥 پنل WireGuard: <code>{wg_panel_url}{wg_panel_base}</code>\n"
                "📦 وضعیت ثبت: به پنل و سرویس‌های کاربر اضافه شد.",
                reply_markup=main_menu(),
            )
            bot.send_document(
                m.chat.id,
                io.BytesIO(wg_conf_bytes),
                visible_file_name=f"{safe_name}.conf",
                caption=f"📄 فایل کانفیگ WireGuard برای <code>{wg_name}</code>",
            )

            try:
                bot.send_message(
                    target_uid,
                    "✅ یک سرویس WireGuard جدید توسط ادمین به حساب شما اضافه شد.\n"
                    f"👤 نام سرویس: <code>{wg_name}</code>\n"
                    f"💾 حجم ثبت‌شده: <b>{wg_gb:g} GB</b>\n"
                    "📄 فایل کانفیگ را در پیام بعدی دریافت کنید.\n"
                    "برای اتصال، فایل را در اپلیکیشن WireGuard ایمپورت کنید.",
                    reply_markup=user_menu(get_balance(target_uid)),
                )
                bot.send_document(
                    target_uid,
                    io.BytesIO(wg_conf_bytes),
                    visible_file_name=f"{safe_name}.conf",
                    caption=f"📄 کانفیگ WireGuard شما — <code>{wg_name}</code>\nاین فایل را در اپ WireGuard ایمپورت کنید.",
                )
            except Exception:
                pass
            return

        # ── blacklist: waiting for identifier / user_id / custom reason ─────
        elif state == S_BL_IDENTIFIER:
            if not _is_admin(uid):
                return
            identifier = (m.text or "").strip()
            if not identifier:
                bot.send_message(
                    m.chat.id,
                    "⚠️ آیدی نامعتبر است. دوباره وارد کنید (مثال: @username).",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data.setdefault(uid, {})["bl_identifier"] = identifier
            _states[uid] = S_BL_USER_ID
            bot.send_message(
                m.chat.id,
                "مرحله 2/3: یوزر آیدی عددی کاربر را وارد کنید.",
                reply_markup=cancel_keyboard(),
            )
            return

        elif state == S_BL_USER_ID:
            if not _is_admin(uid):
                return
            try:
                target_uid = int((m.text or "").strip())
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ یوزر آیدی باید عددی باشد. دوباره وارد کنید.",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data.setdefault(uid, {})["bl_user_id"] = target_uid
            _data[uid].pop("bl_custom_reason", None)
            _states[uid] = S_BL_REASON
            bot.send_message(
                m.chat.id,
                "مرحله 3/3: دلیل بلک‌لیست را انتخاب کنید یا دلیل دلخواه بزنید.",
                reply_markup=blacklist_reason_keyboard(),
            )
            return

        elif state == S_BL_REASON:
            if not _is_admin(uid):
                return
            reason = (m.text or "").strip()
            if not reason:
                bot.send_message(
                    m.chat.id,
                    "⚠️ دلیل نامعتبر است. لطفاً دلیل را وارد کنید.",
                    reply_markup=blacklist_reason_keyboard(),
                )
                return
            d_bl = _data.get(uid, {})
            target_uid = d_bl.get("bl_user_id")
            identifier = d_bl.get("bl_identifier") or str(target_uid)
            _clear_state(uid)
            _apply_blacklist(bot, m.chat.id, int(target_uid), identifier, reason, uid)
            return

        elif state == S_BL_REMOVE_USER_ID:
            if not _is_admin(uid):
                return
            try:
                target_uid = int((m.text or "").strip())
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ یوزر آیدی باید عددی باشد. دوباره وارد کنید.",
                    reply_markup=cancel_keyboard(),
                )
                return

            removed = remove_blacklist(target_uid)
            _clear_state(uid)
            if removed:
                bot.send_message(
                    m.chat.id,
                    "✅ کاربر با موفقیت از بلک‌لیست حذف شد.\n"
                    f"🆔 یوزر آیدی: <code>{target_uid}</code>",
                    reply_markup=main_menu(),
                )
            else:
                bot.send_message(
                    m.chat.id,
                    "ℹ️ این کاربر در بلک‌لیست نبود.\n"
                    f"🆔 یوزر آیدی: <code>{target_uid}</code>",
                    reply_markup=main_menu(),
                )
            return

        # ── all remaining states require admin ────────────────────────────────
        if not _is_admin(uid):
            return

        # ── check traffic: waiting for email
        if state == S_TRAFFIC_EMAIL:
            _clear_state(uid)
            email = m.text.strip()
            bot.send_chat_action(m.chat.id, "typing")
            traffic = xui.get_client_traffic(email)

            if traffic is None:
                bot.send_message(
                    m.chat.id,
                    f"❌ کاربری با ایمیل <code>{email}</code> پیدا نشد.",
                    reply_markup=main_menu(),
                )
                return

            up = traffic.get("up", 0)
            down = traffic.get("down", 0)
            total = traffic.get("total", 0)
            expiry = traffic.get("expiryTime", 0)
            enabled = "✅ فعال" if traffic.get("enable") else "❌ غیرفعال"
            used = up + down
            remain = (total - used) if total > 0 else None

            msg = (
                "📊 <b>اطلاعات ترافیک کاربر</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"👤 ایمیل:         <code>{email}</code>\n"
                f"📶 وضعیت:        {enabled}\n"
                f"⬆️ آپلود:         {_fmt_bytes(up)}\n"
                f"⬇️ دانلود:        {_fmt_bytes(down)}\n"
                f"📦 مجموع مصرف: {_fmt_bytes(used)}\n"
                f"💾 حجم کل:       {'♾ نامحدود' if total == 0 else _fmt_bytes(total)}\n"
                + (
                    f"📉 باقیمانده:    {_fmt_bytes(remain)}\n"
                    if remain is not None
                    else ""
                )
                + f"⏳ انقضا:        {_fmt_expiry(expiry)}"
            )
            bot.send_message(m.chat.id, msg, reply_markup=main_menu())

        # ── create user: waiting for email
        elif state == S_CREATE_EMAIL:
            email = m.text.strip()
            if not email or " " in email:
                bot.send_message(
                    m.chat.id,
                    "⚠️ ایمیل نامعتبر است. بدون فاصله وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data[uid]["email"] = email
            _states[uid] = S_CREATE_USER_ID
            bot.send_message(
                m.chat.id,
                "🆔 یوزر آیدی کاربری که این کانفیگ باید به او تعلق بگیرد را وارد کنید:\n"
                "<i>(اختیاری است؛ اگر نمی‌خواهید، دکمه Skip را بزنید)</i>",
                reply_markup=create_user_target_keyboard(),
            )

        # ── create user: waiting for optional target user_id
        elif state == S_CREATE_USER_ID:
            raw_uid = (m.text or "").strip()
            try:
                target_uid = int(raw_uid)
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ یوزر آیدی باید عددی باشد یا از دکمه Skip استفاده کنید.",
                    reply_markup=create_user_target_keyboard(),
                )
                return
            _data[uid]["assign_user_id"] = target_uid
            _states[uid] = S_CREATE_GB
            bot.send_message(
                m.chat.id,
                "✅ تعلق کانفیگ ثبت شد.\n"
                "💾 حالا حجم اینترنت را به گیگابایت وارد کنید:\n"
                "<i>(برای نامحدود عدد ۰ وارد کنید)</i>",
                reply_markup=cancel_keyboard(),
            )

        # ── create user: waiting for GB
        elif state == S_CREATE_GB:
            try:
                gb = float(m.text.strip().replace(",", "."))
                if gb < 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً یک عدد مثبت وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data[uid]["gb"] = gb
            _states[uid] = S_CREATE_DAYS
            bot.send_message(
                m.chat.id,
                "📅 تعداد روز اعتبار را وارد کنید یا یکی از گزینه‌ها را انتخاب کنید:",
                reply_markup=expiry_keyboard(),
            )

        # ── create user: waiting for expiry days (typed)
        elif state == S_CREATE_DAYS:
            try:
                days = int(m.text.strip())
                if days < 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً یک عدد صحیح مثبت وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            _do_create(bot, xui, uid, m.chat.id, days)

        # ── add traffic: waiting for GB to add
        elif state == S_ADD_TRAFFIC:
            try:
                gb = float(m.text.strip().replace(",", "."))
                if gb < 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً یک عدد مثبت وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            d_data = _data.get(uid, {})
            iid = d_data.get("edit_inbound_id")
            email = d_data.get("edit_email")
            _clear_state(uid)
            if not iid or not email:
                bot.send_message(
                    m.chat.id, "❌ اطلاعات ناقص.", reply_markup=main_menu()
                )
                return
            if gb == 0:
                new_gb = 0.0  # unlimited
            else:
                traffic = xui.get_client_traffic(email)
                cur_bytes = int((traffic or {}).get("total", 0) or 0)
                new_gb = (cur_bytes + int(gb * 1_073_741_824)) / 1_073_741_824
            ok = xui.update_client(iid, email, total_gb=new_gb, enable=True)
            bot.send_message(
                m.chat.id,
                (
                    f"✅ {'حجم نامحدود شد' if gb == 0 else f'{gb:.1f} GB به ترافیک اضافه شد'}."
                )
                if ok
                else "❌ خطا در اضافه کردن ترافیک.",
                reply_markup=client_actions_keyboard(iid, email),
            )

        # ── edit client: waiting for new total GB
        elif state == S_EDIT_GB:
            try:
                gb = float(m.text.strip().replace(",", "."))
                if gb < 0:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً یک عدد مثبت وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            _data.setdefault(uid, {})["new_gb"] = gb
            _states[uid] = S_EDIT_DAYS
            bot.send_message(
                m.chat.id,
                "📅 تعداد روز اعتبار جدید:\n<i>(0 = نامحدود | -1 = بدون تغییر)</i>",
                reply_markup=cancel_keyboard(),
            )

        # ── edit client: waiting for new expiry days
        elif state == S_EDIT_DAYS:
            try:
                days = int(m.text.strip())
                if days < -1:
                    raise ValueError
            except ValueError:
                bot.send_message(
                    m.chat.id,
                    "⚠️ عدد نامعتبر. لطفاً یک عدد صحیح وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return
            d_data = _data.get(uid, {})
            iid = d_data.get("edit_inbound_id")
            email = d_data.get("edit_email")
            gb = d_data.get("new_gb")
            _clear_state(uid)
            if not iid or not email or gb is None:
                bot.send_message(
                    m.chat.id, "❌ اطلاعات ناقص.", reply_markup=main_menu()
                )
                return
            expiry_param = None if days == -1 else days
            ok = xui.update_client(
                iid, email, total_gb=gb, expiry_days=expiry_param, enable=True
            )
            bot.send_message(
                m.chat.id,
                f"✅ کاربر <code>{email}</code> با موفقیت ویرایش شد."
                if ok
                else f"❌ خطا در ویرایش کاربر <code>{email}</code>.",
                reply_markup=client_actions_keyboard(iid, email),
            )

        else:
            if _is_admin(uid):
                bot.send_message(
                    m.chat.id, "یک گزینه را انتخاب کنید:", reply_markup=main_menu()
                )
            else:
                _send_user_menu(bot, m.chat.id, uid)

    # ── callback queries ─────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: True)
    def handle_callback(c: telebot.types.CallbackQuery) -> None:
        uid = c.from_user.id
        d = c.data

        allowed_blocked_callbacks = (
            "blpage:",
            "noop",
        )
        if _is_blocked(uid) and not any(
            d == x or d.startswith(x) for x in allowed_blocked_callbacks
        ):
            bot.answer_callback_query(c.id, "⛔️ دسترسی ندارید")
            _send_blacklist_denied(bot, c.message.chat.id)
            return

        if d == "check_join":
            if not _is_force_join_member(bot, uid):
                bot.answer_callback_query(c.id, "هنوز عضو کانال نیستید")
                _send_force_join(bot, c.message.chat.id)
                return

            bot.answer_callback_query(c.id, "عضویت تایید شد")
            pending_start_text = (_data.get(uid) or {}).get("pending_start_text")
            _register_referral_from_start(bot, uid, pending_start_text)
            mark_user_started(
                uid,
                c.from_user.username,
                c.from_user.first_name,
                c.from_user.last_name,
            )
            _clear_state(uid)
            _send_user_menu(bot, c.message.chat.id, uid)
            return

        if not _is_force_join_member(bot, uid):
            bot.answer_callback_query(c.id, "ابتدا عضو کانال شوید")
            _send_force_join(bot, c.message.chat.id)
            return

        # ── trial toggle (admin only) ─────────────────────────────────────────
        if d.startswith("trial_toggle:"):
            if not _is_admin(uid):
                bot.answer_callback_query(c.id, "⛔️ دسترسی غیر مجاز")
                return
            bot.answer_callback_query(c.id)
            new_state = d.split(":", 1)[1] == "on"
            set_trial_enabled(new_state)
            status = "🟢 فعال" if new_state else "🔴 غیرفعال"
            trials_used = get_trials_count()
            trial_limit = _current_trial_limit()
            trials_cap = (
                f"{trials_used}/{trial_limit}"
                if trial_limit > 0
                else f"{trials_used}/∞"
            )
            bot.edit_message_text(
                f"🧪 <b>اکانت تست</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"وضعیت فعلی: {status}\n"
                f"💾 حجم: <b>{TEST_ACCOUNT_MB:.0f} MB</b>\n"
                f"⏱ مدت تست: <b>{TEST_ACCOUNT_MINUTES} دقیقه</b>\n"
                f"👥 ظرفیت تست: <b>{trials_cap}</b>\n"
                "🎁 شرط رفرال: <b>ندارد</b>",
                chat_id=c.message.chat.id,
                message_id=c.message.message_id,
                reply_markup=trial_toggle_keyboard(new_state),
                parse_mode="HTML",
            )
            return

        # ── payment approve / reject  (admin only, works from group) ─────────
        if d.startswith(("pay_approve:", "pay_reject:", "pay_blacklist:")):
            if not _is_admin(uid):
                bot.answer_callback_query(c.id, "⛔️ دسترسی غیر مجاز")
                return
            bot.answer_callback_query(c.id)
            action, pay_id = d.split(":", 1)
            payment = get_pending_payment(pay_id)
            if not payment:
                bot.answer_callback_query(c.id, "⚠️ پرداخت پیدا نشد یا قبلاً پردازش شده.")
                return
            puid = payment["user_id"]
            amount = payment["amount"]
            username = payment.get("username", str(puid))
            remove_pending_payment(pay_id)
            if action == "pay_approve":
                new_bal = add_balance(puid, amount)
                result_text = f"✅ پرداخت تأیید شد (+{_fmt_toman(amount)})"
                try:
                    bot.send_message(
                        puid,
                        f"✅ شارژ کیف پول تأیید شد!\n"
                        f"💰 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                        f"👛 موجودی جدید: <b>{_fmt_toman(new_bal)}</b>",
                        reply_markup=user_menu(new_bal),
                    )
                except Exception:
                    pass
            elif action == "pay_blacklist":
                identifier = (
                    username if str(username).startswith("@") else f"@{username}"
                )
                set_blacklist(puid, identifier, "رسید فیک", uid)
                result_text = "🚫 کاربر بلک‌لیست شد (دلیل: رسید فیک)"
                try:
                    bot.send_message(
                        puid,
                        "⛔️ شما در لیست بلک‌لیست قرار گرفتین و امکان استفاده از ربات را ندارید.\n"
                        "📌 دلیل: رسید فیک",
                    )
                except Exception:
                    pass
            else:
                result_text = f"❌ پرداخت رد شد"
                try:
                    bot.send_message(
                        puid,
                        "❌ متأسفانه درخواست شارژ شما رد شد.\n"
                        "در صورت نیاز با پشتیبانی تماس بگیرید.",
                        reply_markup=user_menu(get_balance(puid)),
                    )
                except Exception:
                    pass
            # Edit the group message caption
            try:
                new_caption = (
                    f"{c.message.caption or ''}\n\n"
                    f"── {result_text}\n"
                    f"👤 ادمین: @{c.from_user.username or uid}"
                )
                bot.edit_message_caption(
                    caption=new_caption,
                    chat_id=c.message.chat.id,
                    message_id=c.message.message_id,
                )
            except Exception:
                pass
            return

        # ── blacklist reason picker (admin) ──────────────────────────────────
        if d.startswith("blrsn:"):
            if not _is_admin(uid):
                bot.answer_callback_query(c.id, "⛔️ دسترسی غیر مجاز")
                return
            if _states.get(uid) != S_BL_REASON:
                bot.answer_callback_query(c.id, "⚠️ مرحله دلیل فعال نیست")
                return
            bot.answer_callback_query(c.id)
            value = d.split(":", 1)[1]
            if value == "custom":
                _data.setdefault(uid, {})["bl_custom_reason"] = True
                bot.send_message(
                    c.message.chat.id,
                    "✏️ دلیل دلخواه را تایپ کنید:",
                    reply_markup=cancel_keyboard(),
                )
                return

            d_bl = _data.get(uid, {})
            target_uid = d_bl.get("bl_user_id")
            identifier = d_bl.get("bl_identifier") or str(target_uid)
            _clear_state(uid)
            _apply_blacklist(
                bot, c.message.chat.id, int(target_uid), identifier, value, uid
            )
            return

        # ── blacklist admin actions (add/remove) ───────────────────────────
        if d.startswith("bladmin:"):
            if not _is_admin(uid):
                bot.answer_callback_query(c.id, "⛔️ دسترسی غیر مجاز")
                return
            bot.answer_callback_query(c.id)
            action = d.split(":", 1)[1]

            if action == "add":
                _clear_state(uid)
                _states[uid] = S_BL_IDENTIFIER
                bot.send_message(
                    c.message.chat.id,
                    "🚫 <b>افزودن کاربر به بلک‌لیست</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "مرحله 1/3: آیدی کاربر را وارد کنید (مثال: @username).",
                    reply_markup=cancel_keyboard(),
                )
            elif action == "remove":
                _clear_state(uid)
                _states[uid] = S_BL_REMOVE_USER_ID
                bot.send_message(
                    c.message.chat.id,
                    "✅ <b>حذف کاربر از بلک‌لیست</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "یوزر آیدی عددی کاربر را وارد کنید:",
                    reply_markup=cancel_keyboard(),
                )
            else:
                bot.send_message(
                    c.message.chat.id,
                    "⚠️ گزینه نامعتبر است.",
                    reply_markup=main_menu(),
                )
            return

        # ── blacklist pages (all users) ──────────────────────────────────────
        if d.startswith("blpage:"):
            bot.answer_callback_query(c.id)
            page = int(d.split(":", 1)[1])
            _show_blacklist_page(
                bot, c.message.chat.id, page=page, admin_mode=_is_admin(uid)
            )
            return

        # ── user panel callbacks (accessible to all users) ────────────────────
        if d in (
            "wallet",
            "wallet_charge",
            "shop",
            "buy_new_menu",
            "shop_confirm",
            "back_user_menu",
            "shop_name_random",
            "my_configs",
            "my_services",
            "referral",
            "claim_referral_config",
            "renew_confirm",
            "server_status",
        ) or d.startswith(
            (
                "shop_gb:",
                "shop_days:",
                "mc_detail:",
                "mc_refresh:",
                "mc_regen:",
                "mc_renew:",
                "renew_gb:",
                "svc_buy:",
            )
        ):
            bot.answer_callback_query(c.id)

            if d == "back_user_menu" or d == "wallet" and _states.get(uid) is None:
                pass  # fall through to specific handler below

            if d == "wallet":
                balance = get_balance(uid)
                bot.send_message(
                    c.message.chat.id,
                    f"💰 <b>کیف پول</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"موجودی: <b>{_fmt_toman(balance)}</b>\n\n"
                    f"💳 شماره کارت جهت شارژ:\n<code>{CARD_NUMBER}</code>",
                    reply_markup=wallet_keyboard(),
                )

            elif d == "wallet_charge":
                _clear_state(uid)
                _states[uid] = S_WALLET_AMOUNT
                bot.send_message(
                    c.message.chat.id,
                    "💵 مبلغ موردنظر برای شارژ را به <b>تومان</b> وارد کنید (مثال: 300000):",
                    reply_markup=cancel_keyboard(),
                )

            elif d in ("shop", "buy_new_menu"):
                _clear_state(uid)
                balance = get_balance(uid)
                bot.send_message(
                    c.message.chat.id,
                    f"🚀 <b>خرید سرویس جدید</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"👛 موجودی شما: <b>{_fmt_toman(balance)}</b>\n\n"
                    "یک بسته را انتخاب کنید:",
                    reply_markup=services_keyboard(),
                )

            elif d == "shop_name_random":
                if _states.get(uid) != S_SHOP_NAME:
                    bot.send_message(
                        c.message.chat.id, "⚠️ الان در مرحله تعیین نام کانفیگ نیستید."
                    )
                else:
                    gb = (_data.get(uid) or {}).get("shop_gb")
                    random_name = _gen_shop_name(c.from_user.username or uid, gb)
                    _set_shop_email_and_continue(
                        bot, xui, uid, c.message.chat.id, random_name
                    )

            elif d.startswith("shop_inbound:"):
                # legacy — kept for safety; not used in auto-select flow
                parts = d.split(":", 2)
                if len(parts) == 3:
                    iid, proto = int(parts[1]), parts[2]
                    _data.setdefault(uid, {})["shop_inbound_id"] = iid
                    _data[uid]["shop_protocol"] = proto
                    _states[uid] = S_SHOP_GB
                    bot.send_message(
                        c.message.chat.id,
                        "💾 حجم اینترنت را انتخاب کنید:\n"
                        f"<i>هر GB = {_fmt_toman(PRICE_PER_GB)}</i>",
                        reply_markup=shop_gb_keyboard(),
                    )

            elif d.startswith("shop_gb:"):
                val = d.split(":", 1)[1]
                if val == "custom":
                    _states[uid] = S_SHOP_CUSTOM_GB
                    bot.send_message(
                        c.message.chat.id,
                        "✏️ حجم دلخواه را به گیگابایت وارد کنید:\n"
                        f"<i>هر GB = {_fmt_toman(PRICE_PER_GB)}</i>",
                        reply_markup=cancel_keyboard(),
                    )
                else:
                    gb = float(val)
                    _data.setdefault(uid, {})["shop_gb"] = gb
                    _data[uid]["shop_days"] = 0  # always unlimited
                    _states[uid] = None
                    _show_shop_confirm(bot, uid, c.message.chat.id)

            elif d == "shop_confirm":
                _do_shop_purchase(
                    bot, xui, uid, c.message.chat.id, c.from_user.username
                )

            elif d == "back_user_menu":
                _clear_state(uid)
                _send_user_menu(bot, c.message.chat.id, uid)

            elif d == "referral":
                if REFERRAL_ENABLED:
                    _show_referral(bot, c.message.chat.id, uid)
                else:
                    bot.send_message(
                        c.message.chat.id, "⚠️ قابلیت دعوت دوستان موقتاً غیرفعال است."
                    )

            elif d == "claim_referral_config":
                if REFERRAL_ENABLED:
                    _claim_referral_config(
                        bot, xui, uid, c.message.chat.id, c.from_user.username
                    )
                else:
                    bot.send_message(
                        c.message.chat.id, "⚠️ قابلیت دعوت دوستان موقتاً غیرفعال است."
                    )

            elif d == "server_status":
                bot.send_message(c.message.chat.id, _format_server_status_message())

            elif d == "my_configs":
                _sync_deleted_panel_configs_for_user(xui, uid)
                purchases = get_purchases(uid)
                if not purchases:
                    bot.send_message(
                        c.message.chat.id,
                        "📋 شما هنوز کانفیگی خریداری نکرده‌اید.",
                        reply_markup=user_menu(get_balance(uid)),
                    )
                else:
                    bot.send_message(
                        c.message.chat.id,
                        f"📋 <b>کانفیگ‌های من ({len(purchases)}):</b>\n"
                        "یک کانفیگ را انتخاب کنید:",
                        reply_markup=my_configs_keyboard(purchases),
                    )

            elif d == "my_services":
                _sync_deleted_panel_configs_for_user(xui, uid)
                purchases = get_purchases(uid)
                if not purchases:
                    bot.send_message(
                        c.message.chat.id,
                        "📋 شما هنوز سرویسی خریداری نکرده‌اید.\n"
                        "برای خرید روی «خرید سرویس جدید» بزنید.",
                        reply_markup=user_menu(get_balance(uid)),
                    )
                else:
                    bot.send_message(
                        c.message.chat.id,
                        f"📋 <b>سرویس‌های من ({len(purchases)}):</b>\n"
                        "یک سرویس را انتخاب کنید:",
                        reply_markup=my_configs_keyboard(purchases),
                    )

            elif d.startswith("mc_detail:"):
                idx = int(d.split(":", 1)[1])
                _sync_deleted_panel_configs_for_user(xui, uid)
                purchases = get_purchases(uid)
                if idx >= len(purchases):
                    bot.send_message(c.message.chat.id, "❌ کانفیگ یافت نشد.")
                else:
                    p = purchases[idx]
                    import datetime as _dt

                    # ── live data from panel ──────────────────────────────────
                    bot.send_chat_action(c.message.chat.id, "typing")
                    traffic = xui.get_client_traffic(p["email"], p.get("inbound_id"))
                    online_list = _online_set(xui)
                    email_cf = str(p.get("email") or "").strip().casefold()
                    is_online = email_cf in online_list or any(
                        email_cf and email_cf in tok for tok in online_list
                    )

                    if traffic:
                        up = traffic.get("up", 0)
                        down = traffic.get("down", 0)
                        total_b = traffic.get("total", 0)
                        used_b = up + down
                        rem_b = max(0, total_b - used_b) if total_b > 0 else -1
                        expiry_ms = traffic.get("expiryTime", 0)
                        enabled = traffic.get("enable", True)

                        used_str = _fmt_bytes(used_b)
                        total_str = "♾ نامحدود" if total_b == 0 else _fmt_bytes(total_b)
                        rem_str = "♾ نامحدود" if rem_b < 0 else _fmt_bytes(rem_b)

                        if expiry_ms and expiry_ms > 0:
                            exp_dt = _dt.datetime.fromtimestamp(expiry_ms / 1000)
                            now_dt = _dt.datetime.now()
                            days_left = (exp_dt - now_dt).days
                            exp_str = exp_dt.strftime("%Y-%m-%d")
                            if days_left <= 0:
                                exp_label = f"⛔ منقضی شده ({exp_str})"
                            elif days_left <= 5:
                                exp_label = f"⚠️ {days_left} روز مانده ({exp_str})"
                            else:
                                exp_label = f"✅ {days_left} روز مانده ({exp_str})"
                        else:
                            exp_label = "♾ بدون محدودیت"

                        enable_icon = "🟢 فعال" if enabled else "🔴 غیرفعال"
                        online_icon = "🌐 آنلاین" if is_online else "⚫ آفلاین"

                        ts = _dt.datetime.fromtimestamp(p["ts"]).strftime("%Y-%m-%d")
                        days_label = (
                            "♾ بدون محدودیت" if p["days"] == 0 else f"{p['days']} روز"
                        )
                        info_text = (
                            f"⚙️ <b>اطلاعات کانفیگ</b>\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"👤 نام:          <code>{p['email']}</code>\n"
                            f"🔌 پروتکل:      {p['protocol'].upper()}\n"
                            f"📶 وضعیت:       {enable_icon}  {online_icon}\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"📊 مصرف شده:    {used_str}\n"
                            f"  ↑ آپلود:      {_fmt_bytes(up)}\n"
                            f"  ↓ دانلود:     {_fmt_bytes(down)}\n"
                            f"📦 کل حجم:      {total_str}\n"
                            f"🔋 باقی‌مانده:   {rem_str}\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"📅 انقضا:        {exp_label}\n"
                            f"🗓 تاریخ خرید:  {ts}"
                        )
                    else:
                        ts = _dt.datetime.fromtimestamp(p["ts"]).strftime("%Y-%m-%d")
                        days_label = (
                            "♾ بدون محدودیت" if p["days"] == 0 else f"{p['days']} روز"
                        )
                        online_icon = "🌐 آنلاین" if is_online else "⚫ آفلاین"
                        info_text = (
                            f"⚙️ <b>اطلاعات کانفیگ</b>\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"👤 نام:          <code>{p['email']}</code>\n"
                            f"🔌 پروتکل:      {p['protocol'].upper()}\n"
                            f"📶 وضعیت:       {online_icon}\n"
                            "━━━━━━━━━━━━━━━━━━\n"
                            f"💾 حجم خریداری: {p['gb']:.0f} GB\n"
                            f"📅 اعتبار:       {days_label}\n"
                            f"🗓 تاریخ خرید:  {ts}\n\n"
                            "⚠️ اطلاعات لحظه‌ای از پنل دریافت نشد."
                        )
                    bot.send_message(
                        c.message.chat.id,
                        info_text,
                        reply_markup=config_detail_keyboard(idx),
                    )

            elif d.startswith("mc_refresh:"):
                idx = int(d.split(":", 1)[1])
                purchases = get_purchases(uid)
                if idx >= len(purchases):
                    bot.send_message(c.message.chat.id, "❌ کانفیگ یافت نشد.")
                else:
                    p = purchases[idx]
                    if str(p.get("protocol", "")).lower() == "wireguard" and p.get(
                        "wg_conf"
                    ):
                        safe_name = re.sub(
                            r"[^\w\-]", "_", str(p.get("email") or "wireguard")
                        )
                        bot.send_document(
                            c.message.chat.id,
                            io.BytesIO(str(p["wg_conf"]).encode("utf-8")),
                            visible_file_name=f"{safe_name}.conf",
                            caption=f"🔄 فایل WireGuard جدید/ذخیره‌شده برای <code>{p['email']}</code>",
                        )
                    else:
                        links = [
                            _add_insecure_to_link(lnk)
                            for lnk in xui.get_client_links(p["inbound_id"], p["email"])
                        ]
                        if links:
                            bot.send_message(
                                c.message.chat.id,
                                f"🔄 <b>لینک‌های جدید ({p['email']}):</b>",
                            )
                            for lnk in links:
                                bot.send_message(
                                    c.message.chat.id, f"<code>{lnk}</code>"
                                )
                        else:
                            bot.send_message(
                                c.message.chat.id,
                                "⚠️ لینکی دریافت نشد. ممکن است کانفیگ حذف شده باشد.",
                            )
                    if (
                        str(p.get("protocol", "")).lower() != "wireguard"
                        and p.get("sub_id")
                        and XUI_SUB_BASE_URL
                    ):
                        bot.send_message(
                            c.message.chat.id,
                            f"🔗 <b>لینک اشتراک:</b>\n"
                            f"<code>{XUI_SUB_BASE_URL}/sub/{p['sub_id']}</code>",
                        )

            elif d.startswith("mc_regen:"):
                idx = int(d.split(":", 1)[1])
                _sync_deleted_panel_configs_for_user(xui, uid)
                purchases = get_purchases(uid)
                if idx >= len(purchases):
                    bot.send_message(c.message.chat.id, "❌ کانفیگ یافت نشد.")
                else:
                    p = purchases[idx]
                    if str(p.get("protocol", "")).lower() == "wireguard":
                        bot.send_chat_action(c.message.chat.id, "typing")
                        ok, inbound_obj, peer, err = xui.rotate_wireguard_peer_secret(
                            int(p["inbound_id"]),
                            p["email"],
                        )
                        if not ok or not isinstance(peer, dict):
                            bot.send_message(
                                c.message.chat.id,
                                "❌ تعویض Secret برای WireGuard ناموفق بود.\n"
                                f"جزئیات: <code>{err or 'unknown_error'}</code>",
                            )
                        else:
                            parsed_url = urlparse(XUI_URL)
                            server_host = parsed_url.hostname or XUI_URL
                            inbound_port = int(
                                (inbound_obj or {}).get("port")
                                or p.get("inbound_port")
                                or 51820
                            )
                            wg_conf = _build_wg_config_text(
                                peer, server_host, inbound_port
                            )

                            updated_local = update_purchase_fields(
                                uid,
                                int(p["inbound_id"]),
                                p["email"],
                                int(p.get("ts") or 0),
                                {
                                    "wg_conf": wg_conf,
                                    "inbound_port": inbound_port,
                                },
                            )
                            if not updated_local:
                                log.warning(
                                    "mc_regen wg: purchase update not found for user=%s inbound=%s email=%s ts=%s",
                                    uid,
                                    p.get("inbound_id"),
                                    p.get("email"),
                                    p.get("ts"),
                                )

                            safe_name = re.sub(
                                r"[^\w\-]", "_", str(p.get("email") or "wireguard")
                            )

                            bot.send_message(
                                c.message.chat.id,
                                "✅ <b>Secret کانفیگ WireGuard با موفقیت عوض شد.</b>\n"
                                "━━━━━━━━━━━━━━━━━━\n"
                                f"👤 کانفیگ: <code>{p['email']}</code>",
                            )
                            bot.send_document(
                                c.message.chat.id,
                                io.BytesIO(wg_conf.encode("utf-8")),
                                visible_file_name=f"{safe_name}.conf",
                                caption=f"📄 فایل جدید WireGuard برای <code>{p['email']}</code>",
                            )
                    else:
                        bot.send_chat_action(c.message.chat.id, "typing")
                        ok, new_id, new_sub_id, err = xui.regenerate_client_identity(
                            int(p["inbound_id"]),
                            p["email"],
                        )
                        if not ok or not new_id or not new_sub_id:
                            bot.send_message(
                                c.message.chat.id,
                                "❌ ریجنریت UUID/SubID ناموفق بود.\n"
                                f"جزئیات: <code>{err or 'unknown_error'}</code>",
                            )
                        else:
                            updated_local = update_purchase_fields(
                                uid,
                                int(p["inbound_id"]),
                                p["email"],
                                int(p.get("ts") or 0),
                                {"sub_id": new_sub_id, "client_id": new_id},
                            )
                            if not updated_local:
                                log.warning(
                                    "mc_regen: purchase update not found for user=%s inbound=%s email=%s ts=%s",
                                    uid,
                                    p.get("inbound_id"),
                                    p.get("email"),
                                    p.get("ts"),
                                )

                            links = [
                                _add_insecure_to_link(lnk)
                                for lnk in xui.get_client_links(
                                    int(p["inbound_id"]), p["email"]
                                )
                            ]

                            bot.send_message(
                                c.message.chat.id,
                                "✅ <b>UUID و SubID با موفقیت ریجنریت شد.</b>\n"
                                "━━━━━━━━━━━━━━━━━━\n"
                                f"👤 کانفیگ: <code>{p['email']}</code>\n"
                                "🆔 UUID جدید:\n"
                                f"<code>{new_id}</code>\n"
                                "🔑 SubID جدید:\n"
                                f"<code>{new_sub_id}</code>",
                            )

                            if links:
                                bot.send_message(
                                    c.message.chat.id,
                                    f"📋 <b>کانفیگ‌های جدید ({p['email']}):</b>",
                                )
                                for lnk in links:
                                    bot.send_message(
                                        c.message.chat.id, f"<code>{lnk}</code>"
                                    )
                            else:
                                bot.send_message(
                                    c.message.chat.id,
                                    "⚠️ لینک کانفیگ دریافت نشد. دوباره «دریافت لینک جدید» را بزنید.",
                                )

                            if XUI_SUB_BASE_URL:
                                bot.send_message(
                                    c.message.chat.id,
                                    "🔗 <b>لینک اشتراک جدید:</b>\n"
                                    f"<code>{XUI_SUB_BASE_URL}/sub/{new_sub_id}</code>",
                                )

            elif d.startswith("mc_renew:"):
                idx = int(d.split(":", 1)[1])
                purchases = get_purchases(uid)
                if idx >= len(purchases):
                    bot.send_message(c.message.chat.id, "❌ کانفیگ یافت نشد.")
                else:
                    p = purchases[idx]
                    _clear_state(uid)
                    _data[uid] = {"renew_idx": idx}
                    _states[uid] = S_RENEW_GB
                    balance = get_balance(uid)
                    bot.send_message(
                        c.message.chat.id,
                        f"🔄 <b>تمدید سرویس</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        f"👤 کانفیگ: <code>{p['email']}</code>\n"
                        f"👛 موجودی: <b>{_fmt_toman(balance)}</b>\n"
                        f"💰 قیمت: <b>{_fmt_toman(PRICE_PER_GB)} / هر GB</b>\n\n"
                        "➕ چند گیگابایت اضافه شود؟",
                        reply_markup=renew_gb_keyboard(),
                    )

            elif d.startswith("renew_gb:"):
                val = d.split(":", 1)[1]
                if val == "custom":
                    _states[uid] = S_RENEW_CUSTOM_GB
                    bot.send_message(
                        c.message.chat.id,
                        "✏️ حجم دلخواه را به گیگابایت وارد کنید:\n"
                        f"<i>هر GB = {_fmt_toman(PRICE_PER_GB)}</i>",
                        reply_markup=cancel_keyboard(),
                    )
                else:
                    gb = float(val)
                    _data.setdefault(uid, {})["renew_gb"] = gb
                    _states[uid] = None
                    _show_renew_confirm(bot, uid, c.message.chat.id)

            elif d == "renew_confirm":
                _do_renew_purchase(bot, xui, uid, c.message.chat.id)

            elif d.startswith("svc_buy:"):
                gb = float(d.split(":", 1)[1])
                _clear_state(uid)
                _data[uid] = {"shop_gb": gb, "shop_days": 0}
                _states[uid] = S_SHOP_NAME
                balance = get_balance(uid)
                price = calculate_price(gb)
                bot.send_message(
                    c.message.chat.id,
                    f"🛒 <b>خرید سرویس {gb:.0f} GB</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"💰 قیمت: <b>{_fmt_toman(price)}</b>\n"
                    f"👛 موجودی: <b>{_fmt_toman(balance)}</b>\n\n"
                    "در مرحله بعد نام کانفیگ را دستی وارد کنید یا از دکمه رندوم استفاده کنید.",
                )
                _ask_shop_name(bot, c.message.chat.id)

            return

        # ── cancel — smart: admin → main_menu, user → user_menu ──────────────
        if d == "cancel":
            _clear_state(uid)
            if _is_admin(uid):
                bot.answer_callback_query(c.id)
                bot.send_message(
                    c.message.chat.id, "❌ عملیات لغو شد.", reply_markup=main_menu()
                )
            else:
                bot.answer_callback_query(c.id)
                _send_user_menu(bot, c.message.chat.id, uid)
            return

        # ── all remaining callbacks are admin-only ────────────────────────────
        if not _is_admin(uid):
            bot.answer_callback_query(c.id, "⛔️ دسترسی غیر مجاز")
            return

        bot.answer_callback_query(c.id)

        # ── traffic: ask for email ────────────────────────────────────────────
        if d == "cleanup:menu":
            bot.send_message(
                c.message.chat.id,
                "🧹 <b>پاکسازی کانفیگ‌های تمام‌شده</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "از گزینه‌های زیر انتخاب کنید:",
                reply_markup=cleanup_menu_keyboard(),
            )

        elif d in ("cleanup:auto_all", "cleanup:auto_test", "cleanup:auto_ref"):
            kind = "all"
            title = "همه کانفیگ‌های تمام‌شده"
            if d == "cleanup:auto_test":
                kind = "test"
                title = "تست‌های تمام‌شده"
            elif d == "cleanup:auto_ref":
                kind = "ref"
                title = "رفرال‌های تمام‌شده"

            entries = _collect_ended_clients(xui, kind=kind)
            if not entries:
                bot.send_message(
                    c.message.chat.id,
                    f"✅ موردی برای «{title}» پیدا نشد.",
                    reply_markup=cleanup_menu_keyboard(),
                )
            else:
                ok_count, fail_count, removed_records, failed = _delete_ended_entries(
                    xui, entries
                )
                msg = (
                    f"🗑 <b>نتیجه پاکسازی: {title}</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"📦 کاندید حذف: <b>{len(entries)}</b>\n"
                    f"✅ حذف‌شده از پنل: <b>{ok_count}</b>\n"
                    f"❌ ناموفق: <b>{fail_count}</b>\n"
                    f"🧾 رکورد پاک‌شده از تلگرام: <b>{removed_records}</b>"
                )
                if failed:
                    sample = "\n".join(f"• <code>{e}</code>" for e in failed[:10])
                    msg += f"\n\n⚠️ نمونه ناموفق‌ها:\n{sample}"
                    if len(failed) > 10:
                        msg += f"\n... و {len(failed) - 10} مورد دیگر"

                bot.send_message(
                    c.message.chat.id,
                    msg,
                    reply_markup=cleanup_menu_keyboard(),
                )

        elif d == "cleanup:manual":
            _show_cleanup_manual_page(bot, xui, uid, c.message.chat.id, page=0)

        elif d.startswith("cleanup_manual_page:"):
            try:
                page = int(d.split(":", 1)[1])
            except Exception:
                page = 0
            _show_cleanup_manual_page(bot, xui, uid, c.message.chat.id, page=page)

        elif d.startswith("cleanup_manual_pick:"):
            parts = d.split(":", 2)
            if len(parts) != 3:
                bot.send_message(
                    c.message.chat.id,
                    "❌ خطا در انتخاب مورد.",
                    reply_markup=cleanup_menu_keyboard(),
                )
            else:
                try:
                    pick_idx = int(parts[1])
                    page = int(parts[2])
                except Exception:
                    pick_idx, page = -1, 0

                entries = (_data.get(uid) or {}).get("cleanup_manual_entries")
                if not isinstance(entries, list) or not entries:
                    entries = _collect_ended_clients(xui, kind="all")
                    _data.setdefault(uid, {})["cleanup_manual_entries"] = entries

                if pick_idx < 0 or pick_idx >= len(entries):
                    bot.send_message(
                        c.message.chat.id,
                        "⚠️ مورد انتخاب‌شده پیدا نشد؛ لیست دوباره بارگذاری شد.",
                    )
                    _show_cleanup_manual_page(
                        bot, xui, uid, c.message.chat.id, page=page
                    )
                else:
                    target = entries[pick_idx]
                    ok_count, fail_count, removed_records, _ = _delete_ended_entries(
                        xui, [target]
                    )
                    if ok_count > 0:
                        bot.send_message(
                            c.message.chat.id,
                            "✅ کانفیگ انتخاب‌شده حذف شد.\n"
                            f"👤 <code>{target.get('email', '—')}</code>\n"
                            f"🧾 رکورد پاک‌شده از تلگرام: <b>{removed_records}</b>",
                        )
                    else:
                        bot.send_message(
                            c.message.chat.id,
                            "❌ حذف کانفیگ انتخاب‌شده ناموفق بود.",
                        )
                    _show_cleanup_manual_page(
                        bot, xui, uid, c.message.chat.id, page=page
                    )

        # ── traffic: ask for email ────────────────────────────────────────────
        elif d == "traffic":
            _clear_state(uid)
            _states[uid] = S_TRAFFIC_EMAIL
            bot.send_message(
                c.message.chat.id,
                "📧 ایمیل کاربر را وارد کنید:",
                reply_markup=cancel_keyboard(),
            )

        # ── create user: show inbound list ────────────────────────────────────
        elif d == "create":
            inbounds = _client_create_inbounds(xui)
            if not inbounds:
                bot.send_message(
                    c.message.chat.id,
                    "❌ اینباند قابل استفاده برای ساخت کاربر پیدا نشد.\n"
                    "(مثل WireGuard و موارد غیرقابل addClient نادیده گرفته شدند)",
                    reply_markup=main_menu(),
                )
                return
            _clear_state(uid)
            _data[uid] = {}
            bot.send_message(
                c.message.chat.id,
                "🔌 اینباند (outbound) مورد نظر را انتخاب کنید:",
                reply_markup=inbounds_keyboard(inbounds),
            )

        # ── inbound selected ──────────────────────────────────────────────────
        elif d.startswith("inbound:"):
            parts = d.split(":", 2)
            if len(parts) != 3:
                bot.send_message(c.message.chat.id, "❌ خطا.", reply_markup=main_menu())
                return
            _, inbound_id, protocol = parts
            selected_inbound = xui.get_inbound(int(inbound_id))
            if not selected_inbound or not _is_client_addable_inbound(selected_inbound):
                bot.send_message(
                    c.message.chat.id,
                    "⚠️ این inbound برای ساخت کاربر معمولی قابل استفاده نیست.\n"
                    "لطفاً یک inbound دیگر انتخاب کنید.",
                    reply_markup=main_menu(),
                )
                return
            _data.setdefault(uid, {})
            _data[uid]["inbound_id"] = int(inbound_id)
            _data[uid]["protocol"] = protocol
            _states[uid] = S_CREATE_EMAIL
            bot.send_message(
                c.message.chat.id,
                "👤 ایمیل کاربر جدید را وارد کنید:\n<i>(مثال: ali  یا  user123)</i>",
                reply_markup=cancel_keyboard(),
            )

        # ── create user: skip assigning target user_id ──────────────────────
        elif d == "create_uid_skip":
            if _states.get(uid) == S_CREATE_USER_ID:
                _data.setdefault(uid, {})["assign_user_id"] = None
                _states[uid] = S_CREATE_GB
                bot.send_message(
                    c.message.chat.id,
                    "⏭️ مرحله تعلق کاربر رد شد.\n"
                    "💾 حجم اینترنت را به گیگابایت وارد کنید:\n"
                    "<i>(برای نامحدود عدد ۰ وارد کنید)</i>",
                    reply_markup=cancel_keyboard(),
                )
            else:
                bot.send_message(
                    c.message.chat.id,
                    "یک گزینه را انتخاب کنید:",
                    reply_markup=main_menu(),
                )

        # ── quick expiry days picked ──────────────────────────────────────────
        elif d.startswith("days:"):
            if _states.get(uid) == S_CREATE_DAYS:
                days = int(d.split(":", 1)[1])
                _do_create(bot, xui, uid, c.message.chat.id, days)
            else:
                bot.send_message(
                    c.message.chat.id,
                    "یک گزینه را انتخاب کنید:",
                    reply_markup=main_menu(),
                )

        # ── insecure answer ───────────────────────────────────────────────────
        elif d.startswith("insecure:"):
            if _states.get(uid) == S_ASK_INSECURE:
                add_insecure = d.split(":", 1)[1] == "yes"
                _send_client_result(bot, uid, c.message.chat.id, add_insecure)
            else:
                bot.send_message(
                    c.message.chat.id,
                    "یک گزینه را انتخاب کنید:",
                    reply_markup=main_menu(),
                )

        # ── restart xray ─────────────────────────────────────────────────────
        elif d == "restart_xray":
            _restart_xray(bot, xui, c.message.chat.id)

        # ── restart panel confirmation ───────────────────────────────────────
        elif d == "restart_panel":
            bot.send_message(
                c.message.chat.id,
                "⚠️ آیا مطمئن هستید که می‌خواهید پنل را ریستارت کنید؟",
                reply_markup=restart_panel_keyboard(),
            )

        elif d.startswith("restart_panel:"):
            action = d.split(":", 1)[1]
            if action == "yes":
                _restart_panel(bot, xui, c.message.chat.id)
            else:
                bot.send_message(
                    c.message.chat.id,
                    "❎ ریستارت پنل لغو شد.",
                    reply_markup=main_menu(),
                )

        # ── server status ─────────────────────────────────────────────────────
        elif d == "status":
            _show_status(bot, xui, c.message.chat.id)

        # ── backup ────────────────────────────────────────────────────────────
        elif d == "backup":
            _send_backup(bot, xui, c.message.chat.id)

        # ── users stats ───────────────────────────────────────────────────────
        elif d == "users_stats":
            _show_users_stats(bot, xui, c.message.chat.id)

        # ── show clients list ─────────────────────────────────────────────────
        elif d == "show_clients":
            _show_clients_list_page(bot, xui, c.message.chat.id)

        # ── paginate clients list ─────────────────────────────────────────────
        elif d.startswith("cl:"):
            page = int(d.split(":", 1)[1])
            _show_clients_list_page(bot, xui, c.message.chat.id, page)

        # ── client info ───────────────────────────────────────────────────────
        elif d.startswith("ci:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                _show_client_info(bot, xui, c.message.chat.id, int(parts[1]), parts[2])

        # ── client reset traffic ──────────────────────────────────────────────
        elif d.startswith("cr:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                ok = xui.reset_client_traffic(iid, email)
                bot.send_message(
                    c.message.chat.id,
                    f"✅ ترافیک <code>{email}</code> ریست شد."
                    if ok
                    else f"❌ خطا در ریست ترافیک <code>{email}</code>.",
                    reply_markup=client_actions_keyboard(iid, email),
                )

        # ── client add traffic ────────────────────────────────────────────────
        elif d.startswith("cat:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                _data.setdefault(uid, {})["edit_inbound_id"] = iid
                _data[uid]["edit_email"] = email
                _states[uid] = S_ADD_TRAFFIC
                bot.send_message(
                    c.message.chat.id,
                    f"➕ چند گیگابایت به ترافیک <code>{email}</code> اضافه شود?\n"
                    "<i>(عدد 0 = حجم نامحدود)</i>",
                    reply_markup=cancel_keyboard(),
                )

        # ── client edit ───────────────────────────────────────────────────────
        elif d.startswith("ce:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                _data.setdefault(uid, {})["edit_inbound_id"] = iid
                _data[uid]["edit_email"] = email
                _states[uid] = S_EDIT_GB
                bot.send_message(
                    c.message.chat.id,
                    f"✏️ حجم جدید برای <code>{email}</code> (GB):\n"
                    "<i>(عدد 0 = نامحدود)</i>",
                    reply_markup=cancel_keyboard(),
                )

        # ── client toggle enable ──────────────────────────────────────────────
        elif d.startswith("ct:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                traffic = xui.get_client_traffic(email)
                if traffic:
                    cur_enable = traffic.get("enable", True)
                    new_enable = not cur_enable
                    ok = xui.update_client(iid, email, enable=new_enable)
                    state_str = "فعال ✅" if new_enable else "غیرفعال ❌"
                    bot.send_message(
                        c.message.chat.id,
                        f"✅ کاربر <code>{email}</code> {state_str} شد."
                        if ok
                        else f"❌ خطا در تغییر وضعیت کاربر.",
                        reply_markup=client_actions_keyboard(iid, email),
                    )
                else:
                    bot.send_message(
                        c.message.chat.id,
                        "❌ کاربر پیدا نشد.",
                        reply_markup=main_menu(),
                    )

        # ── client delete: ask confirmation ───────────────────────────────────
        elif d.startswith("cd:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                bot.send_message(
                    c.message.chat.id,
                    f"⚠️ آیا مطمئنید که می‌خواهید <code>{email}</code> را <b>حذف</b> کنید؟",
                    reply_markup=client_delete_confirm_keyboard(iid, email),
                )

        # ── client delete: confirmed ──────────────────────────────────────────
        elif d.startswith("cdc:"):
            parts = d.split(":", 2)
            if len(parts) == 3:
                iid, email = int(parts[1]), parts[2]
                ok = xui.delete_client(iid, email)
                bot.send_message(
                    c.message.chat.id,
                    f"✅ کاربر <code>{email}</code> با موفقیت حذف شد."
                    if ok
                    else f"❌ خطا در حذف کاربر <code>{email}</code>.",
                    reply_markup=main_menu(),
                )

        # ── back to main menu ─────────────────────────────────────────────────
        elif d == "back_main":
            bot.send_message(c.message.chat.id, "منوی اصلی:", reply_markup=main_menu())

        # ── noop (pagination label button) ────────────────────────────────────
        elif d == "noop":
            pass

        # ── live monitor controls ─────────────────────────────────────────────
        elif d == "live_monitor_menu":
            bot.send_message(
                c.message.chat.id,
                "🎛 <b>پنل مانیتور</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "از دکمه‌های زیر مانیتور موردنظر را انتخاب کنید:",
                reply_markup=live_monitor_keyboard(),
            )

        elif d == "live_monitor_start":
            _start_live_monitor(bot, xui, c.message.chat.id)
            bot.send_message(
                c.message.chat.id,
                "✅ مانیتور زنده سرور شروع شد.",
                reply_markup=live_monitor_keyboard(),
            )

        elif d == "live_monitor_stop":
            if _stop_live_monitor(c.message.chat.id):
                bot.send_message(
                    c.message.chat.id,
                    "⏹ مانیتور زنده متوقف شد.",
                    reply_markup=live_monitor_keyboard(),
                )
            else:
                bot.send_message(
                    c.message.chat.id,
                    "ℹ️ مانیتور فعالی برای این چت وجود ندارد.",
                    reply_markup=live_monitor_keyboard(),
                )

        elif d in ("node_monitor_open", "node_monitor_refresh"):
            text = _build_nodes_monitor_text(xui)
            if d == "node_monitor_refresh":
                try:
                    bot.edit_message_text(
                        text,
                        chat_id=c.message.chat.id,
                        message_id=c.message.message_id,
                        reply_markup=nodes_monitor_keyboard(),
                        parse_mode="HTML",
                    )
                except Exception:
                    bot.send_message(
                        c.message.chat.id,
                        text,
                        reply_markup=nodes_monitor_keyboard(),
                    )
            else:
                bot.send_message(
                    c.message.chat.id,
                    text,
                    reply_markup=nodes_monitor_keyboard(),
                )

        else:
            log.warning("Unknown callback data: %s", d)
