import logging
import os
from typing import List
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

_raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [
    int(x.strip()) for x in _raw_admins.split(",") if x.strip().lstrip("-").isdigit()
]

# ── 3x-ui panel ───────────────────────────────────────────────────────────────
def _split_xui_origin_and_base(raw_url: str, fallback_base: str) -> tuple[str, str]:
    """
    Accept either origin-only URL (http://host:port) or full panel URL
    (e.g. http://host:port/<secret>/panel/clients), and return:
      - origin URL
      - detected base path up to /panel (or fallback)
    """
    fallback = str(fallback_base or "/panel").strip().rstrip("/") or "/panel"
    raw = str(raw_url or "").strip().rstrip("/")
    if not raw:
        return "http://localhost:54321", fallback

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw, fallback

    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    path = (parsed.path or "").rstrip("/")

    detected_base = ""
    if path:
        panel_idx = path.find("/panel")
        if panel_idx >= 0:
            detected_base = path[: panel_idx + len("/panel")]
        elif path.startswith("/"):
            detected_base = path

    if detected_base.endswith("/clients"):
        detected_base = detected_base[: -len("/clients")]

    detected_base = detected_base.rstrip("/")
    return origin, (detected_base or fallback)


_raw_xui_url = os.getenv("XUI_URL", "http://localhost:54321")
_raw_xui_base_path = os.getenv("XUI_BASE_PATH", "").strip()
XUI_URL, _detected_xui_base_path = _split_xui_origin_and_base(
    _raw_xui_url,
    _raw_xui_base_path or "/panel",
)
XUI_API_KEY = os.getenv("XUI_API_KEY", "")
XUI_USER = os.getenv("XUI_USER", "").strip()
XUI_PASS = os.getenv("XUI_PASS", "").strip()
XUI_BASE_PATH = (_raw_xui_base_path or _detected_xui_base_path).rstrip("/")
# Optional dedicated panel for creating WireGuard inbounds.
WG_XUI_URL = os.getenv("WG_XUI_URL", XUI_URL).rstrip("/")
WG_XUI_API_KEY = os.getenv("WG_XUI_API_KEY", XUI_API_KEY)
WG_XUI_BASE_PATH = os.getenv("WG_XUI_BASE_PATH", XUI_BASE_PATH).rstrip("/")
_raw_wg_ports = os.getenv("WG_TRUSTED_PORTS", "30000-30599")


def _parse_ports(raw: str) -> List[int]:
    out: List[int] = []
    seen = set()
    for token in str(raw or "").split(","):
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            left, right = [x.strip() for x in part.split("-", 1)]
            if not left.isdigit() or not right.isdigit():
                continue
            start = int(left)
            end = int(right)
            if end < start:
                start, end = end, start
            for p in range(start, end + 1):
                if 1 <= p <= 65535 and p not in seen:
                    seen.add(p)
                    out.append(p)
            continue
        if part.isdigit():
            p = int(part)
            if 1 <= p <= 65535 and p not in seen:
                seen.add(p)
                out.append(p)
    return out


WG_TRUSTED_PORTS: List[int] = _parse_ports(_raw_wg_ports)
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "").rstrip("/")
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("0", "false", "no")

# ── Payment / wallet ────────────────────────────────────────────────────────
PAYMENT_GROUP_ID = int(os.getenv("PAYMENT_GROUP_ID", "0"))
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID", "0"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
PRICE_PER_GB = int(
    os.getenv("PRICE_PER_GB", "300")
)  # thousand toman per GB (internal unit)
# Bulk discount: configs >= BULK_DISCOUNT_GB get BULK_DISCOUNT_PCT% off per GB
BULK_DISCOUNT_GB = int(os.getenv("BULK_DISCOUNT_GB", "10"))
BULK_DISCOUNT_PCT = float(os.getenv("BULK_DISCOUNT_PCT", "30"))

# Fixed-tier shop plans: GB → total price (internal unit, thousand toman).
PLAN_PRICES: dict[int, int] = {20: 70, 40: 100, 60: 120, 80: 140, 100: 150}
HOTTEST_PLAN_GB = 100


def calculate_price(gb: float) -> int:
    """Return total price in internal unit (thousand toman)."""
    tier_price = PLAN_PRICES.get(int(gb))
    if tier_price is not None:
        return tier_price
    per_gb = (
        PRICE_PER_GB * (1 - BULK_DISCOUNT_PCT / 100)
        if gb >= BULK_DISCOUNT_GB
        else PRICE_PER_GB
    )
    return int(gb * per_gb)


