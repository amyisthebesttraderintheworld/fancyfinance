from __future__ import annotations

import asyncio
import inspect
import queue
import re
from datetime import datetime, time, timezone
from urllib.parse import quote

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from common import SettingsManager, get_logger
from dashboard_access import DEFAULT_TOKEN_TTL_SECONDS, generate_member_dashboard_token
from email_service import EmailService
from fancyfinance import APP_NAME, __version__
from backtest_service import (
    ALLOWED_REMOTE_CANDLE_COUNTS,
    BacktestServiceError,
    format_backtest_summary,
    run_backtest_recent,
)
from stripe_service import StripeService
from supabase_client import DEFAULT_TRIAL_DAYS, FREE_MEMBERSHIP, PRO_MEMBERSHIP, TRIAL_PRO_MEMBERSHIP, SupabaseManager

cmd_queue = None
config = None
db = SupabaseManager()
settings_mgr = SettingsManager()
logger = get_logger("TelegramBot")
_conflict_logged = False


async def _maybe_await(result):
    if inspect.isawaitable(result):
        await result


async def _reply(target, text: str, **kwargs):
    if getattr(target, "message", None) and hasattr(target.message, "reply_text"):
        await _maybe_await(target.message.reply_text(text, **kwargs))
        return
    if getattr(target, "effective_chat", None) and hasattr(target.effective_chat, "send_message"):
        await _maybe_await(target.effective_chat.send_message(text, **kwargs))
        return
    if hasattr(target, "edit_message_text"):
        await _maybe_await(target.edit_message_text(text, **kwargs))


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_main_menu():
    keyboard = [
        [
            KeyboardButton("📊 Status"),
            KeyboardButton("⚙️ Settings"),
        ],
        [
            KeyboardButton("⏸ Pause"),
            KeyboardButton("▶️ Resume"),
        ],
        [
            KeyboardButton("🆘 Emergency Stop"),
            KeyboardButton("🛑 Shutdown"),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def get_agreement_keyboard():
    keyboard = [
        [KeyboardButton("✅ I Agree"), KeyboardButton("❌ I Disagree")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def _welcome_menu_text() -> str:
    return (
        f"🤖 *{APP_NAME} v{__version__}*\n\n"
        "Trading Bot Connected. Use /help for commands.\n\n"
        "Use the buttons below to control the engine or type a command directly."
    )


def _record_user_agreement(user_id) -> bool:
    return settings_mgr.set(
        f"user_agreed_{user_id}",
        True,
        "Boolean",
        "User agreement to Terms & Conditions",
    )


MENU_BUTTON_COMMANDS = {
    "📊 Status": "/status",
    "⚙️ Settings": "/settings",
    "⏸ Pause": "/pause",
    "▶️ Resume": "/resume",
    "🆘 Emergency Stop": "/emergency_stop",
    "🛑 Shutdown": "/shutdown",
}


def _admin_ids() -> list[int]:
    telegram_cfg = (config or {}).get("telegram", {})
    return telegram_cfg.get("admin_chat_ids", [])


def _is_admin_chat(chat_id: int) -> bool:
    return chat_id in _admin_ids()


def _format_membership(summary: dict | None) -> tuple[str, str, str]:
    if not summary:
        return "Free", "Free access", "Backtesting only"

    if summary.get("tier") == TRIAL_PRO_MEMBERSHIP:
        tier = "Trial Pro"
    elif summary.get("tier") == PRO_MEMBERSHIP:
        tier = "Pro"
    else:
        tier = "Free"
    status = summary.get("status", "free")
    expires_at = summary.get("expires_at")
    source = summary.get("source")

    if summary.get("tier") == PRO_MEMBERSHIP and status == "active" and source == "complimentary":
        status_label = "Complimentary ✅"
    elif summary.get("tier") == TRIAL_PRO_MEMBERSHIP and status == "trial_pro":
        status_label = f"Trial Pro ⏳ ({expires_at or '7 days'})"
    elif summary.get("tier") == TRIAL_PRO_MEMBERSHIP and status == "trial_expired":
        status_label = f"Trial expired ❌ ({expires_at or 'upgrade required'})"
    elif summary.get("tier") == PRO_MEMBERSHIP and status == "active":
        status_label = "Active ✅"
    elif summary.get("tier") == PRO_MEMBERSHIP and status == "expired":
        status_label = f"Expired ❌ ({expires_at or 'renew required'})"
    else:
        status_label = "Free access"

    access = ["Backtesting"]
    if summary.get("can_simulation"):
        access.append("Simulation")
    if summary.get("can_live"):
        access.append("Live")
    return tier, status_label, ", ".join(access)


def _display_price() -> str:
    return ((config or {}).get("stripe") or {}).get("display_price") or "$6.99/month"


def _trial_days() -> int:
    raw = ((config or {}).get("stripe") or {}).get("trial_days", DEFAULT_TRIAL_DAYS)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return DEFAULT_TRIAL_DAYS


def _dashboard_base_url() -> str:
    api_cfg = (config or {}).get("api") or {}
    base_url = str(api_cfg.get("base_url") or "").strip().rstrip("/")
    if base_url:
        return base_url

    stripe_cfg = (config or {}).get("stripe") or {}
    portal_return_url = str(stripe_cfg.get("portal_return_url") or "").strip()
    if "/dashboard" in portal_return_url:
        return portal_return_url.split("/dashboard", 1)[0].rstrip("/")
    return ""


def _default_backtest_candles() -> int:
    return min(ALLOWED_REMOTE_CANDLE_COUNTS)


def _looks_like_timeframe(raw: str) -> bool:
    return bool(re.fullmatch(r"\d+[mhd]", str(raw or "").strip().lower()))


def _backtest_usage_text(default_symbol: str, default_timeframe: str) -> str:
    allowed = " or ".join(str(value) for value in sorted(ALLOWED_REMOTE_CANDLE_COUNTS))
    return (
        "📈 *Free Backtesting*\n\n"
        "Use: `/backtest <symbol> [timeframe] [500|1000]`\n\n"
        f"Examples:\n"
        f"• `/backtest {default_symbol}`\n"
        f"• `/backtest {default_symbol} {default_timeframe}`\n"
        f"• `/backtest {default_symbol} {default_timeframe} {_default_backtest_candles()}`\n\n"
        f"Phemex can only return the latest *{allowed} candles* per backtest run. "
        "Run `/start_trial` or `/subscribe` if you want simulation or live access."
    )


def _paid_upgrade_message(summary: dict | None) -> str:
    tier, status_label, _ = _format_membership(summary)
    display_price = _display_price()
    trial_days = _trial_days()
    trial_note = f"Start with a {trial_days}-day Trial Pro period, then continue at {display_price}." if trial_days > 0 else f"Continue on the paid plan at {display_price}."
    return (
        "🔒 *Paid Membership Required*\n\n"
        f"Simulation and live trading are only available on the paid plan.\n{trial_note}\n\n"
        f"*Current plan:* {tier}\n"
        f"*Membership status:* {status_label}\n\n"
        "Backtesting remains free. Use `/subscribe` to start the upgrade flow."
    )


def _parse_membership_expiry(raw_value: str) -> str | None:
    raw_value = str(raw_value).strip()
    if not raw_value:
        return None

    try:
        if len(raw_value) == 10:
            date_value = datetime.strptime(raw_value, "%Y-%m-%d").date()
            return datetime.combine(date_value, time(23, 59, 59), tzinfo=timezone.utc).isoformat()

        parsed = datetime.fromisoformat(raw_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return None


def _stripe_service() -> StripeService:
    return StripeService(config or {})


async def _send_welcome_menu(target):
    await _reply(target, _welcome_menu_text(), parse_mode="Markdown", reply_markup=get_main_menu())


async def _send_welcome_menu_to_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await _maybe_await(
        context.bot.send_message(
            chat_id=chat_id,
            text=_welcome_menu_text(),
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
    )


async def _delete_sensitive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        logger.warning(f"Failed to delete sensitive Telegram message: {exc}")


async def agree_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if not _record_user_agreement(user.id):
        await _reply(
            update,
            "❌ Could not save your agreement. Please try /agree again.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await _reply(update, "✅ Agreement recorded.", reply_markup=ReplyKeyboardRemove())
    await _send_welcome_menu(update)
    logger.info(f"User {user.id} accepted the risk disclosure via message command.")


async def disagree_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(
        update,
        "No problem. Use /start whenever you want to review the disclosure again.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = getattr(update, "message", None)
    text = getattr(message, "text", "")
    command = MENU_BUTTON_COMMANDS.get(text)
    if not command:
        return

    logger.info(f"Telegram menu button received: {text}")

    if command == "/settings":
        await settings_command(update, context)
        return

    update.message.text = command
    await proxy_command(update, context)


async def setup_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    membership = db.get_membership_summary(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if not membership or not membership.get("can_live"):
        await _reply(update, _paid_upgrade_message(membership), parse_mode="Markdown")
        return

    if not context.args or len(context.args) < 3:
        await _reply(
            update,
            "🔒 *Zero-Knowledge API Vault*\n\nUse: `/setup_api <api_key> <api_secret> <passphrase>`\n\n"
            "Your passphrase is *never stored*. Without it, the database record is useless.\n\n"
            "⚠️ Your message will be deleted after processing.",
            parse_mode="Markdown",
        )
        return

    api_key, api_secret = context.args[:2]
    passphrase = " ".join(context.args[2:]).strip()
    user_id = update.effective_user.id

    if len(passphrase) < 10:
        await _reply(
            update,
            "❌ Please use a stronger vault passphrase with at least 10 characters.",
            parse_mode="Markdown",
        )
        return

    if db.store_user_api_keys(user_id, api_key, api_secret, passphrase, exchange=config.get("exchange", "phemex")):
        await _reply(
            update,
            "✅ *API keys stored in the zero-knowledge vault.*\n\n"
            "Use `/unlock_api <passphrase>` when you want to load them into the current bot session.",
            parse_mode="Markdown",
        )
    else:
        await _reply(update, "❌ Failed to secure keys. Is Supabase configured?", parse_mode="Markdown")

    await _delete_sensitive_message(update, context)


async def unlock_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    membership = db.get_membership_summary(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if not membership or not membership.get("can_live"):
        await _reply(update, _paid_upgrade_message(membership), parse_mode="Markdown")
        return

    if not context.args:
        await _reply(
            update,
            "🔓 Use: `/unlock_api <passphrase>`",
            parse_mode="Markdown",
        )
        return

    passphrase = " ".join(context.args).strip()
    if not passphrase:
        await _reply(update, "❌ Passphrase is required.", parse_mode="Markdown")
        return

    if not cmd_queue:
        await _reply(update, "Engine not connected.")
        await _delete_sensitive_message(update, context)
        return

    cmd_queue.put(("/unlock_api", [str(update.effective_user.id), passphrase], update.effective_chat.id))
    await _reply(update, "🔓 Unlock request queued. The passphrase will only be used for this session.", parse_mode="Markdown")
    await _delete_sensitive_message(update, context)


async def verify_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply(update, "📧 Use: `/verify_email yourname@example.com`", parse_mode="Markdown")
        return

    email = context.args[0].lower()
    otp = db.request_email_verification(update.effective_user.id, email)
    if otp:
        email_service = EmailService(config or {})
        sent = await asyncio.to_thread(
            email_service.send_verification_email,
            email=email,
            otp=otp,
            telegram_id=update.effective_user.id,
            username=update.effective_user.username or "",
            first_name=update.effective_user.first_name or "",
        )
        if sent:
            await _reply(
                update,
                f"📨 *Verification Email Sent to {email}*\n\n"
                "Use `/confirm_email 123456` after you receive the code.",
                parse_mode="Markdown",
            )
            return

        await _reply(
            update,
            "❌ Email delivery is not configured or the webhook failed.\n\n"
            "Ask the admin to set `EMAIL_CONFIRM_WEBHOOK_URL` in Railway.",
            parse_mode="Markdown",
        )
    else:
        await _reply(update, "❌ Failed to initiate email verification.", parse_mode="Markdown")


async def confirm_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply(update, "🔑 Use: `/confirm_email 123456`", parse_mode="Markdown")
        return

    if db.confirm_email_verification(update.effective_user.id, context.args[0]):
        membership = db.get_membership_summary(
            update.effective_user.id,
            update.effective_user.username or "",
            update.effective_user.first_name or "",
        )
        if membership and membership.get("can_live"):
            message = "✅ *Email verified!*\n\nYour account is now eligible for live mode once API keys are stored."
        else:
            message = (
                "✅ *Email verified!*\n\n"
                "Your account is verified, but simulation and live mode still require a paid membership."
            )
        await _reply(update, message, parse_mode="Markdown")
    else:
        await _reply(update, "❌ Invalid or expired verification code.", parse_mode="Markdown")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_or_create_user(user_id, update.effective_user.username or "", update.effective_user.first_name or "")
    if not user:
        await _reply(update, "❌ Could not retrieve profile.")
        return

    status = "Verified ✅" if user.get("is_verified") else "Unverified ❌"
    email = user.get("email") or "Not linked"
    membership = db.get_membership_summary(
        user_id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    vault = db.get_user_api_key_status(user_id)
    plan_name, membership_status, access = _format_membership(membership)
    vault_label = "Zero-knowledge vault configured" if vault.get("zero_knowledge") else (
        "Legacy encrypted storage configured" if vault.get("configured") else "Not configured"
    )
    message = (
        f"👤 *{APP_NAME} Profile*\n\n"
        f"• *Telegram ID:* `{user_id}`\n"
        f"• *Email:* `{email}`\n"
        f"• *Status:* {status}\n\n"
        f"• *Plan:* {plan_name}\n"
        f"• *Membership:* {membership_status}\n"
        f"• *Access:* {access}\n"
        f"• *Vault:* {vault_label}\n\n"
        "Use `/verify_email` to update your email, `/plans` to compare tiers, or `/setup_api` once paid access is active."
    )
    await _reply(update, message, parse_mode="Markdown")


async def signup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    created = db.get_or_create_user(user.id, user.username or "", user.first_name or "")
    if created:
        await _reply(
            update,
            f"✅ *Signup successful!* Welcome to {APP_NAME}, {user.first_name}.\n\n"
            "Next steps:\n"
            "1. Accept the risk disclosure with `/start`\n"
            "2. Verify your email with `/verify_email`\n"
            "3. Use `/start_trial` or `/plans` if you want simulation or live access",
            parse_mode="Markdown",
        )
        return

    await _reply(update, "❌ Signup failed. Please ensure Supabase is configured.")


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    membership = db.get_membership_summary(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    plan_name, membership_status, access = _format_membership(membership)
    display_price = _display_price()
    trial_days = _trial_days()
    trial_line = f"• {trial_days}-day Trial Pro before billing starts\n" if trial_days > 0 else ""
    text = (
        f"💳 *{APP_NAME} Plans*\n\n"
        "*Free*\n"
        "• Backtesting access\n"
        "• Telegram onboarding\n"
        "• Email verification\n\n"
        f"*Pro ({display_price})*\n"
        f"{trial_line}"
        "• Simulation mode\n"
        "• Live trading mode\n"
        "• Secure API key storage\n"
        "• Dashboard and control access\n\n"
        f"*Your current plan:* {plan_name}\n"
        f"*Membership status:* {membership_status}\n"
        f"*Current access:* {access}\n\n"
        "Use `/backtest BTCUSD 1m 500` to run a free backtest, "
        "`/start_trial` to unlock Trial Pro instantly, or `/manage_subscription` if you already have a paid plan."
    )
    await _reply(update, text, parse_mode="Markdown")


async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plans_command(update, context)


async def start_trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    membership = db.get_membership_summary(
        user_id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if membership and membership.get("source") == "complimentary":
        await _reply(update, "✅ Your account already has complimentary Pro access.", parse_mode="Markdown")
        return
    if membership and membership.get("tier") in {TRIAL_PRO_MEMBERSHIP, PRO_MEMBERSHIP} and membership.get("status") in {"trial_pro", "active"}:
        plan_name, membership_status, access = _format_membership(membership)
        await _reply(
            update,
            f"✅ You already have *{plan_name}* access.\n\n*Membership:* {membership_status}\n*Access:* {access}",
            parse_mode="Markdown",
        )
        return

    user = db.get_or_create_user(
        user_id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if user and user.get("trial_started_at"):
        await _reply(
            update,
            "⏳ Your 7-day Trial Pro has already been used.\n\nUse `/subscribe` to continue with full Pro access.",
            parse_mode="Markdown",
        )
        return

    trial_user = db.start_trial_membership(
        user_id,
        days=_trial_days(),
        username=update.effective_user.username or "",
        first_name=update.effective_user.first_name or "",
    )
    if not trial_user:
        await _reply(update, "❌ Could not start your trial right now.", parse_mode="Markdown")
        return

    membership = db.get_membership_summary(
        user_id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    plan_name, membership_status, access = _format_membership(membership)
    await _reply(
        update,
        f"🚀 *{plan_name} unlocked*\n\n"
        f"*Membership:* {membership_status}\n"
        f"*Access:* {access}\n\n"
        "Next steps:\n"
        "1. Use `/dashboard_api` to open your member dashboard\n"
        "2. Verify your email with `/verify_email`\n"
        "3. Store your exchange keys with `/setup_api <api_key> <api_secret> <passphrase>`",
        parse_mode="Markdown",
    )


async def dashboard_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    membership = db.get_membership_summary(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if not membership or not membership.get("can_simulation"):
        await _reply(update, _paid_upgrade_message(membership), parse_mode="Markdown")
        return

    auth_token = str(((config or {}).get("api") or {}).get("auth_token") or "").strip()
    if not auth_token:
        await _reply(
            update,
            "❌ Dashboard access is not configured yet. Ask the admin to set `FANCYFINANCE_API_TOKEN` in Railway.",
            parse_mode="Markdown",
        )
        return

    token = generate_member_dashboard_token(
        auth_token,
        update.effective_user.id,
        ttl_seconds=DEFAULT_TOKEN_TTL_SECONDS,
    )
    base_url = _dashboard_base_url()

    if base_url:
        dashboard_url = f"{base_url}/dashboard/member?access={quote(token)}"
        message = (
            "🧭 *Member Dashboard Access*\n\n"
            "This command mints a fresh read-only dashboard token each time you run it.\n\n"
            f"{dashboard_url}\n\n"
            "If the link expires, run `/dashboard_api` again to rotate it."
        )
    else:
        message = (
            "🧭 *Member Dashboard API Token*\n\n"
            "Use this read-only dashboard token in the website dashboard client:\n\n"
            f"`{token}`\n\n"
            "Run `/dashboard_api` again any time you need a fresh token."
        )

    await _reply(update, message, parse_mode="Markdown")


async def rotate_dashboard_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await dashboard_api_command(update, context)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stripe_service = _stripe_service()
    display_price = _display_price()
    trial_days = _trial_days()
    if not stripe_service.is_checkout_configured():
        await _reply(
            update,
            "❌ Stripe checkout is not configured yet. Ask the admin to set the Stripe Railway variables.",
            parse_mode="Markdown",
        )
        return

    user = db.get_or_create_user(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if not user:
        await _reply(update, "❌ Could not load your user profile.")
        return

    membership = db.get_membership_summary(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if (
        membership
        and membership.get("source") == "stripe"
        and membership.get("tier") in {TRIAL_PRO_MEMBERSHIP, PRO_MEMBERSHIP}
        and membership.get("status") in {"trial_pro", "active"}
    ):
        await _reply(
            update,
            "🧾 You already have Trial Pro or Pro access through Stripe. Use `/manage_subscription` to manage billing.",
            parse_mode="Markdown",
        )
        return

    try:
        session = await asyncio.to_thread(stripe_service.create_checkout_session, user)
    except Exception as exc:
        logger.error(f"Failed to create Stripe checkout session: {exc}")
        await _reply(
            update,
            "❌ Could not create a payment session right now. Please try again shortly.",
            parse_mode="Markdown",
        )
        return

    checkout_url = session.get("url")
    if not checkout_url:
        await _reply(update, "❌ Stripe did not return a checkout URL.")
        return

    subscribe_parts = [f"💳 *Upgrade to Pro ({display_price})*\n\n"]
    if trial_days > 0:
        subscribe_parts.append(
            f"Your checkout starts with a *{trial_days}-day Trial Pro* period before billing begins.\n\n"
        )
    subscribe_parts.extend(
        [
            "Use the secure Stripe checkout link below to activate your membership:\n",
            f"{checkout_url}\n\n",
            "After checkout succeeds, your Trial Pro or Pro access should activate automatically.",
        ]
    )
    subscribe_message = "".join(subscribe_parts)

    await _reply(
        update,
        subscribe_message,
        parse_mode="Markdown",
    )


async def manage_subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_or_create_user(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )
    if not user:
        await _reply(update, "❌ Could not load your user profile.")
        return

    stripe_customer_id = user.get("stripe_customer_id")
    if not stripe_customer_id:
        await _reply(
            update,
            "You do not have a Stripe customer record yet. Use `/subscribe` first.",
            parse_mode="Markdown",
        )
        return

    stripe_service = _stripe_service()
    if not stripe_service.is_portal_configured():
        await _reply(
            update,
            "❌ Stripe billing portal is not configured yet. Ask the admin to set the Stripe return URL.",
            parse_mode="Markdown",
        )
        return

    try:
        session = await asyncio.to_thread(
            stripe_service.create_customer_portal_session,
            customer_id=stripe_customer_id,
        )
    except Exception as exc:
        logger.error(f"Failed to create Stripe portal session: {exc}")
        await _reply(update, "❌ Could not open the billing portal right now.", parse_mode="Markdown")
        return

    portal_url = session.get("url")
    if not portal_url:
        await _reply(update, "❌ Stripe did not return a billing portal URL.")
        return

    await _reply(
        update,
        f"🧾 *Manage Subscription*\n\nOpen your Stripe billing portal here:\n{portal_url}",
        parse_mode="Markdown",
    )


async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_or_create_user(user.id, user.username or "", user.first_name or "")

    args = context.args or []
    exchange_key = (config or {}).get("exchange", "phemex")
    exchange_config = (config or {}).get(exchange_key, {})
    default_symbol = (exchange_config.get("symbols") or ["BTCUSD"])[0]
    default_timeframe = ((config or {}).get("strategy") or {}).get("timeframe", "1m")
    default_candles = _default_backtest_candles()

    if not args or len(args) > 3:
        await _reply(update, _backtest_usage_text(default_symbol, default_timeframe), parse_mode="Markdown")
        return

    symbol = str(args[0]).strip().upper()
    timeframe = default_timeframe
    candles = default_candles
    seen_timeframe = False
    seen_candles = False

    for raw_arg in args[1:]:
        value = str(raw_arg).strip()
        if _looks_like_timeframe(value):
            if seen_timeframe:
                await _reply(update, _backtest_usage_text(default_symbol, default_timeframe), parse_mode="Markdown")
                return
            timeframe = value.lower()
            seen_timeframe = True
            continue

        if value.isdigit():
            if seen_candles:
                await _reply(update, _backtest_usage_text(default_symbol, default_timeframe), parse_mode="Markdown")
                return
            candles = int(value)
            seen_candles = True
            continue

        await _reply(update, _backtest_usage_text(default_symbol, default_timeframe), parse_mode="Markdown")
        return

    if candles not in ALLOWED_REMOTE_CANDLE_COUNTS:
        await _reply(
            update,
            f"❌ Phemex backtests only support `{sorted(ALLOWED_REMOTE_CANDLE_COUNTS)}` candles per run.\n\n"
            + _backtest_usage_text(default_symbol, default_timeframe),
            parse_mode="Markdown",
        )
        return

    await _reply(
        update,
        f"⏳ Running your free backtest for `{symbol}` on `{timeframe}` using the latest `{candles}` candles...",
        parse_mode="Markdown",
    )

    try:
        result = await asyncio.to_thread(
            run_backtest_recent,
            config or {},
            symbol,
            timeframe,
            candles,
        )
    except BacktestServiceError as exc:
        await _reply(update, f"❌ {exc}", parse_mode="Markdown")
        return
    except Exception as exc:
        logger.error(f"Unexpected backtest failure for {symbol}: {exc}")
        await _reply(
            update,
            "❌ Backtest failed unexpectedly. Please try again shortly.",
            parse_mode="Markdown",
        )
        return

    await _reply(update, format_backtest_summary(result), parse_mode="Markdown")


async def grant_pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update.effective_chat.id):
        await _reply(update, "Unauthorized.")
        return

    if not context.args:
        await _reply(update, "Usage: `/grant_pro <telegram_id> [YYYY-MM-DD]`", parse_mode="Markdown")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await _reply(update, "Telegram ID must be numeric.")
        return

    expires_at = None
    if len(context.args) > 1:
        expires_at = _parse_membership_expiry(context.args[1])
        if not expires_at:
            await _reply(update, "Expiry must be `YYYY-MM-DD` or a valid ISO datetime.", parse_mode="Markdown")
            return

    membership = db.set_membership(target_user_id, PRO_MEMBERSHIP, expires_at=expires_at)
    if not membership:
        await _reply(update, "❌ Failed to grant Pro access.")
        return

    expiry_note = f"\n*Expires:* {membership.get('membership_expires_at')}" if membership.get("membership_expires_at") else ""
    await _reply(
        update,
        f"✅ Pro membership granted for `{target_user_id}`.{expiry_note}",
        parse_mode="Markdown",
    )


async def revoke_pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_chat(update.effective_chat.id):
        await _reply(update, "Unauthorized.")
        return

    if not context.args:
        await _reply(update, "Usage: `/revoke_pro <telegram_id>`", parse_mode="Markdown")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await _reply(update, "Telegram ID must be numeric.")
        return

    membership = db.set_membership(target_user_id, FREE_MEMBERSHIP)
    if not membership:
        await _reply(update, "❌ Failed to revoke Pro access.")
        return

    await _reply(update, f"✅ Pro access revoked for `{target_user_id}`.", parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = db.get_or_create_user(user.id, user.username or "", user.first_name or "")
    if not user_record:
        await _reply(update, "❌ System error: could not verify your user account.")
        return

    agreed = settings_mgr.get(f"user_agreed_{user.id}")
    if not agreed:
        disclaimer_text = (
            "⚖️ *IMPORTANT LEGAL & RISK DISCLOSURE*\n\n"
            "1. This software is for *educational purposes only*.\n"
            "2. Trading carries a *significant risk of loss*.\n"
            "3. You are responsible for your API keys and capital.\n"
            "4. The developers are *not* liable for financial losses.\n\n"
            "Do you agree to continue?\n\n"
            "Tap the keyboard button below. If Telegram acts weird, you can also send `/agree`."
        )
        await _reply(update, disclaimer_text, parse_mode="Markdown", reply_markup=get_agreement_keyboard())
        return

    await _send_welcome_menu(update)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fields = settings_mgr.list_all()
    text = "🛠 *Persistent Settings*\n\n"
    keyboard = []

    for key, data in fields.items():
        if key.startswith("user_agreed_"):
            continue
        text += f"• *{key}*: `{data['value']}` ({data['type']})\n_{data['desc']}_\n\n"
        if data["type"] == "Boolean":
            keyboard.append([InlineKeyboardButton(f"Toggle {key}", callback_data=f"toggle_{key}")])

    text += "Use `/set <name> <value>` to change a field."
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await _reply(update, text, parse_mode="Markdown", reply_markup=reply_markup)


async def set_value_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await _reply(update, "❌ Usage: `/set <name> <value>`", parse_mode="Markdown")
        return

    name = context.args[0]
    value = context.args[1]
    if settings_mgr.set(name, value):
        await _reply(update, f"✅ *{name}* updated to `{value}`.", parse_mode="Markdown")
    else:
        await _reply(update, f"❌ Failed to update *{name}*.", parse_mode="Markdown")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    logger.info(f"Telegram callback received: {query.data}")

    if query.data.startswith("agree_"):
        user_id = query.data.split("_", 1)[1]
        saved = _record_user_agreement(user_id)
        if not saved:
            await query.answer("Could not save agreement. Please try again.", show_alert=True)
            return

        await query.answer("Agreement recorded", show_alert=True)
        try:
            await _maybe_await(
                query.edit_message_text(
                    _welcome_menu_text(),
                    parse_mode="Markdown",
                    reply_markup=get_main_menu(),
                )
            )
        except Exception as exc:
            logger.warning(f"Failed to update agreement message in place: {exc}")
            await _send_welcome_menu_to_chat(context, query.message.chat.id)
        logger.info(f"User {user_id} accepted the risk disclosure.")
        return

    await query.answer()

    if query.data.startswith("toggle_"):
        key = query.data.split("_", 1)[1]
        current = settings_mgr.get(key)
        settings_mgr.set(key, not current)
        await settings_command(query, context)
        return

    cmd_mapping = {
        "cmd_status": "/status",
        "cmd_settings": "/settings",
        "cmd_kb": "/kb",
        "cmd_pause": "/pause",
        "cmd_resume": "/resume",
        "cmd_emergency_stop": "/emergency_stop",
        "cmd_shutdown": "/shutdown",
    }
    callback_cmd = cmd_mapping.get(query.data)
    if callback_cmd:
        class MockUpdate:
            def __init__(self, callback_query, text):
                self.message = callback_query.message
                self.message.text = text
                self.effective_chat = callback_query.message.chat

        await proxy_command(MockUpdate(query, callback_cmd), context)


async def kb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb_text = (
        f"📚 *{APP_NAME} Knowledge Base*\n\n"
        "*Strategy stack:* MA crossover, RSI, MACD, ATR, and Bollinger squeeze.\n\n"
        "*Scoring:* Trend (30), RSI (25), Volume (25), Momentum (20).\n\n"
        "*Risk controls:* Position sizing, ATR stops, max daily loss, and safety timeout.\n\n"
        "*Modes:* Backtest, simulation, and live execution.\n"
        "Use `/backtest <symbol> [timeframe] [500|1000]` for free Telegram backtests.\n\n"
        "⚖️ Trading is risky. This project is educational software, not financial advice."
    )
    await _reply(update, kb_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trial_days = _trial_days()
    text = (
        "Available Commands:\n"
        "/start - Show legal notice or main menu\n"
        "/signup - Create your user profile\n"
        "/profile - View verification status\n"
        "/plans - Compare free vs paid access\n"
        "/subscription - View your current membership\n"
        f"/start_trial - Start your {trial_days}-day Trial Pro\n"
        "/dashboard_api - Get your gated member dashboard link\n"
        "/rotate_dashboard_key - Mint a fresh member dashboard link\n"
        "/backtest - Run a free Phemex backtest (500 or 1000 candles)\n"
        f"/subscribe - Start the {trial_days}-day Trial Pro / Pro checkout\n"
        "/manage_subscription - Open billing portal\n"
        "/setup_api - Store exchange API keys in the zero-knowledge vault\n"
        "/unlock_api - Unlock your vault for the current bot session\n"
        "/verify_email - Start email verification\n"
        "/confirm_email - Complete email verification\n"
        "/status - Check bot status\n"
        "/pause - Pause trading\n"
        "/resume - Resume trading\n"
        "/reset - Reset simulation\n"
        "/set_balance <amount> - Set simulation balance\n"
        "/shutdown - Stop the engine\n"
        "/grant_pro <telegram_id> [YYYY-MM-DD] - Admin only\n"
        "/revoke_pro <telegram_id> - Admin only\n"
    )
    await _reply(update, text)


async def proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = getattr(update.message, "text", "")
    if not text:
        return

    parts = text.split()
    command = parts[0]
    args = parts[1:]
    chat_id = update.effective_chat.id

    admin_only_commands = {"/pause", "/resume", "/reset", "/set_balance", "/shutdown", "/emergency_stop"}
    if command in admin_only_commands and not _is_admin_chat(chat_id):
        await _reply(update, "Unauthorized.")
        return

    if cmd_queue:
        cmd_queue.put((command, args, chat_id))
        await _reply(update, f"Command {command} queued.")
    else:
        await _reply(update, "Engine not connected.")


async def set_commands(application: Application):
    commands = [
        BotCommand("start", "Launch main menu"),
        BotCommand("agree", "Accept risk disclosure and open menu"),
        BotCommand("signup", "Create your profile"),
        BotCommand("profile", "View verification status"),
        BotCommand("plans", "See free vs paid access"),
        BotCommand("subscription", "View your membership"),
        BotCommand("start_trial", "Start your Trial Pro"),
        BotCommand("dashboard_api", "Get your member dashboard link"),
        BotCommand("rotate_dashboard_key", "Refresh your member dashboard link"),
        BotCommand("backtest", "Run a free 500/1000 candle backtest"),
        BotCommand("subscribe", "Start Trial Pro / Stripe checkout"),
        BotCommand("manage_subscription", "Open Stripe billing portal"),
        BotCommand("unlock_api", "Unlock your zero-knowledge API vault"),
        BotCommand("status", "Check bot status"),
        BotCommand("verify_email", "Link your email address"),
        BotCommand("confirm_email", "Verify email with 6-digit code"),
        BotCommand("help", "List commands"),
        BotCommand("kb", "View knowledge base"),
        BotCommand("pause", "Pause new trades"),
        BotCommand("resume", "Resume trading"),
        BotCommand("shutdown", "Stop the bot"),
    ]
    await application.bot.set_my_commands(commands)


async def post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        logger.warning(f"Unable to clear Telegram webhook before polling: {exc}")
    await set_commands(application)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    global _conflict_logged

    if isinstance(context.error, Conflict):
        if not _conflict_logged:
            logger.error(
                "Telegram polling conflict detected. Another poller or active webhook is using this bot token. "
                "Disable FancyFinance polling with TELEGRAM_POLLING_ENABLED=false if another service owns inbound Telegram updates."
            )
            _conflict_logged = True
        if context.application.running:
            try:
                context.application.stop_running()
            except Exception as exc:
                logger.warning(f"Failed to stop Telegram application after conflict: {exc}")
        return

    logger.error(f"Telegram error: {context.error}")


def run_bot(engine, command_queue):
    global cmd_queue, config
    cmd_queue = command_queue
    config = engine.config

    telegram_config = config.get("telegram", {})
    token = telegram_config.get("bot_token")
    if not token:
        logger.warning("Telegram bot token missing. Bot controls disabled.")
        return

    if not _is_truthy(telegram_config.get("polling_enabled", True)):
        logger.info("Telegram polling disabled. Outbound notifications remain enabled.")
        return

    application = Application.builder().token(token).post_init(post_init).build()
    application.add_error_handler(error_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("agree", agree_command))
    application.add_handler(CommandHandler("signup", signup_command))
    application.add_handler(CommandHandler("plans", plans_command))
    application.add_handler(CommandHandler("subscription", subscription_command))
    application.add_handler(CommandHandler("start_trial", start_trial_command))
    application.add_handler(CommandHandler("dashboard_api", dashboard_api_command))
    application.add_handler(CommandHandler("rotate_dashboard_key", rotate_dashboard_key_command))
    application.add_handler(CommandHandler("backtest", backtest_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("manage_subscription", manage_subscription_command))
    application.add_handler(CommandHandler("unlock_api", unlock_api_command))
    application.add_handler(CommandHandler("verify_email", verify_email_command))
    application.add_handler(CommandHandler("confirm_email", confirm_email_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("kb", kb_command))
    application.add_handler(CommandHandler("setup_api", setup_api_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("set", set_value_command))
    application.add_handler(CommandHandler("grant_pro", grant_pro_command))
    application.add_handler(CommandHandler("revoke_pro", revoke_pro_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Regex(r"^✅ I Agree$"), agree_command))
    application.add_handler(MessageHandler(filters.Regex(r"^❌ I Disagree$"), disagree_message))
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^(📊 Status|⚙️ Settings|⏸ Pause|▶️ Resume|🆘 Emergency Stop|🛑 Shutdown)$"),
            menu_button_handler,
        )
    )

    for command in ["status", "pause", "resume", "reset", "set_balance", "shutdown", "emergency_stop"]:
        application.add_handler(CommandHandler(command, proxy_command))

    logger.info("Telegram Bot Polling...")
    application.run_polling(stop_signals=None, drop_pending_updates=False)
