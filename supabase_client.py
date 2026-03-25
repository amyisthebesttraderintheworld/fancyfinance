from __future__ import annotations

import os
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from common import get_logger

try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover - optional dependency in local test environments
    Client = Any  # type: ignore[assignment]
    create_client = None

load_dotenv()

FREE_MEMBERSHIP = "free"
PRO_MEMBERSHIP = "pro"
PRO_MEMBERSHIP_ALIASES = {"pro", "paid", "premium", "plus", "simulation", "sim", "live"}
ACTIVE_STRIPE_STATUSES = {"active", "trialing"}


class CipherManager:
    def __init__(self):
        self.logger = get_logger("Cipher")
        self.using_fallback_key = False
        self.status = "configured"
        raw_key = os.getenv("MASTER_ENCRYPTION_KEY")
        if raw_key:
            key = raw_key.encode() if isinstance(raw_key, str) else raw_key
        else:
            key = Fernet.generate_key()
            self.using_fallback_key = True
            self.status = "missing"
            self.logger.warning("MASTER_ENCRYPTION_KEY not found. Using temporary in-memory key.")

        try:
            self.cipher = Fernet(key)
        except Exception:
            self.using_fallback_key = True
            self.status = "invalid"
            self.logger.warning(
                "MASTER_ENCRYPTION_KEY invalid. Expected a Fernet key. Falling back to temporary in-memory key."
            )
            self.cipher = Fernet(Fernet.generate_key())

    def encrypt(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()

    def decrypt(self, encrypted_data: str) -> str:
        return self.cipher.decrypt(encrypted_data.encode()).decode()


class SupabaseManager:
    def __init__(self):
        self.logger = get_logger("Supabase")
        self.cipher = CipherManager()
        self.url = os.getenv("SUPABASE_URL", "")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.client: Optional[Client] = None

        self._users: Dict[int, Dict[str, Any]] = {}
        self._user_configs: Dict[int, Dict[str, Any]] = {}
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._trades: List[Dict[str, Any]] = []

        if create_client and self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                self.logger.info("Supabase client initialized.")
            except Exception as exc:
                self.logger.warning(f"Supabase unavailable, using local in-memory store: {exc}")
        else:
            self.logger.warning("Supabase credentials missing or package unavailable. Using local in-memory store.")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    def _normalize_membership_tier(self, value: Optional[str]) -> str:
        normalized = str(value or FREE_MEMBERSHIP).strip().lower()
        return PRO_MEMBERSHIP if normalized in PRO_MEMBERSHIP_ALIASES else FREE_MEMBERSHIP

    def _membership_is_active(self, user: Dict[str, Any]) -> bool:
        tier = self._normalize_membership_tier(user.get("membership_tier"))
        if tier == FREE_MEMBERSHIP:
            return True

        expires_at = self._parse_datetime(user.get("membership_expires_at"))
        if expires_at is None:
            return True
        return expires_at > datetime.now(timezone.utc)

    def _membership_status(self, user: Dict[str, Any]) -> str:
        tier = self._normalize_membership_tier(user.get("membership_tier"))
        if tier == FREE_MEMBERSHIP:
            return "free"
        return "active" if self._membership_is_active(user) else "expired"

    def _normalize_user_record(self, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not user:
            return user

        user["membership_tier"] = self._normalize_membership_tier(user.get("membership_tier"))
        user["membership_expires_at"] = user.get("membership_expires_at")
        user["membership_status"] = self._membership_status(user)
        user["stripe_customer_id"] = user.get("stripe_customer_id")
        user["stripe_subscription_id"] = user.get("stripe_subscription_id")
        user["stripe_subscription_status"] = user.get("stripe_subscription_status")
        return user

    def _base_user_payload(self, telegram_id: int, username: str, first_name: str) -> Dict[str, Any]:
        return {
            "telegram_id": telegram_id,
            "username": username,
            "first_name": first_name,
            "email": None,
            "pending_email": None,
            "email_otp": None,
            "otp_created_at": None,
            "is_verified": False,
            "created_at": self._now(),
            "updated_at": self._now(),
        }

    def _user_payload(self, telegram_id: int, username: str, first_name: str) -> Dict[str, Any]:
        return {
            **self._base_user_payload(telegram_id, username, first_name),
            "membership_tier": FREE_MEMBERSHIP,
            "membership_expires_at": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "stripe_subscription_status": None,
        }

    def _has_optional_user_columns_error(self, exc: Exception) -> bool:
        message = str(exc)
        return "membership_" in message or "stripe_" in message

    def _persist_user_update(self, telegram_id: int, update_payload: Dict[str, Any]) -> bool:
        if not self.client:
            return True

        try:
            self.client.table("users").update(update_payload).eq("telegram_id", telegram_id).execute()
            return True
        except Exception as exc:
            if self._has_optional_user_columns_error(exc):
                self.logger.warning(
                    "Users table is missing membership/Stripe columns. Update was cached locally only until the "
                    "database schema is expanded."
                )
                return False
            self.logger.error(f"Failed to update user {telegram_id}: {exc}")
            return False

    def _otp_is_fresh(self, created_at: Optional[str], ttl_minutes: int = 15) -> bool:
        if not created_at:
            return False
        created = self._parse_datetime(created_at)
        if created is None:
            return False
        return datetime.now(timezone.utc) - created <= timedelta(minutes=ttl_minutes)

    def store_user_api_keys(self, user_id: int, api_key: str, api_secret: str) -> bool:
        encrypted_key = self.cipher.encrypt(api_key)
        encrypted_secret = self.cipher.encrypt(api_secret)
        payload = {
            "user_id": user_id,
            "api_key_enc": encrypted_key,
            "api_secret_enc": encrypted_secret,
            "updated_at": self._now(),
        }

        self._user_configs[user_id] = payload
        if not self.client:
            return True

        try:
            self.client.table("user_configs").upsert(payload, on_conflict="user_id").execute()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to store user API keys: {exc}")
            return False

    def get_user_api_keys(self, user_id: int) -> Optional[Dict[str, str]]:
        if user_id in self._user_configs:
            config = self._user_configs[user_id]
            return {
                "api_key": self.cipher.decrypt(config["api_key_enc"]),
                "api_secret": self.cipher.decrypt(config["api_secret_enc"]),
            }

        if not self.client:
            return None

        try:
            response = self.client.table("user_configs").select("*").eq("user_id", user_id).limit(1).execute()
            if not response.data:
                return None
            config = response.data[0]
            self._user_configs[user_id] = config
            return {
                "api_key": self.cipher.decrypt(config["api_key_enc"]),
                "api_secret": self.cipher.decrypt(config["api_secret_enc"]),
            }
        except Exception as exc:
            self.logger.error(f"Failed to retrieve user API keys: {exc}")
            return None

    def get_or_create_user(self, telegram_id: int, username: str, first_name: str) -> Optional[Dict[str, Any]]:
        user = self._normalize_user_record(self._users.get(telegram_id))
        if user:
            if username:
                user["username"] = username
            if first_name:
                user["first_name"] = first_name
            user["updated_at"] = self._now()
            return user

        payload = self._user_payload(telegram_id, username, first_name)
        self._users[telegram_id] = payload

        if not self.client:
            return payload

        try:
            response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
            if response.data:
                user = self._normalize_user_record(response.data[0])
                if username or first_name:
                    update_payload = {
                        "username": username or user.get("username"),
                        "first_name": first_name or user.get("first_name"),
                        "updated_at": self._now(),
                    }
                    self.client.table("users").update(update_payload).eq("telegram_id", telegram_id).execute()
                    user.update(update_payload)
                self._users[telegram_id] = user
                return user

            try:
                self.client.table("users").insert(payload).execute()
            except Exception as exc:
                if self._has_optional_user_columns_error(exc):
                    self.logger.warning(
                        "Users table is missing membership/Stripe columns. Inserted base profile only; "
                        "billing state will not persist until the schema is updated."
                    )
                    self.client.table("users").insert(self._base_user_payload(telegram_id, username, first_name)).execute()
                else:
                    raise
            return payload
        except Exception as exc:
            self.logger.error(f"Failed to get or create user: {exc}")
            return self._normalize_user_record(self._users.get(telegram_id))

    def get_membership_summary(
        self,
        telegram_id: int,
        username: str = "",
        first_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, username, first_name)
        if not user:
            return None

        tier = self._normalize_membership_tier(user.get("membership_tier"))
        status = self._membership_status(user)
        return {
            "tier": tier,
            "status": status,
            "expires_at": user.get("membership_expires_at"),
            "can_backtest": True,
            "can_simulation": tier == PRO_MEMBERSHIP and status == "active",
            "can_live": tier == PRO_MEMBERSHIP and status == "active",
        }

    def user_can_access_mode(self, telegram_id: int, mode: str) -> bool:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "backtest":
            return True

        membership = self.get_membership_summary(telegram_id)
        if not membership:
            return False

        if normalized_mode == "simulation":
            return membership["can_simulation"]
        if normalized_mode == "live":
            return membership["can_live"]
        return False

    def set_membership(
        self,
        telegram_id: int,
        tier: str,
        expires_at: Optional[str] = None,
        username: str = "",
        first_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, username, first_name)
        if not user:
            return None

        normalized_tier = self._normalize_membership_tier(tier)
        if normalized_tier == FREE_MEMBERSHIP:
            expires_at = None
        elif expires_at and self._parse_datetime(expires_at) is None:
            raise ValueError("expires_at must be an ISO datetime string")

        update_payload = {
            "membership_tier": normalized_tier,
            "membership_expires_at": expires_at,
            "updated_at": self._now(),
        }
        user.update(update_payload)
        self._normalize_user_record(user)

        if not self.client:
            return user

        self._persist_user_update(telegram_id, update_payload)
        return user

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        if telegram_id in self._users:
            return self._normalize_user_record(self._users.get(telegram_id))

        if not self.client:
            return None

        try:
            response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
            if not response.data:
                return None
            user = self._normalize_user_record(response.data[0])
            self._users[telegram_id] = user
            return user
        except Exception as exc:
            self.logger.error(f"Failed to load user {telegram_id}: {exc}")
            return None

    def find_user_by_stripe_customer_id(self, customer_id: str) -> Optional[Dict[str, Any]]:
        if not customer_id:
            return None

        for user in self._users.values():
            if user.get("stripe_customer_id") == customer_id:
                return self._normalize_user_record(user)

        if not self.client:
            return None

        try:
            response = self.client.table("users").select("*").eq("stripe_customer_id", customer_id).limit(1).execute()
            if not response.data:
                return None
            user = self._normalize_user_record(response.data[0])
            self._users[user["telegram_id"]] = user
            return user
        except Exception as exc:
            self.logger.error(f"Failed to find user by Stripe customer {customer_id}: {exc}")
            return None

    def find_user_by_stripe_subscription_id(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        if not subscription_id:
            return None

        for user in self._users.values():
            if user.get("stripe_subscription_id") == subscription_id:
                return self._normalize_user_record(user)

        if not self.client:
            return None

        try:
            response = (
                self.client.table("users").select("*").eq("stripe_subscription_id", subscription_id).limit(1).execute()
            )
            if not response.data:
                return None
            user = self._normalize_user_record(response.data[0])
            self._users[user["telegram_id"]] = user
            return user
        except Exception as exc:
            self.logger.error(f"Failed to find user by Stripe subscription {subscription_id}: {exc}")
            return None

    def sync_stripe_customer(
        self,
        telegram_id: int,
        *,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        subscription_status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return None

        update_payload = {
            "updated_at": self._now(),
        }
        if customer_id is not None:
            update_payload["stripe_customer_id"] = customer_id
        if subscription_id is not None:
            update_payload["stripe_subscription_id"] = subscription_id
        if subscription_status is not None:
            update_payload["stripe_subscription_status"] = subscription_status

        user.update(update_payload)
        self._normalize_user_record(user)
        self._persist_user_update(telegram_id, update_payload)
        return user

    def activate_paid_membership_from_stripe(
        self,
        telegram_id: int,
        *,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        subscription_status: str = "active",
        period_end: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return None

        if period_end and self._parse_datetime(period_end) is None:
            raise ValueError("period_end must be an ISO datetime string")

        update_payload = {
            "membership_tier": PRO_MEMBERSHIP,
            "membership_expires_at": period_end,
            "stripe_subscription_status": subscription_status,
            "updated_at": self._now(),
        }
        if customer_id is not None:
            update_payload["stripe_customer_id"] = customer_id
        if subscription_id is not None:
            update_payload["stripe_subscription_id"] = subscription_id

        user.update(update_payload)
        self._normalize_user_record(user)
        self._persist_user_update(telegram_id, update_payload)
        return user

    def deactivate_paid_membership(
        self,
        telegram_id: int,
        *,
        subscription_status: str = "canceled",
        clear_subscription_id: bool = False,
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return None

        update_payload = {
            "membership_tier": FREE_MEMBERSHIP,
            "membership_expires_at": None,
            "stripe_subscription_status": subscription_status,
            "updated_at": self._now(),
        }
        if clear_subscription_id:
            update_payload["stripe_subscription_id"] = None

        user.update(update_payload)
        self._normalize_user_record(user)
        self._persist_user_update(telegram_id, update_payload)
        return user

    def request_email_verification(self, telegram_id: int, email: str) -> Optional[str]:
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return None

        otp = "".join(random.choices(string.digits, k=6))
        update_data = {
            "pending_email": email,
            "email_otp": otp,
            "otp_created_at": self._now(),
            "updated_at": self._now(),
        }
        user.update(update_data)

        if not self.client:
            return otp

        try:
            self.client.table("users").update(update_data).eq("telegram_id", telegram_id).execute()
            return otp
        except Exception as exc:
            self.logger.error(f"Failed to request email verification: {exc}")
            return None

    def confirm_email_verification(self, telegram_id: int, otp: str) -> bool:
        user = self._normalize_user_record(self._users.get(telegram_id))

        if not user and self.client:
            try:
                response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
                if response.data:
                    user = self._normalize_user_record(response.data[0])
                    self._users[telegram_id] = user
            except Exception as exc:
                self.logger.error(f"Failed to load verification record: {exc}")
                return False

        if not user:
            return False

        if user.get("email_otp") != otp or not self._otp_is_fresh(user.get("otp_created_at")):
            return False

        update_data = {
            "email": user.get("pending_email"),
            "is_verified": True,
            "email_otp": None,
            "pending_email": None,
            "otp_created_at": None,
            "updated_at": self._now(),
        }
        user.update(update_data)

        if not self.client:
            return True

        try:
            self.client.table("users").update(update_data).eq("telegram_id", telegram_id).execute()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to confirm email verification: {exc}")
            return False

    def log_trade(self, trade_data: Dict[str, Any]) -> bool:
        payload = {**trade_data, "created_at": self._now()}
        self._trades.append(payload)

        if not self.client:
            return True

        try:
            self.client.table("trades").insert(payload).execute()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to log trade: {exc}")
            return False

    def update_position(self, symbol: str, position_data: Dict[str, Any]) -> bool:
        payload = {**position_data, "symbol": symbol, "updated_at": self._now()}
        self._positions[symbol] = payload

        if not self.client:
            return True

        try:
            self.client.table("positions").upsert(payload, on_conflict="symbol").execute()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to update position for {symbol}: {exc}")
            return False

    def remove_position(self, symbol: str) -> bool:
        self._positions.pop(symbol, None)

        if not self.client:
            return True

        try:
            self.client.table("positions").delete().eq("symbol", symbol).execute()
            return True
        except Exception as exc:
            self.logger.error(f"Failed to remove position for {symbol}: {exc}")
            return False

    def list_open_positions(self) -> List[Dict[str, Any]]:
        if self.client:
            try:
                response = self.client.table("positions").select("*").execute()
                if response.data:
                    self._positions = {item["symbol"]: item for item in response.data if item.get("symbol")}
            except Exception as exc:
                self.logger.error(f"Failed to list open positions: {exc}")
        return list(self._positions.values())

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.client:
            try:
                response = (
                    self.client.table("trades")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                if response.data:
                    self._trades = response.data
            except Exception as exc:
                self.logger.error(f"Failed to fetch recent trades: {exc}")
        return self._trades[-limit:]

    def get_user_summary(self, limit: int = 25) -> Dict[str, Any]:
        recent_users = list(self._users.values())
        total_users = len(recent_users)
        verified_users = sum(1 for user in recent_users if user.get("is_verified"))
        api_key_users = len(self._user_configs)

        if self.client:
            try:
                recent_response = (
                    self.client.table("users")
                    .select(
                        "telegram_id, username, first_name, email, pending_email, is_verified, "
                        "membership_tier, membership_expires_at, created_at, updated_at"
                    )
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                recent_users = [self._normalize_user_record(item) for item in (recent_response.data or recent_users)]

                total_response = (
                    self.client.table("users")
                    .select("telegram_id", count="exact")
                    .limit(1)
                    .execute()
                )
                verified_response = (
                    self.client.table("users")
                    .select("telegram_id", count="exact")
                    .eq("is_verified", True)
                    .limit(1)
                    .execute()
                )
                config_response = (
                    self.client.table("user_configs")
                    .select("user_id", count="exact")
                    .limit(1)
                    .execute()
                )

                total_users = total_response.count if total_response.count is not None else total_users
                verified_users = (
                    verified_response.count if verified_response.count is not None else verified_users
                )
                api_key_users = config_response.count if config_response.count is not None else api_key_users
            except Exception as exc:
                self.logger.error(f"Failed to build user summary: {exc}")

        recent_users = [self._normalize_user_record(dict(user)) for user in recent_users]
        free_users = sum(1 for user in recent_users if user.get("membership_tier") == FREE_MEMBERSHIP)
        pro_users = sum(1 for user in recent_users if user.get("membership_tier") == PRO_MEMBERSHIP)
        expired_users = sum(1 for user in recent_users if user.get("membership_status") == "expired")

        return {
            "total": total_users,
            "verified": verified_users,
            "unverified": max(total_users - verified_users, 0),
            "with_api_keys": api_key_users,
            "free": free_users,
            "pro": pro_users,
            "expired": expired_users,
            "recent": recent_users[:limit],
        }
