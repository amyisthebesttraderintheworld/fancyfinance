from __future__ import annotations


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
) -> str:
    auth_required_js = "true" if auth_required else "false"
    public_mode_js = "true" if public_mode else "false"
    auth_hint = (
        "Use the Telegram-issued dashboard token to open this read-only member dashboard. Admin controls stay on /dashboard."
        if public_mode
        else (
            "Enter your FancyFinance API token to unlock live stats, billing visibility, and engine controls."
            if auth_required
            else "API auth is disabled. Live stats and controls are available without a token."
        )
    )
    auth_title = "Member Access" if public_mode else "Unlock live controls"
    brand_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Control Center"
    hero_subtitle = (
        "A read-only live view of FancyFinance performance, runtime health, and recent activity. "
        "Use the main site as the front door, then keep protected operator controls on /dashboard."
        if public_mode
        else "The same Railway-hosted control plane behind FancyFinance, now styled to match the new public site and built for fast operator decisions."
    )
    auth_form_style = "" if auth_required else "display:none;"
    controls_style = "display:none;" if public_mode else ""
    setup_style = "display:none;" if public_mode else ""
    users_style = "display:none;" if public_mode else ""
    user_metric_style = "display:none;" if public_mode else ""
    members_nav = "" if public_mode else '<a href="#users-panel">Members</a>'
    page_title = f"{app_name} Member Dashboard" if public_mode else f"{app_name} Dashboard"
    footer_note = (
        "Use /dashboard_api in Telegram any time you need a fresh access token."
        if public_mode
        else "Auto-refresh runs every 3 seconds while this tab is visible."
    )

    template = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>__PAGE_TITLE__</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet" />
    <style>
      :root {
        color-scheme: dark;
        --background: hsl(220 20% 4%);
        --background-soft: hsl(220 20% 6%);
        --foreground: hsl(210 20% 92%);
        --muted-foreground: hsl(215 12% 58%);
        --card: hsl(220 18% 7%);
        --card-soft: hsl(220 16% 10%);
        --border: hsl(220 14% 14%);
        --border-strong: rgba(49, 196, 110, 0.2);
        --primary: hsl(145 60% 48%);
        --primary-strong: hsl(145 65% 43%);
        --accent: hsl(10 80% 65%);
        --warning: #f0b44d;
        --danger: #d45757;
        --shadow-glow: 0 0 60px -12px hsl(145 60% 48% / 0.15);
        --shadow-card: 0 18px 48px -20px rgba(0, 0, 0, 0.55);
        --gradient-primary: linear-gradient(135deg, hsl(10 80% 65%), hsl(145 60% 48%));
        --gradient-hero: radial-gradient(circle at top center, rgba(47, 208, 111, 0.08), transparent 42%), linear-gradient(180deg, hsl(220 20% 6%) 0%, hsl(220 20% 4%) 100%);
      }

      * {
        box-sizing: border-box;
      }

      html {
        scroll-behavior: smooth;
      }

      body {
        margin: 0;
        min-height: 100vh;
        color: var(--foreground);
        font-family: "Inter", sans-serif;
        background:
          radial-gradient(circle at 20% 0%, rgba(47, 208, 111, 0.08), transparent 26%),
          radial-gradient(circle at 80% 10%, rgba(237, 139, 99, 0.08), transparent 22%),
          var(--gradient-hero);
      }

      a {
        color: inherit;
        text-decoration: none;
      }

      .shell {
        width: min(1380px, calc(100% - 32px));
        margin: 0 auto;
        padding: 20px 0 48px;
      }

      .surface {
        border: 1px solid var(--border);
        background:
          linear-gradient(180deg, rgba(16, 22, 20, 0.94), rgba(10, 14, 13, 0.98));
        box-shadow: var(--shadow-card), inset 0 1px 0 rgba(255, 255, 255, 0.02);
        backdrop-filter: blur(18px);
      }

      .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        padding: 18px 22px;
        border-radius: 20px;
        margin-bottom: 18px;
      }

      .brand-lockup {
        display: flex;
        align-items: center;
        gap: 14px;
      }

      .brand-mark {
        flex: 0 0 auto;
        display: flex;
        align-items: center;
      }

      .brand-logo {
        display: block;
        width: auto;
        height: 58px;
        max-width: min(34vw, 230px);
        object-fit: contain;
        filter: drop-shadow(0 14px 32px rgba(0, 0, 0, 0.35));
      }

      .brand-copy {
        display: grid;
        gap: 5px;
      }

      .brand-title {
        font-family: "Space Grotesk", sans-serif;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: -0.03em;
      }

      .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        width: fit-content;
        border-radius: 999px;
        border: 1px solid rgba(49, 196, 110, 0.18);
        background: rgba(16, 24, 20, 0.9);
        color: var(--muted-foreground);
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.04em;
        padding: 8px 12px;
      }

      .topnav {
        display: flex;
        align-items: center;
        gap: 18px;
        color: var(--muted-foreground);
        font-size: 14px;
      }

      .topnav a:hover {
        color: var(--foreground);
      }

      .nav-cta {
        padding: 12px 18px;
        border-radius: 14px;
        background: var(--primary);
        color: hsl(220 20% 4%);
        font-weight: 700;
        box-shadow: 0 12px 32px -14px rgba(47, 208, 111, 0.8);
      }

      .hero {
        display: grid;
        grid-template-columns: 1.35fr 0.95fr;
        gap: 18px;
        margin-bottom: 18px;
      }

      .hero-card,
      .panel,
      .auth-card {
        border-radius: 24px;
      }

      .hero-card {
        padding: 28px;
      }

      .hero-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 18px;
      }

      .badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.02);
        color: var(--foreground);
        font-size: 13px;
        font-weight: 600;
      }

      .badge.subtle {
        color: var(--muted-foreground);
      }

      .status-dot {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: var(--danger);
        box-shadow: 0 0 0 8px rgba(212, 87, 87, 0.14);
      }

      .status-dot.live {
        background: var(--primary);
        box-shadow: 0 0 0 8px rgba(47, 208, 111, 0.14);
      }

      .status-dot.paused {
        background: var(--warning);
        box-shadow: 0 0 0 8px rgba(240, 180, 77, 0.14);
      }

      h1,
      h2,
      h3 {
        margin: 0;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: -0.04em;
      }

      h1 {
        font-size: clamp(38px, 5vw, 68px);
        line-height: 0.98;
        max-width: 860px;
      }

      .gradient-text {
        background: var(--gradient-primary);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
      }

      .subtitle {
        margin-top: 16px;
        max-width: 760px;
        color: var(--muted-foreground);
        font-size: 18px;
        line-height: 1.6;
      }

      .hero-links {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 22px;
      }

      .link-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        min-height: 46px;
        padding: 0 18px;
        border-radius: 14px;
        font-weight: 700;
        transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
      }

      .link-btn:hover,
      button:hover {
        transform: translateY(-1px);
      }

      .link-btn.primary {
        background: var(--primary);
        color: hsl(220 20% 4%);
        box-shadow: 0 18px 36px -18px rgba(47, 208, 111, 0.7);
      }

      .link-btn.secondary {
        border: 1px solid rgba(49, 196, 110, 0.2);
        color: var(--foreground);
        background: rgba(255, 255, 255, 0.02);
      }

      .hero-grid,
      .list-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 14px;
        margin-top: 24px;
      }

      .metric,
      .mini-card {
        position: relative;
        overflow: hidden;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: linear-gradient(180deg, rgba(23, 31, 28, 0.92), rgba(14, 19, 18, 0.98));
      }

      .metric::before,
      .mini-card::before {
        content: "";
        position: absolute;
        inset: 0 auto auto 0;
        width: 100%;
        height: 1px;
        background: linear-gradient(90deg, rgba(237, 139, 99, 0.32), rgba(47, 208, 111, 0.28));
      }

      .metric-label,
      .mini-card .label {
        display: block;
        color: var(--muted-foreground);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
      }

      .metric-value,
      .mini-card .value {
        display: block;
        margin-top: 10px;
        font-size: 28px;
        font-weight: 800;
        line-height: 1;
      }

      .auth-card,
      .panel {
        padding: 24px;
      }

      .auth-card {
        display: flex;
        flex-direction: column;
        gap: 14px;
      }

      .panel-header {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 18px;
      }

      .panel-title {
        font-size: 24px;
      }

      .panel-subtitle {
        color: var(--muted-foreground);
        font-size: 14px;
        line-height: 1.5;
        margin-top: 6px;
      }

      .field-label {
        color: var(--muted-foreground);
        font-size: 13px;
        font-weight: 600;
      }

      input {
        width: 100%;
        border-radius: 14px;
        border: 1px solid var(--border);
        background: rgba(12, 17, 15, 0.96);
        color: var(--foreground);
        padding: 14px 16px;
        font-size: 15px;
        outline: none;
        transition: border-color 140ms ease, box-shadow 140ms ease;
      }

      input::placeholder {
        color: color-mix(in srgb, var(--muted-foreground) 75%, transparent);
      }

      input:focus {
        border-color: rgba(47, 208, 111, 0.45);
        box-shadow: 0 0 0 4px rgba(47, 208, 111, 0.12);
      }

      .button-row {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }

      button {
        appearance: none;
        border: none;
        border-radius: 14px;
        min-height: 46px;
        padding: 0 16px;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
        transition: transform 140ms ease, opacity 140ms ease, background 140ms ease, border-color 140ms ease;
      }

      button.primary,
      button.success {
        background: var(--primary);
        color: hsl(220 20% 4%);
        box-shadow: 0 18px 36px -18px rgba(47, 208, 111, 0.7);
      }

      button.secondary {
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
        color: var(--foreground);
      }

      button.warning {
        background: rgba(240, 180, 77, 0.12);
        color: #ffd892;
        border: 1px solid rgba(240, 180, 77, 0.25);
      }

      button.danger {
        background: rgba(212, 87, 87, 0.12);
        color: #ffb1b1;
        border: 1px solid rgba(212, 87, 87, 0.25);
      }

      .message {
        min-height: 22px;
        font-size: 14px;
        color: var(--muted-foreground);
      }

      .message.error {
        color: #ff9d9d;
      }

      .content-grid {
        display: grid;
        grid-template-columns: 1.16fr 0.84fr;
        gap: 18px;
      }

      .stack {
        display: grid;
        gap: 18px;
      }

      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }

      .chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
        font-size: 13px;
        color: var(--foreground);
      }

      .chip strong {
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted-foreground);
      }

      .chip.good {
        border-color: rgba(47, 208, 111, 0.2);
      }

      .chip.warn {
        border-color: rgba(240, 180, 77, 0.22);
      }

      .chip.bad {
        border-color: rgba(212, 87, 87, 0.22);
      }

      .table-shell {
        overflow-x: auto;
        border-radius: 16px;
        border: 1px solid var(--border);
        background: rgba(12, 17, 15, 0.72);
      }

      .positions-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: 14px;
      }

      .position-card {
        position: relative;
        overflow: hidden;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid var(--border);
        background: linear-gradient(180deg, rgba(23, 31, 28, 0.92), rgba(14, 19, 18, 0.98));
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
      }

      .position-card::before {
        content: "";
        position: absolute;
        inset: 0 auto auto 0;
        width: 100%;
        height: 1px;
        background: linear-gradient(90deg, rgba(237, 139, 99, 0.32), rgba(47, 208, 111, 0.28));
      }

      .position-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
      }

      .position-symbol {
        font-family: "Space Grotesk", sans-serif;
        font-size: 18px;
        font-weight: 700;
      }

      .position-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 14px;
      }

      .position-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        border: 1px solid rgba(255, 255, 255, 0.06);
        background: rgba(255, 255, 255, 0.03);
        color: var(--muted-foreground);
      }

      .position-pill.user {
        border-color: rgba(237, 139, 99, 0.18);
      }

      .position-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.04em;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
      }

      .position-badge.long {
        border-color: rgba(47, 208, 111, 0.22);
      }

      .position-badge.short {
        border-color: rgba(237, 139, 99, 0.22);
      }

      .position-stats {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }

      .position-stat {
        border-radius: 14px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: rgba(255, 255, 255, 0.02);
        padding: 12px;
      }

      .position-stat .label {
        display: block;
        color: var(--muted-foreground);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
      }

      .position-stat .value {
        display: block;
        margin-top: 8px;
        font-size: 15px;
        font-weight: 700;
      }

      .positive {
        color: #6ef0bf;
      }

      .negative {
        color: #ff93a4;
      }

      .amber {
        color: #ffd892;
      }

      .position-stat.positive {
        border-color: rgba(47, 208, 111, 0.2);
      }

      .position-stat.negative {
        border-color: rgba(212, 87, 87, 0.24);
      }

      .price-line {
        margin-bottom: 14px;
        padding: 14px 14px 12px;
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: linear-gradient(180deg, rgba(8, 12, 11, 0.78), rgba(16, 22, 20, 0.88));
      }

      .price-line-bar {
        position: relative;
        height: 48px;
      }

      .price-line-track {
        position: absolute;
        left: 0;
        right: 0;
        top: 50%;
        height: 10px;
        transform: translateY(-50%);
        border-radius: 999px;
        background: linear-gradient(90deg, rgba(212, 87, 87, 0.18), rgba(255, 196, 95, 0.18), rgba(47, 208, 111, 0.18));
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
      }

      .price-line-fill {
        position: absolute;
        top: 50%;
        height: 10px;
        transform: translateY(-50%);
        border-radius: 999px;
      }

      .price-line-marker {
        position: absolute;
        top: 50%;
        transform: translate(-50%, -50%);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--foreground);
      }

      .price-line-stop {
        color: #ff7f8e;
      }

      .price-line-entry {
        color: #ffc45f;
      }

      .price-line-target {
        color: #63e3b0;
      }

      .price-line-face {
        top: 0;
        transform: translate(-50%, 0);
        font-size: 18px;
        letter-spacing: 0;
        text-transform: none;
        white-space: nowrap;
        text-shadow: 0 0 18px rgba(255, 255, 255, 0.18);
      }

      .price-line-face-flat {
        color: #d6d5de;
      }

      .price-line-face-profit {
        color: #6ef0bf;
      }

      .price-line-face-loss {
        color: #ff93a4;
      }

      .price-line-face-near {
        color: #ffe07d;
      }

      .price-line-labels {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin-top: 8px;
        color: var(--muted-foreground);
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .position-footer {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        margin-top: 12px;
        color: var(--muted-foreground);
        font-size: 12px;
      }

      .keyval-grid {
        display: grid;
        gap: 12px;
      }

      .keyval {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        padding: 12px 14px;
        border-radius: 14px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: rgba(255, 255, 255, 0.02);
      }

      .keyval .key {
        color: var(--muted-foreground);
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }

      .keyval .value {
        font-size: 15px;
        font-weight: 700;
      }

      .activity-list {
        display: grid;
        gap: 12px;
      }

      .activity-row {
        display: grid;
        gap: 6px;
        padding: 14px;
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        background: rgba(255, 255, 255, 0.02);
      }

      .activity-row.bad {
        border-color: rgba(212, 87, 87, 0.22);
      }

      .activity-row.warn {
        border-color: rgba(240, 180, 77, 0.22);
      }

      .activity-row.good {
        border-color: rgba(47, 208, 111, 0.22);
      }

      .activity-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }

      .activity-stamp {
        color: var(--muted-foreground);
        font-size: 12px;
      }

      .activity-source {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 5px 8px;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        border: 1px solid rgba(255, 255, 255, 0.06);
        background: rgba(255, 255, 255, 0.03);
        color: var(--muted-foreground);
      }

      .activity-text {
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 14px;
        line-height: 1.5;
      }

      table {
        width: 100%;
        border-collapse: collapse;
      }

      th,
      td {
        padding: 13px 12px;
        text-align: left;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        font-size: 14px;
        vertical-align: top;
      }

      th {
        color: var(--muted-foreground);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
      }

      tbody tr:hover {
        background: rgba(255, 255, 255, 0.02);
      }

      tr:last-child td {
        border-bottom: none;
      }

      .empty {
        padding: 22px;
        border-radius: 18px;
        border: 1px dashed var(--border);
        background: rgba(255, 255, 255, 0.02);
        color: var(--muted-foreground);
        text-align: center;
      }

      .footer-note {
        margin-top: 16px;
        color: var(--muted-foreground);
        font-size: 13px;
      }

      @media (max-width: 1120px) {
        .hero,
        .content-grid {
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 860px) {
        .hero-grid,
        .list-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .topbar {
          flex-direction: column;
          align-items: flex-start;
        }

        .topnav {
          width: 100%;
          flex-wrap: wrap;
        }

        .brand-logo {
          height: 52px;
          max-width: min(60vw, 220px);
        }
      }

      @media (max-width: 560px) {
        .shell {
          width: min(100% - 18px, 1380px);
          padding-top: 12px;
        }

        .hero-card,
        .auth-card,
        .panel,
        .topbar {
          padding: 18px;
          border-radius: 18px;
        }

        .hero-grid,
        .list-grid {
          grid-template-columns: 1fr;
        }

        .panel-header {
          flex-direction: column;
          align-items: flex-start;
        }

        .position-stats,
        .price-line-labels {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .brand-logo {
          height: 46px;
          max-width: min(70vw, 210px);
        }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <header class="topbar surface">
        <div class="brand-lockup">
          <div class="brand-mark">
            <img class="brand-logo" src="/dashboard/assets/logo.png" alt="FancyFinance logo" />
          </div>
          <div class="brand-copy">
            <div class="eyebrow">Telegram-first algorithmic trading</div>
            <div class="brand-title">__BRAND_TITLE__</div>
          </div>
        </div>
        <nav class="topnav">
          <a href="__PUBLIC_SITE__" target="_blank" rel="noreferrer">Public Site</a>
          <a href="#control-panel">Controls</a>
          <a href="#runtime-panel">Runtime</a>
          __MEMBERS_NAV__
          <a class="nav-cta" href="__PUBLIC_SITE__" target="_blank" rel="noreferrer">FancyFinance Hub</a>
        </nav>
      </header>

      <section class="hero">
        <div class="hero-card surface">
          <div class="hero-badges">
            <div class="badge"><span class="status-dot" id="hero-status-dot"></span><span id="hero-status-text">Awaiting live data</span></div>
            <div class="badge subtle">__APP_NAME__ v__VERSION__</div>
          </div>
          <div class="eyebrow">Operations dashboard</div>
          <h1>Algorithmic trading,<br /><span class="gradient-text">tuned for live control</span></h1>
          <p class="subtitle">
            __HERO_SUBTITLE__
          </p>
          <div class="hero-links">
            <a class="link-btn primary" href="__PUBLIC_SITE__" target="_blank" rel="noreferrer">Open Public Site</a>
            <a class="link-btn secondary" href="#control-panel">Jump to Controls</a>
          </div>
          <div class="hero-grid">
            <div class="metric">
              <span class="metric-label">Wallet</span>
              <span class="metric-value" id="metric-balance">--</span>
            </div>
            <div class="metric">
              <span class="metric-label">Live uPnL</span>
              <span class="metric-value" id="metric-upnl">--</span>
            </div>
            <div class="metric">
              <span class="metric-label">Marked Equity</span>
              <span class="metric-value" id="metric-equity">--</span>
            </div>
            <div class="metric">
              <span class="metric-label">Session Delta</span>
              <span class="metric-value" id="metric-delta">--</span>
            </div>
            <div class="metric">
              <span class="metric-label">Open Positions</span>
              <span class="metric-value" id="metric-positions">--</span>
            </div>
            <div class="metric">
              <span class="metric-label">Realized PnL</span>
              <span class="metric-value" id="metric-pnl">--</span>
            </div>
            <div class="metric" style="__USER_METRIC_STYLE__">
              <span class="metric-label">Users</span>
              <span class="metric-value" id="metric-users">--</span>
            </div>
          </div>
        </div>

        <aside class="auth-card surface">
          <div>
            <div class="eyebrow">Secure Access</div>
            <h2 class="panel-title" style="margin-top: 14px;">__AUTH_TITLE__</h2>
            <p class="panel-subtitle">__AUTH_HINT__</p>
          </div>
          <div style="__AUTH_FORM_STYLE__">
          <label class="field-label" for="api-token">API Token</label>
          <input id="api-token" type="password" placeholder="Paste FANCYFINANCE_API_TOKEN" />
          <div class="button-row">
            <button class="primary" id="save-token-btn">Unlock Dashboard</button>
            <button class="secondary" id="clear-token-btn">Clear Token</button>
            <button class="secondary" id="refresh-btn">Refresh Now</button>
          </div>
          </div>
          <div class="message" id="auth-message"></div>
          <div class="footer-note">__FOOTER_NOTE__</div>
        </aside>
      </section>

      <section class="content-grid">
        <div class="stack">
          <div class="panel surface" id="control-panel" style="__CONTROL_PANEL_STYLE__">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Live Controls</h2>
                <div class="panel-subtitle">Direct engine actions protected by the same API token.</div>
              </div>
              <div class="badge subtle" id="mode-badge">Mode: --</div>
            </div>
            <div class="button-row">
              <button class="warning" id="pause-btn">Pause Engine</button>
              <button class="success" id="resume-btn">Resume Engine</button>
              <button class="danger" id="shutdown-btn">Shutdown Engine</button>
            </div>
            <div class="message" id="control-message"></div>
          </div>

          <div class="panel surface" id="runtime-panel">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Runtime Snapshot</h2>
                <div class="panel-subtitle">Everything the engine is doing right now.</div>
              </div>
            </div>
            <div class="list-grid">
              <div class="mini-card">
                <div class="label">Engine State</div>
                <div class="value" id="runtime-engine">--</div>
              </div>
              <div class="mini-card">
                <div class="label">WebSocket</div>
                <div class="value" id="runtime-websocket">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Command Queue</div>
                <div class="value" id="runtime-queue">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Tracked Symbols</div>
                <div class="value" id="runtime-symbols">--</div>
              </div>
              <div class="mini-card">
                <div class="label">API Vault</div>
                <div class="value" id="runtime-api">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Active Users</div>
                <div class="value" id="runtime-users">--</div>
              </div>
            </div>
            <div class="footer-note" id="runtime-note">Waiting for runtime data.</div>
          </div>

          <div class="panel surface" style="__SETUP_PANEL_STYLE__">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Open Positions</h2>
                <div class="panel-subtitle">Current exposure across active symbols.</div>
              </div>
            </div>
            <div id="positions-wrap"></div>
          </div>

          <div class="panel surface">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Recent Trades</h2>
                <div class="panel-subtitle">Entries and exits from the current engine session.</div>
              </div>
            </div>
            <div id="trades-wrap"></div>
          </div>
        </div>

        <div class="stack">
          <div class="panel surface">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Wallet Snapshot</h2>
                <div class="panel-subtitle">Live mark-to-market, exposure, and how many positions are actually receiving price updates.</div>
              </div>
            </div>
            <div class="keyval-grid" id="wallet-wrap"></div>
          </div>

          <div class="panel surface">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Setup Status</h2>
                <div class="panel-subtitle">Quick read on what is configured correctly.</div>
              </div>
            </div>
            <div class="chips" id="setup-chips"></div>
          </div>

          <div class="panel surface">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Performance</h2>
                <div class="panel-subtitle">Realized outcomes from the current engine session.</div>
              </div>
            </div>
            <div class="list-grid">
              <div class="mini-card">
                <div class="label">Wins</div>
                <div class="value" id="perf-wins">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Losses</div>
                <div class="value" id="perf-losses">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Win Rate</div>
                <div class="value" id="perf-rate">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Trade Count</div>
                <div class="value" id="perf-count">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Avg Trade</div>
                <div class="value" id="perf-avg">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Exposure</div>
                <div class="value" id="perf-exposure">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Marked Prices</div>
                <div class="value" id="perf-marked">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Alert Load</div>
                <div class="value" id="perf-alerts">--</div>
              </div>
            </div>
          </div>

          <div class="panel surface">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Activity Feed</h2>
                <div class="panel-subtitle">Recent engine messages, fills, and direct command responses.</div>
              </div>
            </div>
            <div id="activity-wrap"></div>
          </div>

          <div class="panel surface" id="users-panel" style="__USERS_PANEL_STYLE__">
            <div class="panel-header">
              <div>
                <h2 class="panel-title">Members</h2>
                <div class="panel-subtitle">Signup, billing, and verification visibility from Supabase.</div>
              </div>
            </div>
            <div class="list-grid">
              <div class="mini-card">
                <div class="label">Total Users</div>
                <div class="value" id="users-total">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Verified</div>
                <div class="value" id="users-verified">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Unverified</div>
                <div class="value" id="users-unverified">--</div>
              </div>
              <div class="mini-card">
                <div class="label">API Keys Stored</div>
                <div class="value" id="users-api-keys">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Free</div>
                <div class="value" id="users-free">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Trial Pro</div>
                <div class="value" id="users-trial-pro">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Pro</div>
                <div class="value" id="users-pro">--</div>
              </div>
              <div class="mini-card">
                <div class="label">Expired</div>
                <div class="value" id="users-expired">--</div>
              </div>
            </div>
            <div style="margin-top: 18px;" id="users-wrap"></div>
          </div>
        </div>
      </section>
    </div>

    <script>
      const AUTH_REQUIRED = __AUTH_REQUIRED_JS__;
      const PUBLIC_MODE = __PUBLIC_MODE_JS__;
      const DATA_ENDPOINT = "__DATA_ENDPOINT__";
      const TOKEN_KEY = "__TOKEN_STORAGE_KEY__";
      const QUERY_TOKEN_PARAM = "__QUERY_TOKEN_PARAM__";
      const queryToken = QUERY_TOKEN_PARAM
        ? (new URLSearchParams(window.location.search).get(QUERY_TOKEN_PARAM) || "")
        : "";
      const state = {
        token: queryToken || localStorage.getItem(TOKEN_KEY) || "",
        sessionBaseline: null,
        sessionBaselineKey: "",
      };

      if (queryToken) {
        localStorage.setItem(TOKEN_KEY, queryToken);
      }

      const els = {
        tokenInput: document.getElementById("api-token"),
        authMessage: document.getElementById("auth-message"),
        controlMessage: document.getElementById("control-message"),
        statusDot: document.getElementById("hero-status-dot"),
        statusText: document.getElementById("hero-status-text"),
        modeBadge: document.getElementById("mode-badge"),
      };

      els.tokenInput.value = state.token;

      function escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      }

      function setText(id, value) {
        const node = document.getElementById(id);
        if (node) {
          node.textContent = value;
        }
      }

      function setTextWithTone(id, value, tone = "") {
        const node = document.getElementById(id);
        if (!node) {
          return;
        }
        node.textContent = value;
        node.classList.remove("positive", "negative", "amber");
        if (tone) {
          node.classList.add(tone);
        }
      }

      function formatMoney(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
          return "--";
        }
        const numeric = Number(value);
        return numeric.toLocaleString(undefined, {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: 2,
        });
      }

      function formatMaybeNumber(value, digits = 2) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
          return "--";
        }
        return Number(value).toLocaleString(undefined, {
          minimumFractionDigits: 0,
          maximumFractionDigits: digits,
        });
      }

      function formatSignedMoney(value) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
          return "--";
        }
        const numeric = Number(value);
        const sign = numeric > 0 ? "+" : numeric < 0 ? "-" : "";
        return `${sign}${formatMoney(Math.abs(numeric))}`;
      }

      function formatTimestamp(value) {
        if (!value) {
          return "--";
        }
        let normalizedValue = value;
        if (typeof value === "number" || /^\\d+(\\.\\d+)?$/.test(String(value))) {
          const numeric = Number(value);
          normalizedValue = numeric < 1e12 ? numeric * 1000 : numeric;
        }
        const date = new Date(normalizedValue);
        if (Number.isNaN(date.getTime())) {
          return String(value);
        }
        return date.toLocaleString();
      }

      function formatAge(value) {
        if (!value) {
          return "--";
        }
        let timestamp = Number(value);
        if (!Number.isFinite(timestamp)) {
          timestamp = new Date(value).getTime();
        }
        if (!Number.isFinite(timestamp)) {
          return "--";
        }
        const normalized = timestamp < 1e12 ? timestamp * 1000 : timestamp;
        const elapsedMs = Math.max(Date.now() - normalized, 0);
        const minutes = Math.floor(elapsedMs / 60000);
        if (minutes < 1) {
          return "just now";
        }
        if (minutes < 60) {
          return `${minutes}m ago`;
        }
        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
          return `${hours}h ago`;
        }
        const days = Math.floor(hours / 24);
        if (days < 7) {
          return `${days}d ago`;
        }
        return formatTimestamp(normalized);
      }

      function tradeTimeMs(trade) {
        const raw = trade?.timestamp ?? trade?.created_at;
        if (raw === null || raw === undefined || raw === "") {
          return 0;
        }
        if (typeof raw === "number" || /^\\d+(\\.\\d+)?$/.test(String(raw))) {
          const numeric = Number(raw);
          return numeric < 1e12 ? numeric * 1000 : numeric;
        }
        const parsed = new Date(raw).getTime();
        return Number.isNaN(parsed) ? 0 : parsed;
      }

      function activityTone(entry) {
        const text = String(entry?.text || "").toUpperCase();
        if (text.includes("ERROR") || text.includes("FAIL") || text.includes("STOPPED") || text.includes("UNAUTHORIZED")) {
          return "bad";
        }
        if (text.includes("PAUSE") || text.includes("WARNING") || text.includes("WARN") || text.includes("PENDING")) {
          return "warn";
        }
        if (text.includes("ENTRY") || text.includes("EXIT") || text.includes("STARTED") || text.includes("RESUMED") || text.includes("UNLOCKED")) {
          return "good";
        }
        return "";
      }

      function humanizeMembership(value) {
        const normalized = String(value || "").trim();
        if (!normalized) {
          return "--";
        }
        return normalized
          .replaceAll("_", " ")
          .replaceAll("-", " ")
          .replace(/\\b\\w/g, (char) => char.toUpperCase());
      }

      function headers() {
        const result = {};
        if (AUTH_REQUIRED) {
          if (!state.token) {
            throw new Error("Missing API token");
          }
          result["x-api-key"] = state.token;
        }
        return result;
      }

      function setMessage(node, text, isError = false) {
        node.textContent = text;
        node.className = isError ? "message error" : "message";
      }

      function toneForStatus(value) {
        const normalized = String(value || "").toLowerCase();
        if (normalized.includes("missing") || normalized.includes("offline") || normalized.includes("invalid")) {
          return "bad";
        }
        if (normalized.includes("configured") || normalized.includes("connected") || normalized.includes("enabled") || normalized === "on") {
          return "good";
        }
        if (normalized.includes("disabled") || normalized.includes("unknown")) {
          return "warn";
        }
        return "";
      }

      function renderSetup(config) {
        const chips = [
          ["Supabase", config.supabase_connected ? "Connected" : (config.supabase_configured ? "Configured, offline" : "Missing")],
          ["Encryption", config.encryption_status || "unknown"],
          ["Telegram Polling", config.telegram_polling_enabled ? "Enabled" : "Disabled"],
          ["Notifications", config.telegram_notifications_enabled ? "Enabled" : "Disabled"],
          ["Email Webhook", config.email_webhook_configured ? "Configured" : "Missing"],
          ["Stripe Checkout", config.stripe_checkout_configured ? "Configured" : "Missing"],
          ["Stripe Webhook", config.stripe_webhook_configured ? "Configured" : "Missing"],
          ["Stripe Portal", config.stripe_portal_configured ? "Configured" : "Missing"],
          ["Scan Scope", config.scan_all_symbols ? `All ${config.market_type || "markets"}` : "Configured list"],
          ["Timeframe", config.timeframe || "--"],
          ["Testnet", config.testnet ? "On" : "Off"],
        ];

        document.getElementById("setup-chips").innerHTML = chips
          .map(([label, value]) => `<div class="chip ${toneForStatus(value)}"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span></div>`)
          .join("");
      }

      function toPct(value, low, high) {
        if (!Number.isFinite(value) || !Number.isFinite(low) || !Number.isFinite(high)) {
          return 50;
        }
        if (low === high) {
          return 50;
        }
        const pct = ((value - low) / (high - low)) * 100;
        return Math.min(98, Math.max(2, pct));
      }

      function buildPriceLine(position) {
        const entry = Number(position.entry_price);
        const stop = Number(position.stop_loss);
        const target = Number(position.take_profit);
        const mark = position.mark_price === null || position.mark_price === undefined || Number.isNaN(Number(position.mark_price))
          ? null
          : Number(position.mark_price);
        const hasEntry = Number.isFinite(entry) && entry > 0;
        const hasStop = Number.isFinite(stop) && stop > 0;
        const hasTarget = Number.isFinite(target) && target > 0;
        if (!hasEntry) {
          return "";
        }

        const values = [entry];
        if (hasStop) {
          values.push(stop);
        }
        if (hasTarget) {
          values.push(target);
        }
        if (mark !== null && Number.isFinite(mark) && mark > 0) {
          values.push(mark);
        }
        if (values.length < 2) {
          return "";
        }

        const low = Math.min(...values);
        const high = Math.max(...values);
        const direction = String(position.direction || "").toLowerCase();
        const isLong = direction !== "short";
        const traveler = mark !== null ? mark : entry;
        const fillAnchor = hasStop ? stop : entry;
        const fillLeft = Math.min(toPct(entry, low, high), toPct(fillAnchor, low, high));
        const fillRight = Math.max(toPct(entry, low, high), toPct(fillAnchor, low, high));
        const fillWidth = Math.max(fillRight - fillLeft, 0);

        let face = "(-_-)";
        let faceClass = "price-line-face-flat";
        if (mark !== null) {
          const losing = isLong ? mark < entry : mark > entry;
          face = "(^_^)";
          faceClass = "price-line-face-profit";
          if (losing) {
            face = "(>_<)";
            faceClass = "price-line-face-loss";
          } else if (hasTarget) {
            const totalDistance = Math.abs(target - entry);
            const remainingDistance = Math.abs(target - mark);
            const progress = totalDistance > 0 ? remainingDistance / totalDistance : 1;
            if (progress < 0.15) {
              face = "(*_*)";
              faceClass = "price-line-face-near";
            }
          }
        }

        const fillTone = mark === null
          ? "linear-gradient(90deg, rgba(133, 146, 168, 0.24), rgba(214, 213, 222, 0.16))"
          : ((isLong ? mark >= entry : mark <= entry)
              ? "linear-gradient(90deg, rgba(47, 208, 111, 0.26), rgba(99, 227, 176, 0.18))"
              : "linear-gradient(90deg, rgba(212, 87, 87, 0.28), rgba(255, 127, 142, 0.2))");

        return `
          <div class="price-line">
            <div class="price-line-bar">
              <div class="price-line-track"></div>
              ${fillWidth > 0.5 ? `<div class="price-line-fill" style="left:${fillLeft}%; width:${fillWidth}%; background:${fillTone};"></div>` : ""}
              ${hasStop ? `<span class="price-line-marker price-line-stop" style="left:${toPct(stop, low, high)}%">S</span>` : ""}
              <span class="price-line-marker price-line-entry" style="left:${toPct(entry, low, high)}%">E</span>
              ${hasTarget ? `<span class="price-line-marker price-line-target" style="left:${toPct(target, low, high)}%">T</span>` : ""}
              <span class="price-line-marker price-line-face ${faceClass}" style="left:${toPct(traveler, low, high)}%">${face}</span>
            </div>
            <div class="price-line-labels">
              <span>Stop ${hasStop ? formatMaybeNumber(stop, 4) : "--"}</span>
              <span>Entry ${formatMaybeNumber(entry, 4)}</span>
              <span>Mark ${mark === null ? "--" : formatMaybeNumber(mark, 4)}</span>
              <span>Target ${hasTarget ? formatMaybeNumber(target, 4) : "--"}</span>
            </div>
          </div>
        `;
      }

      function computePortfolio(payload) {
        const snapshot = payload.snapshot || {};
        const positions = Array.isArray(payload.positions) ? payload.positions : [];
        const apiPortfolio = payload.portfolio || {};
        const balance = apiPortfolio.balance ?? snapshot.balance ?? null;
        const liveUpnl = positions.reduce((sum, position) => {
          const entry = Number(position.entry_price);
          const quantity = Number(position.quantity);
          const mark = position.mark_price === null || position.mark_price === undefined || Number.isNaN(Number(position.mark_price))
            ? null
            : Number(position.mark_price);
          if (!Number.isFinite(entry) || !Number.isFinite(quantity) || mark === null) {
            return sum;
          }
          const direction = String(position.direction || "").toLowerCase();
          return sum + (direction === "short" ? (entry - mark) : (mark - entry)) * quantity;
        }, 0);
        const exposure = positions.reduce((sum, position) => {
          const entry = Number(position.entry_price);
          const quantity = Number(position.quantity);
          if (!Number.isFinite(entry) || !Number.isFinite(quantity)) {
            return sum;
          }
          return sum + Math.abs(entry * quantity);
        }, 0);
        const markedPositions = positions.filter((position) => position.mark_price !== null && position.mark_price !== undefined && !Number.isNaN(Number(position.mark_price))).length;
        const markedEquity = balance === null || balance === undefined || Number.isNaN(Number(balance))
          ? null
          : Number(balance) + liveUpnl;
        const baselineKey = `${payload.user_id || "global"}:${snapshot.session_started_at || snapshot.mode || "session"}`;
        if (state.sessionBaselineKey !== baselineKey) {
          state.sessionBaselineKey = baselineKey;
          state.sessionBaseline = markedEquity;
        } else if (state.sessionBaseline == null && markedEquity != null) {
          state.sessionBaseline = markedEquity;
        }
        const sessionDelta = state.sessionBaseline == null || markedEquity == null ? null : markedEquity - state.sessionBaseline;
        return {
          balance,
          liveUpnl,
          markedEquity,
          exposure,
          markedPositions,
          openPositions: positions.length,
          winningPositions: apiPortfolio.winning_positions ?? 0,
          losingPositions: apiPortfolio.losing_positions ?? 0,
          sessionDelta,
        };
      }

      function renderWallet(portfolio) {
        const wrap = document.getElementById("wallet-wrap");
        if (!wrap) {
          return;
        }

        wrap.innerHTML = `
          <div class="keyval">
            <span class="key">Wallet balance</span>
            <span class="value">${formatMoney(portfolio.balance)}</span>
          </div>
          <div class="keyval">
            <span class="key">Live uPnL</span>
            <span class="value ${portfolio.liveUpnl >= 0 ? "positive" : "negative"}">${formatSignedMoney(portfolio.liveUpnl)}</span>
          </div>
          <div class="keyval">
            <span class="key">Marked equity</span>
            <span class="value ${portfolio.sessionDelta == null ? "" : portfolio.sessionDelta >= 0 ? "positive" : "negative"}">${formatMoney(portfolio.markedEquity)}</span>
          </div>
          <div class="keyval">
            <span class="key">Session delta</span>
            <span class="value ${portfolio.sessionDelta == null ? "" : portfolio.sessionDelta >= 0 ? "positive" : "negative"}">${formatSignedMoney(portfolio.sessionDelta)}</span>
          </div>
          <div class="keyval">
            <span class="key">Notional exposure</span>
            <span class="value">${formatMoney(portfolio.exposure)}</span>
          </div>
          <div class="keyval">
            <span class="key">Marked prices live</span>
            <span class="value">${formatMaybeNumber(portfolio.markedPositions, 0)} / ${formatMaybeNumber(portfolio.openPositions, 0)}</span>
          </div>
        `;
      }

      function renderActivity(activity) {
        const wrap = document.getElementById("activity-wrap");
        if (!wrap) {
          return;
        }
        const entries = Array.isArray(activity) ? [...activity].sort((left, right) => tradeTimeMs(right) - tradeTimeMs(left)).slice(0, 18) : [];
        if (!entries.length) {
          wrap.innerHTML = '<div class="empty">No recent engine activity yet.</div>';
          return;
        }

        wrap.innerHTML = `
          <div class="activity-list">
            ${
              entries.map((entry, index) => {
                const tone = activityTone(entry);
                const source = String(entry.source || "event").replaceAll("_", " ");
                return `
                  <article class="activity-row ${tone}" key="${index}">
                    <div class="activity-head">
                      <span class="activity-stamp">${escapeHtml(formatTimestamp(entry.created_at || entry.timestamp))}</span>
                      <span class="activity-source">${escapeHtml(source)}</span>
                    </div>
                    <div class="activity-text">${escapeHtml(String(entry.text || "--"))}</div>
                  </article>
                `;
              }).join("")
            }
          </div>
        `;
      }

      function renderPositions(positions) {
        const wrap = document.getElementById("positions-wrap");
        if (!positions || !positions.length) {
          wrap.innerHTML = '<div class="empty">No open positions right now.</div>';
          return;
        }

        const badgeForDirection = (direction) => {
          const normalized = String(direction || "").toLowerCase();
          if (normalized === "long") {
            return { tone: "long", label: "🙂 Long" };
          }
          if (normalized === "short") {
            return { tone: "short", label: "😈 Short" };
          }
          return { tone: "", label: "😐 Open" };
        };

        wrap.innerHTML = `
          <div class="positions-grid">
            ${
              positions.map((position) => {
                const badge = badgeForDirection(position.direction);
                const mark = position.mark_price === null || position.mark_price === undefined || Number.isNaN(Number(position.mark_price))
                  ? null
                  : Number(position.mark_price);
                const entry = Number(position.entry_price);
                const quantity = Number(position.quantity);
                const direction = String(position.direction || "").toLowerCase();
                const unrealizedPnl = mark === null || !Number.isFinite(entry) || !Number.isFinite(quantity)
                  ? null
                  : (direction === "short" ? (entry - mark) : (mark - entry)) * quantity;
                const pnlClass = unrealizedPnl === null ? "" : unrealizedPnl >= 0 ? "positive" : "negative";
                const notional = Number.isFinite(entry) && Number.isFinite(quantity) ? Math.abs(entry * quantity) : null;
                const userPill = position.user_id === null || position.user_id === undefined
                  ? ""
                  : `<span class="position-pill user">Acct ${escapeHtml(position.user_id)}</span>`;
                const openedPill = `<span class="position-pill">Opened ${escapeHtml(formatAge(position.entry_time))}</span>`;
                const markPill = `<span class="position-pill">${mark === null ? "Mark pending" : `Mark ${escapeHtml(formatMaybeNumber(mark, 4))}`}</span>`;
                return `
                  <article class="position-card">
                    <div class="position-head">
                      <div class="position-symbol">${escapeHtml(position.symbol)}</div>
                      <div class="position-badge ${badge.tone}">${badge.label}</div>
                    </div>
                    <div class="position-meta">
                      ${userPill}
                      ${openedPill}
                      ${markPill}
                    </div>
                    ${buildPriceLine(position)}
                    <div class="position-stats">
                      <div class="position-stat">
                        <span class="label">Entry</span>
                        <span class="value">${formatMaybeNumber(position.entry_price, 4)}</span>
                      </div>
                      <div class="position-stat">
                        <span class="label">Mark</span>
                        <span class="value">${mark === null ? "--" : formatMaybeNumber(mark, 4)}</span>
                      </div>
                      <div class="position-stat ${pnlClass}">
                        <span class="label">Unrealized</span>
                        <span class="value">${formatSignedMoney(unrealizedPnl)}</span>
                      </div>
                      <div class="position-stat">
                        <span class="label">Qty</span>
                        <span class="value">${formatMaybeNumber(position.quantity, 4)}</span>
                      </div>
                      <div class="position-stat">
                        <span class="label">Stop</span>
                        <span class="value">${formatMaybeNumber(position.stop_loss, 4)}</span>
                      </div>
                      <div class="position-stat">
                        <span class="label">Target</span>
                        <span class="value">${formatMaybeNumber(position.take_profit, 4)}</span>
                      </div>
                    </div>
                    <div class="position-footer">
                      <span>${notional == null ? "Notional --" : `Notional ${escapeHtml(formatMoney(notional))}`}</span>
                      <span>${mark === null ? "Live mark pending" : "Live mark online"}</span>
                      <span>${unrealizedPnl == null ? "uPnL waiting" : (unrealizedPnl >= 0 ? "Position green" : "Position red")}</span>
                    </div>
                  </article>
                `;
              }).join("")
            }
          </div>
        `;
      }

      function renderTrades(trades) {
        const wrap = document.getElementById("trades-wrap");
        if (!trades || !trades.length) {
          wrap.innerHTML = '<div class="empty">No trades logged in this session yet.</div>';
          return;
        }

        const ordered = [...trades].sort((left, right) => tradeTimeMs(right) - tradeTimeMs(left));

        wrap.innerHTML = `
          <div class="table-shell">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Direction</th>
                  <th>Price</th>
                  <th>Qty</th>
                  <th>Reason</th>
                  <th>PnL</th>
                </tr>
              </thead>
              <tbody>
                ${
                  ordered.map((trade) => {
                    const pnl = trade.pnl === null || trade.pnl === undefined || Number.isNaN(Number(trade.pnl))
                      ? "--"
                      : formatSignedMoney(trade.pnl);
                    const pnlTone = trade.pnl === null || trade.pnl === undefined || Number.isNaN(Number(trade.pnl))
                      ? ""
                      : Number(trade.pnl) >= 0 ? "positive" : "negative";
                    return `
                    <tr>
                      <td>${escapeHtml(formatTimestamp(trade.created_at || trade.timestamp))}</td>
                      <td>${escapeHtml(trade.symbol)}</td>
                      <td>${escapeHtml(trade.type || "--")}</td>
                      <td>${escapeHtml(trade.direction || "--")}</td>
                      <td>${formatMaybeNumber(trade.price, 4)}</td>
                      <td>${formatMaybeNumber(trade.qty, 4)}</td>
                      <td>${escapeHtml(trade.reason || "--")}</td>
                      <td class="${pnlTone}">${pnl}</td>
                    </tr>
                  `;
                  }).join("")
                }
              </tbody>
            </table>
          </div>
        `;
      }

      function renderUsers(summary) {
        setText("users-total", formatMaybeNumber(summary.total, 0));
        setText("users-verified", formatMaybeNumber(summary.verified, 0));
        setText("users-unverified", formatMaybeNumber(summary.unverified, 0));
        setText("users-api-keys", formatMaybeNumber(summary.with_api_keys, 0));
        setText("users-free", formatMaybeNumber(summary.free, 0));
        setText("users-trial-pro", formatMaybeNumber(summary.trial_pro, 0));
        setText("users-pro", formatMaybeNumber(summary.pro, 0));
        setText("users-expired", formatMaybeNumber(summary.expired, 0));

        const wrap = document.getElementById("users-wrap");
        const users = summary.recent || [];
        if (!users.length) {
          wrap.innerHTML = '<div class="empty">No users recorded yet.</div>';
          return;
        }

        wrap.innerHTML = `
          <div class="table-shell">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Email</th>
                  <th>Verification</th>
                  <th>Plan</th>
                  <th>Membership</th>
                  <th>Joined</th>
                </tr>
              </thead>
              <tbody>
                ${
                  users.map((user) => `
                    <tr>
                      <td>
                        <strong>${escapeHtml(user.first_name || user.username || user.telegram_id || "Unknown")}</strong><br />
                        <span style="color: var(--muted-foreground);">@${escapeHtml(user.username || "n/a")}</span>
                      </td>
                      <td>${escapeHtml(user.email || user.pending_email || "Not set")}</td>
                      <td>${user.is_verified ? "Verified" : "Pending"}</td>
                      <td>${escapeHtml(humanizeMembership(user.membership_tier || "free"))}</td>
                      <td>${escapeHtml(humanizeMembership(user.membership_status || "free"))}</td>
                      <td>${escapeHtml(formatTimestamp(user.created_at))}</td>
                    </tr>
                  `).join("")
                }
              </tbody>
            </table>
          </div>
        `;
      }

      function renderData(payload) {
        const snapshot = payload.snapshot || {};
        const performance = payload.performance || {};
        const runtime = payload.runtime || {};
        const config = payload.config || {};
        const memberAccess = !!payload.member_access;
        const portfolio = computePortfolio(payload);
        const averageTrade = performance.closed_trades ? Number(performance.realized_pnl || 0) / Number(performance.closed_trades || 1) : null;
        const alerts = (Array.isArray(payload.activity) ? payload.activity : []).filter((entry) => {
          const tone = activityTone(entry);
          return tone === "bad" || tone === "warn";
        }).length
          + (runtime.websocket_connected ? 0 : 1)
          + (runtime.safety_pause_remaining_seconds > 0 ? 1 : 0);

        setTextWithTone("metric-balance", formatMoney(portfolio.balance));
        setTextWithTone("metric-upnl", formatSignedMoney(portfolio.liveUpnl), portfolio.liveUpnl > 0 ? "positive" : portfolio.liveUpnl < 0 ? "negative" : "");
        setTextWithTone("metric-equity", formatMoney(portfolio.markedEquity), portfolio.sessionDelta == null ? "" : portfolio.sessionDelta >= 0 ? "positive" : "negative");
        setTextWithTone("metric-delta", formatSignedMoney(portfolio.sessionDelta), portfolio.sessionDelta == null ? "" : portfolio.sessionDelta >= 0 ? "positive" : "negative");
        setText("metric-positions", formatMaybeNumber(snapshot.open_positions, 0));
        setTextWithTone("metric-pnl", formatSignedMoney(performance.realized_pnl), Number(performance.realized_pnl || 0) > 0 ? "positive" : Number(performance.realized_pnl || 0) < 0 ? "negative" : "");
        setText("metric-users", formatMaybeNumber((payload.users || {}).total, 0));
        setText("perf-wins", formatMaybeNumber(performance.wins, 0));
        setText("perf-losses", formatMaybeNumber(performance.losses, 0));
        setText("perf-rate", performance.win_rate !== undefined ? `${formatMaybeNumber(performance.win_rate, 1)}%` : "--");
        setText("perf-count", formatMaybeNumber(snapshot.trade_count, 0));
        setTextWithTone("perf-avg", averageTrade == null ? "--" : formatSignedMoney(averageTrade), averageTrade == null ? "" : averageTrade > 0 ? "positive" : averageTrade < 0 ? "negative" : "");
        setText("perf-exposure", formatMoney(portfolio.exposure));
        setText("perf-marked", `${formatMaybeNumber(portfolio.markedPositions, 0)} / ${formatMaybeNumber(portfolio.openPositions, 0)}`);
        setTextWithTone("perf-alerts", formatMaybeNumber(alerts, 0), alerts > 0 ? "amber" : "positive");
        setText("runtime-engine", runtime.engine_status || "--");
        setTextWithTone("runtime-websocket", runtime.websocket_connected ? "Connected" : "Offline", runtime.websocket_connected ? "positive" : "negative");
        setText("runtime-queue", formatMaybeNumber(runtime.command_queue_depth, 0));
        setText("runtime-symbols", formatMaybeNumber(snapshot.symbol_count || (snapshot.symbols || []).length, 0));
        setTextWithTone("runtime-api", runtime.runtime_api_ready ? "Ready" : "Locked", runtime.runtime_api_ready ? "positive" : "amber");
        setText("runtime-users", formatMaybeNumber(runtime.active_user_count, 0));
        setText(
          "runtime-note",
          runtime.safety_pause_remaining_seconds > 0
            ? `Safety pause active for another ${Math.ceil(runtime.safety_pause_remaining_seconds / 60)} minute(s).`
            : `Last refresh: ${formatTimestamp(snapshot.timestamp)} · ${portfolio.markedPositions}/${portfolio.openPositions} positions have live marks.`
        );

        els.modeBadge.textContent = `Mode: ${snapshot.mode || "--"}`;
        els.statusDot.classList.remove("live", "paused");
        if (snapshot.running && snapshot.paused) {
          els.statusDot.classList.add("paused");
        } else if (snapshot.running) {
          els.statusDot.classList.add("live");
        }
        els.statusText.textContent = snapshot.running ? (snapshot.paused ? "Running, but paused" : "Engine live") : "Engine stopped";

        if (memberAccess) {
          setMessage(els.controlMessage, "Read-only member access active. Telegram controls stay in the bot.", false);
        }

        renderWallet(portfolio);
        renderSetup(config);
        renderPositions(payload.positions || []);
        renderTrades(payload.recent_trades || []);
        renderActivity(payload.activity || []);
        renderUsers(payload.users || {});
      }

      async function loadDashboard() {
        if (AUTH_REQUIRED && !state.token) {
          setMessage(
            els.authMessage,
            PUBLIC_MODE
              ? "Member dashboard locked. Use /dashboard_api in Telegram for a fresh access link."
              : "Dashboard locked. Add a valid API token.",
            true
          );
          return;
        }

        try {
          const response = await fetch(DATA_ENDPOINT, {
            headers: headers(),
          });

          if (response.status === 401) {
            setMessage(els.authMessage, "Dashboard locked. Add a valid dashboard token or API key.", true);
            return;
          }

          if (!response.ok) {
            throw new Error(`Dashboard request failed: ${response.status}`);
          }

          const payload = await response.json();
          setMessage(
            els.authMessage,
            payload.member_access ? "Read-only member dashboard unlocked." : (AUTH_REQUIRED ? "Dashboard unlocked." : "Dashboard is live.")
          );
          renderData(payload);
        } catch (error) {
          setMessage(els.authMessage, error.message || "Could not load dashboard.", true);
        }
      }

      async function runControl(action) {
        if (PUBLIC_MODE) {
          setMessage(els.controlMessage, "Member overview is read-only. Use /dashboard for protected operator controls.", true);
          return;
        }
        const requiresConfirm = action === "shutdown";
        if (requiresConfirm && !window.confirm("Shut the engine down now?")) {
          return;
        }

        try {
          const response = await fetch(`/control/${action}`, {
            method: "POST",
            headers: headers(),
          });
          const payload = await response.json();
          if (!response.ok) {
            throw new Error(payload.detail || `Control failed: ${response.status}`);
          }
          setMessage(els.controlMessage, `Engine action complete: ${payload.status}.`);
          await loadDashboard();
        } catch (error) {
          setMessage(els.controlMessage, error.message || "Control action failed.", true);
        }
      }

      const saveTokenBtn = document.getElementById("save-token-btn");
      const clearTokenBtn = document.getElementById("clear-token-btn");
      const refreshBtn = document.getElementById("refresh-btn");
      const pauseBtn = document.getElementById("pause-btn");
      const resumeBtn = document.getElementById("resume-btn");
      const shutdownBtn = document.getElementById("shutdown-btn");

      if (saveTokenBtn) {
        saveTokenBtn.addEventListener("click", async () => {
          state.token = els.tokenInput.value.trim();
          if (state.token) {
            localStorage.setItem(TOKEN_KEY, state.token);
          } else {
            localStorage.removeItem(TOKEN_KEY);
          }
          await loadDashboard();
        });
      }

      if (clearTokenBtn) {
        clearTokenBtn.addEventListener("click", () => {
          state.token = "";
          els.tokenInput.value = "";
          localStorage.removeItem(TOKEN_KEY);
          setMessage(els.authMessage, "Stored token cleared.");
        });
      }

      if (refreshBtn) {
        refreshBtn.addEventListener("click", loadDashboard);
      }
      if (pauseBtn) {
        pauseBtn.addEventListener("click", () => runControl("pause"));
      }
      if (resumeBtn) {
        resumeBtn.addEventListener("click", () => runControl("resume"));
      }
      if (shutdownBtn) {
        shutdownBtn.addEventListener("click", () => runControl("shutdown"));
      }

      loadDashboard();
      window.setInterval(() => {
        if (document.visibilityState === "visible") {
          loadDashboard();
        }
      }, 3000);
    </script>
  </body>
</html>
"""

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
        .replace("__SETUP_PANEL_STYLE__", setup_style)
        .replace("__USERS_PANEL_STYLE__", users_style)
        .replace("__USER_METRIC_STYLE__", user_metric_style)
        .replace("__MEMBERS_NAV__", members_nav)
        .replace("__FOOTER_NOTE__", footer_note)
        .replace("__AUTH_REQUIRED_JS__", auth_required_js)
        .replace("__PUBLIC_MODE_JS__", public_mode_js)
        .replace("__DATA_ENDPOINT__", data_endpoint)
        .replace("__TOKEN_STORAGE_KEY__", token_storage_key)
        .replace("__QUERY_TOKEN_PARAM__", query_token_param)
        .replace("__PUBLIC_SITE__", PUBLIC_SITE_URL)
    )
