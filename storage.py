"""
Persistent JSON storage for wallet balances and pending payment records.
All functions are thread-safe via a module-level lock.
"""

from __future__ import annotations

import json
import os
import threading

_LOCK = threading.Lock()
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")


# ── internal ──────────────────────────────────────────────────────────────────


def _load() -> dict:
    if os.path.exists(_DB_PATH):
        try:
            with open(_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"wallets": {}, "pending_payments": {}}


def _save(data: dict) -> None:
    with open(_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── wallet ────────────────────────────────────────────────────────────────────


def get_balance(user_id: int) -> int:
    """Return wallet balance (Toman) for the given user ID."""
    with _LOCK:
        data = _load()
        return int(data["wallets"].get(str(user_id), {}).get("balance", 0))


def register_referral(
    referred_user_id: int, referrer_id: int, reward_amount: int
) -> tuple[bool, str, int]:
    """
    Register a referral and optionally credit the referrer.

    Returns:
      (True, "ok", new_referrer_balance) on success
      (False, reason, current_referrer_balance) otherwise
    """
    import time as _time

    with _LOCK:
        data = _load()
        referred_key = str(referred_user_id)
        referrer_key = str(referrer_id)

        wallets = data.setdefault("wallets", {})
        cur_balance = int(wallets.get(referrer_key, {}).get("balance", 0))

        if referred_user_id == referrer_id:
            return False, "self", cur_balance
        known_user_maps = (
            data.get("started_users", {}) or {},
            data.get("wallets", {}) or {},
            data.get("purchases", {}) or {},
            data.get("trials", {}) or {},
            data.get("blacklist", {}) or {},
        )
        if any(referred_key in section for section in known_user_maps):
            return False, "already_started", cur_balance

        for item in (data.get("pending_payments", {}) or {}).values():
            if isinstance(item, dict) and str(item.get("user_id")) == referred_key:
                return False, "already_started", cur_balance

        referrals = data.setdefault("referrals", {})
        if referred_key in referrals:
            return False, "already_referred", cur_balance

        new_balance = cur_balance + max(0, int(reward_amount))
        if reward_amount > 0:
            wallets.setdefault(referrer_key, {"balance": 0})["balance"] = new_balance
        referrals[referred_key] = {
            "referrer_id": referrer_id,
            "reward": max(0, int(reward_amount)),
            "ts": int(_time.time()),
        }
        _save(data)
        return True, "ok", new_balance


def get_referral_stats(user_id: int) -> dict:
    """Return referral count and earned amount for the given referrer."""
    with _LOCK:
        data = _load()
        count = 0
        earned = 0
        referred_users: list[int] = []
        for referred_key, item in (data.get("referrals", {}) or {}).items():
            if not isinstance(item, dict):
                continue
            if int(item.get("referrer_id", 0) or 0) != int(user_id):
                continue
            count += 1
            earned += int(item.get("reward", 0) or 0)
            if str(referred_key).lstrip("-").isdigit():
                referred_users.append(int(referred_key))
        return {"count": count, "earned": earned, "referred_users": referred_users}


def add_balance(user_id: int, amount: int) -> int:
    """Add amount to wallet. Returns new balance."""
    with _LOCK:
        data = _load()
        w = data["wallets"].setdefault(str(user_id), {"balance": 0})
        w["balance"] = int(w.get("balance", 0)) + max(0, int(amount))
        _save(data)
        return w["balance"]


def deduct_balance(user_id: int, amount: int) -> tuple[bool, int]:
    """Deduct amount from wallet. Returns (success, new_balance)."""
    with _LOCK:
        data = _load()
        w = data["wallets"].setdefault(str(user_id), {"balance": 0})
        bal = int(w.get("balance", 0))
        if bal < amount:
            return False, bal
        w["balance"] = bal - amount
        _save(data)
        return True, w["balance"]


# ── pending payments ──────────────────────────────────────────────────────────


def save_pending_payment(
    pay_id: str,
    user_id: int,
    amount: int,
    file_id: str,
    username: str,
) -> None:
    with _LOCK:
        data = _load()
        data["pending_payments"][pay_id] = {
            "user_id": user_id,
            "amount": amount,
            "file_id": file_id,
            "username": username,
        }
        _save(data)


def get_pending_payment(pay_id: str) -> dict | None:
    with _LOCK:
        data = _load()
        return data["pending_payments"].get(pay_id)


def remove_pending_payment(pay_id: str) -> None:
    with _LOCK:
        data = _load()
        data["pending_payments"].pop(pay_id, None)
        _save(data)


# ── purchase history ──────────────────────────────────────────────────────────


def save_purchase(
    user_id: int,
    email: str,
    inbound_id: int,
    protocol: str,
    gb: float,
    days: int,
    sub_id: str,
    extra: dict | None = None,
) -> None:
    """Record a completed purchase for a user."""
    import time as _time

    with _LOCK:
        data = _load()
        purchases = data.setdefault("purchases", {})
        user_list = purchases.setdefault(str(user_id), [])
        item = {
            "email": email,
            "inbound_id": inbound_id,
            "protocol": protocol,
            "gb": gb,
            "days": days,
            "sub_id": sub_id,
            "ts": int(_time.time()),
        }
        if extra:
            item.update(extra)
        user_list.append(item)
        _save(data)


def get_purchases(user_id: int) -> list:
    """Return list of purchase dicts for a user, newest first."""
    with _LOCK:
        data = _load()
        return list(reversed(data.get("purchases", {}).get(str(user_id), [])))


def get_all_purchases() -> list[dict]:
    """Return flat list of all purchases across users (newest first per user)."""
    with _LOCK:
        data = _load()
        rows: list[dict] = []
        for uid_key, items in (data.get("purchases", {}) or {}).items():
            if not str(uid_key).lstrip("-").isdigit() or not isinstance(items, list):
                continue
            uid = int(uid_key)
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                row["user_id"] = uid
                rows.append(row)
        return rows


def remove_purchase(user_id: int, inbound_id: int, email: str) -> bool:
    """Remove first matching purchase for user/inbound/email. Returns True if removed."""
    with _LOCK:
        data = _load()
        user_key = str(user_id)
        purchases = data.get("purchases", {}) or {}
        items = purchases.get(user_key)
        if not isinstance(items, list) or not items:
            return False

        target_email = str(email or "").strip()
        target_inbound = int(inbound_id)
        new_items = []
        removed = False

        for item in items:
            if not isinstance(item, dict):
                new_items.append(item)
                continue
            same_email = str(item.get("email") or "").strip() == target_email
            try:
                same_inbound = int(item.get("inbound_id")) == target_inbound
            except Exception:
                same_inbound = False

            if not removed and same_email and same_inbound:
                removed = True
                continue
            new_items.append(item)

        if not removed:
            return False

        data.setdefault("purchases", {})[user_key] = new_items
        _save(data)
        return True


def update_purchase_fields(
    user_id: int,
    inbound_id: int,
    email: str,
    ts: int,
    fields: dict,
) -> bool:
    """Update one purchase entry for a user identified by inbound/email/ts."""
    with _LOCK:
        data = _load()
        items = (data.get("purchases", {}) or {}).get(str(user_id))
        if not isinstance(items, list) or not items:
            return False

        target_email = str(email or "").strip()
        try:
            target_inbound = int(inbound_id)
        except Exception:
            return False
        try:
            target_ts = int(ts)
        except Exception:
            return False

        updated = False
        for item in items:
            if not isinstance(item, dict):
                continue
            same_email = str(item.get("email") or "").strip() == target_email
            try:
                same_inbound = int(item.get("inbound_id")) == target_inbound
            except Exception:
                same_inbound = False
            try:
                same_ts = int(item.get("ts")) == target_ts
            except Exception:
                same_ts = False

            if same_email and same_inbound and same_ts:
                for k, v in (fields or {}).items():
                    item[k] = v
                updated = True
                break

        if not updated:
            return False

        _save(data)
        return True


# ── trial account tracking ────────────────────────────────────────────────────


def has_used_trial(user_id: int) -> bool:
    """Return True if this user has already claimed a free trial account."""
    with _LOCK:
        data = _load()
        return str(user_id) in data.get("trials", {})


def mark_trial_used(user_id: int, email: str) -> None:
    """Record that the user claimed their trial account."""
    import time as _time

    with _LOCK:
        data = _load()
        data.setdefault("trials", {})[str(user_id)] = {
            "email": email,
            "ts": int(_time.time()),
        }
        _save(data)


def get_trials_count() -> int:
    """Return how many users have claimed trial so far (global)."""
    with _LOCK:
        data = _load()
        return len(data.get("trials", {}))


def mark_user_started(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> None:
    """Upsert user profile when they start the bot."""
    import time as _time

    with _LOCK:
        data = _load()
        started = data.setdefault("started_users", {})
        uid_key = str(user_id)
        now_ts = int(_time.time())

        prev = (
            started.get(uid_key, {}) if isinstance(started.get(uid_key), dict) else {}
        )
        started[uid_key] = {
            "username": (username or "").strip(),
            "first_name": (first_name or "").strip(),
            "last_name": (last_name or "").strip(),
            "first_start_ts": int(prev.get("first_start_ts", now_ts)),
            "last_start_ts": now_ts,
        }
        _save(data)


def get_started_users() -> list[dict]:
    """Return users who started the bot, sorted by latest start."""
    with _LOCK:
        data = _load()
        started = data.get("started_users", {}) or {}
        rows: list[dict] = []
        for uid_key, profile in started.items():
            if not str(uid_key).lstrip("-").isdigit():
                continue
            p = profile if isinstance(profile, dict) else {}
            rows.append(
                {
                    "user_id": int(uid_key),
                    "username": str(p.get("username", "") or "").strip(),
                    "first_name": str(p.get("first_name", "") or "").strip(),
                    "last_name": str(p.get("last_name", "") or "").strip(),
                    "first_start_ts": int(p.get("first_start_ts", 0) or 0),
                    "last_start_ts": int(p.get("last_start_ts", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["last_start_ts"], reverse=True)
        return rows


def reserve_trial_slot(
    user_id: int, email: str, max_total: int
) -> tuple[bool, str, int]:
    """
    Atomically claim a trial slot for a user.

    Returns:
      (True,  "ok",      used_count_after) on success
      (False, "already", used_count_now)   if user already used trial
      (False, "limit",   used_count_now)   if global limit reached
    max_total <= 0 means unlimited global slots.
    """
    import time as _time

    with _LOCK:
        data = _load()
        trials = data.setdefault("trials", {})
        uid_key = str(user_id)

        if uid_key in trials:
            return False, "already", len(trials)

        if max_total > 0 and len(trials) >= max_total:
            return False, "limit", len(trials)

        trials[uid_key] = {
            "email": email,
            "ts": int(_time.time()),
        }
        _save(data)
        return True, "ok", len(trials)


def release_trial_slot(user_id: int) -> None:
    """Rollback a previously reserved trial slot for a user (best-effort)."""
    with _LOCK:
        data = _load()
        data.setdefault("trials", {}).pop(str(user_id), None)
        _save(data)


# ── referral reward config tracking ──────────────────────────────────────────


def has_claimed_referral_config(user_id: int) -> bool:
    """Return True if this user already claimed the referral reward config."""
    with _LOCK:
        data = _load()
        return str(user_id) in data.get("referral_configs", {})


def reserve_referral_config(user_id: int, email: str) -> tuple[bool, str]:
    """
    Atomically reserve the one-time referral reward config for a user.

    Returns:
      (True,  "ok")      on success
      (False, "already") if the user already claimed it
    """
    import time as _time

    with _LOCK:
        data = _load()
        configs = data.setdefault("referral_configs", {})
        uid_key = str(user_id)
        if uid_key in configs:
            return False, "already"
        configs[uid_key] = {
            "email": email,
            "ts": int(_time.time()),
        }
        _save(data)
        return True, "ok"


def release_referral_config(user_id: int) -> None:
    """Rollback a reserved referral reward config if panel creation failed."""
    with _LOCK:
        data = _load()
        data.setdefault("referral_configs", {}).pop(str(user_id), None)
        _save(data)


# ── trial enabled toggle (admin-controlled, persisted) ────────────────────────


def get_trial_enabled() -> bool:
    """Return whether the free trial feature is currently ON. Default: OFF."""
    with _LOCK:
        data = _load()
        return bool(data.get("settings", {}).get("trial_enabled", False))


def set_trial_enabled(enabled: bool) -> None:
    """Turn the free trial feature ON or OFF (persisted across restarts)."""
    with _LOCK:
        data = _load()
        data.setdefault("settings", {})["trial_enabled"] = enabled
        _save(data)


def get_trial_limit(default_limit: int = 0) -> int:
    """Return current global trial limit from settings (fallback to default)."""
    with _LOCK:
        data = _load()
        settings = data.get("settings", {})
        if "trial_limit" not in settings:
            return max(0, int(default_limit))
        try:
            return max(0, int(settings.get("trial_limit", 0)))
        except Exception:
            return max(0, int(default_limit))


def set_trial_limit(limit: int) -> int:
    """Set global trial limit (0 = unlimited). Returns stored value."""
    with _LOCK:
        data = _load()
        val = max(0, int(limit))
        data.setdefault("settings", {})["trial_limit"] = val
        _save(data)
        return val


def increase_trial_limit(delta: int, default_limit: int = 0) -> int:
    """Increase global trial limit by delta. Returns new value."""
    with _LOCK:
        data = _load()
        settings = data.setdefault("settings", {})
        if "trial_limit" in settings:
            try:
                cur = max(0, int(settings.get("trial_limit", 0)))
            except Exception:
                cur = max(0, int(default_limit))
        else:
            cur = max(0, int(default_limit))

        d = int(delta)
        if d <= 0:
            return cur
        if cur == 0:
            # unlimited; increasing has no effect
            return 0

        new_val = cur + d
        settings["trial_limit"] = new_val
        _save(data)
        return new_val


def get_all_known_user_ids() -> list[int]:
    """Return deduplicated list of all user IDs found in storage."""
    with _LOCK:
        data = _load()
        ids: set[int] = set()

        for k in (data.get("wallets", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        for k in (data.get("purchases", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        for k in (data.get("trials", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        for k in (data.get("referral_configs", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        for k in (data.get("started_users", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        for item in (data.get("pending_payments", {}) or {}).values():
            uid = item.get("user_id") if isinstance(item, dict) else None
            if str(uid).lstrip("-").isdigit():
                ids.add(int(uid))

        for k, item in (data.get("referrals", {}) or {}).items():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))
            if isinstance(item, dict):
                referrer_id = item.get("referrer_id")
                if str(referrer_id).lstrip("-").isdigit():
                    ids.add(int(referrer_id))

        for k in (data.get("blacklist", {}) or {}).keys():
            if str(k).lstrip("-").isdigit():
                ids.add(int(k))

        return sorted(ids)


# ── blacklist ────────────────────────────────────────────────────────────────


def set_blacklist(
    user_id: int,
    identifier: str,
    reason: str,
    added_by: int | None = None,
) -> None:
    """Create or update a blacklist entry for the given user."""
    import time as _time

    with _LOCK:
        data = _load()
        data.setdefault("blacklist", {})[str(user_id)] = {
            "identifier": str(identifier or "").strip(),
            "reason": str(reason or "").strip(),
            "added_by": int(added_by) if added_by is not None else None,
            "ts": int(_time.time()),
        }
        _save(data)


def remove_blacklist(user_id: int) -> bool:
    """Remove user from blacklist. Returns True if entry existed."""
    with _LOCK:
        data = _load()
        existed = str(user_id) in (data.get("blacklist", {}) or {})
        data.setdefault("blacklist", {}).pop(str(user_id), None)
        _save(data)
        return existed


def get_blacklist_entry(user_id: int) -> dict | None:
    """Return blacklist entry for user or None."""
    with _LOCK:
        data = _load()
        entry = (data.get("blacklist", {}) or {}).get(str(user_id))
        return dict(entry) if isinstance(entry, dict) else None


def is_user_blacklisted(user_id: int) -> bool:
    """Return True when user is blacklisted."""
    with _LOCK:
        data = _load()
        return str(user_id) in (data.get("blacklist", {}) or {})


def get_blacklist_entries() -> list[dict]:
    """Return all blacklist entries sorted by newest first."""
    with _LOCK:
        data = _load()
        rows: list[dict] = []
        for uid_key, entry in (data.get("blacklist", {}) or {}).items():
            if not str(uid_key).lstrip("-").isdigit():
                continue
            e = entry if isinstance(entry, dict) else {}
            rows.append(
                {
                    "user_id": int(uid_key),
                    "identifier": str(e.get("identifier", "") or "").strip(),
                    "reason": str(e.get("reason", "") or "").strip(),
                    "added_by": e.get("added_by"),
                    "ts": int(e.get("ts", 0) or 0),
                }
            )
        rows.sort(key=lambda x: x["ts"], reverse=True)
        return rows