LOG_GROUP_ID = int(os.getenv("LOG_GROUP_ID", "0"))  # activity log channel

# Users must join this channel before using the customer bot.
FORCE_JOIN_CHANNEL_ID = int(os.getenv("FORCE_JOIN_CHANNEL_ID", "0"))
FORCE_JOIN_CHANNEL_URL = os.getenv("FORCE_JOIN_CHANNEL_URL", "").strip()
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()

# Comma-separated remark names of inbounds allowed in the shop.
# Leave empty to allow all inbounds.
_raw_shop = os.getenv("SHOP_INBOUNDS", "")
SHOP_INBOUNDS: List[str] = [x.strip() for x in _raw_shop.split(",") if x.strip()]

# ── Customer / trial settings ─────────────────────────────────────────────────
# Free trial account size in MB (admin can change at runtime with /trial)
TEST_ACCOUNT_MB = float(os.getenv("TEST_ACCOUNT_MB", "15"))  # Megabytes
TEST_ACCOUNT_DAYS = int(os.getenv("TEST_ACCOUNT_DAYS", "3"))  # days (0 = unlimited)
TEST_ACCOUNT_MINUTES = int(os.getenv("TEST_ACCOUNT_MINUTES", "30"))  # minutes
# Global max number of users who can claim free trial (0 = unlimited)
TEST_ACCOUNT_LIMIT = int(os.getenv("TEST_ACCOUNT_LIMIT", "0"))
# Trial accounts do not require referrals. Referral counts only unlock referral rewards.
TRIAL_REQUIRED_REFERRALS = max(0, int(os.getenv("TRIAL_REQUIRED_REFERRALS", "0")))
# One-time referral reward config, separate from the trial account.
REFERRAL_CONFIG_REQUIRED_REFERRALS = max(
    0, int(os.getenv("REFERRAL_CONFIG_REQUIRED_REFERRALS", "10"))
)
REFERRAL_CONFIG_MB = float(os.getenv("REFERRAL_CONFIG_MB", "100"))
REFERRAL_CONFIG_DAYS = int(os.getenv("REFERRAL_CONFIG_DAYS", "2"))
# TRIAL_ENABLED is controlled at runtime by admin (/trial on|off). Default: OFF.

# Referral feature temporarily disabled; flip to true in .env to re-enable.
REFERRAL_ENABLED = os.getenv("REFERRAL_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)

# How many MB over the panel quota before a client is force-deleted (default: 15 MB)
TRAFFIC_OVERAGE_MB = float(os.getenv("TRAFFIC_OVERAGE_MB", "15"))

# Tutorial text shown when user taps "آموزش استفاده"
TUTORIAL_TEXT = os.getenv(
    "TUTORIAL_TEXT",
    "📖 <b>آموزش استفاده از VPN</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "1️⃣ یکی از کانفیگ‌های خریداری‌شده را کپی کنید.\n"
    "2️⃣ برنامه V2rayNG یا Nekobox را نصب کنید.\n"
    "3️⃣ روی ➕ بزنید و کانفیگ را import کنید.\n"
    "4️⃣ روی سرور انتخاب شده کانکت کنید.\n\n"
    "❓ در صورت مشکل با پشتیبانی تماس بگیرید.",
)

# ── Proxy (optional) ──────────────────────────────────────────────────────────
USE_PROXY = os.getenv("USE_PROXY", "").lower() in ("1", "true", "yes")
PROXY_URL = os.getenv("PROXY_URL", "").strip()
# Use socks5h:// so DNS resolution also goes through proxy (fixes EOF/SSL issues)
if PROXY_URL.startswith("socks5://"):
    PROXY_URL = "socks5h://" + PROXY_URL[9:]
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if USE_PROXY and PROXY_URL else None

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("xui_bot")

# ── Validation ────────────────────────────────────────────────────────────────
if not BOT_TOKEN or BOT_TOKEN.startswith("YOUR_"):
    raise SystemExit("BOT_TOKEN is not set. Configure it in .env")

if not ADMIN_IDS:
    raise SystemExit("ADMIN_IDS is not set. Add at least one Telegram user ID to .env")

if not XUI_API_KEY:
    raise SystemExit("XUI_API_KEY is not set. Add your 3x-ui API key to .env")
