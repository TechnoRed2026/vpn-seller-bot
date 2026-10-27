"""
3x-ui API client — wraps session auth + all required endpoints.
"""

from __future__ import annotations

import base64
import json
import ipaddress
import logging
import re
import time
import uuid
from urllib.parse import quote, urlparse

import requests

try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


def _normalize_wg_b64(key: str) -> str:
    """Convert URL-safe base64 → standard base64 with padding (for WireGuard keys)."""
    if not key:
        return key
    # Replace URL-safe chars with standard base64 chars
    key = key.replace("-", "+").replace("_", "/")
    # Add padding
    pad = len(key) % 4
    if pad == 2:
        key += "=="
    elif pad == 3:
        key += "="
    return key


def _derive_x25519_pubkey(secret_key_b64: str) -> str:
    """Derive X25519 public key (standard base64) from a base64-encoded private key."""
    if not _CRYPTO_AVAILABLE or not secret_key_b64:
        return ""
    try:
        priv_bytes = base64.b64decode(_normalize_wg_b64(secret_key_b64))
        priv_key = X25519PrivateKey.from_private_bytes(priv_bytes)
        pub_bytes = priv_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(pub_bytes).decode()
    except Exception:
        return ""

from config import (
    VERIFY_SSL,
    WG_XUI_API_KEY,
    WG_XUI_BASE_PATH,
    WG_TRUSTED_PORTS,
    WG_XUI_URL,
    XUI_API_KEY,
    XUI_BASE_PATH,
    XUI_PASS,
    XUI_URL,
    XUI_USER,
)

log = logging.getLogger("xui_api")


def _build_api_auth_headers(api_key: str) -> dict[str, str]:
    """Build broad-compatible API auth headers for different 3x-ui versions."""
    key = str(api_key or "").strip()
    if not key:
        return {}
    return {
        "Authorization": f"Bearer {key}",
        "X-API-KEY": key,
        "x-ui-token": key,
    }


