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

    def _otp_is_fresh(self, created_at: Optional[str], ttl_minutes: int = 15) -> bool:
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - created <= timedelta(minutes=ttl_minutes)
        except ValueError:
            return False

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
        user = self._users.get(telegram_id)
        if user:
            if username:
                user["username"] = username
            if first_name:
                user["first_name"] = first_name
            user["updated_at"] = self._now()
            return user

        payload = {
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
        self._users[telegram_id] = payload

        if not self.client:
            return payload

        try:
            response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
            if response.data:
                user = response.data[0]
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

            self.client.table("users").insert(payload).execute()
            return payload
        except Exception as exc:
            self.logger.error(f"Failed to get or create user: {exc}")
            return self._users.get(telegram_id)

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
        user = self._users.get(telegram_id)

        if not user and self.client:
            try:
                response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
                if response.data:
                    user = response.data[0]
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
                    .select("telegram_id, username, first_name, email, pending_email, is_verified, created_at, updated_at")
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                recent_users = recent_response.data or recent_users

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

        return {
            "total": total_users,
            "verified": verified_users,
            "unverified": max(total_users - verified_users, 0),
            "with_api_keys": api_key_users,
            "recent": recent_users[:limit],
        }
