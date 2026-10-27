"""Inline keyboard builders for the 3x-ui Telegram bot."""

from telebot import types

from config import HOTTEST_PLAN_GB, PLAN_PRICES, REFERRAL_ENABLED, SUPPORT_URL


def _fmt_toman(amount_k: float | int) -> str:
    toman = int(round(float(amount_k) * 1000))
    return f"{toman:,} تومان"


# ── Reply keyboard button labels ──────────────────────────────────────────────────
# ── Admin reply-keyboard button labels ───────────────────────────────────────
BTN_TRAFFIC = "📊 ترافیک کاربر"
BTN_CREATE = "➕ ساخت کاربر"
BTN_WIREGUARD = "🛡 ساخت WireGuard"
BTN_STATUS = "🖥 وضعیت سرور"
BTN_BACKUP = "💾 بکاپ"
BTN_RESTART_X = "🔄 ریستارت Xray"
BTN_RESTART_P = "♻️ ریستارت پنل"
BTN_STATS = "👥 آمار کاربران"
BTN_STARTED_USERS = "🧾 کاربران استارت‌زده"
BTN_CLEANUP = "🧹 پاکسازی تمام‌شده‌ها"
BTN_MONITOR = "📡 مانیتور زنده"
BTN_STOP_MON = "⏹ توقف مانیتور"
BTN_TOGGLE_TRIAL = "🛠 مدیریت اکانت تست"
BTN_TEST_ACC_ADMIN = "🎁 گرفتن اکانت تست"
BTN_BLACKLIST_ADMIN = "⛔ مدیریت بلک‌لیست"
BTN_SHOP = "🛒 خرید کانفیگ"
BTN_WALLET = "💰 کیف پول"
BTN_MY_CFGS = "📋 کانفیگ‌های من"
BTN_CHARGE = "💳 شارژ حساب"
BTN_USAGE = "⏱ میزان مصرف"

# ── Customer reply-keyboard button labels ────────────────────────────────────
BTN_BUY_NEW = "🚀 خرید سرویس جدید"
BTN_TEST_ACC = "✏️ اکانت تست"
BTN_PRICING = "📦 سرویس‌ها"
BTN_RENEW = "🔄 تمدید سرویس"
BTN_MY_USAGE = "⏳ میزان مصرف"
BTN_MY_CREDIT = "💳 اعتبار من"
BTN_MY_SERVICES = "📋 سرویس‌های من"
BTN_REFERRAL = "🎁 دعوت دوستان"
BTN_TUTORIAL = "💡 آموزش استفاده"
BTN_BLACKLIST_LIST = "🚫 لیست بلک‌لیست"
BTN_SUPPORT_IDS = "📞 پشتیبانی و کانال"
BTN_SERVER_STATUS = "📡 وضعیت سرورها"


def main_menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.row(types.KeyboardButton(BTN_TRAFFIC), types.KeyboardButton(BTN_CREATE))
    kb.row(types.KeyboardButton(BTN_STATUS), types.KeyboardButton(BTN_BACKUP))
    kb.row(types.KeyboardButton(BTN_RESTART_X), types.KeyboardButton(BTN_RESTART_P))
    kb.row(types.KeyboardButton(BTN_STATS), types.KeyboardButton(BTN_STARTED_USERS))
    kb.row(types.KeyboardButton(BTN_CLEANUP))
    kb.row(types.KeyboardButton(BTN_MONITOR), types.KeyboardButton(BTN_STOP_MON))
    kb.row(
        types.KeyboardButton(BTN_TOGGLE_TRIAL), types.KeyboardButton(BTN_TEST_ACC_ADMIN)
    )
    kb.row(
        types.KeyboardButton(BTN_WIREGUARD), types.KeyboardButton(BTN_BLACKLIST_ADMIN)
    )
    kb.row(types.KeyboardButton(BTN_BLACKLIST_LIST))
    return kb


