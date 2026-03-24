from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from common import get_logger
from fancyfinance import APP_NAME


class EmailService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        email_config = (config or {}).get("email", {})
        self.logger = get_logger("EmailService")
        self.confirm_webhook_url = str(email_config.get("confirm_webhook_url") or "").strip()
        self.confirm_webhook_timeout_seconds = int(email_config.get("confirm_webhook_timeout_seconds") or 15)

    def is_configured(self) -> bool:
        return bool(self.confirm_webhook_url)

    def send_verification_email(
        self,
        *,
        email: str,
        otp: str,
        telegram_id: int,
        username: str = "",
        first_name: str = "",
    ) -> bool:
        if not self.confirm_webhook_url:
            self.logger.warning("Email webhook URL is not configured.")
            return False

        payload = {
            "app": APP_NAME,
            "email": email,
            "otp": otp,
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "confirm_command": f"/confirm_email {otp}",
        }

        try:
            response = requests.post(
                self.confirm_webhook_url,
                json=payload,
                timeout=self.confirm_webhook_timeout_seconds,
            )
            response.raise_for_status()
            self.logger.info(f"Verification email webhook accepted for {email}.")
            return True
        except Exception as exc:
            self.logger.error(f"Verification email webhook failed for {email}: {exc}")
            return False