class XUIClient:
    def __init__(self, on_panel_login=None) -> None:
        self._session = requests.Session()
        self._session.verify = VERIFY_SSL
        # API token headers (compat mode for multiple 3x-ui versions)
        self._session.headers.update(_build_api_auth_headers(XUI_API_KEY))
        self._panel_session = requests.Session()
        self._panel_session.verify = VERIFY_SSL
        self._panel_authed = False
        self._api_bases = self._candidate_api_bases(XUI_BASE_PATH)
        self._wg_api_bases = self._candidate_api_bases(WG_XUI_BASE_PATH)
        self._panel_root = self._api_bases[0]
        self._panel_host = urlparse(XUI_URL).hostname or XUI_URL
        self._on_panel_login = on_panel_login  # callback(host, user) when panel login succeeds

    @staticmethod
    def _candidate_api_bases(base_path: str) -> list[str]:
        """Return possible API base paths, handling both with/without trailing /panel."""
        base = str(base_path or "").rstrip("/")
        if not base:
            return [""]

        candidates: list[str] = []
        if base.endswith("/panel"):
            candidates.extend([base[:-6], base])
        else:
            candidates.extend([base, f"{base}/panel"])

        out: list[str] = []
        seen = set()
        for item in candidates:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    @staticmethod
    def _extract_list_from_obj(obj) -> list:
        """Normalize list payloads from different API response shapes."""
        if isinstance(obj, list):
            return obj
        if not isinstance(obj, dict):
            return []

        preferred_keys = (
            "list",
            "items",
            "rows",
            "results",
            "result",
            "inbounds",
            "clients",
            "clientTraffics",
            "data",
        )
        for key in preferred_keys:
            val = obj.get(key)
            if isinstance(val, list):
                return val

        for val in obj.values():
            if isinstance(val, dict):
                nested = XUIClient._extract_list_from_obj(val)
                if nested:
                    return nested
        return []

    # ── internal ──────────────────────────────────────────────────────────────

    def _req(self, method: str, path: str, **kwargs):
        for base in self._api_bases:
            url = f"{XUI_URL}{base}{path}"
            try:
                r = getattr(self._session, method)(url, timeout=20, **kwargs)
            except Exception as exc:
                log.error("HTTP %s %s (url=%s) → %s", method.upper(), path, url, exc)
                continue

            if r.status_code in (404, 405):
                continue
            return r

        log.error("API 404 — wrong path or invalid token: %s", path)
        return None

    def _wg_req(self, method: str, path: str, **kwargs):
        headers = _build_api_auth_headers(WG_XUI_API_KEY)
        extra_headers = kwargs.pop("headers", {}) or {}
        headers.update(extra_headers)
        for base in self._wg_api_bases:
            url = f"{WG_XUI_URL}{base}{path}"
            try:
                r = requests.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    timeout=20,
                    verify=VERIFY_SSL,
                    **kwargs,
                )
            except Exception as exc:
                log.error("WG HTTP %s %s (url=%s) → %s", method.upper(), path, url, exc)
                continue

            if r.status_code in (404, 405):
                continue
            return r

        log.error("WG API 404 — wrong path or invalid token: %s", path)
        return None

    def _panel_login(self) -> bool:
        """Login with panel credentials for session-only routes like restartPanel."""
        if self._panel_authed:
            return True
        if not XUI_USER or not XUI_PASS:
            log.warning("Panel restart requires XUI_USER/XUI_PASS in .env")
            return False

        csrf_url = f"{XUI_URL}{self._panel_root}/csrf-token"
        login_url = f"{XUI_URL}{self._panel_root}/login"

        try:
            log.info("Panel login attempt: host=%s user=%s", self._panel_host, XUI_USER)
            csrf = self._panel_session.get(csrf_url, timeout=15)
            token = csrf.json().get("obj") if csrf.ok else None
            if not token:
                log.error("Failed to fetch CSRF token for panel login")
                return False

            r = self._panel_session.post(
                login_url,
                json={"username": XUI_USER, "password": XUI_PASS},
                headers={"X-CSRF-Token": token},
                timeout=15,
            )
            if r.ok and r.json().get("success"):
                self._panel_authed = True
                log.info("Panel login success: host=%s user=%s", self._panel_host, XUI_USER)
                # Notify about panel login
                if self._on_panel_login:
                    try:
                        self._on_panel_login(self._panel_host, XUI_USER)
                    except Exception as exc:
                        log.warning("Panel login callback failed: %s", exc)
                return True
            log.error(
                "Panel login failed: host=%s user=%s status=%s body=%s",
                self._panel_host,
                XUI_USER,
                getattr(r, "status_code", "?"),
                getattr(r, "text", "<no response>"),
            )
        except Exception as exc:
            log.error(
                "Panel login exception: host=%s user=%s err=%s",
                self._panel_host,
                XUI_USER,
                exc,
            )
        return False

    def _fetch_csrf_token(self) -> str | None:
        """Fetch a fresh CSRF token for the current panel session."""
        try:
            r = self._panel_session.get(
                f"{XUI_URL}{self._panel_root}/csrf-token", timeout=15
            )
            if r.ok:
                return r.json().get("obj")
        except Exception as exc:
            log.error("Failed to fetch CSRF token: %s", exc)
        return None

    def _panel_req(self, method: str, path: str, **kwargs):
        if not self._panel_login():
            return None
        headers = kwargs.pop("headers", {}) or {}
        if method.lower() in ("post", "put", "delete", "patch"):
            token = self._fetch_csrf_token()
            if token:
                headers["X-CSRF-Token"] = token
        url = f"{XUI_URL}{self._panel_root}{path}"
        try:
            r = getattr(self._panel_session, method)(
                url, headers=headers, timeout=20, **kwargs
            )
            if r.status_code == 404:
                log.error("Panel route 404 — wrong path: %s", path)
                return None
            return r
        except Exception as exc:
            log.error("PANEL HTTP %s %s → %s", method.upper(), path, exc)
            return None

    # ── public API ────────────────────────────────────────────────────────────

    def get_inbounds(self) -> list | None:
        """Return list of all inbound objects, or None on error."""
        for path in (
            "/api/inbounds/list",
            "/api/inbounds/list?page=1&pageSize=1000",
            "/api/inbounds/list?limit=1000",
        ):
            r = self._req("get", path)
            if not (r and r.ok):
                continue
            try:
                d = r.json()
            except Exception:
                continue

            if d.get("success") is False:
                continue

            obj = d.get("obj", d.get("data", []))
            if isinstance(obj, list):
                return obj

            items = self._extract_list_from_obj(obj)
            if items:
                return items

            if isinstance(obj, dict) and not obj:
                return []
        return None

    def get_client_traffic(self, email: str, inbound_id: int | None = None) -> dict | None:
        """Return traffic dict for a client, with inbound fallback for protocols like WireGuard."""
        email_s = str(email or "").strip()
        if not email_s:
            return None

        r = self._req("get", f"/api/inbounds/getClientTraffics/{quote(email_s, safe='')}")
        if r and r.ok:
            d = r.json()
            if d.get("success"):
                obj = d.get("obj")
                if isinstance(obj, dict):
                    return obj

        if inbound_id is None:
            return None

        target = email_s.casefold()
        for item in self.get_client_traffics_by_inbound(int(inbound_id)):
            if not isinstance(item, dict):
                continue
            c_email = str(item.get("email") or "").strip().casefold()
            c_comment = str(item.get("comment") or "").strip().casefold()
            if target and (target == c_email or target == c_comment):
                return item

        # Final fallback: inspect inbound object directly.
        inbound = self.get_inbound(int(inbound_id))
        if not isinstance(inbound, dict):
            return None

        # Some panels expose client stats here even when traffic endpoints fail.
        for item in (inbound.get("clientStats") or []):
            if not isinstance(item, dict):
                continue
            c_email = str(item.get("email") or "").strip().casefold()
            c_comment = str(item.get("comment") or "").strip().casefold()
            if target and (target == c_email or target == c_comment):
                return item

        # WireGuard dedicated-inbound fallback (common when each peer has its own inbound).
        if str(inbound.get("protocol", "")).strip().lower() == "wireguard":
            try:
                settings = json.loads(inbound.get("settings", "{}") or "{}")
            except Exception:
                settings = {}

            peers = settings.get("peers") or []
            peer = None
            if isinstance(peers, list):
                for p in peers:
                    if not isinstance(p, dict):
                        continue
                    p_email = str(p.get("email") or "").strip().casefold()
                    p_comment = str(p.get("comment") or "").strip().casefold()
                    if target and (target == p_email or target == p_comment):
                        peer = p
                        break
                if peer is None and len(peers) == 1 and isinstance(peers[0], dict):
                    peer = peers[0]

            if isinstance(peer, dict):
                return {
                    "email": peer.get("email") or peer.get("remark") or email_s,
                    "comment": peer.get("comment") or "",
                    "up": int(inbound.get("up", 0) or peer.get("up", 0) or 0),
                    "down": int(inbound.get("down", 0) or peer.get("down", 0) or 0),
                    "total": int(peer.get("totalGB", inbound.get("total", 0)) or 0),
                    "expiryTime": int(peer.get("expiryTime", inbound.get("expiryTime", 0)) or 0),
                    "enable": bool(peer.get("enable", inbound.get("enable", True))),
                    "remark": peer.get("remark") or "",
                }
        return None

    def get_client_traffics_by_inbound(self, inbound_id: int) -> list:
        """Return client traffic list for a specific inbound ID."""
        r = self._req("get", f"/api/inbounds/getClientTrafficsById/{inbound_id}")
        if r and r.ok:
            d = r.json()
            if d.get("success"):
                obj = d.get("obj")
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    for key in ("clientTraffics", "clients", "items", "list"):
                        val = obj.get(key)
                        if isinstance(val, list):
                            return val

                    out = []
                    for k, v in obj.items():
                        if not isinstance(v, dict):
                            continue
                        item = dict(v)
                        item.setdefault("email", str(item.get("email") or k))
                        out.append(item)
                    if out:
                        return out
        return []

    def get_online_clients(self) -> list:
        """Return currently online clients (best-effort normalized identifiers)."""
        candidates = [
            ("post", "/api/inbounds/onlines", {"json": {}}),
            ("post", "/api/inbounds/onlines", {}),
            ("get", "/api/inbounds/onlines", {}),
        ]
        for method, path, kwargs in candidates:
            r = self._req(method, path, **kwargs)
            if not (r and r.ok):
                continue
            try:
                d = r.json()
            except Exception:
                continue
            if d.get("success") is False:
                continue
            obj = d.get("obj", d.get("data"))

            def _walk(node):
                if isinstance(node, str):
                    s = node.strip()
                    if s:
                        yield s
                    return
                if isinstance(node, dict):
                    for pref in ("email", "remark", "client", "user", "username", "name"):
                        val = node.get(pref)
                        if isinstance(val, str) and val.strip():
                            yield val.strip()
                    for v in node.values():
                        yield from _walk(v)
                    return
                if isinstance(node, (list, tuple, set)):
                    for item in node:
                        yield from _walk(item)

            seen = set()
            out = []
            for token in _walk(obj):
                for candidate in re.split(r"[\s,;|]+", token):
                    c = str(candidate).strip("\"'<>[](){} ").strip()
                    if not c:
                        continue
                    k = c.casefold()
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append(c)
            return out
        return []

    def add_client(
        self,
        inbound_id: int,
        protocol: str,
        email: str,
        total_gb: float,
        expiry_days: float,
    ) -> tuple[bool, str | None, str | None]:
        """
        Add a new client to an inbound.

        Returns (success, client_uuid_or_password, sub_id).
        total_gb=0  → unlimited
        expiry_days=0 → unlimited
        """
        cid = str(uuid.uuid4())
        sub_id = uuid.uuid4().hex[:16]
        expiry_ms = (
            int((time.time() + expiry_days * 86400) * 1000) if expiry_days > 0 else 0
        )
        total_bytes = int(total_gb * 1_073_741_824) if total_gb > 0 else 0

        proto = protocol.lower()

        if proto in ("vmess", "vless"):
            client = {
                "id": cid,
                "email": email,
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }
        elif proto == "trojan":
            client = {
                "password": cid,
                "email": email,
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }
        else:
            # shadowsocks, etc.
            client = {
                "email": email,
                "password": cid,
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client]}),
        }

        r = self._req("post", "/api/inbounds/addClient", json=payload)
        if r and r.ok:
            try:
                d = r.json()
            except Exception:
                d = {}
            if d.get("success"):
                return True, cid, sub_id
        return False, None, None

    def get_client_links(self, inbound_id: int, email: str) -> list:
        """Return list of config URI strings for a client (vless://, vmess://, etc.)."""
        r = self._req(
            "get",
            f"/api/inbounds/getClientLinks/{inbound_id}/{quote(str(email or '').strip(), safe='')}",
        )
        if r and r.ok:
            d = r.json()
            if d.get("success"):
                return d.get("obj") or []
        return []

    def get_server_status(self) -> dict | None:
        """Return server status object or None."""
        r = self._req("get", "/api/server/status")
        if r and r.ok:
            d = r.json()
            if d.get("success"):
                return d.get("obj")
        return None

    def restart_xray(self) -> bool:
        """Restart Xray service through the panel API."""
        r = self._req("post", "/api/server/restartXrayService")
        return bool(r and r.ok and r.json().get("success"))

    def restart_panel(self) -> bool:
        """Restart the 3x-ui panel itself."""
        r = self._panel_req("post", "/panel/setting/restartPanel")
        return bool(r and r.ok and r.json().get("success"))

    # ── Xray outbounds (server list / status check) ────────────────────────────

    _IGNORED_OUTBOUND_TAGS = {"direct", "blackhole", "blocked"}

    def get_xray_config(self) -> dict | None:
        """Return the full live Xray config (xraySetting incl. outbounds), or None."""
        for method in ("post", "get"):
            r = self._panel_req(method, "/panel/xray/")
            if r is None:
                log.error("xray config (%s): no response (request failed)", method)
                continue
            if not r.ok:
                log.error(
                    "xray config (%s): HTTP %s — body: %s",
                    method,
                    r.status_code,
                    (r.text or "")[:200],
                )
                continue
            if not (r.text or "").strip():
                log.error("xray config (%s): HTTP %s but empty body", method, r.status_code)
                continue
            try:
                d = r.json()
            except ValueError as exc:
                log.error(
                    "xray config (%s): non-JSON body (%s) — body: %s",
                    method,
                    exc,
                    (r.text or "")[:200],
                )
                continue
            if not d.get("success"):
                log.error("xray config (%s): success=false — msg: %s", method, d.get("msg"))
                continue
            try:
                return json.loads(d.get("obj") or "{}")
            except (ValueError, TypeError) as exc:
                log.error("xray config (%s): failed to parse obj: %s", method, exc)
                continue
        return None

    def get_visible_outbounds(self) -> list[dict]:
        """Return customer-facing outbounds — excludes direct/blackhole/blocked system tags."""
        cfg = self.get_xray_config()
        if not cfg:
            return []
        outbounds = (cfg.get("xraySetting") or {}).get("outbounds") or []
        return [
            ob
            for ob in outbounds
            if isinstance(ob, dict)
            and str(ob.get("tag", "")).strip().lower() not in self._IGNORED_OUTBOUND_TAGS
        ]

    def test_outbound(
        self, outbound: dict, all_outbounds: list, mode: str = "http"
    ) -> dict | None:
        """Run the panel's built-in outbound connectivity test. Returns the result obj, or None."""
        payload = {
            "outbound": json.dumps(outbound, ensure_ascii=False),
            "allOutbounds": json.dumps(all_outbounds, ensure_ascii=False),
            "mode": mode,
        }
        r = self._panel_req("post", "/panel/xray/testOutbound", data=payload)
        if not (r and r.ok):
            return None
        try:
            d = r.json()
        except ValueError:
            return None
        return d.get("obj") if d.get("success") else None

    def get_db_backup(self) -> bytes | None:
        """Download x-ui.db as raw bytes, or None on error."""
        r = self._req("get", "/api/server/getDb")
        if r and r.ok:
            return r.content
        return None

    def delete_client(self, inbound_id: int, email: str) -> bool:
        """Delete a client from an inbound by email."""
        r = self._req(
            "post",
            f"/api/inbounds/{inbound_id}/delClientByEmail/{quote(str(email or '').strip(), safe='')}",
        )
        return bool(r and r.ok and r.json().get("success"))

    def reset_client_traffic(self, inbound_id: int, email: str) -> bool:
        """Reset traffic counters for a client."""
        r = self._req(
            "post",
            f"/api/inbounds/{inbound_id}/resetClientTraffic/{quote(str(email or '').strip(), safe='')}",
        )
        return bool(r and r.ok and r.json().get("success"))

    def get_inbound(self, inbound_id: int) -> dict | None:
        """Return a single inbound object, or None on error."""
        r = self._req("get", f"/api/inbounds/get/{inbound_id}")
        if r and r.ok:
            d = r.json()
            if d.get("success"):
                return d.get("obj")
        return None

    def update_client(
        self,
        inbound_id: int,
        email: str,
        total_gb: float | None = None,
        expiry_days: float | None = None,
        enable: bool | None = None,
    ) -> bool:
        """Update a client's settings. Pass None to keep the current value."""
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return False
        try:
            settings = json.loads(inbound.get("settings", "{}"))
        except Exception:
            return False
        clients = settings.get("clients", [])
        client = next((c for c in clients if c.get("email") == email), None)
        if not client:
            return False
        cid = client.get("id") or client.get("password") or ""
        if not cid:
            return False
        if total_gb is not None:
            client["totalGB"] = int(total_gb * 1_073_741_824) if total_gb > 0 else 0
        if expiry_days is not None:
            client["expiryTime"] = (
                int((time.time() + expiry_days * 86400) * 1000) if expiry_days > 0 else 0
            )
        if enable is not None:
            client["enable"] = enable
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client]}),
        }
        r = self._req("post", f"/api/inbounds/updateClient/{cid}", json=payload)
        return bool(r and r.ok and r.json().get("success"))

    def regenerate_client_identity(
        self,
        inbound_id: int,
        email: str,
    ) -> tuple[bool, str | None, str | None, str | None]:
        """Regenerate client uuid/password + subId. Returns (ok, new_id, new_sub_id, err)."""
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return False, None, None, "inbound_not_found"

        try:
            settings = json.loads(inbound.get("settings", "{}") or "{}")
        except Exception:
            return False, None, None, "invalid_inbound_settings"

        clients = settings.get("clients")
        if not isinstance(clients, list):
            return False, None, None, "clients_list_not_found"

        target_email = str(email or "").strip()
        client = next(
            (c for c in clients if str(c.get("email") or "").strip() == target_email),
            None,
        )
        if not isinstance(client, dict):
            return False, None, None, "client_not_found"

        old_cid = str(client.get("id") or client.get("password") or "").strip()
        if not old_cid:
            return False, None, None, "client_id_missing"

        new_id = str(uuid.uuid4())
        new_sub_id = uuid.uuid4().hex[:16]

        if "id" in client and str(client.get("id") or "").strip():
            client["id"] = new_id
        if "password" in client and str(client.get("password") or "").strip():
            client["password"] = new_id
        client["subId"] = new_sub_id

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client]}),
        }
        r = self._req(
            "post",
            f"/api/inbounds/updateClient/{quote(old_cid, safe='')}",
            json=payload,
        )
        if r and r.ok:
            try:
                d = r.json()
            except Exception:
                return False, None, None, "invalid_response"
            if d.get("success"):
                return True, new_id, new_sub_id, None
            return False, None, None, str(d.get("msg") or "something_went_wrong")

        return False, None, None, "network_error"

    def rotate_wireguard_peer_secret(
        self,
        inbound_id: int,
        email: str,
    ) -> tuple[bool, dict | None, dict | None, str | None]:
        """Rotate WireGuard peer private/public keys. Returns (ok, inbound_obj, peer_obj, err)."""
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return False, None, None, "inbound_not_found"

        if str(inbound.get("protocol", "")).strip().lower() != "wireguard":
            return False, None, None, "inbound_protocol_is_not_wireguard"

        try:
            settings = json.loads(inbound.get("settings", "{}") or "{}")
        except Exception:
            return False, None, None, "invalid_inbound_settings"

        peers = settings.get("peers")
        if not isinstance(peers, list) or not peers:
            return False, None, None, "wireguard_peers_not_found"

        target = str(email or "").strip().casefold()
        peer = None
        for p in peers:
            if not isinstance(p, dict):
                continue
            p_email = str(p.get("email") or "").strip().casefold()
            p_comment = str(p.get("comment") or "").strip().casefold()
            if target and target in {p_email, p_comment}:
                peer = p
                break

        if peer is None and len(peers) == 1 and isinstance(peers[0], dict):
            peer = peers[0]

        if not isinstance(peer, dict):
            return False, None, None, "peer_not_found"

        keypair = self.get_new_x25519_cert()
        if not keypair:
            return False, None, None, "x25519_key_generation_failed"

        new_private = _normalize_wg_b64(keypair.get("privateKey", ""))
        new_public = _normalize_wg_b64(keypair.get("publicKey", ""))
        if not new_private or not new_public:
            return False, None, None, "invalid_generated_keypair"

        peer["privateKey"] = new_private
        peer["publicKey"] = new_public

        settings["peers"] = peers
        inbound["settings"] = json.dumps(settings, ensure_ascii=False)

        ok, inbound_obj, err = self.update_inbound(inbound)
        if not ok:
            return False, None, None, err

        server_pub = settings.get("publicKey") or _derive_x25519_pubkey(
            settings.get("secretKey", "")
        )
        peer_out = dict(peer)
        peer_out["_server_public_key"] = server_pub
        peer_out["_mtu"] = int(settings.get("mtu", 1420) or 1420)

        return True, inbound_obj or inbound, peer_out, None

    def get_new_x25519_cert(self) -> dict | None:
        """Return freshly generated X25519 keypair dict {privateKey, publicKey}."""
        r = self._req("get", "/api/server/getNewX25519Cert")
        if r and r.ok:
            try:
                d = r.json()
                if d.get("success"):
                    obj = d.get("obj") or {}
                    if obj.get("privateKey") and obj.get("publicKey"):
                        return obj
            except Exception:
                return None
        return None

    def _wg_get_inbounds(self) -> list:
        r = self._wg_req("get", "/api/inbounds/list")
        if not (r and r.ok):
            return []
        try:
            d = r.json()
        except Exception:
            return []
        if d.get("success"):
            obj = d.get("obj")
            if isinstance(obj, list):
                return obj
        return []

    def _wg_get_new_x25519_cert(self) -> dict | None:
        r = self._wg_req("get", "/api/server/getNewX25519Cert")
        if r and r.ok:
            try:
                d = r.json()
                if d.get("success"):
                    obj = d.get("obj") or {}
                    if obj.get("privateKey") and obj.get("publicKey"):
                        return obj
            except Exception:
                return None
        return None

    def update_inbound(self, inbound: dict) -> tuple[bool, dict | None, str | None]:
        """Update full inbound object. Returns (ok, obj, error_msg)."""
        inbound_id = (inbound or {}).get("id")
        if not inbound_id:
            return False, None, "inbound_id_missing"

        r = self._req("post", f"/api/inbounds/update/{inbound_id}", json=inbound)
        if not r:
            return False, None, "network_error"

        txt = (getattr(r, "text", "") or "").strip()
        if not txt:
            return False, None, "empty_response"

        try:
            d = r.json()
        except Exception:
            return False, None, txt

        if d.get("success"):
            return True, d.get("obj"), None
        return False, d.get("obj"), str(d.get("msg") or "something_went_wrong")

    def add_wireguard_peer(
        self,
        inbound_id: int,
        preferred_ip: str | None = None,
        email: str | None = None,
        total_gb: float = 0,
        expiry_days: float = 0,
        tg_id: int | str | None = None,
        keep_alive: int = 0,
    ) -> tuple[bool, dict | None, str | None]:
        """
        Append a new WireGuard peer to inbound.settings.peers.

        Returns (ok, peer_dict, error_msg).
        """
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return False, None, "inbound_not_found"

        if str(inbound.get("protocol", "")).lower() != "wireguard":
            return False, None, "inbound_protocol_is_not_wireguard"

        try:
            settings = json.loads(inbound.get("settings", "{}") or "{}")
        except Exception:
            return False, None, "invalid_inbound_settings"

        peers = settings.get("peers")
        if not isinstance(peers, list):
            return False, None, "wireguard_peers_not_found"

        used_ips: set[str] = set()
        for p in peers:
            for raw_ip in (p.get("allowedIPs") or []):
                try:
                    iface = ipaddress.ip_interface(str(raw_ip))
                    if isinstance(iface.ip, ipaddress.IPv4Address) and iface.network.prefixlen == 32:
                        used_ips.add(str(iface.ip))
                except Exception:
                    continue

        candidate_ip = None
        if preferred_ip:
            try:
                candidate_ip = str(ipaddress.ip_address(preferred_ip.strip()))
            except Exception:
                candidate_ip = None
            if candidate_ip in used_ips:
                return False, None, "preferred_ip_already_used"

        if not candidate_ip:
            base_prefix = "10.0.0"
            if used_ips:
                first = next(iter(used_ips))
                parts = first.split(".")
                if len(parts) == 4:
                    base_prefix = ".".join(parts[:3])
            for host in range(2, 255):
                probe = f"{base_prefix}.{host}"
                if probe not in used_ips:
                    candidate_ip = probe
                    break

        if not candidate_ip:
            return False, None, "no_free_allowed_ip"

        keypair = self.get_new_x25519_cert()
        if not keypair:
            return False, None, "x25519_key_generation_failed"

        expiry_ms = (
            int((time.time() + expiry_days * 86400) * 1000) if expiry_days > 0 else 0
        )
        total_bytes = int(total_gb * 1_073_741_824) if total_gb > 0 else 0

        peer = {
            "privateKey": _normalize_wg_b64(keypair.get("privateKey", "")),
            "publicKey": _normalize_wg_b64(keypair.get("publicKey", "")),
            "allowedIPs": [f"{candidate_ip}/32"],
            "keepAlive": max(0, int(keep_alive)),
        }
        if email:
            peer.update({
                "email": str(email),
                "comment": str(email),
                "remark": str(email),
                "totalGB": total_bytes,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": str(tg_id or ""),
                "subId": uuid.uuid4().hex[:16],
                "reset": 0,
            })
        if not peer["privateKey"] or not peer["publicKey"]:
            return False, None, "invalid_generated_keypair"

        peers.append(peer)
        settings["peers"] = peers
        inbound["settings"] = json.dumps(settings, ensure_ascii=False)

        ok, _, err = self.update_inbound(inbound)
        if not ok:
            return False, None, err
        # publicKey may be absent; derive it from secretKey via X25519 math
        server_pub = settings.get("publicKey") or _derive_x25519_pubkey(settings.get("secretKey", ""))
        peer["_server_public_key"] = server_pub
        peer["_mtu"] = int(settings.get("mtu", 1420) or 1420)
        return True, peer, None

    def add_wireguard_inbound(
        self,
        remark: str,
        total_gb: float,
        expiry_days: float = 0,
        tg_id: int | str | None = None,
        mtu: int = 1420,
        keep_alive: int = 0,
    ) -> tuple[bool, dict | None, dict | None, str | None]:
        """
        Create a dedicated WireGuard inbound with one peer.

        This makes the service visible as its own row in the 3x-ui Inbounds page.
        Returns (ok, inbound_obj_or_payload, peer_dict, error_msg).
        """
        remark = (remark or "").strip()
        if not remark:
            return False, None, None, "remark_missing"
        if not WG_TRUSTED_PORTS:
            return False, None, None, "trusted_ports_not_configured"

        inbounds = self._wg_get_inbounds()
        used_ports = {int(i.get("port") or 0) for i in inbounds if i.get("port")}
        port = next((p for p in WG_TRUSTED_PORTS if p not in used_ports), None)
        if not port:
            return False, None, None, "no_free_trusted_port"

        server_keypair = self._wg_get_new_x25519_cert()
        peer_keypair = self._wg_get_new_x25519_cert()
        if not server_keypair or not peer_keypair:
            return False, None, None, "x25519_key_generation_failed"

        server_private = _normalize_wg_b64(server_keypair.get("privateKey", ""))
        server_public = _normalize_wg_b64(server_keypair.get("publicKey") or _derive_x25519_pubkey(server_private))
        peer_private = _normalize_wg_b64(peer_keypair.get("privateKey", ""))
        peer_public = _normalize_wg_b64(peer_keypair.get("publicKey", ""))
        if not server_private or not server_public or not peer_private or not peer_public:
            return False, None, None, "invalid_generated_keypair"

        expiry_ms = (
            int((time.time() + expiry_days * 86400) * 1000) if expiry_days > 0 else 0
        )
        total_bytes = int(total_gb * 1_073_741_824) if total_gb > 0 else 0
        peer = {
            "privateKey": peer_private,
            "publicKey": peer_public,
            "allowedIPs": ["10.0.0.2/32"],
            "keepAlive": max(0, int(keep_alive)),
            "email": remark,
            "comment": remark,
            "remark": remark,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": str(tg_id or ""),
            "subId": uuid.uuid4().hex[:16],
            "reset": 0,
        }
        settings = {
            "mtu": int(mtu or 1420),
            "secretKey": server_private,
            "peers": [peer],
            "noKernelTun": False,
        }
        sniffing = {
            "enabled": False,
            "destOverride": ["http", "tls", "quic", "fakedns"],
            "metadataOnly": False,
            "routeOnly": False,
        }
        payload = {
            "up": 0,
            "down": 0,
            "total": total_bytes,
            "remark": remark,
            "enable": True,
            "expiryTime": expiry_ms,
            "listen": "",
            "port": port,
            "protocol": "wireguard",
            "settings": json.dumps(settings, ensure_ascii=False),
            "streamSettings": "",
            "sniffing": json.dumps(sniffing, ensure_ascii=False, indent=2),
        }

        r = self._wg_req("post", "/api/inbounds/add", json=payload)
        if not r:
            return False, None, None, "network_error"
        txt = (getattr(r, "text", "") or "").strip()
        try:
            d = r.json()
        except Exception:
            return False, None, None, txt or "invalid_response"
        if not d.get("success"):
            return False, d.get("obj"), None, str(d.get("msg") or "something_went_wrong")

        inbound_obj = d.get("obj")
        if not isinstance(inbound_obj, dict) or not inbound_obj.get("id"):
            for inb in self._wg_get_inbounds():
                if int(inb.get("port") or 0) == port and (inb.get("remark") or "") == remark:
                    inbound_obj = inb
                    break
        if not isinstance(inbound_obj, dict):
            inbound_obj = payload

        peer["_server_public_key"] = server_public
        peer["_server_host"] = urlparse(WG_XUI_URL).hostname or WG_XUI_URL
        peer["_panel_url"] = WG_XUI_URL
        peer["_panel_base_path"] = WG_XUI_BASE_PATH
        peer["_mtu"] = int(mtu or 1420)
        return True, inbound_obj, peer, None