def customer_menu(
    referral_enabled: bool = REFERRAL_ENABLED
) -> types.ReplyKeyboardMarkup:
    """Persistent reply keyboard shown to regular (non-admin) users."""
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.row(types.KeyboardButton(BTN_BUY_NEW), types.KeyboardButton(BTN_TEST_ACC))
    kb.row(types.KeyboardButton(BTN_MY_SERVICES))
    kb.row(types.KeyboardButton(BTN_RENEW), types.KeyboardButton(BTN_MY_USAGE))
    if referral_enabled:
        kb.row(types.KeyboardButton(BTN_MY_CREDIT), types.KeyboardButton(BTN_REFERRAL))
    else:
        kb.row(types.KeyboardButton(BTN_MY_CREDIT))
    kb.row(types.KeyboardButton(BTN_SERVER_STATUS))
    kb.row(types.KeyboardButton(BTN_TUTORIAL), types.KeyboardButton(BTN_SUPPORT_IDS))
    kb.row(types.KeyboardButton(BTN_BLACKLIST_LIST))
    return kb


def cancel_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def create_user_target_keyboard() -> types.InlineKeyboardMarkup:
    """Optional assignment controls for admin create-user flow."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("⏭️ رد کردن (Skip)", callback_data="create_uid_skip"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def force_join_keyboard(channel_url: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    if channel_url:
        kb.add(types.InlineKeyboardButton("📢 عضویت در کانال", url=channel_url))
    kb.add(types.InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join"))
    return kb


def inbounds_keyboard(inbounds: list) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    for inb in inbounds:
        proto = inb.get("protocol", "?").upper()
        remark = inb.get("remark") or "بدون نام"
        port = inb.get("port", "?")
        label = f"[{proto}]  {remark}  (:{port})"
        kb.add(
            types.InlineKeyboardButton(
                label,
                callback_data=f"inbound:{inb['id']}:{inb.get('protocol', 'vless')}",
            )
        )
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def expiry_keyboard() -> types.InlineKeyboardMarkup:
    """Quick-pick buttons for expiry days; user can also type a number."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("30 روز", callback_data="days:30"),
        types.InlineKeyboardButton("60 روز", callback_data="days:60"),
    )
    kb.add(
        types.InlineKeyboardButton("90 روز", callback_data="days:90"),
        types.InlineKeyboardButton("180 روز", callback_data="days:180"),
    )
    kb.add(types.InlineKeyboardButton("♾ بدون محدودیت", callback_data="days:0"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def insecure_keyboard() -> types.InlineKeyboardMarkup:
    """Ask user whether to add allowInsecure to the config links."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ بله، اضافه کن", callback_data="insecure:yes"),
        types.InlineKeyboardButton("❌ نه، بدون تغییر", callback_data="insecure:no"),
    )
    return kb


def restart_panel_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "✅ بله، ریستارت کن", callback_data="restart_panel:yes"
        ),
        types.InlineKeyboardButton("❌ لغو", callback_data="restart_panel:no"),
    )
    return kb


def trial_toggle_keyboard(enabled: bool) -> types.InlineKeyboardMarkup:
    """Admin keyboard to toggle the free trial feature on/off."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    if enabled:
        kb.add(
            types.InlineKeyboardButton(
                "🔴 غیرفعال کردن", callback_data="trial_toggle:off"
            )
        )
    else:
        kb.add(
            types.InlineKeyboardButton("🟢 فعال کردن", callback_data="trial_toggle:on")
        )
    return kb


def stats_keyboard() -> types.InlineKeyboardMarkup:
    """Keyboard shown after the users stats summary."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "📋 مشاهده لیست کاربران", callback_data="show_clients"
        )
    )
    kb.add(types.InlineKeyboardButton("⬅️ منوی اصلی", callback_data="back_main"))
    return kb


def live_monitor_keyboard() -> types.InlineKeyboardMarkup:
    """Inline controls for live monitor and node monitor views."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "▶️ شروع مانیتور زنده سرور", callback_data="live_monitor_start"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🧩 مانیتور نودها", callback_data="node_monitor_open"
        )
    )
    kb.add(
        types.InlineKeyboardButton("⏹ توقف مانیتور", callback_data="live_monitor_stop")
    )
    kb.add(types.InlineKeyboardButton("⬅️ منوی اصلی", callback_data="back_main"))
    return kb


