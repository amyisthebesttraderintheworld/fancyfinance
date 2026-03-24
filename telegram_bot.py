from __future__ import annotations

import inspect
import queue

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from common import SettingsManager, get_logger
from fancyfinance import APP_NAME, __version__
from supabase_client import SupabaseManager

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
            InlineKeyboardButton("📊 Status", callback_data="cmd_status"),
            InlineKeyboardButton("⚙️ Settings", callback_data="cmd_settings"),
        ],
        [
            InlineKeyboardButton("⏸ Pause", callback_data="cmd_pause"),
            InlineKeyboardButton("▶️ Resume", callback_data="cmd_resume"),
        ],
        [
            InlineKeyboardButton("🆘 Emergency Stop", callback_data="cmd_emergency_stop"),
            InlineKeyboardButton("🛑 Shutdown", callback_data="cmd_shutdown"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def setup_api_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await _reply(
            update,
            "🔒 *Secure API Setup*\n\nUse: `/setup_api <api_key> <api_secret>`\n\n"
            "⚠️ Your message will be deleted after processing.",
            parse_mode="Markdown",
        )
        return

    api_key, api_secret = context.args[:2]
    user_id = update.effective_user.id

    if db.store_user_api_keys(user_id, api_key, api_secret):
        await _reply(update, "✅ *API keys secured and stored.*", parse_mode="Markdown")
    else:
        await _reply(update, "❌ Failed to secure keys. Is Supabase configured?", parse_mode="Markdown")

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception as exc:
        logger.warning(f"Failed to delete secure message: {exc}")


async def verify_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply(update, "📧 Use: `/verify_email yourname@example.com`", parse_mode="Markdown")
        return

    email = context.args[0].lower()
    otp = db.request_email_verification(update.effective_user.id, email)
    if otp:
        logger.info(f"Email verification OTP for {email}: {otp}")
        await _reply(
            update,
            f"📨 *Verification Email Sent to {email}*\n\n"
            "Use `/confirm_email 123456` after you receive the code.",
            parse_mode="Markdown",
        )
    else:
        await _reply(update, "❌ Failed to initiate email verification.", parse_mode="Markdown")


async def confirm_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply(update, "🔑 Use: `/confirm_email 123456`", parse_mode="Markdown")
        return

    if db.confirm_email_verification(update.effective_user.id, context.args[0]):
        await _reply(update, "✅ *Email verified!*", parse_mode="Markdown")
    else:
        await _reply(update, "❌ Invalid or expired verification code.", parse_mode="Markdown")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_or_create_user(user_id, "", "")
    if not user:
        await _reply(update, "❌ Could not retrieve profile.")
        return

    status = "Verified ✅" if user.get("is_verified") else "Unverified ❌"
    email = user.get("email") or "Not linked"
    message = (
        f"👤 *{APP_NAME} Profile*\n\n"
        f"• *Telegram ID:* `{user_id}`\n"
        f"• *Email:* `{email}`\n"
        f"• *Status:* {status}\n\n"
        "Use `/verify_email` to update your email or `/setup_api` to secure exchange keys."
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
            "2. Secure your API keys with `/setup_api`",
            parse_mode="Markdown",
        )
        return

    await _reply(update, "❌ Signup failed. Please ensure Supabase is configured.")


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
            "Do you agree to continue?"
        )
        keyboard = [
            [InlineKeyboardButton("✅ I Agree", callback_data=f"agree_{user.id}")],
            [InlineKeyboardButton("❌ I Disagree", callback_data="cmd_shutdown")],
        ]
        await _reply(update, disclaimer_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    welcome_text = (
        f"🤖 *{APP_NAME} v{__version__}*\n\n"
        "Trading Bot Connected. Use /help for commands.\n\n"
        "Use the buttons below to control the engine or type a command directly."
    )
    await _reply(update, welcome_text, parse_mode="Markdown", reply_markup=get_main_menu())


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
    await query.answer()

    if query.data.startswith("agree_"):
        user_id = query.data.split("_", 1)[1]
        settings_mgr.set(f"user_agreed_{user_id}", True, "Boolean", "User agreement to Terms & Conditions")
        await _reply(query, "✅ *Agreement recorded.*", parse_mode="Markdown")
        return

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
        "*Modes:* Backtest, simulation, and live execution.\n\n"
        "⚖️ Trading is risky. This project is educational software, not financial advice."
    )
    await _reply(update, kb_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Available Commands:\n"
        "/start - Show legal notice or main menu\n"
        "/signup - Create your user profile\n"
        "/profile - View verification status\n"
        "/setup_api - Securely store exchange API keys\n"
        "/verify_email - Start email verification\n"
        "/confirm_email - Complete email verification\n"
        "/status - Check bot status\n"
        "/pause - Pause trading\n"
        "/resume - Resume trading\n"
        "/reset - Reset simulation\n"
        "/set_balance <amount> - Set simulation balance\n"
        "/shutdown - Stop the engine\n"
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

    telegram_cfg = (config or {}).get("telegram", {})
    admin_ids = telegram_cfg.get("admin_chat_ids", [])
    if chat_id not in admin_ids:
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
        BotCommand("signup", "Create your profile"),
        BotCommand("profile", "View verification status"),
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
        try:
            await context.application.stop()
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
    application.add_handler(CommandHandler("signup", signup_command))
    application.add_handler(CommandHandler("verify_email", verify_email_command))
    application.add_handler(CommandHandler("confirm_email", confirm_email_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("kb", kb_command))
    application.add_handler(CommandHandler("setup_api", setup_api_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("set", set_value_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    for command in ["status", "pause", "resume", "reset", "set_balance", "shutdown", "emergency_stop"]:
        application.add_handler(CommandHandler(command, proxy_command))

    logger.info("Telegram Bot Polling...")
    application.run_polling(stop_signals=None, drop_pending_updates=False)
