"""Formatting and parsing helpers used by Telegram handlers."""

import datetime


def fmt_bytes(value: float) -> str:
    if value == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def fmt_uptime(seconds: int) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    return " ".join(parts) or "< ۱ دقیقه"


def fmt_expiry(ms: int) -> str:
    if ms == 0:
        return "♾ بدون محدودیت"
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def fmt_toman(amount_k: float | int) -> str:
    """Format internal thousand-toman amount as human-readable toman."""
    toman = int(round(float(amount_k) * 1000))
    return f"{toman:,} تومان"


def parse_toman_to_k(text: str) -> int:
    """Parse toman text and convert to internal thousand-toman integer."""
    raw = (text or "").strip().replace(",", "").replace(".", "")
    if not raw:
        raise ValueError("empty")
    toman = int(raw)
    if toman <= 0:
        raise ValueError("non-positive")
    if toman % 1000 != 0:
        raise ValueError("not-multiple-of-1000")
    return toman // 1000