def nodes_monitor_keyboard() -> types.InlineKeyboardMarkup:
    """Inline controls for node monitor panel."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "🔄 رفرش نودها", callback_data="node_monitor_refresh"
        ),
        types.InlineKeyboardButton(
            "📡 مانیتور زنده سرور", callback_data="live_monitor_start"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "⬅️ برگشت به مانیتور", callback_data="live_monitor_menu"
        )
    )
    return kb


PAGE_SIZE = 10


def clients_list_keyboard(
    entries: list,
    page: int,
    total_pages: int,
) -> types.InlineKeyboardMarkup:
    """One button per client + pagination nav."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for e in entries:
        kb.add(
            types.InlineKeyboardButton(
                f"{e['emoji']} {e['email']}",
                callback_data=f"ci:{e['inbound_id']}:{e['email']}",
            )
        )
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"cl:{page - 1}"))
    nav.append(
        types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("▶️ بعدی", callback_data=f"cl:{page + 1}"))
    if nav:
        kb.add(*nav)
    kb.add(types.InlineKeyboardButton("⬅️ منوی اصلی", callback_data="back_main"))
    return kb


def client_actions_keyboard(inbound_id: int, email: str) -> types.InlineKeyboardMarkup:
    """Action buttons shown when a specific client is selected."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "🔄 ریست ترافیک", callback_data=f"cr:{inbound_id}:{email}"
        ),
        types.InlineKeyboardButton(
            "➕ اضافه ترافیک", callback_data=f"cat:{inbound_id}:{email}"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "✏️ ویرایش", callback_data=f"ce:{inbound_id}:{email}"
        ),
        types.InlineKeyboardButton(
            "🔛 فعال/غیرفعال", callback_data=f"ct:{inbound_id}:{email}"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "🗑 حذف کاربر", callback_data=f"cd:{inbound_id}:{email}"
        ),
    )
    kb.add(types.InlineKeyboardButton("⬅️ لیست کاربران", callback_data="show_clients"))
    return kb


def client_delete_confirm_keyboard(
    inbound_id: int, email: str
) -> types.InlineKeyboardMarkup:
    """Confirmation dialog before deleting a client."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "✅ بله، حذف کن", callback_data=f"cdc:{inbound_id}:{email}"
        ),
        types.InlineKeyboardButton("❌ لغو", callback_data=f"ci:{inbound_id}:{email}"),
    )
    return kb


# ── User (non-admin) keyboards ────────────────────────────────────────────────


def user_menu(
    balance: int = 0, referral_enabled: bool = REFERRAL_ENABLED
) -> types.InlineKeyboardMarkup:
    """Main menu shown to regular (non-admin) users."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            f"💰 کیف پول: {_fmt_toman(balance)}", callback_data="wallet"
        ),
        types.InlineKeyboardButton("🚀 خرید سرویس جدید", callback_data="buy_new_menu"),
    )
    kb.add(
        types.InlineKeyboardButton("📋 سرویس‌های من", callback_data="my_services"),
    )
    if referral_enabled:
        kb.add(types.InlineKeyboardButton("🎁 دعوت دوستان", callback_data="referral"))
    return kb


def referral_keyboard(balance: int = 0) -> types.InlineKeyboardMarkup:
    """Referral page actions."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "🎁 دریافت کانفیگ رفرال", callback_data="claim_referral_config"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            f"💰 کیف پول: {_fmt_toman(balance)}", callback_data="wallet"
        )
    )
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back_user_menu"))
    return kb


def wallet_keyboard() -> types.InlineKeyboardMarkup:
    """Wallet view — charge + back."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_charge"))
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back_user_menu"))
    return kb


def payment_admin_keyboard(pay_id: str) -> types.InlineKeyboardMarkup:
    """Approve / reject buttons sent to the admin group."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "✅ تأیید پرداخت", callback_data=f"pay_approve:{pay_id}"
        ),
        types.InlineKeyboardButton(
            "❌ رد پرداخت", callback_data=f"pay_reject:{pay_id}"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            "🚫 افزودن به بلک‌لیست (رسید فیک)", callback_data=f"pay_blacklist:{pay_id}"
        ),
    )
    return kb


