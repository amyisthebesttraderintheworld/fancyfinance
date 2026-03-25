from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict


SCOPE_MEMBER_DASHBOARD = "member_dashboard"
DEFAULT_TOKEN_TTL_SECONDS = 24 * 60 * 60


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
