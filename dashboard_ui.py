from __future__ import annotations

import json
import pathlib

PUBLIC_SITE_URL = "/"


def build_dashboard_html(
    app_name: str,
    version: str,
    auth_required: bool,
    *,
    public_mode: bool = False,
    member_session_mode: bool = False,
    data_endpoint: str = "/dashboard/data",
    token_storage_key: str = "fancyfinance_dashboard_token",
    query_token_param: str = "",
    fallback_token_storage_keys: tuple[str, ...] = (),
    persist_token: bool = True,
    telegram_login_enabled: bool = False,
    telegram_login_bot_username: str = "",
    telegram_login_url: str = "",
    telegram_bot_url: str = "https://t.me",
) -> str:
    auth_required_js = "true" if auth_required else "false"
    public_mode_js = "true" if public_mode else "false"
    member_session_mode_js = "true" if member_session_mode else "false"
    persist_token_js = "true" if persist_token else "false"
    token_storage_keys_js = json.dumps([token_storage_key, *fallback_token_storage_keys])
    telegram_login_enabled_js = "true" if telegram_login_enabled else "false"
    telegram_bot_username_js = json.dumps(telegram_login_bot_username or "")
    telegram_login_url_js = json.dumps(telegram_login_url or "")
    auth_hint = (
        "Log in with Telegram to open your own dashboard session. If Telegram web login is unavailable, you can still use /dashboard_login in the bot as a fallback."
        if public_mode
        else (
            "Enter the admin dashboard token to unlock live stats, billing visibility, and engine controls."
            if auth_required
            else "API auth is disabled. Live stats and controls are available without a token."
        )
    )
    auth_title = "Dashboard Login" if public_mode else "Unlock live controls"
    brand_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Control Center"
    hero_subtitle = (
        "A Telegram-linked operations view for your own FancyFinance account, including live readiness, strategy controls, and session health."
        if public_mode
        else "The same Railway-hosted control plane behind FancyFinance, now styled to match the new public site and built for fast operator decisions."
    )
    auth_clear_button = "Log Out" if public_mode else "Clear Token"
    # Always require Telegram login for dashboard access
    telegram_login_intro = (
        "Use the Telegram button below to sign into your personal dashboard."
        if telegram_login_enabled
        else "Telegram web login is not configured yet. Open the bot and use /dashboard_login as a temporary fallback."
    )
    telegram_widget_style = "" if telegram_login_enabled else "display:none;"
    telegram_fallback_style = "display:none;" if telegram_login_enabled else ""
    auth_controls_html = """
      <div class="telegram-login-block" id="telegram-login-block">
        <div class="panel-subtitle">{telegram_login_intro}</div>
        <div class="telegram-login-widget" id="telegram-login-widget" style="{telegram_widget_style}"></div>
        <div id="telegram-login-fallback" style="{telegram_fallback_style}">
          <a class="link-btn primary" href="{telegram_bot_url}" target="_blank" rel="noreferrer">Open Telegram Bot</a>
        </div>
      </div>
      <div class="button-row">
        <button class="secondary" id="member-logout-btn">Log Out</button>
        <button class="secondary" id="member-refresh-btn">Refresh Now</button>
      </div>
    """.format(
        telegram_login_intro=telegram_login_intro,
        telegram_widget_style=telegram_widget_style,
        telegram_fallback_style=telegram_fallback_style,
        telegram_bot_url=telegram_bot_url,
    )
    controls_style = ""
    positions_style = ""
    setup_style = "display:none;" if public_mode else ""
    users_style = "display:none;" if public_mode else ""
    user_metric_style = "display:none;" if public_mode else ""
    members_nav = "" if public_mode else '<a href="#users-panel">Members</a>'
    page_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Dashboard"
    footer_note = (
        "Log in with Telegram below. If the web login ever misbehaves, use /dashboard_login in Telegram for a direct fallback link."
        if public_mode
        else "Auto-refresh runs every 3 seconds while this tab is visible."
    )

    template_path = pathlib.Path(__file__).parent / "dashboard_ui.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Dashboard template not found at {template_path}")

    template = template_path.read_text()

    return (
        template
        .replace("__APP_NAME__", app_name)
        .replace("__PAGE_TITLE__", page_title)
        .replace("__VERSION__", version)
        .replace("__BRAND_TITLE__", brand_title)
        .replace("__HERO_SUBTITLE__", hero_subtitle)
        .replace("__AUTH_TITLE__", auth_title)
        .replace("__AUTH_HINT__", auth_hint)
        .replace("__AUTH_CLEAR_BUTTON__", auth_clear_button)
        .replace("__AUTH_CONTROLS__", auth_controls_html)
        .replace("__CONTROL_PANEL_STYLE__", controls_style)
        .replace("__POSITIONS_PANEL_STYLE__", positions_style)
        .replace("__SETUP_PANEL_STYLE__", setup_style)
        .replace("__USERS_PANEL_STYLE__", users_style)
        .replace("__USER_METRIC_STYLE__", user_metric_style)
        .replace("__MEMBERS_NAV__", members_nav)
        .replace("__FOOTER_NOTE__", footer_note)
        .replace("__AUTH_REQUIRED_JS__", auth_required_js)
        .replace("__PUBLIC_MODE_JS__", public_mode_js)
        .replace("__MEMBER_SESSION_MODE_JS__", member_session_mode_js)
        .replace("__PERSIST_TOKEN_JS__", persist_token_js)
        .replace("__DATA_ENDPOINT__", data_endpoint)
        .replace("__TOKEN_STORAGE_KEY__", token_storage_key)
        .replace("__TOKEN_STORAGE_KEYS__", token_storage_keys_js)
        .replace("__QUERY_TOKEN_PARAM__", query_token_param)
        .replace("__TELEGRAM_LOGIN_ENABLED_JS__", telegram_login_enabled_js)
        .replace("__TELEGRAM_BOT_USERNAME_JS__", telegram_bot_username_js)
        .replace("__TELEGRAM_LOGIN_URL_JS__", telegram_login_url_js)
        .replace("__PUBLIC_SITE__", PUBLIC_SITE_URL)
    )


def build_login_html(
    app_name: str,
    *,
    telegram_login_enabled: bool = False,
    telegram_login_bot_username: str = "",
    telegram_login_url: str = "",
    redirect_to: str = "/dashboard",
) -> str:
    template_path = pathlib.Path(__file__).parent / "dashboard_login.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Login template not found at {template_path}")

    template = template_path.read_text()
    telegram_login_enabled_js = "true" if telegram_login_enabled else "false"
    telegram_bot_username_js = json.dumps(telegram_login_bot_username or "")
    telegram_login_url_js = json.dumps(telegram_login_url or "")

    return (
        template
        .replace("__APP_NAME__", app_name)
        .replace("__TELEGRAM_LOGIN_ENABLED_JS__", telegram_login_enabled_js)
        .replace("__TELEGRAM_BOT_USERNAME_JS__", telegram_bot_username_js)
        .replace("__TELEGRAM_LOGIN_URL_JS__", telegram_login_url_js)
        .replace("__REDIRECT_TO__", redirect_to)
    )