def blacklist_reason_keyboard() -> types.InlineKeyboardMarkup:
    """Preset reasons + custom reason entry for blacklist actions."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("رسید فیک", callback_data="blrsn:رسید فیک"),
        types.InlineKeyboardButton(
            "اسکم و درگیری", callback_data="blrsn:اسکم و درگیری"
        ),
    )
    kb.add(
        types.InlineKeyboardButton("دروغ گویی", callback_data="blrsn:دروغ گویی"),
        types.InlineKeyboardButton("⏺ دلیل دلخواه", callback_data="blrsn:custom"),
    )
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def blacklist_admin_keyboard() -> types.InlineKeyboardMarkup:
    """Admin actions for blacklist management (add/remove)."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            "🚫 افزودن به بلک‌لیست", callback_data="bladmin:add"
        ),
        types.InlineKeyboardButton(
            "✅ حذف از بلک‌لیست", callback_data="bladmin:remove"
        ),
    )
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def blacklist_list_keyboard(
    page: int, total_pages: int, admin_mode: bool = False
) -> types.InlineKeyboardMarkup:
    """Pagination keyboard for blacklist list."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    nav = []
    if page > 0:
        nav.append(
            types.InlineKeyboardButton("◀️ قبلی", callback_data=f"blpage:{page - 1}")
        )
    nav.append(
        types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav.append(
            types.InlineKeyboardButton("▶️ بعدی", callback_data=f"blpage:{page + 1}")
        )
    if nav:
        kb.add(*nav)
    back_cb = "back_main" if admin_mode else "back_user_menu"
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data=back_cb))
    return kb


def services_keyboard() -> types.InlineKeyboardMarkup:
    """Fixed-tier GB plans available for purchase; hottest plan listed first."""
    kb = types.InlineKeyboardMarkup(row_width=1)

    ordered_gbs = sorted(PLAN_PRICES, key=lambda g: (g != HOTTEST_PLAN_GB, g))
    for gb in ordered_gbs:
        price = PLAN_PRICES[gb]
        if gb == HOTTEST_PLAN_GB:
            label = f"🔥 {gb} GB  —  {_fmt_toman(price)}  (داغ‌ترین پلن)"
        else:
            label = f"🔹 {gb} GB  —  {_fmt_toman(price)}"
        kb.add(
            types.InlineKeyboardButton(label, callback_data=f"svc_buy:{gb}")
        )
    if SUPPORT_URL:
        kb.add(
            types.InlineKeyboardButton(
                "📞 پلن‌های اوت‌باند — با پشتیبانی تماس بگیرید",
                url=SUPPORT_URL,
            )
        )
    kb.add(
        types.InlineKeyboardButton("🌍 لیست سرورها", callback_data="server_status")
    )
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back_user_menu"))
    return kb


def shop_gb_keyboard() -> types.InlineKeyboardMarkup:
    """GB selection: 1,2,3 / 5,10,15 + custom."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("1 GB", callback_data="shop_gb:1"),
        types.InlineKeyboardButton("2 GB", callback_data="shop_gb:2"),
        types.InlineKeyboardButton("3 GB", callback_data="shop_gb:3"),
    )
    kb.add(
        types.InlineKeyboardButton("5 GB", callback_data="shop_gb:5"),
        types.InlineKeyboardButton("10 GB", callback_data="shop_gb:10"),
        types.InlineKeyboardButton("15 GB", callback_data="shop_gb:15"),
    )
    kb.add(types.InlineKeyboardButton("✏️ مقدار دلخواه", callback_data="shop_gb:custom"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def shop_days_keyboard() -> types.InlineKeyboardMarkup:
    """Quick day selection in the shop."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("30 روز", callback_data="shop_days:30"),
        types.InlineKeyboardButton("60 روز", callback_data="shop_days:60"),
    )
    kb.add(
        types.InlineKeyboardButton("90 روز", callback_data="shop_days:90"),
        types.InlineKeyboardButton("180 روز", callback_data="shop_days:180"),
    )
    kb.add(types.InlineKeyboardButton("♾ بدون محدودیت", callback_data="shop_days:0"))
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def shop_inbounds_keyboard(inbounds: list) -> types.InlineKeyboardMarkup:
    """Inbound list with shop_ prefix callbacks."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for inb in inbounds:
        proto = inb.get("protocol", "?").upper()
        remark = inb.get("remark") or "بدون نام"
        port = inb.get("port", "?")
        label = f"[{proto}]  {remark}  (:{port})"
        kb.add(
            types.InlineKeyboardButton(
                label,
                callback_data=f"shop_inbound:{inb['id']}:{inb.get('protocol', 'vless')}",
            )
        )
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def shop_confirm_keyboard() -> types.InlineKeyboardMarkup:
    """Final confirm/cancel for a shop order."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ تأیید خرید", callback_data="shop_confirm"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
    )
    return kb


def shop_name_keyboard() -> types.InlineKeyboardMarkup:
    """One-click random shop config name generator."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "🎲 ساخت نام رندوم", callback_data="shop_name_random"
        )
    )
    return kb


