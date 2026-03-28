from __future__ import annotations

import json
import os
import random
import re
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from common import get_logger
from zero_knowledge_vault import (
    InvalidPassphraseError,
    PBKDF2_ITERATIONS,
    VAULT_VERSION,
    ZeroKnowledgeVault,
)

try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover - optional dependency in local test environments
    Client = Any  # type: ignore[assignment]
    create_client = None

load_dotenv()

FREE_MEMBERSHIP = "free"
TRIAL_PRO_MEMBERSHIP = "trial_pro"
PRO_MEMBERSHIP = "pro"
TRIAL_PRO_MEMBERSHIP_ALIASES = {
    "trial",
    "trialing",
    "trial_pro",
    "trial-pro",
    "trialpro",
    "trial pro",
}
PRO_MEMBERSHIP_ALIASES = {"pro", "paid", "premium", "plus", "simulation", "sim", "live"}
ACTIVE_STRIPE_STATUSES = {"active", "trialing"}
DEFAULT_TRIAL_DAYS = 7
GLOBAL_ACCOUNT_USER_ID = 0


class CipherManager:
    def __init__(self, mode="production"):
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

        if self.using_fallback_key and str(mode).lower() not in {"backtest", "simulation", "dev", "testing", "local"}:
            raise RuntimeError(
                "MASTER_ENCRYPTION_KEY is required in non-test modes. Refusing to start with a temporary key."
            )

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
    def __init__(self, mode: str = "production"):
        self.logger = get_logger("Supabase")
        self.cipher = CipherManager(mode=mode)
        self.vault = ZeroKnowledgeVault()
        self.url = os.getenv("SUPABASE_URL", "")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.client: Optional[Client] = None
        self.complimentary_pro_ids = self._parse_telegram_id_env("COMPLIMENTARY_PRO_TELEGRAM_IDS")

        self._users: Dict[int, Dict[str, Any]] = {}
        self._user_configs: Dict[int, Dict[str, Any]] = {}
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._trades: List[Dict[str, Any]] = []
        self._trade_user_scope_warning_logged = False
        self._position_user_scope_warning_logged = False
        self._strategy_config_warning_logged = False
        self._unsupported_trade_columns: set[str] = set()
        self._unsupported_position_columns: set[str] = set()
        self._trade_column_warning_logged: set[str] = set()
        self._position_column_warning_logged: set[str] = set()

        if create_client and self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                self.logger.info("Supabase client initialized.")
            except Exception as exc:
                self.logger.warning(f"Supabase unavailable, using local in-memory store: {exc}")
        else:
            self.logger.warning("Supabase credentials missing or package unavailable. Using local in-memory store.")

        if self.complimentary_pro_ids:
            self.logger.info(
                f"Configured complimentary Pro access for {len(self.complimentary_pro_ids)} Telegram account(s)."
            )

    def _parse_telegram_id_env(self, env_key: str) -> set[int]:
        raw_value = os.getenv(env_key, "")
        parsed_ids: set[int] = set()
        for item in raw_value.split(","):
            stripped = item.strip()
            if not stripped:
                continue
            try:
                parsed_ids.add(int(stripped))
            except ValueError:
                self.logger.warning(f"Ignoring invalid Telegram ID `{stripped}` in {env_key}.")
        return parsed_ids

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
        normalized = str(value or FREE_MEMBERSHIP).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {item.replace("-", "_").replace(" ", "_") for item in TRIAL_PRO_MEMBERSHIP_ALIASES}:
            return TRIAL_PRO_MEMBERSHIP
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
        if tier == TRIAL_PRO_MEMBERSHIP:
            return "trial_pro" if self._membership_is_active(user) else "trial_expired"
        return "active" if self._membership_is_active(user) else "expired"

    def _normalize_user_record(self, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not user:
            return user

        normalized_tier = self._normalize_membership_tier(user.get("membership_tier"))
        if str(user.get("stripe_subscription_status") or "").strip().lower() == "trialing" and normalized_tier == PRO_MEMBERSHIP:
            normalized_tier = TRIAL_PRO_MEMBERSHIP

        user["membership_tier"] = normalized_tier
        user["membership_expires_at"] = user.get("membership_expires_at")
        user["membership_status"] = self._membership_status(user)
        user["trial_started_at"] = user.get("trial_started_at")
        user["stripe_customer_id"] = user.get("stripe_customer_id")
        user["stripe_subscription_id"] = user.get("stripe_subscription_id")
        user["stripe_subscription_status"] = user.get("stripe_subscription_status")
        user["membership_source"] = "stripe" if user.get("stripe_subscription_id") else "manual"
        user["has_agreed"] = bool(user.get("has_agreed", False))
        return user

    def _is_complimentary_pro(self, telegram_id: int) -> bool:
        return telegram_id in self.complimentary_pro_ids

    def _apply_complimentary_override(self, user: Optional[Dict[str, Any]], persist: bool = False) -> Optional[Dict[str, Any]]:
        if not user:
            return user

        telegram_id = user.get("telegram_id")
        if not isinstance(telegram_id, int) or not self._is_complimentary_pro(telegram_id):
            return self._normalize_user_record(user)

        update_payload = {
            "membership_tier": PRO_MEMBERSHIP,
            "membership_expires_at": None,
            "updated_at": self._now(),
        }

        user.update(update_payload)
        normalized_user = self._normalize_user_record(user)
        if normalized_user is not None:
            normalized_user["membership_status"] = "active"
            normalized_user["membership_source"] = "complimentary"

        if persist:
            self._persist_user_update(telegram_id, update_payload)

        return normalized_user

    def _trial_expiry(self, days: int = DEFAULT_TRIAL_DAYS) -> str:
        safe_days = max(int(days or DEFAULT_TRIAL_DAYS), 1)
        return (datetime.now(timezone.utc) + timedelta(days=safe_days)).isoformat()

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
            "trial_started_at": None,
            "has_agreed": False,
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
            "has_agreed": False,
        }

    def _has_optional_user_columns_error(self, exc: Exception) -> bool:
        message = str(exc)
        return "membership_" in message or "stripe_" in message or "trial_" in message

    def _has_optional_trade_scope_error(self, exc: Exception) -> bool:
        return "user_id" in str(exc).lower()

    def _position_store_key(self, symbol: str, user_id: Optional[int] = None) -> str:
        scoped_user_id = self._stored_user_id(user_id)
        return f"{scoped_user_id}:{symbol}"

    def _stored_user_id(self, user_id: Optional[int]) -> int:
        if user_id is None:
            return GLOBAL_ACCOUNT_USER_ID
        return int(user_id)

    def _warn_missing_trade_scope(self):
        if self._trade_user_scope_warning_logged:
            return
        self._trade_user_scope_warning_logged = True
        self.logger.warning(
            "Trades table is missing the user_id scope. User-scoped trade history is cached locally only until the "
            "database schema is expanded."
        )

    def _warn_missing_position_scope(self):
        if self._position_user_scope_warning_logged:
            return
        self._position_user_scope_warning_logged = True
        self.logger.warning(
            "Positions table is missing the user_id scope. User-scoped open positions are cached locally only until "
            "the database schema is expanded."
        )

    def _extract_missing_schema_column(self, exc: Exception, table_name: str) -> Optional[str]:
        match = re.search(rf"Could not find the '([^']+)' column of '{re.escape(table_name)}'", str(exc))
        if not match:
            return None
        return match.group(1)

    def _warn_missing_trade_column(self, column: str):
        if column in self._trade_column_warning_logged:
            return
        self._trade_column_warning_logged.add(column)
        self.logger.warning(
            f"Trades table is missing optional column `{column}`. Persisted remaining trade fields only; `{column}` "
            "will stay cached locally until the database schema is expanded."
        )

    def _warn_missing_position_column(self, column: str):
        if column in self._position_column_warning_logged:
            return
        self._position_column_warning_logged.add(column)
        self.logger.warning(
            f"Positions table is missing optional column `{column}`. Persisted remaining position fields only; "
            f"`{column}` will stay cached locally until the database schema is expanded."
        )

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

    def _vault_associated_data(self, user_id: int, exchange: str) -> bytes:
        return f"{VAULT_VERSION}:{user_id}:{exchange}".encode("utf-8")

    def _extract_vault_record(self, config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not config:
            return None

        if config.get("encrypted_blob") and config.get("salt") and config.get("nonce"):
            return {
                "version": config.get("version", VAULT_VERSION),
                "exchange": config.get("exchange", "phemex"),
                "encrypted_blob": config["encrypted_blob"],
                "salt": config["salt"],
                "nonce": config["nonce"],
                "kdf": config.get("kdf", "pbkdf2-sha256"),
                "kdf_iterations": int(config.get("kdf_iterations") or PBKDF2_ITERATIONS),
            }

        metadata_raw = config.get("api_secret_enc")
        if not config.get("api_key_enc") or not metadata_raw:
            return None

        try:
            metadata = json.loads(metadata_raw)
        except (TypeError, ValueError):
            return None

        if not isinstance(metadata, dict) or metadata.get("version") != VAULT_VERSION:
            return None

        return {
            "version": metadata.get("version", VAULT_VERSION),
            "exchange": metadata.get("exchange", "phemex"),
            "encrypted_blob": config["api_key_enc"],
            "salt": metadata["salt"],
            "nonce": metadata["nonce"],
            "kdf": metadata.get("kdf", "pbkdf2-sha256"),
            "kdf_iterations": int(metadata.get("kdf_iterations") or PBKDF2_ITERATIONS),
        }

    def _warn_missing_strategy_config_column(self):
        if self._strategy_config_warning_logged:
            return
        self._strategy_config_warning_logged = True
        self.logger.warning(
            "user_configs is missing the strategy_config_json column. Strategy settings are cached locally only "
            "until the database schema is expanded."
        )

    def _decode_user_settings(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not config:
            return {}

        raw = config.get("strategy_config_json")
        if isinstance(raw, dict):
            parsed = dict(raw)
        elif raw:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                return {}
            parsed = dict(decoded) if isinstance(decoded, dict) else {}
        else:
            return {}

        if "strategy_profile" in parsed or "simulation_state" in parsed or "member_state" in parsed:
            return parsed
        return {"strategy_profile": parsed} if parsed else {}

    def _encode_user_settings(
        self,
        *,
        strategy_profile: Optional[Dict[str, Any]] = None,
        simulation_state: Optional[Dict[str, Any]] = None,
        member_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        payload: Dict[str, Any] = {}
        if strategy_profile:
            payload["strategy_profile"] = dict(strategy_profile)
        if simulation_state:
            payload["simulation_state"] = dict(simulation_state)
        if member_state:
            payload["member_state"] = dict(member_state)
        if not payload:
            return None
        return json.dumps(payload, separators=(",", ":"))

    def _upsert_user_config_fields(self, user_id: int, fields: Dict[str, Any]) -> bool:
        cached = dict(self._user_configs.get(user_id) or {})
        cached["user_id"] = user_id
        cached.update(fields)
        cached["updated_at"] = self._now()
        self._user_configs[user_id] = cached

        if not self.client:
            return True

        payload = {"user_id": user_id, "updated_at": cached["updated_at"], **fields}
        try:
            self.client.table("user_configs").upsert(payload, on_conflict="user_id").execute()
            return True
        except Exception as exc:
            if "strategy_config_json" in str(exc):
                self._warn_missing_strategy_config_column()
                return False
            self.logger.error(f"Failed to update user config for {user_id}: {exc}")
            return False

    def _pack_legacy_vault_columns(self, vault_record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "api_key_enc": vault_record["encrypted_blob"],
            "api_secret_enc": json.dumps(
                {
                    "version": vault_record["version"],
                    "exchange": vault_record["exchange"],
                    "salt": vault_record["salt"],
                    "nonce": vault_record["nonce"],
                    "kdf": vault_record["kdf"],
                    "kdf_iterations": vault_record["kdf_iterations"],
                },
                separators=(",", ":"),
            ),
        }

    def _fetch_user_config(self, user_id: int) -> Optional[Dict[str, Any]]:
        if user_id in self._user_configs:
            return self._user_configs[user_id]

        if not self.client:
            return None

        try:
            response = self.client.table("user_configs").select("*").eq("user_id", user_id).limit(1).execute()
            if not response.data:
                return None
            config = response.data[0]
            self._user_configs[user_id] = config
            return config
        except Exception as exc:
            self.logger.error(f"Failed to retrieve user API config: {exc}")
            return None

    def get_user_api_key_status(self, user_id: int) -> Dict[str, Any]:
        config = self._fetch_user_config(user_id)
        vault_record = self._extract_vault_record(config)
        if vault_record:
            return {
                "configured": True,
                "zero_knowledge": True,
                "exchange": vault_record.get("exchange", "phemex"),
                "requires_passphrase": True,
                "version": vault_record.get("version", VAULT_VERSION),
            }

        has_legacy = bool(config and config.get("api_key_enc") and config.get("api_secret_enc"))
        return {
            "configured": has_legacy,
            "zero_knowledge": False,
            "exchange": (config or {}).get("exchange", "phemex"),
            "requires_passphrase": False,
            "version": "legacy" if has_legacy else None,
        }

    def get_user_strategy_config(self, user_id: int) -> Optional[Dict[str, Any]]:
        config = self._fetch_user_config(user_id)
        if not config:
            return None
        settings = self._decode_user_settings(config)
        profile = settings.get("strategy_profile")
        return dict(profile) if isinstance(profile, dict) else None

    def get_user_simulation_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        config = self._fetch_user_config(user_id)
        if not config:
            return None
        settings = self._decode_user_settings(config)
        state = settings.get("simulation_state")
        return dict(state) if isinstance(state, dict) else None

    def get_user_member_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        config = self._fetch_user_config(user_id)
        if not config:
            return None
        settings = self._decode_user_settings(config)
        state = settings.get("member_state")
        return dict(state) if isinstance(state, dict) else None

    def list_user_ids_with_simulation_state(self) -> List[int]:
        results: set[int] = set()

        for user_id, config in self._user_configs.items():
            settings = self._decode_user_settings(config)
            if isinstance(settings.get("simulation_state"), dict):
                results.add(int(user_id))

        if not self.client:
            return sorted(results)

        try:
            response = self.client.table("user_configs").select("user_id, strategy_config_json").execute()
            for item in response.data or []:
                user_id = item.get("user_id")
                if user_id is None:
                    continue
                cached = dict(self._user_configs.get(int(user_id)) or {})
                cached.update(item)
                self._user_configs[int(user_id)] = cached
                settings = self._decode_user_settings(item)
                if isinstance(settings.get("simulation_state"), dict):
                    results.add(int(user_id))
        except Exception as exc:
            if "strategy_config_json" in str(exc):
                self._warn_missing_strategy_config_column()
            else:
                self.logger.error(f"Failed to list simulation state users: {exc}")

        return sorted(results)

    def store_user_strategy_config(self, user_id: int, strategy_config: Dict[str, Any]) -> bool:
        cached = dict(self._user_configs.get(user_id) or self._fetch_user_config(user_id) or {})
        settings = self._decode_user_settings(cached)
        encoded = self._encode_user_settings(
            strategy_profile=dict(strategy_config),
            simulation_state=settings.get("simulation_state") if isinstance(settings.get("simulation_state"), dict) else None,
            member_state=settings.get("member_state") if isinstance(settings.get("member_state"), dict) else None,
        )
        return self._upsert_user_config_fields(
            user_id,
            {"strategy_config_json": encoded} if encoded is not None else {},
        )

    def store_user_simulation_state(self, user_id: int, simulation_state: Dict[str, Any]) -> bool:
        cached = dict(self._user_configs.get(user_id) or self._fetch_user_config(user_id) or {})
        settings = self._decode_user_settings(cached)
        encoded = self._encode_user_settings(
            strategy_profile=settings.get("strategy_profile") if isinstance(settings.get("strategy_profile"), dict) else None,
            simulation_state=dict(simulation_state),
            member_state=settings.get("member_state") if isinstance(settings.get("member_state"), dict) else None,
        )
        return self._upsert_user_config_fields(
            user_id,
            {"strategy_config_json": encoded} if encoded is not None else {},
        )

    def store_user_member_state(self, user_id: int, member_state: Dict[str, Any]) -> bool:
        cached = dict(self._user_configs.get(user_id) or self._fetch_user_config(user_id) or {})
        settings = self._decode_user_settings(cached)
        encoded = self._encode_user_settings(
            strategy_profile=settings.get("strategy_profile") if isinstance(settings.get("strategy_profile"), dict) else None,
            simulation_state=settings.get("simulation_state") if isinstance(settings.get("simulation_state"), dict) else None,
            member_state=dict(member_state),
        )
        return self._upsert_user_config_fields(
            user_id,
            {"strategy_config_json": encoded} if encoded is not None else {},
        )

    def store_user_api_keys(
        self,
        user_id: int,
        api_key: str,
        api_secret: str,
        passphrase: str,
        exchange: str = "phemex",
    ) -> bool:
        vault_record = self.vault.encrypt_credentials(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            exchange=exchange,
            associated_data=self._vault_associated_data(user_id, exchange),
        )
        payload = {
            "user_id": user_id,
            **vault_record,
            "updated_at": self._now(),
        }

        self._user_configs[user_id] = {**dict(self._user_configs.get(user_id) or {}), **payload}
        if not self.client:
            return True

        try:
            self.client.table("user_configs").upsert(payload, on_conflict="user_id").execute()
            return True
        except Exception as exc:
            message = str(exc)
            if any(column in message for column in ("encrypted_blob", "salt", "nonce", "kdf_", "exchange", "version")):
                fallback_payload = {
                    "user_id": user_id,
                    **self._pack_legacy_vault_columns(vault_record),
                    "updated_at": self._now(),
                }
                try:
                    self.client.table("user_configs").upsert(fallback_payload, on_conflict="user_id").execute()
                    self._user_configs[user_id] = {
                        **dict(self._user_configs.get(user_id) or {}),
                        **payload,
                        **fallback_payload,
                    }
                    self.logger.warning(
                        "user_configs is missing dedicated vault columns. Stored zero-knowledge vault in legacy columns."
                    )
                    return True
                except Exception as fallback_exc:
                    self.logger.error(f"Failed to store user API vault in fallback columns: {fallback_exc}")
                    return False
            self.logger.error(f"Failed to store user API keys: {exc}")
            return False

    def get_user_api_keys(
        self,
        user_id: int,
        *,
        passphrase: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        config = self._fetch_user_config(user_id)
        if not config:
            return None

        vault_record = self._extract_vault_record(config)
        if vault_record:
            target_exchange = exchange or vault_record.get("exchange", "phemex")
            if not passphrase:
                self.logger.warning(
                    f"User {user_id} API vault is locked. A passphrase is required to decrypt zero-knowledge credentials."
                )
                return None
            try:
                return self.vault.decrypt_credentials(
                    vault_record,
                    passphrase=passphrase,
                    associated_data=self._vault_associated_data(user_id, target_exchange),
                )
            except InvalidPassphraseError:
                self.logger.warning(f"Invalid passphrase for user {user_id} API vault.")
                return None
            except Exception as exc:
                self.logger.error(f"Failed to decrypt user {user_id} API vault: {exc}")
                return None

        try:
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
            return self._apply_complimentary_override(user, persist=True)

        payload = self._user_payload(telegram_id, username, first_name)
        self._users[telegram_id] = payload

        if not self.client:
            return self._apply_complimentary_override(payload, persist=False)

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
                return self._apply_complimentary_override(user, persist=True)

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
            return self._apply_complimentary_override(payload, persist=True)
        except Exception as exc:
            self.logger.error(f"Failed to get or create user: {exc}")
            return self._apply_complimentary_override(self._users.get(telegram_id), persist=False)

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
        is_verified = bool(user.get("is_verified"))
        if self._is_complimentary_pro(telegram_id):
            status = "active"
            is_verified = True

        paid_access = (is_verified or tier == TRIAL_PRO_MEMBERSHIP) and tier in {TRIAL_PRO_MEMBERSHIP, PRO_MEMBERSHIP} and status in {"trial_pro", "active"}
        return {
            "tier": tier,
            "status": status,
            "expires_at": user.get("membership_expires_at"),
            "can_backtest": True,
            "can_simulation": paid_access,
            "can_live": paid_access,
            "is_verified": is_verified,
            "source": "complimentary" if self._is_complimentary_pro(telegram_id) else user.get("membership_source", "manual"),
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

    def start_trial_membership(
        self,
        telegram_id: int,
        *,
        days: int = DEFAULT_TRIAL_DAYS,
        username: str = "",
        first_name: str = "",
    ) -> Optional[Dict[str, Any]]:
        user = self.get_or_create_user(telegram_id, username, first_name)
        if not user:
            return None

        if user.get("trial_started_at"):
            return self._normalize_user_record(user)

        expires_at = self._trial_expiry(days)
        update_payload = {
            "membership_tier": TRIAL_PRO_MEMBERSHIP,
            "membership_expires_at": expires_at,
            "trial_started_at": self._now(),
            "updated_at": self._now(),
        }
        user.update(update_payload)
        self._normalize_user_record(user)

        if not self.client:
            return user

        self._persist_user_update(telegram_id, update_payload)
        return user

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
        elif normalized_tier == TRIAL_PRO_MEMBERSHIP and not expires_at:
            expires_at = self._trial_expiry()
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
            return self._apply_complimentary_override(self._users.get(telegram_id), persist=True)

        if not self.client:
            return None

        try:
            response = self.client.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
            if not response.data:
                return None
            user = self._normalize_user_record(response.data[0])
            self._users[telegram_id] = user
            return self._apply_complimentary_override(user, persist=True)
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

    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return None

        for user in self._users.values():
            if str(user.get("email") or "").strip().lower() == normalized_email:
                return self._normalize_user_record(user)

        if not self.client:
            return None

        try:
            response = self.client.table("users").select("*").eq("email", normalized_email).limit(1).execute()
            if not response.data:
                return None
            user = self._normalize_user_record(response.data[0])
            self._users[user["telegram_id"]] = user
            return user
        except Exception as exc:
            self.logger.error(f"Failed to find user by email {normalized_email}: {exc}")
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

        if subscription_id and user.get("stripe_subscription_id") == subscription_id and user.get("stripe_subscription_status") == "active":
            # Idempotent handling: already active with same subscription.
            self.logger.info(f"Skipping duplicate subscription activation for user {telegram_id} subscription {subscription_id}.")
            return user

        if period_end and self._parse_datetime(period_end) is None:
            raise ValueError("period_end must be an ISO datetime string")

        normalized_subscription_status = str(subscription_status or "").strip().lower() or "active"
        membership_tier = TRIAL_PRO_MEMBERSHIP if normalized_subscription_status == "trialing" else PRO_MEMBERSHIP
        effective_period_end = period_end
        if membership_tier == TRIAL_PRO_MEMBERSHIP and not effective_period_end:
            effective_period_end = self._trial_expiry()

        update_payload = {
            "membership_tier": membership_tier,
            "membership_expires_at": effective_period_end,
            "stripe_subscription_status": normalized_subscription_status,
            "updated_at": self._now(),
        }
        if membership_tier == TRIAL_PRO_MEMBERSHIP and not user.get("trial_started_at"):
            update_payload["trial_started_at"] = self._now()
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

    def set_user_agreement(self, telegram_id: int, has_agreed: bool = True) -> bool:
        user = self.get_or_create_user(telegram_id, "", "")
        if not user:
            return False

        normalized = bool(has_agreed)
        user["has_agreed"] = normalized
        update_payload = {
            "has_agreed": normalized,
            "updated_at": self._now(),
        }

        if not self.client:
            return True

        try:
            self.client.table("users").update(update_payload).eq("telegram_id", telegram_id).execute()
            return True
        except Exception as exc:
            if self._has_optional_user_columns_error(exc):
                self.logger.warning(
                    "Users table is missing has_agreed column. Agreement state stored locally only."
                )
                return True
            self.logger.error(f"Failed to update user agreement for {telegram_id}: {exc}")
            return False

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

    def log_trade(self, trade_data: Dict[str, Any], user_id: Optional[int] = None) -> bool:
        scoped_user_id = self._stored_user_id(user_id)
        payload = {"created_at": self._now(), **trade_data}
        payload.setdefault("user_id", scoped_user_id)
        self._trades.append(payload)

        if not self.client:
            return True

        try:
            db_payload = dict(payload)
            db_payload.pop("timestamp", None)
            while True:
                retry_payload = {
                    key: value for key, value in db_payload.items() if key not in self._unsupported_trade_columns
                }
                try:
                    self.client.table("trades").insert(retry_payload).execute()
                    return True
                except Exception as exc:
                    if self._has_optional_trade_scope_error(exc):
                        self._warn_missing_trade_scope()
                        return False
                    missing_column = self._extract_missing_schema_column(exc, "trades")
                    if missing_column and missing_column in retry_payload:
                        self._unsupported_trade_columns.add(missing_column)
                        self._warn_missing_trade_column(missing_column)
                        continue
                    self.logger.error(f"Failed to log trade: {exc}")
                    return False
        except Exception as exc:
            self.logger.error(f"Failed to log trade: {exc}")
            return False

    def update_position(self, symbol: str, position_data: Dict[str, Any], user_id: Optional[int] = None) -> bool:
        scoped_user_id = self._stored_user_id(user_id)
        payload = {**position_data, "symbol": symbol, "updated_at": self._now()}
        payload.setdefault("user_id", scoped_user_id)
        self._positions[self._position_store_key(symbol, scoped_user_id)] = payload

        if not self.client:
            return True

        try:
            while True:
                retry_payload = {
                    key: value for key, value in payload.items() if key not in self._unsupported_position_columns
                }
                try:
                    self.client.table("positions").upsert(retry_payload, on_conflict="user_id,symbol").execute()
                    return True
                except Exception as exc:
                    if self._has_optional_trade_scope_error(exc):
                        self._warn_missing_position_scope()
                        return False
                    missing_column = self._extract_missing_schema_column(exc, "positions")
                    if missing_column and missing_column in retry_payload:
                        self._unsupported_position_columns.add(missing_column)
                        self._warn_missing_position_column(missing_column)
                        continue
                    self.logger.error(f"Failed to update position for {symbol}: {exc}")
                    return False
        except Exception as exc:
            self.logger.error(f"Failed to update position for {symbol}: {exc}")
            return False

    def remove_position(self, symbol: str, user_id: Optional[int] = None) -> bool:
        scoped_user_id = self._stored_user_id(user_id)
        self._positions.pop(self._position_store_key(symbol, scoped_user_id), None)

        if not self.client:
            return True

        try:
            self.client.table("positions").delete().eq("symbol", symbol).eq("user_id", scoped_user_id).execute()
            return True
        except Exception as exc:
            if self._has_optional_trade_scope_error(exc):
                self._warn_missing_position_scope()
                return False
            self.logger.error(f"Failed to remove position for {symbol}: {exc}")
            return False

    def list_open_positions(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.client:
            try:
                query = self.client.table("positions").select("*")
                if user_id is not None:
                    query = query.eq("user_id", self._stored_user_id(user_id))
                response = query.execute()
                self._positions = {
                    self._position_store_key(item["symbol"], item.get("user_id")): item
                    for item in (response.data or [])
                    if item.get("symbol")
                }
            except Exception as exc:
                if user_id is not None and self._has_optional_trade_scope_error(exc):
                    self._warn_missing_position_scope()
                else:
                    self.logger.error(f"Failed to list open positions: {exc}")
        if user_id is not None:
            scoped_user_id = self._stored_user_id(user_id)
            return [position for position in self._positions.values() if position.get("user_id") == scoped_user_id]
        return list(self._positions.values())

    def get_recent_trades(
        self,
        limit: int = 50,
        since: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        since_dt = self._parse_datetime(since)

        if self.client:
            try:
                query = self.client.table("trades").select("*")
                if since:
                    query = query.gte("created_at", since)
                if user_id is not None:
                    query = query.eq("user_id", self._stored_user_id(user_id))
                response = query.order("created_at", desc=True).limit(limit).execute()
                self._trades = list(response.data or [])
                return list(self._trades)
            except Exception as exc:
                if user_id is not None and self._has_optional_trade_scope_error(exc):
                    self._warn_missing_trade_scope()
                else:
                    self.logger.error(f"Failed to fetch recent trades: {exc}")

        filtered = list(self._trades)
        if user_id is not None:
            scoped_user_id = self._stored_user_id(user_id)
            filtered = [trade for trade in filtered if trade.get("user_id") == scoped_user_id]

        if since_dt:
            filtered = [
                trade
                for trade in filtered
                if (trade_dt := self._parse_datetime(trade.get("created_at"))) and trade_dt >= since_dt
            ]
            return filtered[-limit:]

        return filtered[-limit:]

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
                        "membership_tier, membership_expires_at, trial_started_at, created_at, updated_at"
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

        recent_users = [self._apply_complimentary_override(dict(user), persist=False) for user in recent_users]
        free_users = sum(1 for user in recent_users if user.get("membership_tier") == FREE_MEMBERSHIP)
        trial_users = sum(1 for user in recent_users if user.get("membership_tier") == TRIAL_PRO_MEMBERSHIP)
        pro_users = sum(1 for user in recent_users if user.get("membership_tier") == PRO_MEMBERSHIP)
        expired_users = sum(1 for user in recent_users if user.get("membership_status") in {"expired", "trial_expired"})

        return {
            "total": total_users,
            "verified": verified_users,
            "unverified": max(total_users - verified_users, 0),
            "with_api_keys": api_key_users,
            "free": free_users,
            "trial_pro": trial_users,
            "pro": pro_users,
            "expired": expired_users,
            "recent": recent_users[:limit],
        }
