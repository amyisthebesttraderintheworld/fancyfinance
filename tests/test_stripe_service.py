import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock

from stripe_service import StripeService


def _signature(secret: str, payload: bytes, timestamp: int | None = None) -> str:
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.{payload.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def test_process_checkout_session_completed_activates_membership():
    config = {
        "stripe": {
            "webhook_secret": "whsec_test",
            "trial_days": 7,
        }
    }
    service = StripeService(config)
    db = MagicMock()

    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "payment_status": "no_payment_required",
                    "client_reference_id": "12345",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "metadata": {"telegram_id": "12345"},
                }
            },
        }
    ).encode("utf-8")

    result = service.process_webhook(
        payload=payload,
        signature_header=_signature("whsec_test", payload),
        db=db,
    )

    assert result["ok"] is True
    assert result["event_type"] == "checkout.session.completed"
    db.sync_stripe_customer.assert_called_once()
    db.activate_paid_membership_from_stripe.assert_called_once()
    assert db.activate_paid_membership_from_stripe.call_args.kwargs["subscription_status"] == "trialing"


def test_process_checkout_session_completed_activates_membership_by_email_when_metadata_missing():
    config = {
        "stripe": {
            "webhook_secret": "whsec_test",
            "trial_days": 7,
        }
    }
    service = StripeService(config)
    db = MagicMock()
    db.find_user_by_email.return_value = {"telegram_id": 12345, "email": "user@example.com"}

    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "payment_status": "paid",
                    "customer": "cus_123",
                    "subscription": "sub_123",
                    "customer_details": {"email": "user@example.com"},
                    "metadata": {},
                }
            },
        }
    ).encode("utf-8")

    result = service.process_webhook(
        payload=payload,
        signature_header=_signature("whsec_test", payload),
        db=db,
    )

    assert result["ok"] is True
    assert result["handled"] is True
    db.find_user_by_email.assert_called_once_with("user@example.com")
    db.activate_paid_membership_from_stripe.assert_called_once()
    assert db.activate_paid_membership_from_stripe.call_args.args[0] == 12345
    assert db.activate_paid_membership_from_stripe.call_args.kwargs["subscription_status"] == "active"


def test_process_subscription_deleted_deactivates_membership():
    config = {
        "stripe": {
            "webhook_secret": "whsec_test",
        }
    }
    service = StripeService(config)
    db = MagicMock()
    db.find_user_by_stripe_subscription_id.return_value = {"telegram_id": 12345}

    payload = json.dumps(
        {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                }
            },
        }
    ).encode("utf-8")

    result = service.process_webhook(
        payload=payload,
        signature_header=_signature("whsec_test", payload),
        db=db,
    )

    assert result["handled"] is True
    db.sync_stripe_customer.assert_called_once()
    db.deactivate_paid_membership.assert_called_once()


def test_process_subscription_updated_falls_back_to_email_lookup():
    config = {
        "stripe": {
            "webhook_secret": "whsec_test",
        }
    }
    service = StripeService(config)
    db = MagicMock()
    db.find_user_by_email.return_value = {"telegram_id": 12345, "email": "user@example.com"}
    db.find_user_by_stripe_subscription_id.return_value = None
    db.find_user_by_stripe_customer_id.return_value = None

    payload = json.dumps(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_123",
                    "customer": "cus_123",
                    "status": "active",
                    "metadata": {"email": "user@example.com"},
                    "current_period_end": 1770000000,
                }
            },
        }
    ).encode("utf-8")

    result = service.process_webhook(
        payload=payload,
        signature_header=_signature("whsec_test", payload),
        db=db,
    )

    assert result["handled"] is True
    db.find_user_by_email.assert_called_once_with("user@example.com")
    db.activate_paid_membership_from_stripe.assert_called_once()


def test_create_checkout_session_includes_trial_for_new_customer(monkeypatch):
    config = {
        "stripe": {
            "secret_key": "sk_test_123",
            "price_id": "price_123",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
            "trial_days": 7,
        }
    }
    service = StripeService(config)

    captured_payload = {}

    def fake_post(endpoint, data):
        captured_payload["endpoint"] = endpoint
        captured_payload["data"] = data
        return {"url": "https://checkout.stripe.com/pay/cs_test"}

    monkeypatch.setattr(service, "_post", fake_post)

    session = service.create_checkout_session({"telegram_id": 12345, "email": "user@example.com"})

    assert session["url"].startswith("https://checkout.stripe.com/")
    assert captured_payload["endpoint"] == "/checkout/sessions"
    assert captured_payload["data"]["subscription_data[trial_period_days]"] == 7
