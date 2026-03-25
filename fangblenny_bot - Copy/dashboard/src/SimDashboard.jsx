import { useEffect, useMemo, useRef, useState } from 'react'
import heroArt from './assets/hero.png'
import { useTelegram } from './hooks/useTelegram'

const DEFAULT_POLL_MS = Number.parseInt(import.meta.env.VITE_POLL_MS ?? '2000', 10)
const DEFAULT_INIT_BALANCE = Number.parseFloat(import.meta.env.VITE_INITIAL_BALANCE ?? '100')
const DEFAULT_SESSION = import.meta.env.VITE_SIM_SESSION ?? '1'
const DEFAULT_MODE = (import.meta.env.VITE_DEFAULT_MODE ?? 'live').toLowerCase() === 'sim' ? 'sim' : 'live'

const FAST_TRACK_COOLDOWN_SECS = 300
const MAX_REENTRY_COOLDOWN_SECS = 4 * 4 * 3600
const MAX_EQUITY_HISTORY = 120
const MAX_LOG_LINES = 18
const TRADE_HISTORY_LIMIT = 12

const FEEDS = {
  live: {
    label: 'Live Production',
    modeLabel: 'Real assets active',
    account: 'live_account',
    trades: 'live_trade_results',
    cooldowns: 'live_cooldowns',
    logs: 'live_logs',
    config: 'live_config',
  },
  sim: {
    label: 'Simulation',
    modeLabel: 'Paper trading feed',
    account: 'paper_account',
    trades: 'sim_trade_results',
    cooldowns: 'sim_cooldowns',
    logs: 'sim_logs',
    config: 'sim_config',
  },
}

