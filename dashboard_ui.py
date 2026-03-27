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
    data_endpoint: str = "/dashboard/data",
    token_storage_key: str = "fancyfinance_dashboard_token",
    query_token_param: str = "",
    fallback_token_storage_keys: tuple[str, ...] = (),
    persist_token: bool = True,
) -> str:
    auth_required_js = "true" if auth_required else "false"
    public_mode_js = "true" if public_mode else "false"
    persist_token_js = "true" if persist_token else "false"
    token_storage_keys_js = json.dumps([token_storage_key, *fallback_token_storage_keys])
    auth_hint = (
        "Sign in from Telegram. Your dashboard login link opens a user-scoped session, so the member dashboard no longer needs a pasted API key."
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
    if public_mode:
        auth_controls_html = """
          <div class="button-row">
            <a class="link-btn primary" href="https://t.me/FancyFinanceBot" target="_blank" rel="noreferrer">Open Telegram</a>
            <button class="secondary" id="member-logout-btn">Log Out</button>
            <button class="secondary" id="member-refresh-btn">Refresh Now</button>
          </div>
        """
    elif auth_required:
        auth_controls_html = """
          <div>
            <label class="field-label" for="api-token">Admin Token</label>
            <input id="api-token" type="password" placeholder="Paste the FancyFinance admin dashboard token" />
            <div class="button-row">
              <button class="primary" id="save-token-btn">Unlock Dashboard</button>
              <button class="secondary" id="clear-token-btn">Clear Token</button>
              <button class="secondary" id="refresh-btn">Refresh Now</button>
            </div>
          </div>
        """
    else:
        auth_controls_html = """
          <div class="button-row">
            <button class="secondary" id="refresh-btn">Refresh Now</button>
          </div>
        """
    controls_style = ""
    positions_style = ""
    setup_style = "display:none;" if public_mode else ""
    users_style = "display:none;" if public_mode else ""
    user_metric_style = "display:none;" if public_mode else ""
    members_nav = "" if public_mode else '<a href="#users-panel">Members</a>'
    page_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Dashboard"
    footer_note = (
        "Use /dashboard_login in Telegram any time you need a fresh login link."
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
        .replace("__PERSIST_TOKEN_JS__", persist_token_js)
        .replace("__DATA_ENDPOINT__", data_endpoint)
        .replace("__TOKEN_STORAGE_KEY__", token_storage_key)
        .replace("__TOKEN_STORAGE_KEYS__", token_storage_keys_js)
        .replace("__QUERY_TOKEN_PARAM__", query_token_param)
        .replace("__PUBLIC_SITE__", PUBLIC_SITE_URL)
    )
