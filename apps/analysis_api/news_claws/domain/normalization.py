from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only absolute http/https article URLs without credentials are allowed")
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query_items = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((scheme, host, path, urlencode(sorted(query_items)), ""))


def content_hash(*parts: str | None) -> str:
    normalized = "\n".join(normalize_text(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def text_tokens(value: str) -> set[str]:
    normalized = normalize_text(value).lower()
    latin = set(re.findall(r"[a-z][a-z0-9._-]+|\b\d+\b", normalized))
    cjk_chunks = re.findall(r"[\u3400-\u9fff]+", normalized)
    cjk = {
        chunk[index : index + 2] for chunk in cjk_chunks for index in range(max(1, len(chunk) - 1))
    }
    return latin | cjk


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = text_tokens(left)
    right_tokens = text_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
