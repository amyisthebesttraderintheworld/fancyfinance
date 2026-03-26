from __future__ import annotations

import json
import pathlib

PUBLIC_SITE_URL = "https://fancy-bot-front.lovable.app/"


def build_dashboard_html(
    app_name: str,
    version: str,
    auth_required: bool,
    *,
    public_mode: bool = False,
    data_endpoint: str = "/dashboard/data",
    token_storage_key: str = "fancyfinance_api_token",
    query_token_param: str = "",
    fallback_token_storage_keys: tuple[str, ...] = (),
) -> str:
    auth_required_js = "true" if auth_required else "false"
    public_mode_js = "true" if public_mode else "false"
    token_storage_keys_js = json.dumps([token_storage_key, *fallback_token_storage_keys])
    auth_hint = (
        "Open this dashboard from Telegram. The signed access link binds the page to your Telegram ID and unlocks user-scoped controls."
        if public_mode
        else (
            "Enter your FancyFinance API token to unlock live stats, billing visibility, and engine controls."
            if auth_required
            else "API auth is disabled. Live stats and controls are available without a token."
        )
    )
    auth_title = "Member Session" if public_mode else "Unlock live controls"
    brand_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Control Center"
    hero_subtitle = (
        "A Telegram-linked operations view for your own FancyFinance account, including live readiness, strategy controls, and session health."
        if public_mode
        else "The same Railway-hosted control plane behind FancyFinance, now styled to match the new public site and built for fast operator decisions."
    )
    auth_form_style = "" if auth_required else "display:none;"
    controls_style = ""
    positions_style = ""
    setup_style = "display:none;" if public_mode else ""
    users_style = "display:none;" if public_mode else ""
    user_metric_style = "display:none;" if public_mode else ""
    members_nav = "" if public_mode else '<a href="#users-panel">Members</a>'
    page_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Dashboard"
    footer_note = (
        "Use /dashboard_api in Telegram any time you need a fresh access link."
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
        .replace("__AUTH_FORM_STYLE__", auth_form_style)
        .replace("__CONTROL_PANEL_STYLE__", controls_style)
        .replace("__POSITIONS_PANEL_STYLE__", positions_style)
        .replace("__SETUP_PANEL_STYLE__", setup_style)
        .replace("__USERS_PANEL_STYLE__", users_style)
        .replace("__USER_METRIC_STYLE__", user_metric_style)
        .replace("__MEMBERS_NAV__", members_nav)
        .replace("__FOOTER_NOTE__", footer_note)
        .replace("__AUTH_REQUIRED_JS__", auth_required_js)
        .replace("__PUBLIC_MODE_JS__", public_mode_js)
        .replace("__DATA_ENDPOINT__", data_endpoint)
        .replace("__TOKEN_STORAGE_KEY__", token_storage_key)
        .replace("__TOKEN_STORAGE_KEYS__", token_storage_keys_js)
        .replace("__QUERY_TOKEN_PARAM__", query_token_param)
        .replace("__PUBLIC_SITE__", PUBLIC_SITE_URL)
    )
