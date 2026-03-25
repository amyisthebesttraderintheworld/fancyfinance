from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from common import get_logger
from fancyfinance import APP_NAME
from supabase_client import ACTIVE_STRIPE_STATUSES, DEFAULT_TRIAL_DAYS, SupabaseManager


class StripeService:
    api_base_url = "https://api.stripe.com/v1"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        stripe_config = (config or {}).get("stripe", {})
        self.logger = get_logger("StripeService")
        self.secret_key = str(stripe_config.get("secret_key") or "").strip()
        self.webhook_secret = str(stripe_config.get("webhook_secret") or "").strip()
        self.price_id = str(stripe_config.get("price_id") or "").strip()
        self.success_url = str(stripe_config.get("success_url") or "").strip()
        self.cancel_url = str(stripe_config.get("cancel_url") or "").strip()
        self.portal_return_url = str(
            stripe_config.get("portal_return_url") or stripe_config.get("cancel_url") or ""
        ).strip()
        self.trial_days = max(int(stripe_config.get("trial_days") or DEFAULT_TRIAL_DAYS), 0)
        self.timeout_seconds = int(stripe_config.get("timeout_seconds") or 20)
        self.webhook_tolerance_seconds = int(stripe_config.get("webhook_tolerance_seconds") or 300)

    def is_checkout_configured(self) -> bool:
        return bool(self.secret_key and self.price_id and self.success_url and self.cancel_url)

    def is_portal_configured(self) -> bool:
        return bool(self.secret_key and self.portal_return_url)

    def is_webhook_configured(self) -> bool:
        return bool(self.webhook_secret)

    def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f"{self.api_base_url}{endpoint}",
            data=data,
            auth=(self.secret_key, ""),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def create_checkout_session(
        self,
        user: Dict[str, Any],
        *,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_checkout_configured():
            raise ValueError("Stripe checkout is not fully configured")

        telegram_id = str(user["telegram_id"])
        session_success_url = success_url or self.success_url
        session_cancel_url = cancel_url or self.cancel_url
        if "{CHECKOUT_SESSION_ID}" not in session_success_url:
            separator = "&" if "?" in session_success_url else "?"
            session_success_url = f"{session_success_url}{separator}session_id={{CHECKOUT_SESSION_ID}}"

        payload = {
            "mode": "subscription",
            "success_url": session_success_url,
            "cancel_url": session_cancel_url,
            "line_items[0][price]": self.price_id,
            "line_items[0][quantity]": 1,
            "allow_promotion_codes": "true",
            "client_reference_id": telegram_id,
            "metadata[app]": APP_NAME,
            "metadata[telegram_id]": telegram_id,
            "metadata[username]": str(user.get("username") or ""),
            "metadata[first_name]": str(user.get("first_name") or ""),
            "subscription_data[metadata][telegram_id]": telegram_id,
            "subscription_data[metadata][username]": str(user.get("username") or ""),
            "subscription_data[metadata][first_name]": str(user.get("first_name") or ""),
        }

        if user.get("stripe_customer_id"):
            payload["customer"] = user["stripe_customer_id"]
        elif user.get("email"):
            payload["customer_email"] = user["email"]

        if self.trial_days > 0 and not user.get("stripe_customer_id") and not user.get("stripe_subscription_id"):
            payload["subscription_data[trial_period_days]"] = self.trial_days

        session = self._post("/checkout/sessions", payload)
        self.logger.info(f"Created Stripe Checkout Session for Telegram user {telegram_id}.")
        return session

    def create_customer_portal_session(
        self,
        *,
        customer_id: str,
        return_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.is_portal_configured():
            raise ValueError("Stripe billing portal is not fully configured")
        if not customer_id:
            raise ValueError("Stripe customer ID is required")

        session = self._post(
            "/billing_portal/sessions",
            {
                "customer": customer_id,
                "return_url": return_url or self.portal_return_url,
            },
        )
        self.logger.info(f"Created Stripe billing portal session for customer {customer_id}.")
        return session

    def _verify_signature(self, payload: bytes, signature_header: str):
        if not self.webhook_secret:
            raise ValueError("Stripe webhook secret is not configured")
        if not signature_header:
            raise ValueError("Missing Stripe-Signature header")

        values: Dict[str, list[str]] = {}
        for part in signature_header.split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            values.setdefault(key.strip(), []).append(value.strip())

        if "t" not in values or "v1" not in values:
            raise ValueError("Malformed Stripe-Signature header")

        timestamp = int(values["t"][0])
        if abs(int(time.time()) - timestamp) > self.webhook_tolerance_seconds:
            raise ValueError("Stripe webhook timestamp outside allowed tolerance")

        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not any(hmac.compare_digest(expected, candidate) for candidate in values["v1"]):
            raise ValueError("Invalid Stripe webhook signature")

    def _period_end_from_unix(self, raw_value: Any) -> Optional[str]:
        if not raw_value:
            return None
        try:
            return datetime.fromtimestamp(int(raw_value), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    def process_webhook(self, *, payload: bytes, signature_header: str, db: SupabaseManager) -> Dict[str, Any]:
        self._verify_signature(payload, signature_header)
        event = json.loads(payload.decode("utf-8"))
        event_type = event.get("type") or ""
        obj = ((event.get("data") or {}).get("object") or {})

        handled = False
        target_user = None

        if event_type == "checkout.session.completed":
            telegram_id = ((obj.get("metadata") or {}).get("telegram_id") or obj.get("client_reference_id") or "").strip()
            if telegram_id.isdigit():
                target_user = db.sync_stripe_customer(
                    int(telegram_id),
                    customer_id=obj.get("customer"),
                    subscription_id=obj.get("subscription"),
                    subscription_status="checkout_completed",
                )
                if obj.get("mode") == "subscription" and obj.get("payment_status") in {"paid", "no_payment_required"}:
                    initial_status = "trialing" if obj.get("payment_status") == "no_payment_required" and self.trial_days > 0 else "active"
                    target_user = db.activate_paid_membership_from_stripe(
                        int(telegram_id),
                        customer_id=obj.get("customer"),
                        subscription_id=obj.get("subscription"),
                        subscription_status=initial_status,
                        period_end=None,
                    )
                handled = True

        elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
            customer_id = obj.get("customer")
            subscription_id = obj.get("id")
            subscription_status = str(obj.get("status") or "")
            metadata = obj.get("metadata") or {}
            telegram_id = str(metadata.get("telegram_id") or "").strip()

            if telegram_id.isdigit():
                target_user = db.get_user(int(telegram_id))
            if not target_user and subscription_id:
                target_user = db.find_user_by_stripe_subscription_id(subscription_id)
            if not target_user and customer_id:
                target_user = db.find_user_by_stripe_customer_id(customer_id)

            if target_user:
                period_end = self._period_end_from_unix(obj.get("current_period_end"))
                if subscription_status in ACTIVE_STRIPE_STATUSES:
                    db.activate_paid_membership_from_stripe(
                        target_user["telegram_id"],
                        customer_id=customer_id,
                        subscription_id=subscription_id,
                        subscription_status=subscription_status,
                        period_end=period_end,
                    )
                else:
                    db.sync_stripe_customer(
                        target_user["telegram_id"],
                        customer_id=customer_id,
                        subscription_id=subscription_id,
                        subscription_status=subscription_status,
                    )
                    db.deactivate_paid_membership(
                        target_user["telegram_id"],
                        subscription_status=subscription_status,
                    )
                handled = True

        elif event_type == "customer.subscription.deleted":
            customer_id = obj.get("customer")
            subscription_id = obj.get("id")
            target_user = (
                db.find_user_by_stripe_subscription_id(subscription_id)
                or db.find_user_by_stripe_customer_id(customer_id)
            )
            if target_user:
                db.sync_stripe_customer(
                    target_user["telegram_id"],
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    subscription_status="canceled",
                )
                db.deactivate_paid_membership(
                    target_user["telegram_id"],
                    subscription_status="canceled",
                    clear_subscription_id=False,
                )
                handled = True

        elif event_type == "invoice.paid":
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")
            target_user = (
                db.find_user_by_stripe_subscription_id(subscription_id)
                or db.find_user_by_stripe_customer_id(customer_id)
            )
            if target_user:
                line_items = ((obj.get("lines") or {}).get("data") or [])
                period_end = None
                if line_items:
                    period_end = self._period_end_from_unix((((line_items[0] or {}).get("period") or {}).get("end")))
                db.activate_paid_membership_from_stripe(
                    target_user["telegram_id"],
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    subscription_status="active",
                    period_end=period_end,
                )
                handled = True

        elif event_type == "invoice.payment_failed":
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")
            target_user = (
                db.find_user_by_stripe_subscription_id(subscription_id)
                or db.find_user_by_stripe_customer_id(customer_id)
            )
            if target_user:
                db.sync_stripe_customer(
                    target_user["telegram_id"],
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    subscription_status="past_due",
                )
                handled = True

        return {
            "ok": True,
            "event_type": event_type,
            "handled": handled,
            "telegram_id": target_user.get("telegram_id") if target_user else None,
        }
