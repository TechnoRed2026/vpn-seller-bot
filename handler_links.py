"""Config-link helpers."""

import base64
import json


def add_insecure_to_link(link: str) -> str:
    """Inject insecure flags into supported config links."""
    if not link:
        return link
    lo = link.lower()

    if lo.startswith("vmess://"):
        try:
            b64 = link[8:]
            b64 += "=" * (-len(b64) % 4)
            cfg = json.loads(base64.b64decode(b64).decode("utf-8"))
            cfg["allowInsecure"] = 1
            cfg["skipCertVerify"] = True
            encoded = (
                base64.b64encode(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))
                .decode()
                .rstrip("=")
            )
            return f"vmess://{encoded}"
        except Exception:
            return link

    if lo.startswith(("vless://", "trojan://")):
        frag_idx = link.rfind("#")
        fragment = link[frag_idx:] if frag_idx != -1 else ""
        base = link[:frag_idx] if frag_idx != -1 else link
        q_idx = base.find("?")
        if q_idx != -1:
            pre = base[:q_idx]
            query = base[q_idx + 1 :]
            pairs = [
                p
                for p in query.split("&")
                if p and p.split("=", 1)[0] not in ("insecure", "allowInsecure")
            ]
            pairs += ["insecure=1", "allowInsecure=1"]
            return f"{pre}?{'&'.join(pairs)}{fragment}"
        return f"{base}?insecure=1&allowInsecure=1{fragment}"

    return link