def my_configs_keyboard(purchases: list) -> types.InlineKeyboardMarkup:
    """List of user's purchased configs; each button opens the detail view."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for idx, p in enumerate(purchases):
        gb_label = f"{p['gb']:.0f}GB"
        days_label = "∞" if p["days"] == 0 else f"{p['days']}d"
        label = f"⚙️ {p['email']}  ({gb_label} / {days_label})"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"mc_detail:{idx}"))
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back_user_menu"))
    return kb


def config_detail_keyboard(idx: int) -> types.InlineKeyboardMarkup:
    """Action buttons for a single purchased config."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "🔄 دریافت لینک جدید", callback_data=f"mc_refresh:{idx}"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🆕 ریجنریت شناسه / Secret", callback_data=f"mc_regen:{idx}"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "➕ تمدید / افزایش حجم", callback_data=f"mc_renew:{idx}"
        )
    )
    kb.add(types.InlineKeyboardButton("⬅️ برگشت به لیست", callback_data="my_configs"))
    return kb


def renew_gb_keyboard() -> types.InlineKeyboardMarkup:
    """GB selection for renewal."""
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("1 GB", callback_data="renew_gb:1"),
        types.InlineKeyboardButton("2 GB", callback_data="renew_gb:2"),
        types.InlineKeyboardButton("3 GB", callback_data="renew_gb:3"),
    )
    kb.add(
        types.InlineKeyboardButton("5 GB", callback_data="renew_gb:5"),
        types.InlineKeyboardButton("10 GB", callback_data="renew_gb:10"),
        types.InlineKeyboardButton("15 GB", callback_data="renew_gb:15"),
    )
    kb.add(
        types.InlineKeyboardButton("✏️ مقدار دلخواه", callback_data="renew_gb:custom")
    )
    kb.add(types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"))
    return kb


def renew_confirm_keyboard() -> types.InlineKeyboardMarkup:
    """Final confirm/cancel for a renewal order."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ تأیید تمدید", callback_data="renew_confirm"),
        types.InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
    )
    return kb


def cleanup_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Admin cleanup actions for ended configs."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "🗑 پاک کردن همه کانفیگ‌های تمام‌شده", callback_data="cleanup:auto_all"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🧪 پاک کردن تست‌های تمام‌شده", callback_data="cleanup:auto_test"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🎁 پاک کردن رفرال‌های تمام‌شده", callback_data="cleanup:auto_ref"
        )
    )
    kb.add(
        types.InlineKeyboardButton(
            "🛠 انتخاب دستی (صفحه‌ای)", callback_data="cleanup:manual"
        )
    )
    kb.add(types.InlineKeyboardButton("⬅️ منوی اصلی", callback_data="back_main"))
    return kb


def cleanup_manual_list_keyboard(
    entries: list,
    page: int,
    total_pages: int,
) -> types.InlineKeyboardMarkup:
    """Paginated manual delete list for ended configs (5 per page by caller)."""
    kb = types.InlineKeyboardMarkup(row_width=1)
    for e in entries:
        kb.add(
            types.InlineKeyboardButton(
                e["label"],
                callback_data=f"cleanup_manual_pick:{e['idx']}:{page}",
            )
        )

    nav = []
    if page > 0:
        nav.append(
            types.InlineKeyboardButton(
                "◀️ قبلی", callback_data=f"cleanup_manual_page:{page - 1}"
            )
        )
    nav.append(
        types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav.append(
            types.InlineKeyboardButton(
                "▶️ بعدی", callback_data=f"cleanup_manual_page:{page + 1}"
            )
        )
    if nav:
        kb.add(*nav)

    kb.add(
        types.InlineKeyboardButton("🔄 رفرش لیست", callback_data="cleanup:manual")
    )
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="cleanup:menu"))
    return kb