const CSS = /* css */ `
  .db {
    min-height: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 18px 0 44px;
    background:
      radial-gradient(circle at 14% 8%, rgba(154, 99, 255, 0.18), transparent 20%),
      radial-gradient(circle at 82% 16%, rgba(198, 139, 255, 0.12), transparent 14%),
      radial-gradient(circle at 84% 88%, rgba(118, 83, 255, 0.14), transparent 18%),
      linear-gradient(180deg, rgba(9, 9, 14, 0.96), rgba(4, 4, 8, 0.98));
    color: var(--text);
  }

  .db-shell {
    width: min(1440px, calc(100% - 32px));
    margin: 0 auto;
    display: grid;
    gap: 18px;
  }

  .db-card {
    position: relative;
    overflow: hidden;
    border-radius: var(--radius-xl);
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    backdrop-filter: blur(24px);
  }

  .db-card::before {
    content: '';
    position: absolute;
    inset: 14px;
    border-radius: calc(var(--radius-xl) - 10px);
    border: 1px solid rgba(255, 255, 255, 0.04);
    pointer-events: none;
  }

  .db-card::after {
    content: '';
    position: absolute;
    inset: auto 18px 0 18px;
    height: 72px;
    border-radius: 999px 999px 0 0;
    background: linear-gradient(90deg, transparent, rgba(154, 99, 255, 0.16), rgba(198, 139, 255, 0.18), transparent);
    filter: blur(22px);
    pointer-events: none;
  }

  .db-topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 18px 22px;
  }

  .db-brand {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
  }

  .db-brand__mark {
    width: 52px;
    height: 52px;
    border-radius: 18px;
    display: grid;
    place-items: center;
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0.04)),
      linear-gradient(135deg, rgba(154, 99, 255, 0.24), rgba(255, 255, 255, 0.03));
    border: 1px solid rgba(255, 255, 255, 0.18);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.04em;
  }

  .db-brand__copy {
    min-width: 0;
  }

  .db-kicker {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .db-kicker::before {
    content: '';
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: var(--violet-strong);
    box-shadow: 0 0 18px rgba(198, 139, 255, 0.55);
  }

  .db-brand__title {
    margin: 8px 0 0;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(1.1rem, 2vw, 1.5rem);
    font-weight: 700;
    letter-spacing: -0.04em;
  }

  .db-topbar__meta {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .db-user,
  .db-time,
  .db-session {
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.03);
    padding: 10px 14px;
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 600;
  }

  .db-time {
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
  }

  .db-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.18fr) minmax(300px, 0.82fr);
    gap: 22px;
    padding: 28px;
  }

  .db-hero__copy {
    position: relative;
    z-index: 1;
    display: grid;
    gap: 18px;
  }

  .db-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .db-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    padding: 0 14px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.03);
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .db-chip::before {
    content: '';
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: currentColor;
    box-shadow: 0 0 12px currentColor;
  }

  .db-chip--green {
    color: var(--green);
    background: var(--green-soft);
    border-color: rgba(91, 240, 177, 0.3);
  }

  .db-chip--amber {
    color: var(--amber);
    background: var(--amber-soft);
    border-color: rgba(255, 202, 114, 0.26);
  }

  .db-chip--red {
    color: var(--red);
    background: var(--red-soft);
    border-color: rgba(255, 120, 148, 0.3);
  }

  .db-chip--violet {
    color: var(--violet-strong);
    background: var(--violet-soft);
    border-color: rgba(154, 99, 255, 0.28);
  }

  .db-hero__title {
    margin: 0;
    max-width: 12ch;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(2.6rem, 6vw, 4.8rem);
    font-weight: 700;
    line-height: 0.96;
    letter-spacing: -0.06em;
  }

  .db-hero__title span {
    color: var(--violet-strong);
  }

  .db-hero__body {
    max-width: 58ch;
    color: var(--text-muted);
    font-size: clamp(0.98rem, 1.4vw, 1.08rem);
    line-height: 1.7;
  }

  .db-hero__actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 14px;
  }

  .db-segment {
    display: inline-grid;
    grid-template-columns: repeat(2, minmax(112px, 1fr));
    gap: 6px;
    padding: 6px;
    border-radius: 18px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.03);
  }

  .db-segment__button {
    border: 0;
    border-radius: 12px;
    padding: 12px 16px;
    background: transparent;
    color: var(--text-soft);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    transition: 160ms ease;
  }

  .db-segment__button:hover {
    color: var(--text);
  }

  .db-segment__button.is-active {
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.03)),
      linear-gradient(135deg, rgba(154, 99, 255, 0.2), rgba(255, 255, 255, 0.03));
    color: var(--text);
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
  }

  .db-control-row {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .db-button {
    min-height: 48px;
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 0 18px;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text);
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    transition: transform 160ms ease, border-color 160ms ease, background 160ms ease, color 160ms ease;
  }

  .db-button:hover {
    transform: translateY(-1px);
  }

  .db-button--success {
    border-color: rgba(91, 240, 177, 0.28);
    background: linear-gradient(180deg, rgba(91, 240, 177, 0.22), rgba(91, 240, 177, 0.08));
    color: var(--green);
  }

  .db-button--danger {
    border-color: rgba(255, 120, 148, 0.28);
    background: linear-gradient(180deg, rgba(255, 120, 148, 0.22), rgba(255, 120, 148, 0.08));
    color: var(--red);
  }

  .db-button--ghost {
    color: var(--text-muted);
  }

  .db-button.is-active {
    color: #07070b;
    border-color: transparent;
  }

  .db-button--success.is-active {
    background: linear-gradient(180deg, #80ffd3, #4de3ab);
    box-shadow: 0 18px 40px -24px rgba(91, 240, 177, 0.72);
  }

  .db-button--danger.is-active {
    background: linear-gradient(180deg, #ff9eb2, #ff6f90);
    box-shadow: 0 18px 40px -24px rgba(255, 120, 148, 0.72);
  }

  .db-note {
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.5;
  }

  .db-note strong {
    color: var(--text);
  }

  .db-hero__visual {
    position: relative;
    display: grid;
    align-items: stretch;
  }

  .db-art {
    position: relative;
    min-height: 320px;
    border-radius: 28px;
    border: 1px solid rgba(255, 255, 255, 0.09);
    background:
      radial-gradient(circle at top, rgba(255, 255, 255, 0.08), transparent 28%),
      linear-gradient(180deg, rgba(18, 18, 28, 0.84), rgba(9, 10, 16, 0.9));
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    overflow: hidden;
  }

  .db-art::before,
  .db-art::after {
    content: '';
    position: absolute;
    border-radius: 26px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    pointer-events: none;
  }

  .db-art::before {
    inset: 18px 18px auto;
    height: 58%;
  }

  .db-art::after {
    inset: auto 16px 18px;
    height: 24%;
    background: linear-gradient(90deg, rgba(126, 77, 255, 0.18), rgba(198, 139, 255, 0.18));
    filter: blur(20px);
    opacity: 0.9;
  }

  .db-art__image {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    transform: translateY(8px) scale(0.98);
    opacity: 0.96;
  }

  .db-floating-note {
    position: absolute;
    display: grid;
    gap: 5px;
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(15, 16, 25, 0.84);
    box-shadow: var(--shadow-md);
    backdrop-filter: blur(18px);
    animation: db-float 6s ease-in-out infinite;
  }

  .db-floating-note--top {
    top: 22px;
    right: 22px;
  }

  .db-floating-note--bottom {
    left: 22px;
    bottom: 24px;
    animation-delay: -3s;
  }

  .db-floating-note__label {
    color: var(--text-soft);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .db-floating-note__value {
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.05em;
  }

  .db-floating-note__sub {
    color: var(--text-muted);
    font-size: 12px;
  }

  .db-metric-grid {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 12px;
  }

  .db-metric-card {
    position: relative;
    overflow: hidden;
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: var(--panel-soft);
    padding: 16px;
    min-height: 120px;
  }

  .db-metric-card::before {
    content: '';
    position: absolute;
    inset: 0 auto auto 0;
    width: 100%;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(198, 139, 255, 0.55), transparent);
  }

  .db-metric-card__label {
    color: var(--text-soft);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .db-metric-card__value {
    display: block;
    margin-top: 14px;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 30px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.05em;
  }

  .db-metric-card__value--green {
    color: var(--green);
  }

  .db-metric-card__value--red {
    color: var(--red);
  }

  .db-metric-card__value--amber {
    color: var(--amber);
  }

  .db-metric-card__value--violet {
    color: var(--violet-strong);
  }

  .db-metric-card__foot {
    margin-top: 10px;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.45;
  }

  .db-layout {
    display: grid;
    grid-template-columns: minmax(0, 1.06fr) minmax(320px, 0.74fr);
    gap: 18px;
  }

  .db-main,
  .db-side {
    display: grid;
    gap: 18px;
  }

  .db-panel__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    padding: 22px 24px 0;
  }

  .db-panel__eyebrow {
    color: var(--text-soft);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .db-panel__title {
    margin: 10px 0 0;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.04em;
  }

  .db-panel__subtitle {
    margin: 8px 0 0;
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1.55;
  }

  .db-panel__tag {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 36px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.03);
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }

  .db-panel__tag::before {
    content: '';
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--violet-strong);
  }

  .db-panel__body {
    padding: 20px 24px 24px;
  }

  .db-position-grid {
    display: grid;
    gap: 16px;
  }

  .db-position {
    position: relative;
    padding: 20px;
    border-radius: 24px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background:
      linear-gradient(180deg, rgba(22, 23, 36, 0.92), rgba(11, 12, 18, 0.88)),
      radial-gradient(circle at top, rgba(255, 255, 255, 0.04), transparent 32%);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
  }

  .db-position__top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  .db-position__symbol {
    margin: 12px 0 0;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(1.3rem, 2.1vw, 1.65rem);
    font-weight: 700;
    letter-spacing: -0.05em;
  }

  .db-side-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    padding: 0 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .db-side-pill--long {
    color: var(--green);
    background: var(--green-soft);
    border: 1px solid rgba(91, 240, 177, 0.28);
  }

  .db-side-pill--short {
    color: var(--red);
    background: var(--red-soft);
    border: 1px solid rgba(255, 120, 148, 0.28);
  }

  .db-position__pnl {
    text-align: right;
  }

  .db-position__pnl strong {
    display: block;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.05em;
  }

  .db-position__pnl span {
    display: block;
    margin-top: 8px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-position__stats {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 10px;
    margin: 18px 0 16px;
  }

  .db-statbox {
    padding: 12px;
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.03);
  }

  .db-statbox__label {
    color: var(--text-soft);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .db-statbox__value {
    display: block;
    margin-top: 8px;
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.4;
  }

  .db-position__footer {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 14px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-position__footer span {
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.02);
    padding: 9px 12px;
  }

  .db-price-line {
    padding: 18px 14px 12px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0.01)),
      radial-gradient(circle at center, rgba(154, 99, 255, 0.08), transparent 56%);
  }

  .db-price-line__bar {
    position: relative;
    height: 42px;
  }

  .db-price-line__track {
    position: absolute;
    inset: 50% 0 auto;
    height: 8px;
    transform: translateY(-50%);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.55);
  }

  .db-price-line__fill {
    position: absolute;
    top: 50%;
    height: 8px;
    transform: translateY(-50%);
    border-radius: 999px;
    transition: 180ms ease;
  }

  .db-price-line__stage {
    position: absolute;
    top: 50%;
    width: 3px;
    height: 14px;
    transform: translate(-50%, -50%);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.26);
  }

  .db-price-line__stage--hit {
    background: var(--violet-strong);
    box-shadow: 0 0 12px rgba(198, 139, 255, 0.6);
  }

  .db-price-line__marker {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 700;
    text-shadow: 0 2px 10px rgba(0, 0, 0, 0.55);
    z-index: 2;
  }

  .db-price-line__face {
    top: calc(50% - 24px);
    transform: translate(-50%, -50%);
    font-size: 18px;
    z-index: 4;
    text-shadow:
      0 0 16px rgba(255, 255, 255, 0.1),
      0 8px 18px rgba(0, 0, 0, 0.8);
  }

  .db-price-line__face--profit {
    color: var(--green);
  }

  .db-price-line__face--loss {
    color: var(--red);
  }

  .db-price-line__face--near {
    color: var(--amber);
    animation: db-pulse 0.9s ease-in-out infinite;
  }

  .db-price-line__labels {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-top: 14px;
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
  }

  .db-price-line__labels span {
    white-space: nowrap;
  }

  .db-mini-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 18px;
  }

  .db-mini-card {
    min-height: 96px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.03);
    padding: 16px;
  }

  .db-mini-card__label {
    color: var(--text-soft);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .db-mini-card__value {
    display: block;
    margin-top: 10px;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.05em;
  }

  .db-wallet-grid {
    display: grid;
    gap: 10px;
  }

  .db-keyval {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    padding: 12px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .db-keyval:last-child {
    border-bottom: 0;
  }

  .db-keyval__key {
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-keyval__value {
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 600;
    text-align: right;
  }

  .db-sparkline {
    margin-top: 16px;
    padding: 10px 0 0;
  }

  .db-config-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 18px;
  }

  .db-config-chip {
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.03);
    padding: 10px 14px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-config-chip strong {
    color: var(--text);
    font-weight: 700;
  }

  .db-insight-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin-top: 18px;
  }

  .db-trade-list {
    display: grid;
    gap: 12px;
  }

  .db-trade-row {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) auto auto;
    align-items: center;
    gap: 14px;
    padding: 16px 18px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.03);
  }

  .db-trade-row__symbol {
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 19px;
    font-weight: 700;
    letter-spacing: -0.04em;
  }

  .db-trade-row__meta {
    margin-top: 6px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-trade-row__center {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 8px;
    color: var(--text-muted);
    font-size: 12px;
  }

  .db-trade-row__pnl {
    min-width: 120px;
    text-align: right;
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    font-weight: 700;
  }

  .db-cooldown-list {
    display: grid;
    gap: 12px;
  }

  .db-cooldown {
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(255, 255, 255, 0.03);
  }

  .db-cooldown__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .db-cooldown__symbol {
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    font-weight: 700;
  }

  .db-cooldown__meta {
    margin-top: 6px;
    color: var(--text-muted);
    font-size: 13px;
  }

  .db-cooldown__bar {
    height: 8px;
    margin-top: 12px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    overflow: hidden;
  }

  .db-cooldown__fill {
    height: 100%;
    border-radius: inherit;
  }

  .db-log-list {
    display: grid;
    gap: 10px;
  }

  .db-log-row {
    display: grid;
    gap: 4px;
    padding: 12px 14px;
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    background: rgba(255, 255, 255, 0.02);
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
  }

  .db-log-row__stamp {
    color: var(--text-soft);
  }

  .db-log-row__msg {
    color: var(--text-muted);
    line-height: 1.6;
    word-break: break-word;
  }

  .db-log-row--green .db-log-row__msg {
    color: var(--green);
  }

  .db-log-row--amber .db-log-row__msg {
    color: var(--amber);
  }

  .db-log-row--red .db-log-row__msg {
    color: var(--red);
  }

  .db-log-row--violet .db-log-row__msg {
    color: var(--violet-strong);
  }

  .db-empty {
    padding: 28px 18px;
    border-radius: 18px;
    border: 1px dashed rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.02);
    color: var(--text-muted);
    text-align: center;
    line-height: 1.6;
  }

  .db-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 8px;
    color: var(--text-soft);
    font-size: 12px;
  }

  .db-footer strong {
    color: var(--text);
  }

  .db-green {
    color: var(--green);
  }

  .db-red {
    color: var(--red);
  }

  .db-amber {
    color: var(--amber);
  }

  .db-violet {
    color: var(--violet-strong);
  }

  @keyframes db-float {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-8px); }
  }

  @keyframes db-pulse {
    0%, 100% { transform: translate(-50%, -50%) scale(1); }
    50% { transform: translate(-50%, -50%) scale(1.12); }
  }

  @media (max-width: 1200px) {
    .db-hero,
    .db-layout {
      grid-template-columns: 1fr;
    }

    .db-metric-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .db-position__stats {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }

  @media (max-width: 900px) {
    .db-topbar,
    .db-panel__head {
      flex-direction: column;
      align-items: flex-start;
    }

    .db-topbar__meta {
      justify-content: flex-start;
    }

    .db-metric-grid,
    .db-mini-grid,
    .db-insight-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .db-trade-row {
      grid-template-columns: 1fr;
      align-items: flex-start;
    }

    .db-trade-row__center,
    .db-trade-row__pnl {
      text-align: left;
      align-items: flex-start;
    }
  }

  @media (max-width: 640px) {
    .db-shell {
      width: min(100% - 18px, 1440px);
    }

    .db-hero,
    .db-panel__body,
    .db-topbar {
      padding-left: 18px;
      padding-right: 18px;
    }

    .db-hero {
      padding-top: 22px;
      padding-bottom: 22px;
    }

    .db-hero__title {
      max-width: none;
    }

    .db-metric-grid,
    .db-mini-grid,
    .db-insight-grid,
    .db-position__stats {
      grid-template-columns: 1fr;
    }

    .db-segment {
      width: 100%;
    }

    .db-control-row {
      width: 100%;
    }

    .db-button {
      flex: 1 1 calc(50% - 5px);
    }
  }
`

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function buildFeedUrl(basePath, fileName) {
  const root = basePath ? basePath.replace(/\/$/, '') : ''
  return `${root}/${fileName}.json?t=${Date.now()}`
}

