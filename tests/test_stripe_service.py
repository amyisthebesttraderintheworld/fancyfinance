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
                    "payment_status": "paid",
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
