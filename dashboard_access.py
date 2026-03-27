from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Mapping


SCOPE_MEMBER_DASHBOARD = "member_dashboard"
DEFAULT_TOKEN_TTL_SECONDS = 24 * 60 * 60
DEFAULT_TELEGRAM_AUTH_MAX_AGE_SECONDS = 10 * 60


class DashboardAccessError(ValueError):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(f"{raw}{padding}".encode("ascii"))


def _sign(secret: str, payload_segment: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), payload_segment.encode("ascii"), hashlib.sha256).digest())


def generate_member_dashboard_token(secret: str, user_id: int, *, ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS) -> str:
    if not secret:
        raise DashboardAccessError("Dashboard access secret is required.")

    payload = {
        "sub": int(user_id),
        "scope": SCOPE_MEMBER_DASHBOARD,
        "exp": int(time.time()) + max(int(ttl_seconds), 60),
    }
    payload_segment = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_segment = _sign(secret, payload_segment)
    return f"{payload_segment}.{signature_segment}"


def verify_member_dashboard_token(secret: str, token: str) -> Dict[str, Any]:
    if not secret:
        raise DashboardAccessError("Dashboard access secret is required.")
    if not token or "." not in token:
        raise DashboardAccessError("Malformed dashboard access token.")

    payload_segment, signature_segment = token.split(".", 1)
    expected_signature = _sign(secret, payload_segment)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise DashboardAccessError("Invalid dashboard access signature.")

    try:
        payload = json.loads(_b64decode(payload_segment).decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parsing guard
        raise DashboardAccessError("Invalid dashboard access payload.") from exc

    if payload.get("scope") != SCOPE_MEMBER_DASHBOARD:
        raise DashboardAccessError("Invalid dashboard access scope.")

    if int(payload.get("exp") or 0) < int(time.time()):
        raise DashboardAccessError("Dashboard access token expired.")

    return payload


def verify_telegram_login_payload(
    bot_token: str,
    payload: Mapping[str, Any],
    *,
    max_age_seconds: int = DEFAULT_TELEGRAM_AUTH_MAX_AGE_SECONDS,
) -> Dict[str, Any]:
    if not bot_token:
        raise DashboardAccessError("Telegram bot token is required.")

    raw_hash = str(payload.get("hash") or "").strip()
    if not raw_hash:
        raise DashboardAccessError("Missing Telegram login hash.")

    items: list[tuple[str, str]] = []
    for key, value in payload.items():
        if key in {"hash", "next"}:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        items.append((str(key), text))

    if not items:
        raise DashboardAccessError("Telegram login payload is empty.")

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(items, key=lambda item: item[0])
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, raw_hash):
        raise DashboardAccessError("Invalid Telegram login signature.")

    try:
        telegram_user_id = int(str(payload.get("id") or "").strip())
    except (TypeError, ValueError) as exc:
        raise DashboardAccessError("Telegram login payload is missing a valid user ID.") from exc

    try:
        auth_date = int(str(payload.get("auth_date") or "").strip())
    except (TypeError, ValueError) as exc:
        raise DashboardAccessError("Telegram login payload is missing a valid auth date.") from exc

    now = int(time.time())
    if auth_date > now + 60:
        raise DashboardAccessError("Telegram login timestamp is in the future.")
    if now - auth_date > max(int(max_age_seconds), 60):
        raise DashboardAccessError("Telegram login payload expired.")

    return {
        "id": telegram_user_id,
        "auth_date": auth_date,
        "first_name": str(payload.get("first_name") or "").strip(),
        "last_name": str(payload.get("last_name") or "").strip(),
        "username": str(payload.get("username") or "").strip(),
        "photo_url": str(payload.get("photo_url") or "").strip(),
        "lang": str(payload.get("lang") or "").strip(),
    }