function parseTradeFeed(text) {
  if (!text.trim()) {
    return []
  }

  try {
    const parsed = JSON.parse(text)
    return Array.isArray(parsed) ? parsed : [parsed]
  } catch {
    return text
      .trim()
      .split('\n')
      .map((line) => {
        try {
          return JSON.parse(line)
        } catch {
          return null
        }
      })
      .filter(Boolean)
  }
}

function parseJsonFeed(text) {
  if (!text.trim()) {
    return null
  }

  return JSON.parse(text)
}

function fmtClock(value) {
  return new Date(value).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function fmtTimestamp(value) {
  if (!value) {
    return '--'
  }

  const raw = typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))
    ? Number(value) < 1e12
      ? Number(value) * 1000
      : Number(value)
    : value

  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) {
    return 'expired'
  }

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = Math.floor(totalSeconds % 60)

  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, '0')}m`
  }

  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`
  }

  return `${seconds}s`
}

function fmtAge(entryTime, nowMs) {
  if (!entryTime) {
    return null
  }

  const openedAt = new Date(entryTime).getTime()
  if (Number.isNaN(openedAt)) {
    return null
  }

  return fmtDuration(Math.floor((nowMs - openedAt) / 1000))
}

function fmtMoney(value, digits = 2) {
  if (!Number.isFinite(Number(value))) {
    return '--'
  }

  return Number(value).toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function fmtSignedMoney(value, digits = 2) {
  if (!Number.isFinite(Number(value))) {
    return '--'
  }

  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${fmtMoney(numeric, digits)}`
}

function fmtNumber(value, digits = 2) {
  if (!Number.isFinite(Number(value))) {
    return '--'
  }

  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

function fmtPrice(value) {
  if (!Number.isFinite(Number(value))) {
    return '--'
  }

  const numeric = Number(value)
  const absolute = Math.abs(numeric)

  if (absolute >= 1000) {
    return numeric.toFixed(2)
  }

  if (absolute >= 1) {
    return numeric.toFixed(4)
  }

  return numeric.toPrecision(5)
}

function fmtPercent(value, digits = 1) {
  if (!Number.isFinite(Number(value))) {
    return '--'
  }

  return `${Number(value).toFixed(digits)}%`
}

function computeProfitFactor(trades) {
  const grossWin = trades.filter((trade) => trade.pnl > 0).reduce((sum, trade) => sum + Number(trade.pnl || 0), 0)
  const grossLoss = trades
    .filter((trade) => Number(trade.pnl || 0) <= 0)
    .reduce((sum, trade) => sum + Math.abs(Number(trade.pnl || 0)), 0)

  if (grossLoss === 0) {
    return grossWin > 0 ? Infinity : null
  }

  return grossWin / grossLoss
}

function computeStreak(trades) {
  if (!trades.length) {
    return 0
  }

  const ordered = [...trades].sort((left, right) => {
    const leftTs = left.timestamp ? new Date(left.timestamp).getTime() : 0
    const rightTs = right.timestamp ? new Date(right.timestamp).getTime() : 0
    return leftTs - rightTs
  })

  const lastWasWin = Number(ordered[ordered.length - 1].pnl || 0) > 0
  let streak = 0

  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const tradeIsWin = Number(ordered[index].pnl || 0) > 0
    if (tradeIsWin === lastWasWin) {
      streak += 1
    } else {
      break
    }
  }

  return lastWasWin ? streak : -streak
}

function computeMaxDrawdown(history) {
  if (history.length < 2) {
    return 0
  }

  let peak = history[0]
  let maxDrawdown = 0

  history.forEach((point) => {
    if (point > peak) {
      peak = point
    }

    const drawdown = peak > 0 ? (peak - point) / peak : 0
    if (drawdown > maxDrawdown) {
      maxDrawdown = drawdown
    }
  })

  return maxDrawdown
}

function toPct(value, min, max) {
  if (max === min) {
    return 50
  }

  return clamp(((value - min) / (max - min)) * 100, 1, 99)
}

function tradeSortTime(trade) {
  return trade.timestamp ? new Date(trade.timestamp).getTime() : 0
}

function toneForTradePnl(value) {
  if (!Number.isFinite(Number(value))) {
    return 'violet'
  }

  if (Number(value) > 0) {
    return 'green'
  }

  if (Number(value) < 0) {
    return 'red'
  }

  return 'amber'
}

function toneForLog(line) {
  const upper = String(line).toUpperCase()

  if (upper.includes('ERROR') || upper.includes('WARN') || upper.includes('FAIL')) {
    return 'red'
  }

  if (upper.includes('SKIP') || upper.includes('COOLDOWN')) {
    return 'amber'
  }

  if (upper.includes('TP') || upper.includes('ENTER') || upper.includes('ARMED')) {
    return 'green'
  }

  return 'violet'
}

function Sparkline({ data, positive }) {
  if (!data || data.length < 2) {
    return null
  }

  const width = 320
  const height = 44
  const low = Math.min(...data)
  const high = Math.max(...data)
  const span = high - low || 1

  const points = data.map((point, index) => {
    const x = (index / (data.length - 1)) * width
    const y = height - ((point - low) / span) * (height - 6) - 3
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const fillPoints = [`0,${height}`, ...points, `${width},${height}`].join(' ')
  const color = positive ? '#5bf0b1' : '#ff7894'
  const gradientId = positive ? 'db-spark-positive' : 'db-spark-negative'

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.24" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={fillPoints} fill={`url(#${gradientId})`} />
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}

function SummaryMetric({ label, value, footnote, tone = 'violet' }) {
  return (
    <article className="db-metric-card">
      <span className="db-metric-card__label">{label}</span>
      <span className={`db-metric-card__value db-metric-card__value--${tone}`}>{value}</span>
      <div className="db-metric-card__foot">{footnote}</div>
    </article>
  )
}

function PriceLine({ position }) {
  const isLong = position.side === 'Buy'
  const entry = Number(position.entry ?? 0)
  const stop = Number(position.stop_price ?? 0)
  const originalStop = Number(position.original_stop ?? position.stop_price ?? 0)
  const takeProfit = Number(position.take_profit ?? 0)
  const mark = position.mark_price != null ? Number(position.mark_price) : null
  const stages = Array.isArray(position.tp_stages) ? position.tp_stages : []

  const points = [entry, stop, originalStop, takeProfit, mark, ...stages.map((stage) => Number(stage.price))]
    .filter((value) => Number.isFinite(value))

  if (points.length < 2) {
    return null
  }

  const low = Math.min(...points)
  const high = Math.max(...points)
  const fillLeft = Math.min(toPct(entry, low, high), toPct(stop, low, high))
  const fillRight = Math.max(toPct(entry, low, high), toPct(stop, low, high))
  const fillWidth = fillRight - fillLeft

  const inProfit = mark == null ? null : isLong ? mark > entry : mark < entry
  const fillColor = inProfit === true
    ? 'linear-gradient(90deg, rgba(91, 240, 177, 0.3), rgba(134, 241, 255, 0.3))'
    : inProfit === false
      ? 'linear-gradient(90deg, rgba(255, 120, 148, 0.3), rgba(255, 202, 114, 0.2))'
      : 'linear-gradient(90deg, rgba(154, 99, 255, 0.24), rgba(134, 241, 255, 0.18))'

  let face = '(⁠◔⁠‿⁠◔⁠)'
  let faceClass = 'db-price-line__face--profit'

  if (mark != null) {
    const losing = isLong ? mark < entry : mark > entry
    if (losing) {
      face = 'ರ⁠╭⁠╮⁠ರ'
      faceClass = 'db-price-line__face--loss'
    } else {
      const totalDistance = Math.abs(takeProfit - entry)
      const distanceToTakeProfit = Math.abs(takeProfit - mark)
      const progress = totalDistance > 0 ? distanceToTakeProfit / totalDistance : 1
      if (progress < 0.15) {
        face = '(⁠☆⁠▽⁠☆⁠)'
        faceClass = 'db-price-line__face--near'
      }
    }
  }

  return (
    <div className="db-price-line">
      <div className="db-price-line__bar">
        <div className="db-price-line__track" />
        {fillWidth > 0.5 && (
          <div
            className="db-price-line__fill"
            style={{
              left: `${fillLeft}%`,
              width: `${fillWidth}%`,
              background: fillColor,
            }}
          />
        )}

        {stages.map((stage, index) => (
          <div
            key={`${stage.price}-${index}`}
            className={`db-price-line__stage${stage.hit ? ' db-price-line__stage--hit' : ''}`}
            style={{ left: `${toPct(Number(stage.price), low, high)}%` }}
            title={`TP ${index + 1}: ${fmtPrice(stage.price)}${stage.hit ? ' hit' : ''}`}
          />
        ))}

        <span className="db-price-line__marker" style={{ left: `${toPct(originalStop, low, high)}%`, color: '#78475e' }}>
          x
        </span>
        <span className="db-price-line__marker" style={{ left: `${toPct(stop, low, high)}%`, color: '#ff7894' }}>
          S
        </span>
        <span className="db-price-line__marker" style={{ left: `${toPct(entry, low, high)}%`, color: '#ffca72' }}>
          E
        </span>
        <span className="db-price-line__marker" style={{ left: `${toPct(takeProfit, low, high)}%`, color: '#86f1ff' }}>
          T
        </span>

        {mark != null && (
          <span
            className={`db-price-line__marker db-price-line__face ${faceClass}`}
            style={{ left: `${toPct(mark, low, high)}%` }}
          >
            {face}
          </span>
        )}
      </div>

      <div className="db-price-line__labels">
        <span>STOP {fmtPrice(stop)}</span>
        <span>ENTRY {fmtPrice(entry)}</span>
        <span>TARGET {fmtPrice(takeProfit)}</span>
      </div>
    </div>
  )
}

function LogRow({ line }) {
  const boundary = String(line).indexOf(']')
  const stamp = boundary >= 0 ? String(line).slice(0, boundary + 1) : 'log'
  const message = boundary >= 0 ? String(line).slice(boundary + 1).trim() : String(line)
  const tone = toneForLog(line)

  return (
    <div className={`db-log-row db-log-row--${tone}`}>
      <span className="db-log-row__stamp">{stamp}</span>
      <span className="db-log-row__msg">{message}</span>
    </div>
  )
}

export default function SimDashboard({
  basePath = '',
  pollMs = DEFAULT_POLL_MS,
  initBalance = DEFAULT_INIT_BALANCE,
  simSession = DEFAULT_SESSION,
}) {
  const {
    user,
    viewportHeight,
    isTelegram,
    haptic,
    safeAreaTop,
    safeAreaBottom,
  } = useTelegram()

  const [mode, setMode] = useState(DEFAULT_MODE)
  const [account, setAccount] = useState({ balance: initBalance, positions: [] })
  const [trades, setTrades] = useState([])
  const [cooldowns, setCooldowns] = useState({ last_exit: {}, fast_track: {} })
  const [logs, setLogs] = useState([])
  const [config, setConfig] = useState(null)
  const [tickMs, setTickMs] = useState(Date.now())
  const [pollStatus, setPollStatus] = useState('ok')
  const [lastPollMs, setLastPollMs] = useState(null)
  const [botEnabled, setBotEnabled] = useState(true)
  const [sessionStartEquity, setSessionStartEquity] = useState(null)
  const [controlNotice, setControlNotice] = useState('Control channel is ready.')
  const [controlTone, setControlTone] = useState('violet')

  const modeRef = useRef(mode)
  const equityHistory = useRef([])

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    if (config && typeof config.enabled === 'boolean') {
      setBotEnabled(config.enabled)
    }
  }, [config])

  useEffect(() => {
    equityHistory.current = []
    setAccount({ balance: initBalance, positions: [] })
    setTrades([])
    setCooldowns({ last_exit: {}, fast_track: {} })
    setLogs([])
    setConfig(null)
    setLastPollMs(null)
    setSessionStartEquity(null)
    setControlNotice(mode === 'live' ? 'Live feed armed.' : 'Simulation feed selected. Surface sim JSON in public/ to populate it.')
    setControlTone(mode === 'live' ? 'green' : 'amber')
  }, [initBalance, mode])

  useEffect(() => {
    const timerId = window.setInterval(() => setTickMs(Date.now()), 1000)
    return () => window.clearInterval(timerId)
  }, [])

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      const requestedMode = modeRef.current
      const feed = FEEDS[requestedMode]

      const requests = await Promise.allSettled([
        fetch(buildFeedUrl(basePath, feed.account)).then(async (response) => {
          if (!response.ok) {
            throw new Error(`${feed.account}.json ${response.status}`)
          }

          return parseJsonFeed(await response.text())
        }),
        fetch(buildFeedUrl(basePath, feed.trades)).then(async (response) => {
          if (!response.ok) {
            throw new Error(`${feed.trades}.json ${response.status}`)
          }

          return parseTradeFeed(await response.text())
        }),
        fetch(buildFeedUrl(basePath, feed.cooldowns)).then(async (response) => {
          if (!response.ok) {
            throw new Error(`${feed.cooldowns}.json ${response.status}`)
          }

          return parseJsonFeed(await response.text())
        }),
        fetch(buildFeedUrl(basePath, feed.logs)).then(async (response) => {
          if (!response.ok) {
            throw new Error(`${feed.logs}.json ${response.status}`)
          }

          return parseJsonFeed(await response.text())
        }),
        fetch(buildFeedUrl(basePath, feed.config)).then(async (response) => {
          if (!response.ok) {
            throw new Error(`${feed.config}.json ${response.status}`)
          }

          return parseJsonFeed(await response.text())
        }),
      ])

      if (cancelled || requestedMode !== modeRef.current) {
        return
      }

      let anyOk = false

      if (requests[0].status === 'fulfilled' && requests[0].value) {
        setAccount(requests[0].value)
        anyOk = true
      }

      if (requests[1].status === 'fulfilled') {
        setTrades(Array.isArray(requests[1].value) ? requests[1].value : [])
        anyOk = true
      }

      if (requests[2].status === 'fulfilled' && requests[2].value) {
        setCooldowns(requests[2].value)
        anyOk = true
      }

      if (requests[3].status === 'fulfilled' && requests[3].value) {
        setLogs(Array.isArray(requests[3].value) ? requests[3].value : [])
        anyOk = true
      }

      if (requests[4].status === 'fulfilled' && requests[4].value) {
        setConfig(requests[4].value)
        anyOk = true
      }

      if (requests[0].status === 'fulfilled' && requests[0].value) {
        const nextAccount = requests[0].value
        const nextPositions = Array.isArray(nextAccount.positions) ? nextAccount.positions : []
        const nextUsedBalance = Number(nextAccount.used_balance ?? nextPositions.reduce((sum, position) => sum + Number(position.margin || 0), 0))
        const nextUpnl = nextPositions.reduce((sum, position) => {
          if (position.mark_price == null) {
            return sum
          }

          const entry = Number(position.entry ?? 0)
          const mark = Number(position.mark_price)
          const size = Number(position.size ?? 0)
          return sum + (position.side === 'Buy' ? (mark - entry) * size : (entry - mark) * size)
        }, 0)

        const nextBalance = Number(nextAccount.balance ?? 0)
        const nextEquity = nextUsedBalance > nextBalance ? nextBalance + nextUpnl : nextBalance + nextUpnl
        setSessionStartEquity((previous) => (previous == null ? nextEquity : previous))
      }

      setPollStatus(anyOk ? 'ok' : 'err')

      if (anyOk) {
        setLastPollMs(Date.now())
      }

      if (isTelegram && haptic) {
        if (!anyOk && pollStatus === 'ok') {
          haptic.notify('error')
        } else if (anyOk && pollStatus === 'err') {
          haptic.notify('success')
        }
      }
    }

    poll()
    const intervalId = window.setInterval(poll, pollMs)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [basePath, haptic, isTelegram, mode, pollMs, pollStatus])

  const feed = FEEDS[mode]
  const positions = Array.isArray(account.positions) ? account.positions : []
  const usedBalance = Number(account.used_balance ?? positions.reduce((sum, position) => sum + Number(position.margin || 0), 0))
  const totalBalance = Number(account.balance ?? 0)
  const freeBalance = Number(account.free_balance ?? Math.max(totalBalance - usedBalance, 0))

  const currentUpnl = positions.reduce((sum, position) => {
    if (position.mark_price == null) {
      return sum
    }

    const entry = Number(position.entry ?? 0)
    const mark = Number(position.mark_price)
    const size = Number(position.size ?? 0)
    return sum + (position.side === 'Buy' ? (mark - entry) * size : (entry - mark) * size)
  }, 0)

  const markedEquity = totalBalance + currentUpnl
  const sessionDelta = sessionStartEquity == null ? 0 : markedEquity - sessionStartEquity

  useEffect(() => {
    if (markedEquity > 0) {
      equityHistory.current.push(markedEquity)
      if (equityHistory.current.length > MAX_EQUITY_HISTORY) {
        equityHistory.current.shift()
      }
    }
  }, [markedEquity])

  const sortedTrades = useMemo(
    () => [...trades].sort((left, right) => tradeSortTime(right) - tradeSortTime(left)),
    [trades]
  )
  const recentTrades = sortedTrades.slice(0, TRADE_HISTORY_LIMIT)
  const wins = trades.filter((trade) => Number(trade.pnl || 0) > 0)
  const losses = trades.filter((trade) => Number(trade.pnl || 0) <= 0)
  const totalTrades = trades.length
  const winRate = totalTrades > 0 ? (wins.length / totalTrades) * 100 : 0
  const totalClosedPnl = trades.reduce((sum, trade) => sum + Number(trade.pnl || 0), 0)
  const averagePnl = totalTrades > 0 ? totalClosedPnl / totalTrades : null
  const profitFactor = useMemo(() => computeProfitFactor(trades), [trades])
  const streak = useMemo(() => computeStreak(trades), [trades])
  const maxDrawdown = computeMaxDrawdown(equityHistory.current)

  const insights = useMemo(() => {
    if (!trades.length) {
      return null
    }

    const byHour = {}
    const bySymbol = {}
    let winHoldTotal = 0
    let winHoldCount = 0
    let lossHoldTotal = 0
    let lossHoldCount = 0

    trades.forEach((trade) => {
      const timestamp = trade.timestamp ? new Date(trade.timestamp) : new Date()
      const hour = Number.isNaN(timestamp.getTime()) ? '0' : String(timestamp.getHours())
      const symbol = trade.symbol || 'UNK'
      const pnl = Number(trade.pnl || 0)

      if (!byHour[hour]) {
        byHour[hour] = []
      }
      if (!bySymbol[symbol]) {
        bySymbol[symbol] = []
      }

      byHour[hour].push(pnl)
      bySymbol[symbol].push(pnl)

      if (trade.hold_time_s != null) {
        if (pnl > 0) {
          winHoldTotal += Number(trade.hold_time_s)
          winHoldCount += 1
        } else {
          lossHoldTotal += Number(trade.hold_time_s)
          lossHoldCount += 1
        }
      }
    })

    let bestHour = null
    let bestHourRate = -1
    Object.entries(byHour).forEach(([hour, values]) => {
      if (values.length < 2) {
        return
      }

      const winsAtHour = values.filter((value) => value > 0).length
      const rate = winsAtHour / values.length
      if (rate > bestHourRate) {
        bestHourRate = rate
        bestHour = hour
      }
    })

    let bestSymbol = null
    let bestSymbolPnl = -Infinity
    Object.entries(bySymbol).forEach(([symbol, values]) => {
      const pnl = values.reduce((sum, value) => sum + value, 0)
      if (pnl > bestSymbolPnl) {
        bestSymbolPnl = pnl
        bestSymbol = symbol
      }
    })

    return {
      bestHour: bestHour == null ? '--' : `${bestHour}:00`,
      bestSymbol: bestSymbol || '--',
      avgWinHold: winHoldCount ? `${Math.round(winHoldTotal / winHoldCount / 60)}m` : '--',
      avgLossHold: lossHoldCount ? `${Math.round(lossHoldTotal / lossHoldCount / 60)}m` : '--',
    }
  }, [trades])

  const errorCount = logs.filter((line) => {
    const upper = String(line).toUpperCase()
    return upper.includes('ERROR') || upper.includes('WARN') || upper.includes('FAIL')
  }).length

  const cooldownRows = []
  const nowSeconds = tickMs / 1000

  Object.entries(cooldowns.last_exit ?? {}).forEach(([symbol, entry]) => {
    const [timestamp, score] = Array.isArray(entry) ? entry : [Number(entry), null]
    const remaining = Math.max(0, MAX_REENTRY_COOLDOWN_SECS - (nowSeconds - Number(timestamp)))
    if (remaining > 0) {
      cooldownRows.push({
        symbol,
        type: 'Re-entry',
        score,
        remaining,
        max: MAX_REENTRY_COOLDOWN_SECS,
      })
    }
  })

  Object.entries(cooldowns.fast_track ?? {}).forEach(([symbol, timestamp]) => {
    const remaining = Math.max(0, FAST_TRACK_COOLDOWN_SECS - (nowSeconds - Number(timestamp)))
    if (remaining > 0) {
      cooldownRows.push({
        symbol,
        type: 'Fast-track',
        score: null,
        remaining,
        max: FAST_TRACK_COOLDOWN_SECS,
      })
    }
  })

  cooldownRows.sort((left, right) => left.remaining - right.remaining)

  const strategyChips = config
    ? [
        ['Direction', config.direction ?? '--'],
        ['Timeframe', config.timeframe ?? '--'],
        ['Min score', fmtNumber(config.min_score, 0)],
        ['Gap', fmtNumber(config.min_score_gap, 0)],
        ['Workers', fmtNumber(config.workers, 0)],
        ['Interval', config.interval ? `${config.interval}s` : '--'],
        ['Rate', config.rate_limit_rps ? `${fmtNumber(config.rate_limit_rps, 1)} rps` : '--'],
      ]
    : []

  const healthTone = pollStatus === 'err' ? 'red' : errorCount > 0 ? 'amber' : botEnabled ? 'green' : 'violet'
  const healthLabel = pollStatus === 'err'
    ? 'Feed lost'
    : errorCount > 0
      ? 'Needs attention'
      : botEnabled
        ? 'Engine healthy'
        : 'Paused by config'

  const controlNoticeClass = controlTone === 'green'
    ? 'db-green'
    : controlTone === 'red'
      ? 'db-red'
      : controlTone === 'amber'
        ? 'db-amber'
        : 'db-violet'

  const tgName = user
    ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username || 'tg user'
    : null

  const rootStyle = {
    height: `${viewportHeight}px`,
    paddingTop: safeAreaTop > 0 ? `${safeAreaTop}px` : undefined,
    paddingBottom: safeAreaBottom > 0 ? `${safeAreaBottom}px` : undefined,
  }

  const sendBotCommand = async (enabled) => {
    setControlNotice(`${enabled ? 'Start' : 'Stop'} command sent…`)
    setControlTone('violet')

    if (haptic) {
      haptic.impact('heavy')
    }

    try {
      const apiBase = window.location.origin.replace(':5173', ':8000')
      const response = await fetch(`${apiBase}/api/control`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ is_live: mode === 'live', enabled }),
      })

      if (!response.ok) {
        throw new Error(`control ${response.status}`)
      }

      setBotEnabled(enabled)
      setControlNotice(enabled ? 'Engine start acknowledged.' : 'Engine stop acknowledged.')
      setControlTone('green')
    } catch {
      setBotEnabled(enabled)
      setControlNotice(enabled
        ? 'Control API did not answer, but the UI flipped to start for responsiveness.'
        : 'Control API did not answer, but the UI flipped to stop for responsiveness.')
      setControlTone('amber')
    }
  }

  return (
    <div className="db" style={rootStyle}>
      <style>{CSS}</style>

      <div className="db-shell">
        <header className="db-card db-topbar">
          <div className="db-brand">
            <div className="db-brand__mark">FB</div>
            <div className="db-brand__copy">
              <span className="db-kicker">Layered trading cockpit</span>
              <h1 className="db-brand__title">FangBlenny Dashboard</h1>
            </div>
          </div>

          <div className="db-topbar__meta">
            <span className="db-session">Session {simSession}</span>
            {tgName && <span className="db-user">@{tgName}</span>}
            <span className="db-time">{fmtClock(tickMs)}</span>
          </div>
        </header>

        <section className="db-card db-hero">
          <div className="db-hero__copy">
            <div className="db-chip-row">
              <span className={`db-chip db-chip--${healthTone}`}>{healthLabel}</span>
              <span className="db-chip db-chip--violet">{feed.label}</span>
              <span className={`db-chip db-chip--${pollStatus === 'ok' ? 'green' : 'red'}`}>
                {pollStatus === 'ok' ? 'Feed online' : 'Polling error'}
              </span>
            </div>

            <h2 className="db-hero__title">
              More control,
              <br />
              less guesswork,
              <br />
              <span>same face-driven price line.</span>
            </h2>

            <div className="db-hero__body">
              This pass pushes the dashboard toward the layered black-and-violet mockup in the local hero art,
              while keeping the price line with the little mood faces front and center inside every open position.
            </div>

            <div className="db-hero__actions">
              <div className="db-segment">
                <button
                  className={`db-segment__button${mode === 'sim' ? ' is-active' : ''}`}
                  onClick={() => {
                    if (mode !== 'sim') {
                      setMode('sim')
                      if (haptic) {
                        haptic.selection()
                      }
                    }
                  }}
                  type="button"
                >
                  Simulation
                </button>
                <button
                  className={`db-segment__button${mode === 'live' ? ' is-active' : ''}`}
                  onClick={() => {
                    if (mode !== 'live') {
                      setMode('live')
                      if (haptic) {
                        haptic.selection()
                      }
                    }
                  }}
                  type="button"
                >
                  Live
                </button>
              </div>

              <div className="db-control-row">
                <button
                  className={`db-button db-button--success${botEnabled ? ' is-active' : ''}`}
                  onClick={() => {
                    if (!botEnabled) {
                      sendBotCommand(true)
                    }
                  }}
                  type="button"
                >
                  Start Engine
                </button>
                <button
                  className={`db-button db-button--danger${!botEnabled ? ' is-active' : ''}`}
                  onClick={() => {
                    if (botEnabled) {
                      sendBotCommand(false)
                    }
                  }}
                  type="button"
                >
                  Stop Engine
                </button>
              </div>
            </div>

            <div className="db-note">
              <strong className={controlNoticeClass}>{controlNotice}</strong>
              {' '}
              Last good poll: {lastPollMs ? fmtTimestamp(lastPollMs) : 'waiting for first response'}.
            </div>
          </div>

          <div className="db-hero__visual">
            <div className="db-art">
              <img className="db-art__image" src={heroArt} alt="" />

              <div className="db-floating-note db-floating-note--top">
                <span className="db-floating-note__label">Mode</span>
                <span className="db-floating-note__value">{mode === 'live' ? 'LIVE' : 'SIM'}</span>
                <span className="db-floating-note__sub">{feed.modeLabel}</span>
              </div>

              <div className="db-floating-note db-floating-note--bottom">
                <span className="db-floating-note__label">Open risk</span>
                <span className="db-floating-note__value">{positions.length}</span>
                <span className="db-floating-note__sub">{cooldownRows.length} active cooldowns</span>
              </div>
            </div>
          </div>

          <div className="db-metric-grid">
            <SummaryMetric
              label="Marked equity"
              value={fmtMoney(markedEquity)}
              footnote={`${fmtMoney(totalBalance)} wallet + ${fmtSignedMoney(currentUpnl)} live uPnL`}
              tone={sessionDelta >= 0 ? 'green' : 'red'}
            />
            <SummaryMetric
              label="Session delta"
              value={fmtSignedMoney(sessionDelta)}
              footnote={sessionStartEquity == null ? 'Waiting for first baseline sample' : `Since ${fmtTimestamp(lastPollMs || tickMs)}`}
              tone={sessionDelta > 0 ? 'green' : sessionDelta < 0 ? 'red' : 'violet'}
            />
            <SummaryMetric
              label="Realized PnL"
              value={fmtSignedMoney(totalClosedPnl)}
              footnote={`${wins.length} wins, ${losses.length} losses`}
              tone={totalClosedPnl > 0 ? 'green' : totalClosedPnl < 0 ? 'red' : 'violet'}
            />
            <SummaryMetric
              label="Open positions"
              value={fmtNumber(positions.length, 0)}
              footnote={positions.length ? `${fmtMoney(usedBalance)} margin committed` : 'Book is flat'}
              tone={positions.length ? 'amber' : 'violet'}
            />
            <SummaryMetric
              label="Win rate"
              value={totalTrades ? fmtPercent(winRate, 0) : '--'}
              footnote={totalTrades ? `${fmtNumber(totalTrades, 0)} closed trades` : 'No closes yet'}
              tone={winRate >= 55 ? 'green' : winRate > 0 ? 'amber' : 'violet'}
            />
            <SummaryMetric
              label="Alert load"
              value={fmtNumber(errorCount, 0)}
              footnote={errorCount ? 'Log scan sees warnings or errors' : 'Log feed looks clean right now'}
              tone={errorCount ? 'red' : 'green'}
            />
          </div>
        </section>

        <div className="db-layout">
          <div className="db-main">
            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Live exposure</div>
                  <h3 className="db-panel__title">Open Positions</h3>
                  <p className="db-panel__subtitle">
                    The new shell is calmer, but the face-driven price line stays exactly where you need it: under every live position.
                  </p>
                </div>
                <span className="db-panel__tag">
                  {positions.length ? `${positions.length} active` : 'No exposure'}
                </span>
              </div>

              <div className="db-panel__body">
                {positions.length === 0 ? (
                  <div className="db-empty">No open positions right now.</div>
                ) : (
                  <div className="db-position-grid">
                    {positions.map((position) => {
                      const isLong = position.side === 'Buy'
                      const entry = Number(position.entry ?? 0)
                      const mark = position.mark_price != null ? Number(position.mark_price) : null
                      const margin = Number(position.margin ?? 0)
                      const leverage = Number(position.leverage ?? 0)
                      const size = Number(position.size ?? 0)
                      const pnl = mark == null ? null : isLong ? (mark - entry) * size : (entry - mark) * size
                      const pnlPct = pnl == null || margin <= 0 ? null : (pnl / margin) * 100
                      const tpStages = Array.isArray(position.tp_stages) ? position.tp_stages : []
                      const hitStages = tpStages.filter((stage) => stage.hit).length

                      return (
                        <article className="db-position" key={`${position.symbol}-${position.entry_time}`}>
                          <div className="db-position__top">
                            <div>
                              <span className={`db-side-pill ${isLong ? 'db-side-pill--long' : 'db-side-pill--short'}`}>
                                {isLong ? 'Long' : 'Short'}
                              </span>
                              <h4 className="db-position__symbol">{position.symbol}</h4>
                            </div>

                            <div className="db-position__pnl">
                              <strong className={pnl == null ? '' : pnl >= 0 ? 'db-green' : 'db-red'}>
                                {pnl == null ? '--' : fmtSignedMoney(pnl, 3)}
                              </strong>
                              <span>{pnlPct == null ? 'Waiting for live mark' : `${fmtPercent(pnlPct, 1)} on margin`}</span>
                            </div>
                          </div>

                          <div className="db-position__stats">
                            <div className="db-statbox">
                              <span className="db-statbox__label">Entry</span>
                              <span className="db-statbox__value">{fmtPrice(entry)}</span>
                            </div>
                            <div className="db-statbox">
                              <span className="db-statbox__label">Mark</span>
                              <span className="db-statbox__value">{fmtPrice(mark)}</span>
                            </div>
                            <div className="db-statbox">
                              <span className="db-statbox__label">Stop</span>
                              <span className="db-statbox__value">{fmtPrice(position.stop_price)}</span>
                            </div>
                            <div className="db-statbox">
                              <span className="db-statbox__label">Target</span>
                              <span className="db-statbox__value">{fmtPrice(position.take_profit)}</span>
                            </div>
                            <div className="db-statbox">
                              <span className="db-statbox__label">Margin</span>
                              <span className="db-statbox__value">{fmtMoney(margin)}</span>
                            </div>
                            <div className="db-statbox">
                              <span className="db-statbox__label">Leverage</span>
                              <span className="db-statbox__value">{fmtNumber(leverage, 0)}x</span>
                            </div>
                          </div>

                          <PriceLine position={position} />

                          <div className="db-position__footer">
                            <span>Opened {fmtAge(position.entry_time, tickMs) || '--'} ago</span>
                            <span>Score {fmtNumber(position.entry_score, 0)}</span>
                            <span>{fmtNumber(hitStages, 0)}/{fmtNumber(tpStages.length, 0)} TP stages hit</span>
                            <span>{position.native_orders_armed ? 'Native exits armed' : 'Native exits pending'}</span>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                )}
              </div>
            </section>

            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Closed flow</div>
                  <h3 className="db-panel__title">Recent Trades</h3>
                  <p className="db-panel__subtitle">
                    A tighter ledger of closes with direction, hold time, and realized result.
                  </p>
                </div>
                <span className="db-panel__tag">
                  {recentTrades.length} shown
                </span>
              </div>

              <div className="db-panel__body">
                {recentTrades.length === 0 ? (
                  <div className="db-empty">No trade history yet.</div>
                ) : (
                  <div className="db-trade-list">
                    {recentTrades.map((trade, index) => {
                      const holdMinutes = trade.hold_time_s != null ? Math.round(Number(trade.hold_time_s) / 60) : null
                      const pnlTone = toneForTradePnl(trade.pnl)

                      return (
                        <article className="db-trade-row" key={`${trade.symbol}-${trade.timestamp}-${index}`}>
                          <div>
                            <div className="db-trade-row__symbol">{trade.symbol}</div>
                            <div className="db-trade-row__meta">
                              {fmtTimestamp(trade.timestamp)} · {trade.reason || 'close'}
                            </div>
                          </div>

                          <div className="db-trade-row__center">
                            <span className={`db-side-pill ${trade.direction === 'SHORT' ? 'db-side-pill--short' : 'db-side-pill--long'}`}>
                              {trade.direction || 'LONG'}
                            </span>
                            <span>{holdMinutes == null ? '--' : `${holdMinutes}m hold`}</span>
                          </div>

                          <div className={`db-trade-row__pnl db-${pnlTone}`}>
                            {fmtSignedMoney(trade.pnl, 4)}
                          </div>
                        </article>
                      )
                    })}
                  </div>
                )}
              </div>
            </section>
          </div>

          <aside className="db-side">
            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Capital</div>
                  <h3 className="db-panel__title">Wallet Snapshot</h3>
                  <p className="db-panel__subtitle">
                    Balance, available margin, live mark-to-market, and a short equity trace.
                  </p>
                </div>
              </div>

              <div className="db-panel__body">
                <div className="db-mini-grid">
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Available</span>
                    <span className="db-mini-card__value">{fmtMoney(freeBalance)}</span>
                  </div>
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Used</span>
                    <span className="db-mini-card__value">{fmtMoney(usedBalance)}</span>
                  </div>
                </div>

                <div className="db-wallet-grid">
                  <div className="db-keyval">
                    <span className="db-keyval__key">Wallet balance</span>
                    <span className="db-keyval__value">{fmtMoney(totalBalance)}</span>
                  </div>
                  <div className="db-keyval">
                    <span className="db-keyval__key">Live uPnL</span>
                    <span className={`db-keyval__value ${currentUpnl >= 0 ? 'db-green' : 'db-red'}`}>
                      {fmtSignedMoney(currentUpnl)}
                    </span>
                  </div>
                  <div className="db-keyval">
                    <span className="db-keyval__key">Marked equity</span>
                    <span className={`db-keyval__value ${sessionDelta >= 0 ? 'db-green' : 'db-red'}`}>
                      {fmtMoney(markedEquity)}
                    </span>
                  </div>
                  <div className="db-keyval">
                    <span className="db-keyval__key">Session delta</span>
                    <span className={`db-keyval__value ${sessionDelta >= 0 ? 'db-green' : 'db-red'}`}>
                      {fmtSignedMoney(sessionDelta)}
                    </span>
                  </div>
                </div>

                <div className="db-sparkline">
                  <Sparkline data={equityHistory.current} positive={sessionDelta >= 0} />
                </div>
              </div>
            </section>

            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Performance</div>
                  <h3 className="db-panel__title">Strategy Pulse</h3>
                  <p className="db-panel__subtitle">
                    Keep the high-signal stats and config together instead of scattering them across the page.
                  </p>
                </div>
              </div>

              <div className="db-panel__body">
                <div className="db-mini-grid">
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Profit factor</span>
                    <span className="db-mini-card__value">
                      {profitFactor == null ? '--' : profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}
                    </span>
                  </div>
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Max drawdown</span>
                    <span className="db-mini-card__value">{maxDrawdown > 0 ? fmtPercent(maxDrawdown * 100, 1) : '--'}</span>
                  </div>
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Avg trade</span>
                    <span className="db-mini-card__value">{averagePnl == null ? '--' : fmtSignedMoney(averagePnl, 4)}</span>
                  </div>
                  <div className="db-mini-card">
                    <span className="db-mini-card__label">Streak</span>
                    <span className={`db-mini-card__value ${streak > 0 ? 'db-green' : streak < 0 ? 'db-red' : ''}`}>
                      {streak === 0 ? '--' : streak > 0 ? `${streak}W` : `${Math.abs(streak)}L`}
                    </span>
                  </div>
                </div>

                {strategyChips.length > 0 && (
                  <div className="db-config-grid">
                    {strategyChips.map(([label, value]) => (
                      <div className="db-config-chip" key={label}>
                        <strong>{label}:</strong> {value}
                      </div>
                    ))}
                  </div>
                )}

                {insights && (
                  <div className="db-insight-grid">
                    <div className="db-mini-card">
                      <span className="db-mini-card__label">Power hour</span>
                      <span className="db-mini-card__value">{insights.bestHour}</span>
                    </div>
                    <div className="db-mini-card">
                      <span className="db-mini-card__label">Best symbol</span>
                      <span className="db-mini-card__value">{insights.bestSymbol}</span>
                    </div>
                    <div className="db-mini-card">
                      <span className="db-mini-card__label">Avg win hold</span>
                      <span className="db-mini-card__value">{insights.avgWinHold}</span>
                    </div>
                    <div className="db-mini-card">
                      <span className="db-mini-card__label">Avg loss hold</span>
                      <span className="db-mini-card__value">{insights.avgLossHold}</span>
                    </div>
                  </div>
                )}
              </div>
            </section>

            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Queueing</div>
                  <h3 className="db-panel__title">Cooldowns</h3>
                  <p className="db-panel__subtitle">
                    Cooldowns stay visible, but the presentation is less terminal and more control surface.
                  </p>
                </div>
                <span className="db-panel__tag">{cooldownRows.length} active</span>
              </div>

              <div className="db-panel__body">
                {cooldownRows.length === 0 ? (
                  <div className="db-empty">No active cooldowns.</div>
                ) : (
                  <div className="db-cooldown-list">
                    {cooldownRows.map((cooldown) => {
                      const progress = clamp(((cooldown.max - cooldown.remaining) / cooldown.max) * 100, 0, 100)
                      const fillColor = cooldown.type === 'Fast-track'
                        ? 'linear-gradient(90deg, rgba(134, 241, 255, 0.9), rgba(154, 99, 255, 0.85))'
                        : 'linear-gradient(90deg, rgba(255, 120, 148, 0.9), rgba(255, 202, 114, 0.82))'

                      return (
                        <div className="db-cooldown" key={`${cooldown.symbol}-${cooldown.type}`}>
                          <div className="db-cooldown__head">
                            <span className="db-cooldown__symbol">{cooldown.symbol}</span>
                            <span className={`db-side-pill ${cooldown.type === 'Fast-track' ? 'db-side-pill--long' : 'db-side-pill--short'}`}>
                              {cooldown.type}
                            </span>
                          </div>
                          <div className="db-cooldown__meta">
                            {cooldown.score == null ? 'No score attached' : `Score ${cooldown.score}`} · {fmtDuration(cooldown.remaining)} left
                          </div>
                          <div className="db-cooldown__bar">
                            <div className="db-cooldown__fill" style={{ width: `${progress}%`, background: fillColor }} />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </section>

            <section className="db-card">
              <div className="db-panel__head">
                <div>
                  <div className="db-panel__eyebrow">Live feed</div>
                  <h3 className="db-panel__title">System Log</h3>
                  <p className="db-panel__subtitle">
                    Recent engine output, color-grouped for failures, skips, and fills.
                  </p>
                </div>
                <span className="db-panel__tag">{logs.length} entries</span>
              </div>

              <div className="db-panel__body">
                {logs.length === 0 ? (
                  <div className="db-empty">No log lines available.</div>
                ) : (
                  <div className="db-log-list">
                    {[...logs].reverse().slice(0, MAX_LOG_LINES).map((line, index) => (
                      <LogRow key={`${line}-${index}`} line={line} />
                    ))}
                  </div>
                )}
              </div>
            </section>
          </aside>
        </div>

        <footer className="db-footer">
          <span>
            <strong>FancyBot</strong> · {feed.label} · polling every {pollMs}ms
          </span>
          <span>{config?.timestamp ? `config ${fmtTimestamp(config.timestamp)}` : 'waiting for config timestamp'}</span>
        </footer>
      </div>
    </div>
  )
}
