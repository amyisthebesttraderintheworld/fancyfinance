#!/usr/bin/env python3
"""
Phemex Automated Trading Bot
==============================
Runs the dual scanner on a schedule, picks the best setups, and auto-executes.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import logging
import math
import os
import re
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path configuration ───────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import requests
import urllib.parse
from websocket import WebSocketApp
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from colorama import init, Fore, Style
from dotenv import load_dotenv

if sys.platform != "win32":
    import select
    import termios
    import tty

import blessed
import websocket
from core import bot_core

# ── Scanner imports ──────────────────────────────────────────────────
try:
    from legacy import phemex_common as pc
    from scanners import long as scanner_long
    from scanners import short as scanner_short
except ImportError:
    # Handle other import paths if necessary
    pass

load_dotenv()
init(autoreset=True)

# ────────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────────
def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip().strip("'\"").strip()


SCRIPT_DIR          = Path(__file__).parent
DASHBOARD_PUBLIC_DIR = SCRIPT_DIR.parent / "dashboard" / "public"
LIVE_ACCOUNT_FILE   = DASHBOARD_PUBLIC_DIR / "live_account.json"
LIVE_COOLDOWN_FILE  = DASHBOARD_PUBLIC_DIR / "live_cooldowns.json"
LIVE_LOGS_FILE      = DASHBOARD_PUBLIC_DIR / "live_logs.json"
LIVE_RESULTS_FILE   = DASHBOARD_PUBLIC_DIR / "live_trade_results.json"
LIVE_CONFIG_FILE    = DASHBOARD_PUBLIC_DIR / "live_config.json"
DASHBOARD_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL       = os.getenv("PHEMEX_BASE_URL", "https://api.phemex.com").rstrip('/')
API_KEY        = _env_str("PHEMEX_API_KEY")
API_SECRET     = _env_str("PHEMEX_API_SECRET")
BOT_LOG_FILE   = Path(SCRIPT_DIR) / "bot_trades.json"
BLACKLIST_FILE = Path(SCRIPT_DIR) / "bot_blacklist.json"
LIVE_SESSION   = _env_str("LIVE_SESSION", "1")
POSITION_MODE  = _env_str("PHEMEX_POSITION_MODE", "AUTO").upper()

# Strategy parameters (Aligned with simulation bot)
MARGIN_USDT     = bot_core.MARGIN_USDT
LEVERAGE        = bot_core.LEVERAGE
TRAIL_PCT       = bot_core.TRAIL_PCT
TAKE_PROFIT_PCT = bot_core.TAKE_PROFIT_PCT
MAX_POSITIONS   = bot_core.MAX_POSITIONS
TAKER_FEE_RATE  = 0.001  # 0.1% Phemex taker fee
USE_NATIVE_EXIT_ORDERS = os.getenv("BOT_USE_NATIVE_EXIT_ORDERS", "true").lower() == "true"
STOP_REFRESH_MIN_INTERVAL = float(os.getenv("BOT_STOP_REFRESH_MIN_INTERVAL", "2.0"))
NATIVE_SYNC_LOOKBACK_HOURS = int(os.getenv("BOT_NATIVE_SYNC_LOOKBACK_HOURS", "12"))
ENTRY_MARGIN_BUFFER_USDT = float(os.getenv("BOT_ENTRY_MARGIN_BUFFER_USDT", "1.0"))
MIN_ENTRY_MARGIN_USDT = float(os.getenv("BOT_MIN_ENTRY_MARGIN_USDT", "5.0"))
MIN_LIVE_ENTRY_SCORE = int(os.getenv("BOT_MIN_LIVE_ENTRY_SCORE", "130"))
NATIVE_ARM_GRACE_SECONDS = float(os.getenv("BOT_NATIVE_ARM_GRACE_SECONDS", "20.0"))
NATIVE_ARM_RETRY_INTERVAL = float(os.getenv("BOT_NATIVE_ARM_RETRY_INTERVAL", "2.0"))
ENTRY_PAUSE_AFTER_PROTECTION_FAILURE_SECONDS = float(
    os.getenv("BOT_ENTRY_PAUSE_AFTER_PROTECTION_FAILURE_SECONDS", "900.0")
)
LOW_MARGIN_SCAN_LOG_INTERVAL_SECONDS = float(os.getenv("BOT_LOW_MARGIN_SCAN_LOG_INTERVAL_SECONDS", "60.0"))
LOOP_SKIP_BACKOFF_SECONDS = float(os.getenv("BOT_LOOP_SKIP_BACKOFF_SECONDS", "15.0"))
LOOP_ERROR_BACKOFF_SECONDS = float(os.getenv("BOT_LOOP_ERROR_BACKOFF_SECONDS", "15.0"))
LOOP_STATE_LOG_INTERVAL_SECONDS = float(os.getenv("BOT_LOOP_STATE_LOG_INTERVAL_SECONDS", "60.0"))
TP_STAGE_WEIGHTS = (0.5, 0.25, 0.25)

# Fast-track entry: fire immediately when score exceeds threshold
FAST_TRACK_SCORE            = int(os.getenv("BOT_FAST_TRACK_SCORE", "125"))
FAST_TRACK_COOLDOWN_SECONDS = 300   # seconds before same symbol can fast-track again
RESULT_STALENESS_SECONDS    = 120   # discard scan results older than this

# Unicode Block Elements U+2581–U+2588
_SPARK_CHARS = "▁▂▃▄▅▆▇█"

_live_prices: Dict[str, float] = {}
_prices_lock = threading.Lock()
_ws_app: Optional[WebSocketApp] = None
_ws_thread: Optional[threading.Thread] = None

# New client-side position management
_client_managed_positions: Dict[str, dict] = {}
_stop_lock = threading.Lock()
_cooldown_lock   = threading.Lock()
_log_lock        = threading.Lock()
_display_lock    = threading.Lock()
_fast_track_lock = threading.Lock()
_file_io_lock    = threading.Lock()
_entry_lock      = threading.Lock()
_entry_pause_lock = threading.Lock()

_slot_available_event  = threading.Event()
_display_paused        = threading.Event()
_display_thread_running = False
_no_tui = False

FAST_TRACK_COOLDOWN: Dict[str, float] = {}  # symbol → timestamp of last fast-track
_fast_track_opened:  set[str]         = set()
LAST_EXIT_TIME:      Dict[str, Tuple[float, int]] = {}  # symbol → (timestamp, score)
_entry_pause_until = 0.0
_entry_pause_reason = ""
_low_margin_scan_log_message = ""
_low_margin_scan_logged_at = 0.0
_low_margin_scan_lock = threading.Lock()
_loop_state_key = ""
_loop_state_logged_at = 0.0
_loop_state_lock = threading.Lock()

# TUI log buffer
_bot_logs: List[str] = []
_max_logs  = 100

# Equity sparkline history
_equity_history: List[float] = []
_max_history     = 50

logger = logging.getLogger("phemex_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@dataclass(frozen=True)
class LiveRuntimeConfig:
    enabled: bool
    direction: str
    min_score: int
    min_score_gap: int
    timeframe: str
    min_volume: int
    workers: int
    rate_limit_rps: float
    interval: int


def _telegram_config() -> Tuple[str, str]:
    return _env_str("TG_CHAT_ID"), _env_str("TG_BOT_TOKEN")


def _read_json_dict(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with _file_io_lock:
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)


def _write_json_payload(path: Path, payload: Any, *, indent: Optional[int] = None) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=indent))


def _blacklisted_symbols() -> set[str]:
    return {str(symbol).upper() for symbol in _read_json_dict(BLACKLIST_FILE).keys()}


def _is_symbol_blacklisted(symbol: str) -> bool:
    return str(symbol or "").upper() in _blacklisted_symbols()


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    return parsed


def _coerce_float(value: Any, default: float, minimum: Optional[float] = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    return parsed


def _normalize_choice(value: Any, choices: set[str], default: str) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in choices else default


def _normalize_timeframe(value: Any, default: str) -> str:
    normalized = str(value or "").strip().upper()
    return normalized or default


def _runtime_snapshot_from_bot_core(enabled: bool = True) -> LiveRuntimeConfig:
    return LiveRuntimeConfig(
        enabled=enabled,
        direction=_normalize_choice(bot_core.DIRECTION, {"LONG", "SHORT", "BOTH"}, "BOTH"),
        min_score=max(0, int(bot_core.MIN_SCORE)),
        min_score_gap=max(0, int(bot_core.MIN_SCORE_GAP)),
        timeframe=_normalize_timeframe(bot_core.TIMEFRAME, "4H"),
        min_volume=max(0, int(bot_core.MIN_VOLUME)),
        workers=max(1, int(bot_core.MAX_WORKERS)),
        rate_limit_rps=max(0.1, float(bot_core.RATE_LIMIT_RPS)),
        interval=max(1, int(bot_core.SCAN_INTERVAL)),
    )


def _resolve_live_runtime_config(args: argparse.Namespace, dashboard_config: Optional[dict] = None) -> LiveRuntimeConfig:
    dashboard_config = dashboard_config or {}

    default_direction = _normalize_choice(
        os.getenv("BOT_DIRECTION", getattr(args, "direction", "BOTH")),
        {"LONG", "SHORT", "BOTH"},
        "BOTH",
    )
    enabled = _coerce_bool(dashboard_config.get("enabled", True), True) and _coerce_bool(
        os.getenv("BOT_ENABLED", "true"),
        True,
    )

    return LiveRuntimeConfig(
        enabled=enabled,
        direction=_normalize_choice(dashboard_config.get("direction", default_direction), {"LONG", "SHORT", "BOTH"}, default_direction),
        min_score=_coerce_int(
            dashboard_config.get("min_score", os.getenv("BOT_MIN_SCORE", getattr(args, "min_score", bot_core.MIN_SCORE))),
            getattr(args, "min_score", bot_core.MIN_SCORE),
            minimum=0,
        ),
        min_score_gap=_coerce_int(
            dashboard_config.get("min_score_gap", os.getenv("BOT_MIN_SCORE_GAP", getattr(args, "min_score_gap", bot_core.MIN_SCORE_GAP))),
            getattr(args, "min_score_gap", bot_core.MIN_SCORE_GAP),
            minimum=0,
        ),
        timeframe=_normalize_timeframe(
            dashboard_config.get("timeframe", os.getenv("BOT_TIMEFRAME", getattr(args, "timeframe", bot_core.TIMEFRAME))),
            _normalize_timeframe(getattr(args, "timeframe", bot_core.TIMEFRAME), "4H"),
        ),
        min_volume=_coerce_int(
            dashboard_config.get("min_volume", os.getenv("BOT_MIN_VOLUME", getattr(args, "min_vol", bot_core.MIN_VOLUME))),
            getattr(args, "min_vol", bot_core.MIN_VOLUME),
            minimum=0,
        ),
        workers=_coerce_int(
            dashboard_config.get("workers", os.getenv("BOT_MAX_WORKERS", getattr(args, "workers", bot_core.MAX_WORKERS))),
            getattr(args, "workers", bot_core.MAX_WORKERS),
            minimum=1,
        ),
        rate_limit_rps=_coerce_float(
            dashboard_config.get("rate_limit_rps", os.getenv("BOT_RATE_LIMIT_RPS", getattr(args, "rate", bot_core.RATE_LIMIT_RPS))),
            getattr(args, "rate", bot_core.RATE_LIMIT_RPS),
            minimum=0.1,
        ),
        interval=_coerce_int(
            dashboard_config.get("interval", os.getenv("BOT_SCAN_INTERVAL", getattr(args, "interval", bot_core.SCAN_INTERVAL))),
            getattr(args, "interval", bot_core.SCAN_INTERVAL),
            minimum=1,
        ),
    )


def _apply_runtime_config(args: argparse.Namespace, runtime: LiveRuntimeConfig) -> None:
    args.direction = runtime.direction
    args.min_score = runtime.min_score
    args.min_score_gap = runtime.min_score_gap
    args.timeframe = runtime.timeframe
    args.min_vol = runtime.min_volume
    args.workers = runtime.workers
    args.rate = runtime.rate_limit_rps
    args.interval = runtime.interval

    bot_core.DIRECTION = runtime.direction
    bot_core.MIN_SCORE = runtime.min_score
    bot_core.MIN_SCORE_GAP = runtime.min_score_gap
    bot_core.TIMEFRAME = runtime.timeframe
    bot_core.MIN_VOLUME = runtime.min_volume
    bot_core.MAX_WORKERS = runtime.workers
    bot_core.RATE_LIMIT_RPS = runtime.rate_limit_rps
    bot_core.SCAN_INTERVAL = runtime.interval


def _persist_runtime_config(runtime: LiveRuntimeConfig) -> None:
    try:
        _write_json_payload(
            LIVE_CONFIG_FILE,
            {
                "enabled": runtime.enabled,
                "direction": runtime.direction,
                "min_score": runtime.min_score,
                "min_score_gap": runtime.min_score_gap,
                "timeframe": runtime.timeframe,
                "min_volume": runtime.min_volume,
                "workers": runtime.workers,
                "rate_limit_rps": runtime.rate_limit_rps,
                "interval": runtime.interval,
                "timestamp": datetime.datetime.now().isoformat(),
            },
        )
    except OSError:
        pass


def _load_live_runtime_config(args: argparse.Namespace) -> LiveRuntimeConfig:
    runtime = _resolve_live_runtime_config(args, _read_json_dict(LIVE_CONFIG_FILE))
    _apply_runtime_config(args, runtime)
    _persist_runtime_config(runtime)
    return runtime


def _build_live_scan_cfg(runtime: LiveRuntimeConfig) -> dict:
    return {
        "MIN_VOLUME": runtime.min_volume,
        "TIMEFRAME": runtime.timeframe,
        "TOP_N": 50,
        "MIN_SCORE": 0,
        "MAX_WORKERS": runtime.workers,
        "RATE_LIMIT_RPS": runtime.rate_limit_rps,
    }


def _build_verify_scan_cfg(runtime: Optional[LiveRuntimeConfig] = None) -> dict:
    snapshot = runtime or _runtime_snapshot_from_bot_core()
    return {
        "TIMEFRAME": snapshot.timeframe,
        "MIN_VOLUME": snapshot.min_volume,
        "RATE_LIMIT_RPS": snapshot.rate_limit_rps,
        "CANDLES": 100,
    }


def _scan_due(last_scan_started_at: float, interval_seconds: int, now: Optional[float] = None) -> bool:
    current_time = time.time() if now is None else now
    if last_scan_started_at <= 0:
        return True
    return current_time - last_scan_started_at >= max(interval_seconds, 1)


def _next_engine_wait_seconds(last_scan_started_at: float, interval_seconds: int, now: Optional[float] = None) -> float:
    if last_scan_started_at <= 0:
        return min(60.0, max(float(interval_seconds), 15.0))
    current_time = time.time() if now is None else now
    remaining = max((last_scan_started_at + max(interval_seconds, 1)) - current_time, 0.0)
    return min(60.0, remaining)


def _next_loop_wait_seconds(
    last_scan_started_at: float,
    interval_seconds: int,
    *,
    scan_due: bool,
    scan_executed: bool,
    now: Optional[float] = None,
) -> float:
    wait_seconds = _next_engine_wait_seconds(last_scan_started_at, interval_seconds, now=now)
    if scan_due and not scan_executed:
        skip_backoff = max(min(float(interval_seconds), LOOP_SKIP_BACKOFF_SECONDS), 1.0)
        return max(wait_seconds, skip_backoff)
    return wait_seconds


def _loop_error_backoff_seconds(error_streak: int) -> float:
    streak = max(int(error_streak), 1)
    return min(max(LOOP_ERROR_BACKOFF_SECONDS, 1.0) * streak, 60.0)


def _wait_for_engine_wake(timeout_seconds: float) -> None:
    timeout = max(timeout_seconds, 0.0)
    if timeout > 0.0:
        _slot_available_event.wait(timeout=timeout)
    _slot_available_event.clear()

# ────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────

def tui_log(msg: str) -> None:
    """Appends a timestamped message to the internal TUI log buffer and saves to JSON."""
    with _log_lock:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        _bot_logs.append(f"[{timestamp}] {msg}")
        if len(_bot_logs) > _max_logs:
            _bot_logs.pop(0)
        try:
            _write_json_payload(LIVE_LOGS_FILE, _bot_logs)
        except OSError:
            pass


def _reset_low_margin_scan_log_state() -> None:
    global _low_margin_scan_log_message, _low_margin_scan_logged_at
    with _low_margin_scan_lock:
        _low_margin_scan_log_message = ""
        _low_margin_scan_logged_at = 0.0


def _log_low_margin_scan_skip(free_balance: float, now: Optional[float] = None) -> bool:
    global _low_margin_scan_log_message, _low_margin_scan_logged_at

    usable_margin = _entry_margin_from_free_balance(free_balance)
    message = (
        f"Skipping scan: usable free margin ${usable_margin:.2f} "
        f"is below minimum ${MIN_ENTRY_MARGIN_USDT:.2f}."
    )
    current_time = time.time() if now is None else now

    with _low_margin_scan_lock:
        should_log = (
            message != _low_margin_scan_log_message
            or (current_time - _low_margin_scan_logged_at) >= LOW_MARGIN_SCAN_LOG_INTERVAL_SECONDS
        )
        if should_log:
            _low_margin_scan_log_message = message
            _low_margin_scan_logged_at = current_time

    if should_log:
        tui_log(message)
    return should_log


def _log_loop_state_once(message_key: str, message: str, *, now: Optional[float] = None) -> bool:
    global _loop_state_key, _loop_state_logged_at

    current_time = time.time() if now is None else now
    with _loop_state_lock:
        should_log = (
            message_key != _loop_state_key
            or (current_time - _loop_state_logged_at) >= LOOP_STATE_LOG_INTERVAL_SECONDS
        )
        if should_log:
            _loop_state_key = message_key
            _loop_state_logged_at = current_time

    if should_log:
        tui_log(message)
    return should_log


def _clear_loop_state_notice() -> None:
    global _loop_state_key, _loop_state_logged_at
    with _loop_state_lock:
        _loop_state_key = ""
        _loop_state_logged_at = 0.0

# ────────────────────────────────────────────────────────────────────
# Phemex API & Helpers
# ────────────────────────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({
    "User-Agent": "fangblenny-bot/1.0",
    "Accept": "application/json",
})

def _auth_headers(path: str, query: str = "", body: str = "") -> dict:
    # Use standard 60s expiry.
    expiry = int(time.time()) + 60
    
    # Legacy Phemex Formula: Path + Query + Expiry
    # Note: query should NOT include leading '?'
    message = path + query + str(expiry)
        
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    
    return {
        "x-phemex-access-token": API_KEY,
        "x-phemex-request-expiry": str(expiry),
        "x-phemex-request-signature": signature,
        "Content-Type": "application/json",
    }

def _get(path: str, params: dict = None) -> Optional[dict]:
    # Ensure stable parameter ordering for consistent signature/URL
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    url = BASE_URL + path + (("?" + query) if query else "")
    try:
        resp = _session.get(url, headers=_auth_headers(path, query), timeout=12)
        
        data = None
        try:
            data = resp.json()
        except:
            pass

        if resp.status_code >= 400 or (data and data.get("code", 0) != 0):
            code = data.get("code") if data else resp.status_code
            msg = data.get("msg") if data else resp.text
            logger.error("GET %s failed [%s]: %s", path, code, msg)
            return data if data else {"code": resp.status_code, "msg": resp.text}
            
        return data
    except Exception as e:
        logger.error("GET %s failed: %s", path, e)
        return None

def _put(path: str, params: dict = None, body: dict = None) -> Optional[dict]:
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    body_str = json.dumps(body, separators=(',', ':')) if body else ""
    url = BASE_URL + path + (("?" + query) if query else "")
    try:
        resp = _session.put(url, headers=_auth_headers(path, query, body_str), data=body_str, timeout=12)
        if resp.status_code >= 400:
            msg = f"API PUT {path} failed [{resp.status_code}]"
            try:
                err_data = resp.json()
                msg += f": {err_data.get('msg', resp.text)}"
            except:
                msg += f": {resp.text[:50]}"
            tui_log(f"{Fore.RED}{msg}")
            logger.error("PUT %s failed [%d]: %s", path, resp.status_code, resp.text)
            return None
        return resp.json()
    except Exception as e:
        tui_log(f"{Fore.RED}PUT {path} exception: {str(e)[:50]}")
        logger.error("PUT %s failed: %s", path, e)
        return None


def _delete(path: str, params: dict = None) -> Optional[dict]:
    query = urllib.parse.urlencode(sorted(params.items())) if params else ""
    url = BASE_URL + path + (("?" + query) if query else "")
    try:
        resp = _session.delete(url, headers=_auth_headers(path, query), timeout=12)
        data = None
        try:
            data = resp.json()
        except Exception:
            pass

        if resp.status_code >= 400 or (data and data.get("code", 0) not in {0, 10002}):
            code = data.get("code") if data else resp.status_code
            msg = data.get("msg") if data else resp.text
            logger.error("DELETE %s failed [%s]: %s", path, code, msg)
            return data if data else {"code": resp.status_code, "msg": resp.text}
        return data
    except Exception as e:
        logger.error("DELETE %s failed: %s", path, e)
        return None

def _normalize_position_side(position_side: Optional[str]) -> Optional[str]:
    if not position_side:
        return None
    normalized = position_side.strip().upper()
    if normalized in {"BUY", "LONG"}:
        return "Long"
    if normalized in {"SELL", "SHORT"}:
        return "Short"
    return None


def _candidate_pos_sides(position_side: Optional[str]) -> List[str]:
    hedged_side = _normalize_position_side(position_side)
    if not hedged_side:
        return ["Merged"]

    if POSITION_MODE in {"HEDGE", "HEDGED"}:
        return [hedged_side, "Merged"]
    if POSITION_MODE in {"ONEWAY", "ONE_WAY", "ONE-WAY", "MERGED"}:
        return ["Merged", hedged_side]
    return ["Merged", hedged_side]


def _is_inconsistent_pos_mode_error(resp: Optional[dict]) -> bool:
    if not isinstance(resp, dict):
        return False
    msg = str(resp.get("msg") or "")
    return resp.get("code") == 20004 or "INCONSISTENT_POS_MODE" in msg


def _is_missing_order_error(resp: Optional[dict]) -> bool:
    if not isinstance(resp, dict):
        return False
    msg = str(resp.get("msg") or "").upper()
    return resp.get("code") == 10002 or "ORDER_NOT_FOUND" in msg


def _is_no_available_balance_error(resp: Optional[dict]) -> bool:
    if not isinstance(resp, dict):
        return False
    msg = str(resp.get("msg") or "").upper()
    return resp.get("code") == 11001 or "NO_ENOUGH_AVAILABLE_BALANCE" in msg


def _is_exchange_entry_blocked_error(resp: Optional[dict]) -> bool:
    if not isinstance(resp, dict):
        return False
    msg = str(resp.get("msg") or "").upper()
    return resp.get("code") == 11150 or "REDUCE_ONLY" in msg or "OI_LIMIT" in msg


def _format_leverage(leverage: float) -> str:
    rounded = round(float(leverage), 8)
    if abs(rounded - round(rounded)) < 1e-8:
        return str(int(round(rounded)))
    return f"{rounded:.8f}".rstrip("0").rstrip(".")


def _signed_exchange_leverage(leverage: float, exchange_pos: Optional[dict] = None) -> float:
    signed = abs(float(leverage))
    if isinstance(exchange_pos, dict):
        if bool(exchange_pos.get("crossMargin")):
            return -signed
        current = _as_float(exchange_pos.get("leverageRr"), 0.0)
        if current < 0.0:
            return -signed
    return signed


def _candidate_leverage_params(side: str, exchange_pos: Optional[dict] = None) -> List[dict]:
    pos_mode = str((exchange_pos or {}).get("posMode") or "").strip().upper()
    if pos_mode == "HEDGED":
        return [{"longLeverageRr": "", "shortLeverageRr": ""}, {"leverageRr": ""}]
    if pos_mode in {"ONEWAY", "ONE_WAY", "ONE-WAY", "MERGED"}:
        return [{"leverageRr": ""}, {"longLeverageRr": "", "shortLeverageRr": ""}]
    if POSITION_MODE in {"HEDGE", "HEDGED"}:
        return [{"longLeverageRr": "", "shortLeverageRr": ""}, {"leverageRr": ""}]
    return [{"leverageRr": ""}, {"longLeverageRr": "", "shortLeverageRr": ""}]


def _current_exchange_leverage(symbol: str, side: str, fallback: float) -> float:
    exchange_pos = _get_exchange_position(symbol, side)
    if not exchange_pos:
        return max(float(fallback), 1.0)

    leverage = abs(_as_float(exchange_pos.get("leverageRr"), 0.0))
    cost_ratio_key = "buyValueToCostRr" if side == "Buy" else "sellValueToCostRr"
    cost_ratio = _as_float(exchange_pos.get(cost_ratio_key), 0.0)
    if cost_ratio > 0.0:
        leverage = min(leverage or (1.0 / cost_ratio), 1.0 / cost_ratio) if leverage > 0.0 else (1.0 / cost_ratio)
    if leverage <= 0.0:
        leverage = float(fallback)
    return _effective_entry_leverage(symbol, leverage)


def _sync_symbol_leverage(symbol: str, side: str, leverage: float) -> bool:
    exchange_pos = _get_exchange_position(symbol, side)
    leverage_str = _format_leverage(_signed_exchange_leverage(leverage, exchange_pos))
    last_resp = None
    for param_template in _candidate_leverage_params(side, exchange_pos):
        params = {"symbol": symbol}
        for key in param_template:
            params[key] = leverage_str
        last_resp = _put("/g-positions/leverage", params=params)
        if last_resp and last_resp.get("code") == 0:
            return True
        if not _is_inconsistent_pos_mode_error(last_resp):
            break
    logger.error("Failed to set leverage for %s to %sx: %s", symbol, leverage_str, last_resp)
    return False


def place_market_order(
    symbol: str,
    side: str,
    qty_str: str,
    position_side: Optional[str] = None,
) -> Optional[dict]:
    # Try the configured/default position mode first, then hedge-mode fallback
    # when Phemex reports an inconsistent account mode.
    last_resp = None
    for pos_side in _candidate_pos_sides(position_side or side):
        last_resp = _put("/g-orders/create", params={
            "clOrdID": f"bot-{int(time.time() * 1000)}",
            "symbol": symbol,
            "side": side,
            "ordType": "Market",
            "orderQtyRq": qty_str,
            "posSide": pos_side,
            "timeInForce": "ImmediateOrCancel",
        })
        if last_resp and last_resp.get("code") == 0:
            return last_resp
        if not _is_inconsistent_pos_mode_error(last_resp):
            return last_resp
        logger.warning("Retrying %s %s with alternate posSide after inconsistent mode response.", symbol, side)
    return last_resp


def _position_close_side(position_side: str) -> str:
    return "Sell" if position_side == "Buy" else "Buy"


def _current_pos_side(position_side: str) -> str:
    return _candidate_pos_sides(position_side)[0]


_ORDER_STATUS_MAP = {
    0: "Created",
    1: "Untriggered",
    2: "Deactivated",
    3: "Triggered",
    4: "Rejected",
    5: "New",
    6: "PartiallyFilled",
    7: "Filled",
    8: "Canceled",
}

_ORDER_TYPE_MAP = {
    1: "Market",
    2: "Limit",
    3: "Stop",
    4: "StopLimit",
    5: "MarketIfTouched",
    6: "LimitIfTouched",
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _qty_step(symbol: str) -> float:
    _load_instruments()
    return float(_instrument_cache.get(symbol, {}).get("step", 0.001))


def _price_tick(symbol: str) -> float:
    _load_instruments()
    return float(_instrument_cache.get(symbol, {}).get("tick", 0.0001))


def _get_exchange_position(symbol: str, position_side: Optional[str] = None) -> Optional[dict]:
    resp = _get("/g-accounts/accountPositions", params={"currency": "USDT", "symbol": symbol})
    if not resp or resp.get("code") != 0:
        return None
    positions = (resp.get("data") or {}).get("positions") or []
    matches = [pos for pos in positions if pos.get("symbol") == symbol]
    target_side = _normalize_position_side(position_side)
    if target_side:
        for pos in matches:
            if _normalize_position_side(pos.get("posSide")) == target_side:
                return pos
    for pos in matches:
        if abs(_as_float(pos.get("size"), 0.0)) > 0.0:
            return pos
    if matches:
        return matches[0]
    return None


def _effective_native_stop_price(symbol: str, side: str, desired_stop_price: float) -> Optional[float]:
    stop_price = max(desired_stop_price, 0.0)
    exchange_pos = _get_exchange_position(symbol, side)
    if not exchange_pos:
        return stop_price if stop_price > 0.0 else None

    liquidation_price = _as_float(exchange_pos.get("liquidationPriceRp"), 0.0)
    mark_price = _as_float(exchange_pos.get("markPriceRp"), 0.0)
    tick = _price_tick(symbol)

    if side == "Buy" and liquidation_price > 0.0:
        stop_price = max(stop_price, liquidation_price + tick)
        if mark_price > 0.0 and stop_price >= (mark_price - tick / 2.0):
            return None
    elif side == "Sell" and liquidation_price > 0.0:
        stop_price = min(stop_price, liquidation_price - tick)
        if stop_price <= 0.0:
            return None
        if mark_price > 0.0 and stop_price <= (mark_price + tick / 2.0):
            return None

    return stop_price if stop_price > 0.0 else None


def _order_id(order: Optional[dict]) -> str:
    if not isinstance(order, dict):
        return ""
    return str(order.get("orderID") or order.get("orderId") or "")


def _order_status(order: Optional[dict]) -> str:
    if not isinstance(order, dict):
        return ""
    status = order.get("ordStatus")
    if isinstance(status, int):
        return _ORDER_STATUS_MAP.get(status, str(status))
    return str(status or "")


def _order_type(order: Optional[dict]) -> str:
    if not isinstance(order, dict):
        return ""
    order_type = order.get("ordType") or order.get("orderType")
    if isinstance(order_type, int):
        return _ORDER_TYPE_MAP.get(order_type, str(order_type))
    return str(order_type or "")


def _order_exec_qty(order: Optional[dict]) -> float:
    if not isinstance(order, dict):
        return 0.0
    for key in ("execQtyRq", "cumQtyRq"):
        if key in order:
            return _as_float(order.get(key), 0.0)
    order_qty = _as_float(order.get("orderQtyRq"), 0.0)
    leaves_qty = _as_float(order.get("leavesQtyRq"), 0.0)
    return max(order_qty - leaves_qty, 0.0)


def _order_leaves_qty(order: Optional[dict]) -> float:
    if not isinstance(order, dict):
        return 0.0
    return _as_float(order.get("leavesQtyRq"), 0.0)


def _order_exec_price(order: Optional[dict], fallback: float = 0.0) -> float:
    if not isinstance(order, dict):
        return fallback
    for key in ("avgTransactPriceRp", "execPriceRp", "priceRp", "stopPxRp"):
        price = _as_float(order.get(key), 0.0)
        if price > 0:
            return price
    return fallback


def _order_is_filled(order: Optional[dict]) -> bool:
    return _order_status(order) == "Filled" and _order_exec_qty(order) > 0.0


def _entry_time_ms(pos: dict) -> int:
    entry_time = pos.get("entry_time")
    if isinstance(entry_time, str):
        try:
            return int(datetime.datetime.fromisoformat(entry_time).timestamp() * 1000) - 300_000
        except ValueError:
            pass
    return int((time.time() - (NATIVE_SYNC_LOOKBACK_HOURS * 3600)) * 1000)


def _stop_has_improved(symbol: str, side: str, new_stop: float, current_stop: float) -> bool:
    rounded_new = _as_float(_round_price(symbol, new_stop), 0.0)
    rounded_current = _as_float(_round_price(symbol, current_stop), 0.0)
    tick = _price_tick(symbol)
    if side == "Buy":
        return rounded_new > (rounded_current + tick / 2.0)
    return rounded_current == 0.0 or rounded_new < (rounded_current - tick / 2.0)


def _track_partial_tp_fill(symbol: str, pos: dict, qty: float, price: float) -> None:
    if qty <= 0.0:
        return
    _log_closed_trade(
        symbol,
        pos["side"],
        float(pos["entry"]),
        price,
        qty,
        pos.get("entry_score", 0),
        pos.get("entry_time"),
        "partial_tp",
    )
    tui_log(f"PARTIAL TP: {symbol} closed at {price}")


def _allocate_tp_stage_quantities(symbol: str, total_qty: float, stage_indices: List[int]) -> Dict[int, float]:
    if total_qty <= 0.0 or not stage_indices:
        return {}

    weights = [TP_STAGE_WEIGHTS[idx] if idx < len(TP_STAGE_WEIGHTS) else 1.0 for idx in stage_indices]
    weight_total = sum(weights) or float(len(stage_indices))
    remaining_qty = max(float(total_qty), 0.0)
    allocations: Dict[int, float] = {}

    for idx, weight in zip(stage_indices[:-1], weights[:-1]):
        stage_qty = float(_round_qty(symbol, total_qty * (weight / weight_total)))
        stage_qty = min(max(stage_qty, 0.0), remaining_qty)
        allocations[idx] = stage_qty
        remaining_qty = max(remaining_qty - stage_qty, 0.0)

    allocations[stage_indices[-1]] = remaining_qty
    return allocations


def _rebalance_unfilled_tp_stages(symbol: str, pos: dict, open_size: float) -> bool:
    stages = pos.get("tp_stages", [])
    if not stages or open_size <= 0.0:
        return False

    active_indices = [idx for idx, stage in enumerate(stages) if not stage.get("hit")]
    if not active_indices:
        return False

    allocations = _allocate_tp_stage_quantities(symbol, open_size, active_indices)
    qty_eps = max(_qty_step(symbol) / 2.0, 1e-9)
    changed = False

    for idx in active_indices:
        stage = stages[idx]
        new_qty = max(float(allocations.get(idx, 0.0)), 0.0)
        if abs(_as_float(stage.get("qty"), 0.0) - new_qty) > qty_eps:
            stage["qty"] = new_qty
            changed = True
        if _as_float(stage.get("filled_qty"), 0.0) != 0.0:
            stage["filled_qty"] = 0.0
            changed = True
        if _as_float(stage.get("logged_qty"), 0.0) != 0.0:
            stage["logged_qty"] = 0.0
            changed = True
        if stage.get("order_id") is not None:
            stage["order_id"] = None
            changed = True
        if stage.get("pending"):
            stage.pop("pending", None)
            changed = True

    return changed


def _required_free_balance() -> float:
    return float(MIN_ENTRY_MARGIN_USDT + ENTRY_MARGIN_BUFFER_USDT)


def _entry_margin_from_free_balance(free_balance: float) -> float:
    usable_free = max(float(free_balance) - ENTRY_MARGIN_BUFFER_USDT, 0.0)
    return min(float(MARGIN_USDT), usable_free)


def _effective_live_entry_min_score(runtime: Optional[LiveRuntimeConfig] = None) -> int:
    runtime_min = int(runtime.min_score) if runtime is not None else int(bot_core.MIN_SCORE)
    return max(runtime_min, int(MIN_LIVE_ENTRY_SCORE))


def _account_free_balance(acc: Optional[dict]) -> float:
    if not isinstance(acc, dict):
        return 0.0
    free_balance = _as_float(acc.get("free_balance"), -1.0)
    if free_balance >= 0.0:
        return free_balance
    balance = _as_float(acc.get("balance"), 0.0)
    used_balance = _as_float(acc.get("used_balance"), 0.0)
    if used_balance > 0.0:
        return max(balance - used_balance, 0.0)
    return balance


def _has_free_capacity_for_entry(acc: Optional[dict]) -> bool:
    return _entry_margin_from_free_balance(_account_free_balance(acc)) + 1e-9 >= float(MIN_ENTRY_MARGIN_USDT)


def _symbol_entry_cooldown_active(symbol: str, now: Optional[float] = None) -> bool:
    with _cooldown_lock:
        last_exit_data = LAST_EXIT_TIME.get(symbol)
    if not last_exit_data:
        return False
    last_exit, last_score = last_exit_data
    current_time = time.time() if now is None else now
    return (current_time - last_exit) < bot_core.get_cooldown_duration(last_score)


def _mark_entry_cooldown(symbol: str, score: int) -> None:
    with _cooldown_lock:
        LAST_EXIT_TIME[symbol] = (time.time(), int(score))
    save_live_cooldowns()


def _has_live_entry_capacity(acc: Optional[dict] = None) -> bool:
    if _entry_pause_active():
        return False
    with _stop_lock:
        if len(_client_managed_positions) >= bot_core.MAX_POSITIONS:
            return False
    snapshot = acc if isinstance(acc, dict) else load_live_account()
    return _has_free_capacity_for_entry(snapshot)

def fetch_live_account_state() -> dict:
    """Fetches real balance and positions from Phemex Unified account."""
    balance = 0.0
    used_balance = 0.0
    free_balance = 0.0
    
    # Use Unified V3 accountPositions
    resp = _get("/g-accounts/accountPositions", params={"currency": "USDT"})
    if resp and resp.get("code") == 0:
        data = resp.get("data", {})
        account = data.get("account", {})
        if account:
            # accountBalanceRv is a string representation of the total balance
            balance = float(account.get("accountBalanceRv", 0.0))
            used_balance = float(account.get("totalUsedBalanceRv", 0.0))
            free_balance = max(balance - used_balance, 0.0)
            positions = data.get("positions", []) or []
            _sync_positions_with_exchange(positions, balance, free_balance, used_balance)
            return {
                "balance": balance,
                "used_balance": used_balance,
                "free_balance": free_balance,
                "positions": list(_client_managed_positions.values()),
            }
    
    # Final Error Log
    final_code = resp.get("code") if resp else "Unknown"
    tui_log(f"{Fore.RED}Balance fetch failed. Code: {final_code}")

    return {
        "balance": 0.0,
        "used_balance": 0.0,
        "free_balance": 0.0,
        "positions": list(_client_managed_positions.values()),
    }

def load_live_account() -> dict:
    """Loads the live account state, syncing with Phemex if necessary."""
    if not LIVE_ACCOUNT_FILE.exists():
        data = fetch_live_account_state()
        save_live_account(data)
        return data
    try:
        return json.loads(LIVE_ACCOUNT_FILE.read_text())
    except json.JSONDecodeError:
        data = fetch_live_account_state()
        save_live_account(data)
        return data

def save_live_account(data: dict) -> None:
    """Persists the current live account state to disk."""
    _write_json_payload(LIVE_ACCOUNT_FILE, data, indent=2)


def _load_positions_from_disk() -> None:
    """Rehydrate tracked positions after a bot restart."""
    if not LIVE_ACCOUNT_FILE.exists():
        return
    try:
        data = json.loads(LIVE_ACCOUNT_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return

    positions = data.get("positions", [])
    if not isinstance(positions, list):
        return

    with _stop_lock:
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            symbol = pos.get("symbol")
            if not symbol or symbol in _client_managed_positions:
                continue
            _client_managed_positions[symbol] = pos


def _persist_live_positions(
    balance: Optional[float] = None,
    free_balance: Optional[float] = None,
    used_balance: Optional[float] = None,
) -> None:
    """Flush the client-managed position snapshot to the dashboard immediately."""
    snapshot = {}
    try:
        snapshot = json.loads(LIVE_ACCOUNT_FILE.read_text())
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        snapshot = {}

    if balance is None:
        balance = _as_float(snapshot.get("balance"), 0.0)
    if used_balance is None:
        used_balance = _as_float(snapshot.get("used_balance"), 0.0)
    if free_balance is None:
        free_balance = _as_float(snapshot.get("free_balance"), max(balance - used_balance, 0.0))

    save_live_account({
        "balance": balance,
        "used_balance": used_balance,
        "free_balance": free_balance,
        "positions": list(_client_managed_positions.values()),
    })

def save_live_cooldowns() -> None:
    """Persists active re-entry and fast-track cooldowns to disk."""
    with _cooldown_lock:
        active_exit = {s: [ts, sc] for s, (ts, sc) in LAST_EXIT_TIME.items() if time.time() - ts < 3600}
    with _fast_track_lock:
        active_ft = {s: ts for s, ts in FAST_TRACK_COOLDOWN.items() if time.time() - ts < FAST_TRACK_COOLDOWN_SECONDS}

    data = {"last_exit": active_exit, "fast_track": active_ft}
    try:
        _write_json_payload(LIVE_COOLDOWN_FILE, data)
    except OSError:
        pass

def load_live_cooldowns() -> None:
    """Loads re-entry and fast-track cooldowns from disk."""
    global LAST_EXIT_TIME, FAST_TRACK_COOLDOWN
    if not LIVE_COOLDOWN_FILE.exists():
        return
    try:
        data = json.loads(LIVE_COOLDOWN_FILE.read_text())
        if isinstance(data, dict) and "last_exit" in data and "fast_track" in data:
            with _cooldown_lock:
                LAST_EXIT_TIME = {s: (float(v[0]), int(v[1])) for s, v in data["last_exit"].items() if time.time() - float(v[0]) < 3600}
            with _fast_track_lock:
                FAST_TRACK_COOLDOWN = {s: float(ts) for s, ts in data["fast_track"].items() if time.time() - float(ts) < FAST_TRACK_COOLDOWN_SECONDS}
    except Exception:
        pass


def _entry_pause_state() -> Tuple[float, str]:
    with _entry_pause_lock:
        return _entry_pause_until, _entry_pause_reason


def _pause_new_entries(reason: str, duration: Optional[float] = None) -> None:
    global _entry_pause_until, _entry_pause_reason
    pause_for = float(duration if duration is not None else ENTRY_PAUSE_AFTER_PROTECTION_FAILURE_SECONDS)
    now = time.time()
    with _entry_pause_lock:
        new_until = now + max(pause_for, 0.0)
        if new_until > _entry_pause_until:
            _entry_pause_until = new_until
            _entry_pause_reason = reason
    minutes = max(int(round(pause_for / 60.0)), 1)
    tui_log(f"SAFETY PAUSE: {reason}. New entries paused for {minutes}m.")


def _entry_pause_active() -> bool:
    pause_until, _ = _entry_pause_state()
    return time.time() < pause_until

def _close_all_positions() -> None:
    """Closes all client-managed positions."""
    close_requests = []
    with _stop_lock:
        symbols = list(_client_managed_positions.keys())
        for symbol in symbols:
            pos = _client_managed_positions[symbol]
            close_requests.append({
                "symbol": symbol,
                "side": pos["side"],
                "size": _as_float(pos.get("size"), 0.0),
            })

    for req in close_requests:
        if USE_NATIVE_EXIT_ORDERS:
            cancel_all_orders(req["symbol"])
        close_side = "Sell" if req["side"] == "Buy" else "Buy"
        resp = place_market_order(req["symbol"], close_side, _round_qty(req["symbol"], req["size"]), position_side=req["side"])
        if not resp or resp.get("code") != 0:
            tui_log(f"ERROR: Manual close failed for {req['symbol']}: {resp}")
            continue
        with _stop_lock:
            _client_managed_positions.pop(req["symbol"], None)
        tui_log(f"MANUAL CLOSE: {req['symbol']}")

    _persist_live_positions(fetch_live_account_state().get("balance", 0.0))
    _slot_available_event.set()

def _get_current_price_rest(symbol: str) -> Optional[float]:
    path = "/md/v2/kline/list"
    params = {"symbol": symbol, "interval": "1m", "limit": 1}
    data = _get(path, params)
    if data and data.get("code") == 0 and data["data"]["rows"]:
        try:
            return float(data["data"]["rows"][0][-2])
        except (ValueError, IndexError):
            return None
    return None

_instrument_cache: Dict[str, dict] = {}
_instrument_loaded = False


def _load_instruments() -> None:
    global _instrument_loaded
    if _instrument_loaded:
        return
    data = _get("/public/products")
    if data and data.get("code") == 0:
        products = data.get("data", {}).get("perpProductsV2", []) or data.get("data", {}).get("products", [])
        for prod in products:
            symbol = prod.get("symbol")
            if not symbol:
                continue
            try:
                qty_step = float(prod.get("qtyStepSize") or prod.get("qtyStepSizeRq") or "0.001")
            except (TypeError, ValueError):
                qty_step = 0.001
            try:
                tick_size = float(prod.get("tickSize") or "0.0001")
            except (TypeError, ValueError):
                tick_size = 0.0001
            _instrument_cache[symbol] = {
                "step": qty_step if qty_step > 0 else 0.001,
                "tick": tick_size if tick_size > 0 else 0.0001,
                "qty_precision": int(prod.get("qtyPrecision", 3) or 3),
                "price_precision": int(prod.get("pricePrecision", 4) or 4),
                "max_leverage": _as_float(
                    prod.get("maxOpenPosLeverage") or prod.get("maxLeverage") or prod.get("defaultLeverage"),
                    0.0,
                ),
            }
    _instrument_loaded = True


def _symbol_max_leverage(symbol: str) -> float:
    _load_instruments()
    return _as_float(_instrument_cache.get(symbol, {}).get("max_leverage"), 0.0)


def _effective_entry_leverage(symbol: str, requested_leverage: float) -> float:
    leverage = max(float(requested_leverage), 1.0)
    max_leverage = _symbol_max_leverage(symbol)
    if max_leverage > 0.0:
        leverage = min(leverage, max_leverage)
    return leverage


def _round_qty(symbol: str, qty: float) -> str:
    _load_instruments()
    info = _instrument_cache.get(symbol)
    if info:
        step = info["step"]
        rounded = math.floor(max(qty, 0.0) / step) * step
        decimals = info.get("qty_precision", 3)
        return f"{rounded:.{decimals}f}"
    return f"{math.floor(max(qty, 0.0) * 1000) / 1000:.3f}"


def _round_price(symbol: str, price: float) -> str:
    _load_instruments()
    info = _instrument_cache.get(symbol)
    if info:
        tick = info["tick"]
        rounded = math.floor(max(price, 0.0) / tick) * tick
        decimals = info.get("price_precision", 4)
        return f"{rounded:.{decimals}f}"
    return f"{max(price, 0.0):.4f}"

def send_telegram_message(message: str):
    chat_id, bot_token = _telegram_config()
    if not chat_id or not bot_token:
        logger.debug("Telegram notification skipped because TG_CHAT_ID/TG_BOT_TOKEN is not configured.")
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")


def get_active_orders(symbol: str) -> Optional[List[dict]]:
    resp = _get("/g-orders/activeList", params={"symbol": symbol})
    if not resp:
        return None
    if resp.get("code") == 10002:
        return []
    if resp.get("code") != 0:
        return None
    return resp.get("data", {}).get("rows", []) or []


def get_closed_orders(symbol: str, start_ms: int, end_ms: int, limit: int = 50) -> Optional[List[dict]]:
    resp = _get("/exchange/order/v2/orderList", params={
        "symbol": symbol,
        "currency": "USDT",
        "start": start_ms,
        "end": end_ms,
        "offset": 0,
        "limit": limit,
        "withCount": "false",
    })
    if not resp or resp.get("code") != 0:
        return None
    data = resp.get("data")
    if isinstance(data, dict):
        return data.get("rows", []) or []
    if isinstance(data, list):
        return data
    return []


def _reconcile_symbol_with_exchange(symbol: str, exchange_pos: Optional[dict]) -> bool:
    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        arm_pending = bool(pos.get("native_arm_pending"))
        arm_started_at = _as_float(pos.get("native_arm_started_at"), 0.0)
        local_size_before = _as_float(pos.get("size"), 0.0)
        local_mark_before = _as_float(pos.get("mark_price"), 0.0)
        entry_time_ms = _entry_time_ms(pos)

    exchange_size = _as_float((exchange_pos or {}).get("size"), 0.0)
    exchange_mark = _as_float((exchange_pos or {}).get("markPriceRp"), local_mark_before)
    qty_eps = max(_qty_step(symbol) / 2.0, 1e-9)

    if exchange_mark > 0.0:
        with _prices_lock:
            _live_prices[symbol] = exchange_mark

    if not USE_NATIVE_EXIT_ORDERS:
        changed = False
        with _stop_lock:
            pos = _client_managed_positions.get(symbol)
            if pos:
                if exchange_mark > 0.0 and exchange_mark != _as_float(pos.get("mark_price"), 0.0):
                    pos["mark_price"] = exchange_mark
                    changed = True
                if exchange_size > qty_eps and abs(exchange_size - _as_float(pos.get("size"), 0.0)) > qty_eps:
                    pos["size"] = exchange_size
                    changed = True
        return changed

    if arm_pending and (time.time() - arm_started_at) < 15.0:
        changed = False
        with _stop_lock:
            pos = _client_managed_positions.get(symbol)
            if pos and exchange_mark > 0.0 and exchange_mark != _as_float(pos.get("mark_price"), 0.0):
                pos["mark_price"] = exchange_mark
                changed = True
        return changed

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        missing_ids = (
            not pos.get("stop_order_id")
            or any(not stage.get("hit") and not stage.get("order_id") for stage in pos.get("tp_stages", []))
        )

    size_changed = abs(exchange_size - local_size_before) > qty_eps or (exchange_size <= qty_eps < local_size_before)
    if not size_changed and not missing_ids:
        changed = False
        with _stop_lock:
            pos = _client_managed_positions.get(symbol)
            if pos and exchange_mark > 0.0 and exchange_mark != _as_float(pos.get("mark_price"), 0.0):
                pos["mark_price"] = exchange_mark
                changed = True
        return changed

    active_orders = get_active_orders(symbol)
    if active_orders is None:
        return False

    closed_orders = get_closed_orders(symbol, entry_time_ms, int(time.time() * 1000)) or []
    active_by_id = {_order_id(order): order for order in active_orders if _order_id(order)}
    closed_by_id = {_order_id(order): order for order in closed_orders if _order_id(order)}

    partial_events: List[dict] = []
    exit_event: Optional[dict] = None
    needs_arm = False
    changed = False

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False

        local_size_before = _as_float(pos.get("size"), 0.0)
        initial_size = sum(_as_float(stage.get("qty"), 0.0) for stage in pos.get("tp_stages", [])) or local_size_before
        pos["mark_price"] = exchange_mark or pos.get("mark_price")
        pos.pop("exit_pending", None)
        pos.pop("stop_refresh_pending", None)

        stop_order_id = str(pos.get("stop_order_id") or "")
        stop_order = active_by_id.get(stop_order_id) or closed_by_id.get(stop_order_id)
        stop_exec_qty = _order_exec_qty(stop_order)
        stop_filled = _order_is_filled(stop_order)

        stage_states = []
        total_tp_exec = 0.0
        for idx, stage in enumerate(pos.get("tp_stages", [])):
            stage_qty = _as_float(stage.get("qty"), 0.0)
            order_id = str(stage.get("order_id") or "")
            order = active_by_id.get(order_id) or closed_by_id.get(order_id)
            executed_qty = min(max(_order_exec_qty(order), _as_float(stage.get("filled_qty"), 0.0)), stage_qty)
            total_tp_exec += executed_qty
            stage_states.append({
                "index": idx,
                "order": order,
                "executed_qty": executed_qty,
                "exec_price": _order_exec_price(order, _as_float(stage.get("price"), 0.0)),
            })

        active_stage_qty_total = sum(
            max(_as_float(stage.get("qty"), 0.0) - _as_float(stage.get("filled_qty"), 0.0), 0.0)
            for stage in pos.get("tp_stages", [])
            if not stage.get("hit")
        )
        if (
            exchange_size > qty_eps
            and abs(active_stage_qty_total - exchange_size) > qty_eps
            and total_tp_exec <= qty_eps
            and not stop_filled
            and _rebalance_unfilled_tp_stages(symbol, pos, exchange_size)
        ):
            pos["size"] = exchange_size
            pos["native_orders_armed"] = False
            initial_size = sum(_as_float(stage.get("qty"), 0.0) for stage in pos.get("tp_stages", [])) or exchange_size
            changed = True

        final_tp_index = None
        if exchange_size <= qty_eps and not stop_filled and total_tp_exec >= (initial_size - qty_eps):
            running_exec = 0.0
            for state in stage_states:
                running_exec += state["executed_qty"]
                if running_exec >= (initial_size - qty_eps):
                    final_tp_index = state["index"]
                    break

        new_partial_qty = 0.0
        for state in stage_states:
            idx = state["index"]
            stage = pos["tp_stages"][idx]
            stage_qty = _as_float(stage.get("qty"), 0.0)
            executed_qty = min(state["executed_qty"], stage_qty)
            prev_logged_qty = _as_float(stage.get("logged_qty"), 0.0)
            defer_to_full_close = final_tp_index is not None and idx == final_tp_index
            delta_qty = max(executed_qty - prev_logged_qty, 0.0)

            stage["filled_qty"] = executed_qty
            stage["hit"] = executed_qty >= (stage_qty - qty_eps)
            stage.pop("pending", None)

            if not defer_to_full_close and delta_qty > qty_eps:
                partial_events.append({
                    "qty": delta_qty,
                    "price": state["exec_price"] or _as_float(stage.get("price"), 0.0),
                    "side": pos["side"],
                    "entry": _as_float(pos.get("entry"), 0.0),
                    "entry_score": pos.get("entry_score", 0),
                    "entry_time": pos.get("entry_time"),
                })
                stage["logged_qty"] = prev_logged_qty + delta_qty
                new_partial_qty += delta_qty
                changed = True
            elif not defer_to_full_close:
                stage["logged_qty"] = max(prev_logged_qty, executed_qty)

        active_order_ids = set(active_by_id)
        if exchange_size > qty_eps:
            if abs(exchange_size - local_size_before) > qty_eps:
                pos["size"] = exchange_size
                changed = True

            if stop_order_id:
                if stop_order_id in active_order_ids:
                    pos["native_orders_armed"] = True
                elif not stop_filled:
                    needs_arm = True
            else:
                needs_arm = True

            for idx, stage in enumerate(pos.get("tp_stages", [])):
                if stage.get("hit"):
                    continue
                order_id = str(stage.get("order_id") or "")
                order = active_by_id.get(order_id) or closed_by_id.get(order_id)
                if order_id and order_id in active_order_ids:
                    continue
                if _order_is_filled(order):
                    continue
                needs_arm = True

            pos["native_orders_armed"] = not needs_arm

        else:
            remaining_qty = max(local_size_before - new_partial_qty, 0.0)
            if stop_filled:
                if remaining_qty <= qty_eps:
                    remaining_qty = stop_exec_qty
                if remaining_qty > qty_eps:
                    exit_event = {
                        "reason": "stop",
                        "qty": remaining_qty,
                        "price": _order_exec_price(stop_order, _as_float(pos.get("stop_price"), 0.0)),
                        "side": pos["side"],
                        "entry": _as_float(pos.get("entry"), 0.0),
                        "entry_score": pos.get("entry_score", 0),
                        "entry_time": pos.get("entry_time"),
                    }
            elif final_tp_index is not None:
                final_stage = pos["tp_stages"][final_tp_index]
                final_state = stage_states[final_tp_index]
                final_exec_qty = final_state["executed_qty"]
                final_prev_logged = _as_float(final_stage.get("logged_qty"), 0.0)
                close_qty = max(final_exec_qty - final_prev_logged, remaining_qty, 0.0)
                if close_qty > qty_eps:
                    final_stage["filled_qty"] = final_exec_qty
                    final_stage["logged_qty"] = final_exec_qty
                    final_stage["hit"] = True
                    exit_event = {
                        "reason": "tp",
                        "qty": close_qty,
                        "price": final_state["exec_price"] or _as_float(final_stage.get("price"), 0.0),
                        "side": pos["side"],
                        "entry": _as_float(pos.get("entry"), 0.0),
                        "entry_score": pos.get("entry_score", 0),
                        "entry_time": pos.get("entry_time"),
                    }
            elif remaining_qty > qty_eps:
                exit_event = {
                    "reason": "sync_close",
                    "qty": remaining_qty,
                    "price": exchange_mark or _as_float(pos.get("mark_price"), 0.0) or _as_float(pos.get("entry"), 0.0),
                    "side": pos["side"],
                    "entry": _as_float(pos.get("entry"), 0.0),
                    "entry_score": pos.get("entry_score", 0),
                    "entry_time": pos.get("entry_time"),
                }

            if exit_event:
                _client_managed_positions.pop(symbol, None)
                with _cooldown_lock:
                    LAST_EXIT_TIME[symbol] = (time.time(), exit_event["entry_score"])
                changed = True

    for partial_event in partial_events:
        _track_partial_tp_fill(symbol, partial_event, partial_event["qty"], partial_event["price"])

    if exit_event:
        cancel_all_orders(symbol)
        save_live_cooldowns()
        _slot_available_event.set()

        pnl = (
            (exit_event["price"] - exit_event["entry"]) * exit_event["qty"]
            if exit_event["side"] == "Buy"
            else (exit_event["entry"] - exit_event["price"]) * exit_event["qty"]
        )
        reason_label = {
            "stop": "Stop Hit",
            "tp": "Take Profit Hit",
            "sync_close": "Exchange Close",
        }[exit_event["reason"]]
        tui_log(f"{reason_label.upper()}: {symbol} closed at {exit_event['price']}")
        logger.info("%s: %s closed at %s, PnL %.4f", reason_label.upper(), symbol, exit_event["price"], pnl)
        send_telegram_message(
            f"🔔 *LIVE TRADE CLOSED ({reason_label})*\n"
            f"Symbol: {symbol}\n"
            f"Exit: {exit_event['price']}\n"
            f"PnL: {pnl:+.4f} USDT"
        )
        _log_closed_trade(
            symbol,
            exit_event["side"],
            exit_event["entry"],
            exit_event["price"],
            exit_event["qty"],
            exit_event["entry_score"],
            exit_event["entry_time"],
            exit_event["reason"],
        )

    if needs_arm and exchange_size > qty_eps:
        if not _arm_native_exit_orders(symbol, strict=True):
            tui_log(f"ERROR: Failed to repair native exit orders for {symbol}")
        changed = True

    return changed or bool(partial_events) or exit_event is not None


def _sync_positions_with_exchange(
    exchange_positions: List[dict],
    balance: float,
    free_balance: float,
    used_balance: float,
) -> None:
    exchange_by_symbol: Dict[str, dict] = {}
    for pos in exchange_positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue
        current = exchange_by_symbol.get(symbol)
        if current is None or abs(_as_float(pos.get("size"), 0.0)) > abs(_as_float(current.get("size"), 0.0)):
            exchange_by_symbol[symbol] = pos
    with _stop_lock:
        tracked_symbols = list(_client_managed_positions.keys())

    changed = False
    for symbol in tracked_symbols:
        changed = _reconcile_symbol_with_exchange(symbol, exchange_by_symbol.get(symbol)) or changed

    if changed:
        _persist_live_positions(balance, free_balance, used_balance)


def cancel_all_orders(symbol: str) -> bool:
    ok = False
    for untriggered in ("false", "true"):
        resp = _delete("/g-orders/all", params={"symbol": symbol, "untriggered": untriggered})
        if resp and resp.get("code") == 0:
            ok = True
    return ok


def place_stop_close_order(
    symbol: str,
    side: str,
    stop_price: float,
    position_side: str,
) -> Optional[dict]:
    return _put("/g-orders/create", params={
        "clOrdID": f"bot-stop-{int(time.time() * 1000)}",
        "symbol": symbol,
        "side": side,
        "ordType": "Stop",
        "orderQtyRq": "0",
        "stopPxRp": _round_price(symbol, stop_price),
        "triggerType": "ByLastPrice",
        "timeInForce": "ImmediateOrCancel",
        "closeOnTrigger": "true",
        "posSide": _current_pos_side(position_side),
    })


def amend_stop_close_order(
    symbol: str,
    order_id: str,
    stop_price: float,
    position_side: str,
) -> Optional[dict]:
    return _put("/g-orders/replace", params={
        "symbol": symbol,
        "orderID": order_id,
        "stopPxRp": _round_price(symbol, stop_price),
        "triggerType": "ByLastPrice",
        "posSide": _current_pos_side(position_side),
    })


def place_take_profit_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    position_side: str,
) -> Optional[dict]:
    qty_str = _round_qty(symbol, qty)
    if float(qty_str) <= 0:
        return {"code": 0, "msg": "", "data": {"orderID": None}}
    return _put("/g-orders/create", params={
        "clOrdID": f"bot-tp-{int(time.time() * 1000)}",
        "symbol": symbol,
        "side": side,
        "ordType": "Limit",
        "priceRp": _round_price(symbol, price),
        "orderQtyRq": qty_str,
        "reduceOnly": "true",
        "timeInForce": "GoodTillCancel",
        "posSide": _current_pos_side(position_side),
    })


def _place_with_retries(fn, attempts: int = 3, delay: float = 1.0):
    last_resp = None
    for attempt in range(attempts):
        last_resp = fn()
        if last_resp and last_resp.get("code") == 0:
            return last_resp
        if attempt < attempts - 1:
            time.sleep(delay)
    return last_resp


def _wait_for_exchange_position(
    symbol: str,
    position_side: str,
    min_size: float,
    timeout: float = 8.0,
    poll_interval: float = 0.5,
) -> bool:
    deadline = time.time() + max(timeout, 0.0)
    qty_eps = max(_qty_step(symbol) / 2.0, 1e-9)
    target_size = max(float(min_size) - qty_eps, qty_eps)
    while time.time() <= deadline:
        exchange_pos = _get_exchange_position(symbol, position_side)
        exchange_size = abs(_as_float((exchange_pos or {}).get("size"), 0.0))
        if exchange_size >= target_size:
            return True
        time.sleep(max(poll_interval, 0.1))
    return False


def _confirmed_entry_snapshot(
    symbol: str,
    position_side: str,
    fallback_price: float,
    fallback_size: float,
    timeout: float = 4.0,
    poll_interval: float = 0.25,
) -> Tuple[float, float]:
    deadline = time.time() + max(timeout, 0.0)
    confirmed_price = float(fallback_price)
    confirmed_size = max(float(fallback_size), 0.0)

    while time.time() <= deadline:
        exchange_pos = _get_exchange_position(symbol, position_side)
        if exchange_pos:
            exchange_size = abs(_as_float(exchange_pos.get("size"), 0.0))
            exchange_price = _as_float(
                exchange_pos.get("avgEntryPriceRp") or exchange_pos.get("avgEntryPrice"),
                confirmed_price,
            )
            if exchange_price > 0.0:
                confirmed_price = exchange_price
            if exchange_size > 0.0:
                return exchange_size, confirmed_price
        time.sleep(max(poll_interval, 0.1))

    return confirmed_size, confirmed_price


def _schedule_native_arm_retry(symbol: str) -> None:
    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return
        now = time.time()
        pos["native_orders_armed"] = False
        pos["native_arm_pending"] = False
        pos["native_arm_started_at"] = 0.0
        pos["native_arm_last_attempt_at"] = now
        pos["native_arm_deadline"] = max(_as_float(pos.get("native_arm_deadline"), 0.0), now + NATIVE_ARM_GRACE_SECONDS)


def _close_unprotected_position(symbol: str, reason: str) -> bool:
    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        if pos.get("exit_pending"):
            return False
        pos["exit_pending"] = True
        close_plan = {
            "symbol": symbol,
            "side": pos["side"],
            "size": float(pos.get("size") or 0.0),
            "entry": float(pos.get("entry") or 0.0),
            "entry_score": int(pos.get("entry_score") or 0),
        }

    cancel_all_orders(symbol)
    close_resp = place_market_order(
        symbol,
        _position_close_side(close_plan["side"]),
        _round_qty(symbol, close_plan["size"]),
        position_side=close_plan["side"],
    )
    if close_resp and close_resp.get("code") == 0:
        with _stop_lock:
            _client_managed_positions.pop(symbol, None)
        with _cooldown_lock:
            LAST_EXIT_TIME[symbol] = (time.time(), close_plan["entry_score"])
        save_live_cooldowns()
        _persist_live_positions()
        _slot_available_event.set()
        _pause_new_entries(reason)
        send_telegram_message(
            f"⚠️ *LIVE ENTRY REVERSED*\n"
            f"Symbol: {symbol}\n"
            f"Reason: {reason}"
        )
        return True

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if pos:
            pos.pop("exit_pending", None)
    tui_log(f"CRITICAL: Auto-close failed for unprotected {symbol}: {close_resp}")
    send_telegram_message(
        f"⚠️ *UNPROTECTED LIVE POSITION*\n"
        f"Symbol: {symbol}\n"
        f"Reason: {reason}\n"
        f"Immediate action needed."
    )
    return False


def _arm_native_exit_orders(symbol: str, strict: bool = False) -> bool:
    if not USE_NATIVE_EXIT_ORDERS:
        return True

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        now = time.time()
        started_at = _as_float(pos.get("native_arm_started_at"), 0.0)
        if pos.get("native_arm_pending"):
            last_attempt_at = _as_float(pos.get("native_arm_last_attempt_at"), 0.0)
            if (
                started_at
                and last_attempt_at
                and (now - started_at) < 15.0
                and (now - last_attempt_at) < 15.0
            ):
                return bool(pos.get("native_orders_armed"))
        pos["native_arm_pending"] = True
        pos["native_arm_started_at"] = started_at or now
        pos["native_arm_last_attempt_at"] = now
        side = pos["side"]
        close_side = _position_close_side(side)
        stop_price = float(pos.get("stop_price") or 0.0)
        tp_stages = [
            {
                "index": idx,
                "price": float(stage["price"]),
                "qty": max(float(stage["qty"]) - float(stage.get("filled_qty") or 0.0), 0.0),
            }
            for idx, stage in enumerate(pos.get("tp_stages", []))
            if not stage.get("hit") and max(float(stage.get("qty") or 0.0) - float(stage.get("filled_qty") or 0.0), 0.0) > 0.0
        ]

    if not _wait_for_exchange_position(symbol, side, _as_float(pos.get("size"), 0.0)):
        tui_log(f"ERROR: Exchange position for {symbol} was not ready for native exit arming.")
        _schedule_native_arm_retry(symbol)
        return False

    exchange_pos = _get_exchange_position(symbol, side)
    exchange_size = abs(_as_float((exchange_pos or {}).get("size"), 0.0))
    qty_eps = max(_qty_step(symbol) / 2.0, 1e-9)
    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        if exchange_size > qty_eps:
            if _rebalance_unfilled_tp_stages(symbol, pos, exchange_size):
                pos["native_orders_armed"] = False
            if abs(_as_float(pos.get("size"), 0.0) - exchange_size) > qty_eps:
                pos["size"] = exchange_size
        stop_price = float(pos.get("stop_price") or 0.0)
        tp_stages = [
            {
                "index": idx,
                "price": float(stage["price"]),
                "qty": max(float(stage["qty"]) - float(stage.get("filled_qty") or 0.0), 0.0),
            }
            for idx, stage in enumerate(pos.get("tp_stages", []))
            if not stage.get("hit") and max(float(stage.get("qty") or 0.0) - float(stage.get("filled_qty") or 0.0), 0.0) > 0.0
        ]

    effective_stop_price = _effective_native_stop_price(symbol, side, stop_price)
    if effective_stop_price is None:
        _schedule_native_arm_retry(symbol)
        tui_log(f"ERROR: Native stop for {symbol} is invalid against liquidation/current price.")
        return False
    stop_price = effective_stop_price

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if pos:
            pos["stop_price"] = stop_price

    active_orders = get_active_orders(symbol)
    if active_orders is None:
        tui_log(f"ERROR: Failed to query active orders for {symbol} while arming native exits.")
        _schedule_native_arm_retry(symbol)
        return False
    if active_orders:
        cancel_all_orders(symbol)
        time.sleep(0.3)

    stop_resp = _place_with_retries(lambda: place_stop_close_order(symbol, close_side, stop_price, side))
    if not stop_resp or stop_resp.get("code") != 0:
        _schedule_native_arm_retry(symbol)
        tui_log(f"ERROR: Failed to place native stop for {symbol}: {stop_resp}")
        return False

    stop_order_id = (stop_resp.get("data") or {}).get("orderID")
    stage_order_ids: Dict[int, Optional[str]] = {}
    all_tp_ok = True
    for stage in tp_stages:
        tp_resp = _place_with_retries(
            lambda stage=stage: place_take_profit_order(symbol, close_side, stage["qty"], stage["price"], side)
        )
        if not tp_resp or tp_resp.get("code") != 0:
            all_tp_ok = False
            tui_log(f"ERROR: Failed to place TP{stage['index'] + 1} for {symbol}: {tp_resp}")
            stage_order_ids[stage["index"]] = None
            continue
        stage_order_ids[stage["index"]] = (tp_resp.get("data") or {}).get("orderID")

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return False
        pos["exchange_exit_mode"] = "native"
        pos["stop_order_id"] = stop_order_id
        pos["last_submitted_stop_price"] = stop_price
        pos["last_stop_refresh_ts"] = time.time()
        pos["native_orders_armed"] = all_tp_ok
        pos["native_arm_pending"] = False
        pos["native_arm_started_at"] = 0.0
        pos["native_arm_last_attempt_at"] = time.time()
        pos["native_arm_deadline"] = 0.0
        for stage in pos.get("tp_stages", []):
            if not stage.get("hit"):
                stage["order_id"] = None
        for idx, order_id in stage_order_ids.items():
            if idx < len(pos.get("tp_stages", [])):
                pos["tp_stages"][idx]["order_id"] = order_id

    _persist_live_positions()

    if strict and not all_tp_ok:
        cancel_all_orders(symbol)
        _schedule_native_arm_retry(symbol)
        return False
    return True


def _refresh_stop_order(symbol: str, stop_price: float, position_side: str) -> None:
    if not USE_NATIVE_EXIT_ORDERS:
        return

    effective_stop_price = _effective_native_stop_price(symbol, position_side, stop_price)
    if effective_stop_price is None:
        tui_log(f"ERROR: Failed to refresh native stop for {symbol}: invalid stop vs liquidation/current price.")
        return
    stop_price = effective_stop_price

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return
        order_id = pos.get("stop_order_id")
        pos["stop_price"] = stop_price
        pos["stop_refresh_pending"] = True

    if order_id:
        resp = amend_stop_close_order(symbol, order_id, stop_price, position_side)
        if resp and _is_missing_order_error(resp):
            close_side = _position_close_side(position_side)
            resp = place_stop_close_order(symbol, close_side, stop_price, position_side)
    else:
        close_side = _position_close_side(position_side)
        resp = place_stop_close_order(symbol, close_side, stop_price, position_side)

    with _stop_lock:
        pos = _client_managed_positions.get(symbol)
        if not pos:
            return
        pos.pop("stop_refresh_pending", None)
        if resp and resp.get("code") == 0:
            pos["stop_order_id"] = (resp.get("data") or {}).get("orderID") or pos.get("stop_order_id")
            pos["last_submitted_stop_price"] = stop_price
            pos["last_stop_refresh_ts"] = time.time()
        else:
            pos["native_orders_armed"] = False
            tui_log(f"ERROR: Failed to refresh native stop for {symbol}: {resp}")

    if resp and resp.get("code") == 0:
        _persist_live_positions()

def _get_single_ticker(symbol: str) -> Optional[dict]:
    """patch[7]: fetch one ticker directly — ~200x cheaper than get_tickers()."""
    url = f"{pc.BASE_URL}/md/v3/ticker/24hr"
    try:
        resp = requests.get(url, params={"symbol": symbol}, timeout=8)
        data = resp.json()
        if data.get("error") is not None:
            return None
        return data.get("result")
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# WebSocket & Live Price Feed
# ─────────────────────────────────────────────────────────────────────────────

def _ws_on_message(ws: WebSocketApp, message: str) -> None:
    """Handles inbound WebSocket messages and updates the live price cache."""
    try:
        data = json.loads(message)
        if "market24h_p" in data:
            tick   = data["market24h_p"]
            symbol = tick.get("symbol")
            close  = tick.get("closeRp")
            if symbol and close is not None:
                with _prices_lock:
                    _live_prices[symbol] = float(close)
                _check_stops_live(symbol)
    except json.JSONDecodeError as e:
        logger.debug(f"WS message parse error: {e}")


def _ws_on_open(ws: WebSocketApp) -> None:
    """Subscribes to all currently open positions on WebSocket connect."""
    logger.info("WebSocket connection opened.")
    symbols = list(_client_managed_positions.keys())
    if symbols:
        ws.send(json.dumps({"id": 1, "method": "market24h_p.subscribe", "params": symbols}))


def _ws_heartbeat(ws: WebSocketApp, stop_event: threading.Event) -> None:
    """Keeps the WebSocket alive by sending periodic pings."""
    while not stop_event.is_set():
        time.sleep(5)
        # Check if this heartbeat instance is still the active one
        if ws is not _ws_app:
            logger.debug("Heartbeat thread detected stale WS app — exiting.")
            break
        try:
            if ws.sock and ws.sock.connected:
                ws.send(json.dumps({"id": 0, "method": "server.ping", "params": []}))
            else:
                # Exit if socket is no longer connected
                break
        except (requests.exceptions.ConnectionError, BrokenPipeError):
            logger.debug("WebSocket closed during heartbeat — exiting heartbeat thread.")
            break
        except Exception as e:
            logger.debug(f"Heartbeat error: {e}")
            break


def _ws_run_loop() -> None:
    """Maintains the WebSocket connection, reconnecting while positions are open."""
    global _ws_app
    ws_url = "wss://testnet.phemex.com/ws" if "testnet" in pc.BASE_URL else "wss://ws.phemex.com"

    retries = 0
    while True:
        stop_event = threading.Event()
        _ws_app = WebSocketApp(ws_url, on_message=_ws_on_message, on_open=_ws_on_open)
        threading.Thread(target=_ws_heartbeat, args=(_ws_app, stop_event), daemon=True).start()
        _ws_app.run_forever()

        # Signal heartbeat to stop after run_forever exits
        stop_event.set()

        # Grace period to allow pending saves/subscriptions to complete
        time.sleep(2.0)
        if not _client_managed_positions:
            break

        retries += 1
        delay = min(2**retries, 60)
        logger.info(f"WebSocket disconnected. Retrying in {delay}s (attempt {retries})...")
        time.sleep(delay)


def _ensure_ws_started() -> None:
    """Starts the WebSocket thread if it is not already running."""
    global _ws_thread
    if _ws_thread is None or not _ws_thread.is_alive():
        _ws_thread = threading.Thread(target=_ws_run_loop, daemon=True)
        _ws_thread.start()


def _subscribe_symbol(symbol: str) -> None:
    """Subscribes the WebSocket to a new symbol after a short delay."""
    def _do_sub() -> None:
        time.sleep(1.5)
        if _ws_app and _ws_app.sock and _ws_app.sock.connected:
            symbols = list(_client_managed_positions.keys())
            _ws_app.send(json.dumps({"id": 1, "method": "market24h_p.subscribe", "params": symbols}))

    threading.Thread(target=_do_sub, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Stop / Take-Profit Monitoring
# ─────────────────────────────────────────────────────────────────────────────

def _check_stops_live(symbol: str) -> None:
    """Evaluates trailing-stop and take-profit levels for a symbol on each price tick."""
    if USE_NATIVE_EXIT_ORDERS:
        refresh_args = None
        retry_arm = False
        protection_timeout_reason = None
        with _stop_lock:
            pos = _client_managed_positions.get(symbol)
            if not pos:
                return

            with _prices_lock:
                current_price = _live_prices.get(symbol)
            if current_price is None:
                return

            side = pos["side"]
            stop_price = _as_float(pos.get("stop_price"), 0.0)
            if stop_price <= 0.0:
                return

            if side == "Buy":
                if current_price > _as_float(pos.get("high_water"), 0.0):
                    pos["high_water"] = current_price
                    pos["stop_price"] = current_price * (1.0 - bot_core.TRAIL_PCT)
            else:
                if current_price < _as_float(pos.get("low_water"), 9_999_999.0):
                    pos["low_water"] = current_price
                    pos["stop_price"] = current_price * (1.0 + bot_core.TRAIL_PCT)

            pos["mark_price"] = current_price

            if not pos.get("native_orders_armed"):
                now = time.time()
                arm_deadline = _as_float(pos.get("native_arm_deadline"), 0.0)
                last_attempt = _as_float(pos.get("native_arm_last_attempt_at"), 0.0)

                if arm_deadline and now >= arm_deadline:
                    protection_timeout_reason = f"native exit orders could not be armed for {symbol}"
                elif not pos.get("native_arm_pending") and (now - last_attempt) >= NATIVE_ARM_RETRY_INTERVAL:
                    pos["native_arm_last_attempt_at"] = now
                    retry_arm = True

            if pos.get("stop_refresh_pending"):
                return

            current_stop = _as_float(pos.get("stop_price"), stop_price)
            last_submitted = _as_float(pos.get("last_submitted_stop_price"), 0.0)
            last_refresh_ts = _as_float(pos.get("last_stop_refresh_ts"), 0.0)
            if pos.get("native_orders_armed") and (
                not pos.get("stop_order_id")
                or (
                    (time.time() - last_refresh_ts) >= STOP_REFRESH_MIN_INTERVAL
                    and _stop_has_improved(symbol, side, current_stop, last_submitted)
                )
            ):
                refresh_args = (symbol, current_stop, side)

        if protection_timeout_reason:
            if _close_unprotected_position(symbol, protection_timeout_reason):
                tui_log(f"CRITICAL: {symbol} closed because native exits never armed.")
            return

        if retry_arm:
            _arm_native_exit_orders(symbol, strict=True)
            return

        if refresh_args:
            _refresh_stop_order(*refresh_args)
        return

    # Narrow lock scope — copy data then release lock
    exit_to_process = None
    partial_tp_to_process = None
    
    with _stop_lock:
        if symbol not in _client_managed_positions:
            return

        pos = _client_managed_positions[symbol]
        if pos.get("exit_pending"):
            return
        with _prices_lock:
            current_price = _live_prices.get(symbol)
        if current_price is None:
            return

        side  = pos["side"]
        entry = pos["entry"]
        size  = float(pos["size"])
        # Use .get() for stop_price and check existence
        stop_price = pos.get("stop_price")
        if stop_price is None:
            return

        stop_hit   = False
        tp_hit     = False
        exit_price = current_price
        partial_tp = False
        q_to_close = 0.0

        if side == "Buy":
            if current_price > pos.get("high_water", 0.0):
                pos["high_water"]  = current_price
                pos["stop_price"]  = current_price * (1.0 - bot_core.TRAIL_PCT)
                stop_price = pos["stop_price"] # update local stop_price
                
            if current_price <= stop_price:
                stop_hit   = True
                exit_price = stop_price
            else:
                # Check stages
                for stage_idx, stage in enumerate(pos.get("tp_stages", [])):
                    if stage.get("pending"):
                        continue
                    if not stage["hit"] and current_price >= stage["price"]:
                        tp_hit = True
                        exit_price = stage["price"]
                        q_to_close = stage["qty"]
                        if q_to_close >= pos["size"]:
                            partial_tp = False
                        else:
                            partial_tp = True
                            stage["pending"] = True
                            partial_tp_to_process = {
                                "symbol": symbol, "side": side, "entry": entry,
                                "exit_price": exit_price, "qty": q_to_close,
                                "score": pos.get("entry_score", 0), "time": pos.get("entry_time"),
                                "stage_index": stage_idx, "mark_price": current_price,
                            }
                        break
        else:
            if current_price < pos.get("low_water", 9_999_999.0):
                pos["low_water"]  = current_price
                pos["stop_price"] = current_price * (1.0 + bot_core.TRAIL_PCT)
                stop_price = pos["stop_price"] # update local stop_price
                
            if current_price >= stop_price:
                stop_hit   = True
                exit_price = stop_price
            else:
                # Check stages
                for stage_idx, stage in enumerate(pos.get("tp_stages", [])):
                    if stage.get("pending"):
                        continue
                    if not stage["hit"] and current_price <= stage["price"]:
                        tp_hit = True
                        exit_price = stage["price"]
                        q_to_close = stage["qty"]
                        if q_to_close >= pos["size"]:
                            partial_tp = False
                        else:
                            partial_tp = True
                            stage["pending"] = True
                            partial_tp_to_process = {
                                "symbol": symbol, "side": side, "entry": entry,
                                "exit_price": exit_price, "qty": q_to_close,
                                "score": pos.get("entry_score", 0), "time": pos.get("entry_time"),
                                "stage_index": stage_idx, "mark_price": current_price,
                            }
                        break

        if not (stop_hit or tp_hit):
            pos["mark_price"] = current_price
            return

        if partial_tp and partial_tp_to_process:
            pos["exit_pending"] = True
        else:
            pos["exit_pending"] = True

        exit_reason = "Stop Hit" if stop_hit else "Take Profit Hit"
        pnl = (exit_price - entry) * size if side == "Buy" else (entry - exit_price) * size

        if not partial_tp:
            # Prepare for I/O outside the lock
            exit_to_process = {
                "symbol": symbol,
                "side": side,
                "exit_reason": exit_reason,
                "exit_price": exit_price,
                "pnl": pnl,
                "entry": entry,
                "size": size,
                "entry_score": pos.get("entry_score", 0),
                "entry_time": pos.get("entry_time"),
                "stop_hit": stop_hit,
            }

    # Process I/O outside the lock
    if partial_tp_to_process:
        close_side = "Sell" if partial_tp_to_process["side"] == "Buy" else "Buy"
        resp = place_market_order(
            symbol,
            close_side,
            _round_qty(symbol, partial_tp_to_process["qty"]),
            position_side=partial_tp_to_process["side"],
        )
        if not resp or resp.get("code") != 0:
            with _stop_lock:
                pos = _client_managed_positions.get(symbol)
                if pos:
                    stage_index = partial_tp_to_process["stage_index"]
                    stages = pos.get("tp_stages", [])
                    if 0 <= stage_index < len(stages):
                        stages[stage_index].pop("pending", None)
                    pos.pop("exit_pending", None)
            tui_log(f"ERROR: Partial TP close failed for {symbol}: {resp}")
            return

        with _stop_lock:
            pos = _client_managed_positions.get(symbol)
            if pos:
                stage_index = partial_tp_to_process["stage_index"]
                stages = pos.get("tp_stages", [])
                if 0 <= stage_index < len(stages):
                    stages[stage_index].pop("pending", None)
                    stages[stage_index]["hit"] = True
                pos["size"] = max(float(pos["size"]) - partial_tp_to_process["qty"], 0.0)
                pos["mark_price"] = partial_tp_to_process["mark_price"]
                pos.pop("exit_pending", None)

        _log_closed_trade(
            symbol,
            partial_tp_to_process["side"],
            partial_tp_to_process["entry"],
            partial_tp_to_process["exit_price"],
            partial_tp_to_process["qty"],
            partial_tp_to_process["score"],
            partial_tp_to_process["time"],
            "partial_tp",
        )
        tui_log(f"PARTIAL TP: {symbol} closed at {partial_tp_to_process['exit_price']}")
        _persist_live_positions()
        return

    if exit_to_process:
        close_side = "Sell" if exit_to_process["side"] == "Buy" else "Buy"
        resp = place_market_order(
            symbol,
            close_side,
            _round_qty(symbol, exit_to_process["size"]),
            position_side=exit_to_process["side"],
        )
        if not resp or resp.get("code") != 0:
            with _stop_lock:
                pos = _client_managed_positions.get(symbol)
                if pos:
                    pos.pop("exit_pending", None)
            tui_log(f"ERROR: Exit close failed for {symbol}: {resp}")
            return

        with _stop_lock:
            _client_managed_positions.pop(symbol, None)
        with _cooldown_lock:
            LAST_EXIT_TIME[symbol] = (time.time(), exit_to_process["entry_score"])

        save_live_cooldowns()
        _slot_available_event.set()

        logger.info(f"{exit_to_process['exit_reason'].upper()} HIT: {symbol} closed at {exit_to_process['exit_price']}, PnL: {exit_to_process['pnl']:.4f}")
        send_telegram_message(f"🔔 *LIVE TRADE CLOSED ({exit_to_process['exit_reason']})*\nSymbol: {symbol}\nExit: {exit_to_process['exit_price']}\nPnL: {exit_to_process['pnl']:+.4f} USDT")
        _log_closed_trade(symbol, exit_to_process["side"], exit_to_process["entry"], 
                          exit_to_process["exit_price"], exit_to_process["size"], 
                          exit_to_process["entry_score"], exit_to_process["entry_time"], 
                          "stop" if exit_to_process["stop_hit"] else "tp")
        _persist_live_positions()

def _log_closed_trade(
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float,
    size: float,
    entry_score: float,
    entry_time: Optional[str],
    reason: str,
) -> None:
    """Appends a closed-trade record to live_trade_results.json."""
    pnl = (exit_price - entry) * size if direction == "Buy" else (entry - exit_price) * size

    hold_time = 0
    if entry_time:
        try:
            hold_time = (datetime.datetime.now() - datetime.datetime.fromisoformat(entry_time)).total_seconds()
        except ValueError:
            pass

    record = {
        "symbol":      symbol,
        "direction":   "LONG" if direction == "Buy" else "SHORT",
        "entry":       entry,
        "exit":        exit_price,
        "pnl":         round(pnl, 4),
        "hold_time_s": int(hold_time),
        "score":       entry_score,
        "reason":      reason,
        "timestamp":   datetime.datetime.now().isoformat(),
    }

    try:
        with _file_io_lock:
            with open(LIVE_RESULTS_FILE, "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps(record) + "\n")
    except OSError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# TUI — Drawing Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _vlen(s: str) -> int:
    """Visible length of a string — strips ANSI/escape codes."""
    return len(re.sub(r"\x1b\[[0-9;]*[mKHJ]", "", s))

def _rpad(s: str, width: int, char: str = " ") -> str:
    """Right-pad a styled string to exact visible `width`."""
    return s + char * max(0, width - _vlen(s))

def _box_top(title: str, width: int, right_tag: str = "") -> str:
    """Single-line top border: ┌─ TITLE ──────────── right_tag ┐"""
    inner = width - 2
    if title:
        lbl = f"─ {title} "
        if right_tag:
            gap = inner - _vlen(lbl) - _vlen(right_tag) - 1
            return f"┌{lbl}{'─' * max(gap, 1)}{right_tag}┐"
        return f"┌{lbl}{'─' * (inner - _vlen(lbl))}┐"
    return f"┌{'─' * inner}┐"

def _box_bot(width: int) -> str:
    return f"└{'─' * (width - 2)}┘"

def _box_row(term: blessed.Terminal, content: str, width: int) -> str:
    """│ content (padded) │  — content is already styled."""
    inner = width - 4
    padded = _rpad(content, inner)
    return term.cyan("│") + " " + padded + term.normal + " " + term.cyan("│")

def _box_empty(term: blessed.Terminal, width: int) -> str:
    return term.cyan("│") + " " * (width - 2) + term.cyan("│")

def sparkline(data: List[float], width: int) -> str:
    """Returns a unicode sparkline of `width` characters from the given data."""
    if not data:
        return "▁" * width
    data = data[-width:]
    lo, hi = min(data), max(data)
    rng = hi - lo if hi != lo else 1.0
    return "".join(_SPARK_CHARS[min(int((v - lo) / rng * 7), 7)] for v in data)

def _draw_header(term: blessed.Terminal, current_time: str, max_width: int = 80) -> None:
    """Draws the top header: double outer box, title left, clock right."""
    w = max_width
    title     = "PHEMEX LIVE BOT"
    badge     = "◈ LIVE"
    session_s = f"SESS: {LIVE_SESSION}"
    
    left_raw  = f"  ⚡ {title}  {badge}"
    right_raw = f"{session_s}  {current_time}  "
    gap       = max(0, w - 2 - len(left_raw) - len(right_raw))

    left_styled  = (
        "  ⚡ "
        + term.bold_cyan(title)
        + "  "
        + term.bold_red(badge)
    )
    right_styled = term.bold_white(session_s) + "  " + term.bold_white(current_time) + "  "
    body = term.cyan("║") + left_styled + " " * gap + right_styled + term.cyan("║")

    print(term.move_xy(2, 1) + term.cyan("╔" + "═" * (w - 2) + "╗"))
    print(term.move_xy(2, 2) + body)
    print(term.move_xy(2, 3) + term.cyan("╠" + "═" * (w - 2) + "╣"))

def _draw_positions_section(
    term: blessed.Terminal,
    positions: List[Dict[str, Any]],
    current_prices: Dict[str, float],
    start_row: int,
    max_width: int = 80,
) -> int:
    """Renders the active-positions panel."""
    w   = max_width
    row = start_row
    n   = len(positions)

    slot_tag = f"─ {n} open " if n else "─ idle "
    print(term.move_xy(2, row) + term.cyan(_box_top("OPEN POSITIONS", w, slot_tag)))
    row += 1

    if not positions:
        msg = term.white("  Waiting for qualifying setups") + term.cyan(" ·")
        print(term.move_xy(2, row) + _box_row(term, _rpad(msg, w - 4), w))
        row += 1
    else:
        for pos in positions:
            sym        = pos["symbol"]
            side       = pos["side"]
            entry      = float(pos["entry"])
            size       = float(pos["size"])
            stop       = float(pos.get("stop_price", 0))
            tp         = float(pos.get("take_profit", 0))
            orig_stop  = float(pos.get("original_stop", stop))
            score      = pos.get("entry_score", 0)
            now        = current_prices.get(sym)
            is_long    = side == "Buy"

            upnl = 0.0
            if now:
                upnl = (now - entry) * size if is_long else (entry - now) * size
            
            # Direction badge
            dir_badge = (
                term.bold_green("▲ LONG ") if is_long else term.bold_red("▼ SHORT")
            )
            now_str = f"{now:.5g}" if now else "·······"
            if now:
                pnl_str = (
                    term.bold_green(f"+{upnl:.4f}")
                    if upnl >= 0 else term.bold_red(f"{upnl:.4f}")
                )
            else:
                pnl_str = term.white("·······")

            margin_s = term.cyan(f"M: ${pos.get('margin', 0.0):.1f}")
            lev_s    = term.cyan(f"{pos.get('leverage', 0)}x")
            # ── Row 1: direction · symbol · entry → now · pnl · score ──────
            score_badge = term.yellow(f"[{score}]")
            arrow       = term.white("──▶")
            entry_s     = term.white(f"{entry:.5g}")
            now_s       = term.white(now_str)
            sym_s       = term.bold_white(f"{sym:<12}")

            line1 = f" {dir_badge} {sym_s} {entry_s} {arrow} {now_s}  {margin_s} ({lev_s})  {pnl_str}  {score_badge}"
            print(term.move_xy(2, row) + _box_row(term, line1, w))
            row += 1

            # ── Row 2: price-position bar ────────────────────────────────────
            if now:
                bar_w = w - 16
                pts   = [orig_stop, stop, entry, now, tp]
                lo    = min(pts)
                hi    = max(pts)
                rng   = (hi - lo) if hi != lo else 1.0

                def gp(v: float) -> int:
                    return max(0, min(bar_w - 1, int((v - lo) / rng * (bar_w - 1))))

                bar = list("─" * bar_w)
                bar[gp(orig_stop)] = term.red("╳")
                bar[gp(stop)]      = term.bold_red("S")
                bar[gp(entry)]     = term.yellow("E")
                bar[gp(tp)]        = term.bold_green("T")
                bar[gp(now)]       = term.bold_white("●")

                sl_s  = term.red(f"{stop:.4g}")
                tp_s  = term.green(f"{tp:.4g}")
                label = f"    ╰ SL {sl_s}  TP {tp_s}  " + term.cyan("[") + "".join(bar) + term.cyan("]")
                print(term.move_xy(2, row) + _box_row(term, label, w))
                row += 1

    print(term.move_xy(2, row) + term.cyan(_box_bot(w)))
    row += 1
    return row

def _draw_account_session_section(
    term: blessed.Terminal,
    balance: float,
    locked_margin: float,
    current_upnl: float,
    equity: float,
    total_trades: int,
    wins: int,
    losses: int,
    win_rate: float,
    total_closed_pnl: float,
    start_row: int,
    max_width: int = 80,
    equity_history: List[float] = None
) -> int:
    """Two-column panel: wallet left, session stats right."""
    spark_data = equity_history if equity_history else []
    w   = max_width
    lw  = 36          # left column width
    gap = 2
    rw  = w - lw - gap

    eq_color   = term.bold_green  if equity  >= balance else term.bold_red
    upnl_color = term.green       if current_upnl >= 0 else term.red
    rpnl_color = term.bold_green  if total_closed_pnl >= 0 else term.bold_red

    spark = sparkline(spark_data, lw - 6)
    spark_colored = term.green(spark) if current_upnl >= 0 else term.red(spark)

    # ── Left panel: wallet ────────────────────────────────────────────────────
    left_lines: List[str] = []
    left_lines.append(term.cyan(_box_top("WALLET (LIVE)", lw)))
    left_lines.append(_box_row(term, "  Balance  " + term.bold_white(f"${balance:9.2f}"), lw))
    left_lines.append(_box_row(term, "  Locked   " + term.yellow(f"${locked_margin:9.2f}"), lw))
    left_lines.append(_box_row(term, "  uPnL     " + upnl_color(f"{current_upnl:+.4f}"), lw))
    left_lines.append(_box_row(term, "  Equity   " + eq_color(f"${equity:9.2f}"), lw))
    left_lines.append(_box_row(term, "  " + spark_colored + "  equity", lw))
    left_lines.append(term.cyan(_box_bot(lw)))

    # ── Right panel: statistics ───────────────────────────────────────────────
    right_lines: List[str] = []
    right_lines.append(term.cyan(_box_top("STATISTICS", rw)))
    right_lines.append(_box_row(term, "  Trades  " + term.bold_white(str(total_trades).ljust(4)), rw))
    right_lines.append(_box_row(term, f"  {term.bold_green(f'✅ {wins}W')}   {term.bold_red(f'❌ {losses}L')}   Rate {term.yellow(f'{win_rate:.1f}%')}", rw))
    right_lines.append(_box_row(term, "  Realized  " + rpnl_color(f"{total_closed_pnl:+.4f}"), rw))
    right_lines.append(_box_empty(term, rw))
    right_lines.append(term.cyan(_box_bot(rw)))

    row = start_row
    for l_line, r_line in zip(left_lines, right_lines):
        print(term.move_xy(2, row) + l_line + " " * gap + r_line)
        row += 1
    return row

def _draw_history_section(
    term: blessed.Terminal,
    history: List[Dict[str, Any]],
    start_row: int,
    max_width: int = 80,
) -> int:
    """Two-per-row closed trade history (last 6)."""
    w      = max_width
    row    = start_row
    recent = history[::-1][:6]

    print(term.move_xy(2, row) + term.cyan(_box_top("TRADE HISTORY", w)))
    row += 1

    if not recent:
        msg = term.white("  No closed trades yet")
        print(term.move_xy(2, row) + _box_row(term, msg, w))
        row += 1
    else:
        col_w = (w - 6) // 2
        def _fmt(t: dict) -> str:
            pnl   = t["pnl"]
            c     = term.bold_green if pnl > 0 else term.bold_red
            badge = "✅" if pnl > 0 else "❌"
            ts    = t["timestamp"][11:16]
            sym   = t["symbol"][:10].ljust(10)
            d     = t["direction"][:5].ljust(5)
            return f" {term.white(ts)} {term.bold_white(sym)} {term.cyan(d)} {badge} {c(f'{pnl:+.4f}')}"

        for i in range(0, len(recent), 2):
            left_cell = _fmt(recent[i])
            if i + 1 < len(recent):
                right_cell = _fmt(recent[i + 1])
                sep        = term.cyan("│")
                content    = _rpad(left_cell, col_w) + sep + right_cell
            else:
                content = left_cell
            print(term.move_xy(2, row) + _box_row(term, content, w))
            row += 1

    print(term.move_xy(2, row) + term.cyan(_box_bot(w)))
    row += 1
    return row

def _draw_system_logs_section(
    term: blessed.Terminal,
    logs: List[str],
    start_row: int,
    max_width: int = 80,
) -> int:
    """Scrolling log panel."""
    w   = max_width
    row = start_row
    print(term.move_xy(2, row) + term.cyan(_box_top("SYSTEM LOG", w)))
    row += 1
    with _log_lock:
        display_logs = list(logs[-6:])
    while len(display_logs) < 6:
        display_logs.append("")
    for entry in display_logs:
        if not entry:
            print(term.move_xy(2, row) + _box_empty(term, w))
        else:
            ts_end   = entry.find("]") + 1
            ts_part  = entry[:ts_end]
            msg_part = entry[ts_end:]
            msg_upper = msg_part.upper()
            if "⚡" in entry or "FAST" in msg_upper: msg_color = term.bold_yellow
            elif "TAKE PROFIT" in msg_upper or "ENTERED" in msg_upper: msg_color = term.green
            elif "STOP" in msg_upper or "CLOSED" in msg_upper: msg_color = term.red
            elif "ERROR" in msg_upper or "WARN" in msg_upper: msg_color = term.bold_red
            elif "SCAN" in msg_upper or "COMPLETE" in msg_upper: msg_color = term.cyan
            else: msg_color = term.white
            styled = term.white(ts_part) + msg_color(msg_part)
            print(term.move_xy(2, row) + _box_row(term, styled, w))
        row += 1
    print(term.move_xy(2, row) + term.cyan(_box_bot(w)))
    row += 1
    return row

def _draw_footer(term: blessed.Terminal, row: int, max_width: int = 80) -> None:
    """Bottom bar."""
    w          = max_width
    left_part  = "  " + term.bold_white("[S]") + term.white(" Close All") + "  " + term.bold_white("[Q]") + term.white(" Quit") + "  "
    right_part = "  ⚡ " + term.bold_cyan("FANCYBOT") + term.white(" v2 (LIVE)") + "  "
    gap        = max(0, w - 2 - _vlen(left_part) - _vlen(right_part))
    inner      = left_part + term.cyan("─" * gap) + right_part
    print(term.move_xy(2, row) + term.cyan("╚═") + inner + term.cyan("═╝"))

def _live_pnl_display() -> None:
    """Main TUI loop."""
    global _display_thread_running, _equity_history
    term = blessed.Terminal()
    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        try:
            while True:
                if _display_paused.is_set():
                    time.sleep(0.5)
                    continue
                
                acc = fetch_live_account_state()
                save_live_account(acc)
                
                history: List[dict] = []
                if LIVE_RESULTS_FILE.exists():
                    try:
                        history = [json.loads(ln) for ln in LIVE_RESULTS_FILE.read_text().splitlines() if ln.strip()]
                    except Exception: pass

                wins = [t for t in history if t["pnl"] > 0]
                total_trades = len(history)
                win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0.0
                total_closed_pnl = sum(t["pnl"] for t in history)
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                balance = acc.get("balance", 0.0)

                with _prices_lock:
                    current_upnl = 0.0
                    locked_margin = 0.0
                    for sym, pos in _client_managed_positions.items():
                        locked_margin += pos.get("margin", 0.0)
                        if _live_prices.get(sym):
                            now, entry, size = _live_prices[sym], pos["entry"], float(pos["size"])
                            current_upnl += (now - entry) * size if pos["side"] == "Buy" else (entry - now) * size

                equity = balance + locked_margin + current_upnl
                _equity_history.append(equity)
                if len(_equity_history) > _max_history: _equity_history.pop(0)

                print(term.home, end="")
                _draw_header(term, current_time, 80)
                row = 4
                row = _draw_positions_section(term, list(_client_managed_positions.values()), _live_prices, row, 80)
                row = _draw_account_session_section(term, balance, locked_margin, current_upnl, equity, total_trades, len(wins), total_trades-len(wins), win_rate, total_closed_pnl, row, 80, _equity_history)
                row = _draw_history_section(term, history, row, 80)
                row = _draw_system_logs_section(term, _bot_logs, row, 80)
                _draw_footer(term, row, 80)

                key = term.inkey(timeout=0.8)
                if key.lower() == "s":
                    _display_paused.set()
                    print(term.move_xy(4, row+1) + term.on_red(term.bold_white("  ⚠  CLOSE ALL TRADES? (Y/N)  ")), end="", flush=True)
                    if term.inkey().lower() == "y": _close_all_positions()
                    _display_paused.clear()
                elif key.lower() == "q": break
        except KeyboardInterrupt: pass
        finally:
            with _display_lock: _display_thread_running = False

def verify_live_candidate(
    symbol: str,
    direction: str,
    original_score: int,
    wait_seconds: int = 20,
    runtime: Optional[LiveRuntimeConfig] = None,
) -> Optional[dict]:
    """Waits, then re-scans a single symbol to verify the signal is still valid."""
    if _is_symbol_blacklisted(symbol):
        tui_log(f"SKIP: {symbol} verification skipped because it is blacklisted.")
        return None
    if _symbol_entry_cooldown_active(symbol):
        tui_log(f"SKIP: {symbol} verification skipped due to cooldown.")
        return None
    if not _has_live_entry_capacity():
        tui_log(f"SKIP: {symbol} verification skipped because no entry capacity remains.")
        return None

    steps = 3
    step_wait = wait_seconds / steps
    initial_price = None
    last_result = None

    tui_log(f"VERIFY: {symbol} ({direction}) for {wait_seconds}s...")

    for i in range(steps):
        time.sleep(step_wait)
        if _symbol_entry_cooldown_active(symbol):
            tui_log(f"SKIP: {symbol} verification stopped due to cooldown.")
            return None
        if not _has_live_entry_capacity():
            tui_log(f"SKIP: {symbol} verification stopped because no entry capacity remains.")
            return None
        try:
            ticker = _get_single_ticker(symbol)
        except Exception as e:
            tui_log(f"FAIL: Error fetching ticker for {symbol}: {e}")
            return None

        if not ticker:
            tui_log(f"FAIL: {symbol} ticker not found during verification.")
            return None

        current_price = float(ticker.get("lastRp") or ticker.get("closeRp") or 0.0)
        if initial_price is None: initial_price = current_price

        price_change = pc.pct_change(current_price, initial_price)
        if direction == "LONG":
            if price_change < -0.6:
                tui_log(f"FAIL: {symbol} dropping during verify: {price_change:+.2f}%")
                return None
        else:
            if price_change > 0.6:
                tui_log(f"FAIL: {symbol} pumping during verify: {price_change:+.2f}%")
                return None

        scanner = scanner_long if direction == "LONG" else scanner_short
        cfg = _build_verify_scan_cfg(runtime)
        fresh_result = scanner.analyse(ticker, cfg, enable_ai=False, enable_entity=False)

        if not fresh_result:
            tui_log(f"FAIL: {symbol} no longer qualifies at step {i+1}")
            return None

        fresh_score = fresh_result["score"]
        current_spread = fresh_result.get("spread", 0.0)
        if current_spread is not None and current_spread > 0.25:
            tui_log(f"FAIL: {symbol} spread too high: {current_spread:.2f}%")
            return None

        current_rsi = fresh_result.get("rsi")
        if current_rsi:
            if direction == "LONG" and current_rsi > 70:
                tui_log(f"FAIL: {symbol} RSI {current_rsi:.1f} — overbought.")
                return None
            elif direction == "SHORT" and current_rsi < 30:
                tui_log(f"FAIL: {symbol} RSI {current_rsi:.1f} — oversold.")
                return None

        if fresh_score < original_score * 0.85:
            tui_log(f"FAIL: {symbol} score dropped: {original_score} -> {fresh_score}")
            return None

        last_result = fresh_result
        tui_log(f"  Step {i+1}/{steps}: {symbol} score {fresh_score} ({price_change:+.2f}%)")

    final_change = pc.pct_change(last_result["price"], initial_price)
    if abs(final_change) > 1.5:
        tui_log(f"FAIL: {symbol} overextended ({final_change:+.2f}%) during verify.")
        return None

    tui_log(f"VERIFIED: {symbol} score {last_result['score']} — ready for LIVE entry.")
    return last_result

# ────────────────────────────────────────────────────────────────────
# Client-Side Stop-Loss and PnL Management (to match simulation bot)
# ────────────────────────────────────────────────────────────────────
def update_pnl_and_stops() -> None:
    """Polls live prices and evaluates trailing-stop and take-profit levels."""
    with _stop_lock:
        symbols = list(_client_managed_positions.keys())
    if not symbols:
        return

    if USE_NATIVE_EXIT_ORDERS:
        fetch_live_account_state()
        with _stop_lock:
            symbols = list(_client_managed_positions.keys())
        if not symbols:
            return

    for symbol in symbols:
        with _prices_lock:
            current_price = _live_prices.get(symbol)
        if not current_price:
            current_price = _get_current_price_rest(symbol)
            if current_price:
                with _prices_lock:
                    _live_prices[symbol] = current_price
        if current_price:
            _check_stops_live(symbol)

# ────────────────────────────────────────────────────────────────────
# Core Execution Logic
# ────────────────────────────────────────────────────────────────────
def execute_setup(result: dict, direction: str, dry_run: bool = False) -> bool:
    """Opens a new live position."""
    symbol, price, score = result["inst_id"], result["price"], result["score"]
    side = "Buy" if direction == "LONG" else "Sell"

    with _entry_lock:
        if _entry_pause_active():
            return False
        if _is_symbol_blacklisted(symbol):
            tui_log(f"SKIP: {symbol} is blacklisted.")
            return False

        acc = fetch_live_account_state()
        free_balance = _account_free_balance(acc)
        max_margin = _entry_margin_from_free_balance(free_balance)
        if max_margin + 1e-9 < float(MIN_ENTRY_MARGIN_USDT):
            tui_log(
                f"SKIP: {symbol} usable free margin ${max_margin:.2f} "
                f"is below minimum ${MIN_ENTRY_MARGIN_USDT:.2f}."
            )
            return False

        with _cooldown_lock:
            last_exit_data = LAST_EXIT_TIME.get(symbol)
        if last_exit_data:
            last_exit, last_score = last_exit_data
            if time.time() - last_exit < bot_core.get_cooldown_duration(last_score):
                return False

        effective_min_score = _effective_live_entry_min_score()
        if score < effective_min_score:
            tui_log(
                f"SKIP: {symbol} score {score} is below live entry floor {effective_min_score}."
            )
            return False

        requested_leverage = bot_core.get_score_leverage(score)
        active_leverage = _effective_entry_leverage(symbol, requested_leverage)
        if active_leverage + 1e-9 < float(requested_leverage):
            tui_log(
                f"INFO: {symbol} leverage capped at {_format_leverage(active_leverage)}x "
                f"(requested {_format_leverage(requested_leverage)}x)."
            )

        with _stop_lock:
            if len(_client_managed_positions) >= bot_core.MAX_POSITIONS:
                return False
            if symbol in _client_managed_positions:
                return False

        if dry_run:
            tui_log(f"[DRY RUN] Would open {direction} {symbol} @ {price}")
            return True

        if not _sync_symbol_leverage(symbol, side, active_leverage):
            fallback_leverage = _current_exchange_leverage(symbol, side, active_leverage)
            tui_log(
                f"WARN: Failed to set {symbol} leverage to "
                f"{_format_leverage(active_leverage)}x; continuing with "
                f"{_format_leverage(fallback_leverage)}x sizing."
            )
            active_leverage = fallback_leverage

        active_margin = max_margin
        qty_str = ""
        order_resp = None
        min_margin = float(MIN_ENTRY_MARGIN_USDT)
        while active_margin + 1e-9 >= min_margin:
            notional = active_margin * active_leverage
            qty_raw = notional / price
            qty_str = _round_qty(symbol, qty_raw)
            if float(qty_str) <= 0:
                return False
            order_resp = place_market_order(symbol, side, qty_str, position_side=side)
            if order_resp and order_resp.get("code") == 0:
                break
            if _is_exchange_entry_blocked_error(order_resp):
                _mark_entry_cooldown(symbol, score)
                tui_log(
                    f"WARN: {symbol} entry blocked by exchange ({order_resp.get('msg')}); "
                    f"cooling down before retry."
                )
                return False
            if not _is_no_available_balance_error(order_resp):
                tui_log(f"ERROR: Order failed for {symbol}: {order_resp}")
                return False

            next_margin = min(active_margin - 0.5, active_margin * 0.85)
            if next_margin + 1e-9 < min_margin:
                tui_log(
                    f"ERROR: Order failed for {symbol}: {order_resp} "
                    f"(usable margin tried down to ${active_margin:.2f})"
                )
                return False
            tui_log(
                f"WARN: {symbol} entry size too large for available balance; "
                f"retrying with margin ${next_margin:.2f}."
            )
            active_margin = next_margin

        if not order_resp or order_resp.get("code") != 0:
            tui_log(f"ERROR: Order failed for {symbol}: {order_resp}")
            return False

        avg_price = float(order_resp.get("data", {}).get("avgPriceRp") or price)
        requested_qty = float(qty_str)
        q_total, avg_price = _confirmed_entry_snapshot(symbol, side, avg_price, requested_qty)
        qty_eps = max(_qty_step(symbol) / 2.0, 1e-9)
        if abs(q_total - requested_qty) > qty_eps:
            tui_log(
                f"INFO: {symbol} confirmed live size {_round_qty(symbol, q_total)} "
                f"differs from requested {_round_qty(symbol, requested_qty)}; "
                f"using exchange size for exits."
            )
        protection = bot_core.build_trade_protection(avg_price, q_total, direction, qty_rounder=lambda q: _round_qty(symbol, q))
        with _stop_lock:
            _client_managed_positions[symbol] = {
                "symbol": symbol, "side": side, "size": q_total, "margin": active_margin, "leverage": active_leverage,
                "entry": avg_price, "entry_score": score, "entry_time": datetime.datetime.now().isoformat(),
                "native_orders_armed": not USE_NATIVE_EXIT_ORDERS,
                "native_arm_pending": USE_NATIVE_EXIT_ORDERS,
                "native_arm_started_at": time.time() if USE_NATIVE_EXIT_ORDERS else 0.0,
                "native_arm_last_attempt_at": 0.0,
                "native_arm_deadline": 0.0,
                **protection,
            }
        _persist_live_positions()

        if USE_NATIVE_EXIT_ORDERS and not _arm_native_exit_orders(symbol, strict=True):
            with _stop_lock:
                pos = _client_managed_positions.get(symbol)
                if pos:
                    pos["native_orders_armed"] = False
                    pos["native_arm_pending"] = False
                    pos["native_arm_started_at"] = 0.0
                    pos["native_arm_deadline"] = max(
                        _as_float(pos.get("native_arm_deadline"), 0.0),
                        time.time() + NATIVE_ARM_GRACE_SECONDS,
                    )
            _persist_live_positions()
            tui_log(
                f"WARN: {symbol} opened before native exits were ready; "
                f"retrying protection for up to {int(NATIVE_ARM_GRACE_SECONDS)}s."
            )

        tui_log(f"ENTERED {'▲ LONG' if direction == 'LONG' else '▼ SHORT'} {symbol} @ {avg_price} (Score: {score})")
        send_telegram_message(f"🚀 *LIVE TRADE OPENED*\n*Symbol:* {symbol}\n*Direction:* {direction}\n*Price:* *{avg_price:.4g}*\n*Score:* {score}")

        bot_core.log_trade({
            "timestamp": datetime.datetime.now().isoformat(),
            "symbol":    symbol,
            "direction": direction,
            "price":     avg_price,
            "qty":       str(q_total),
            "leverage":  active_leverage,
            "score":     score,
            "status":    "live_entry",
        }, BOT_LOG_FILE)

        _subscribe_symbol(symbol)
        _ensure_ws_started()
        save_live_account(fetch_live_account_state())

        with _display_lock:
            global _display_thread_running
            if not _display_thread_running and not _no_tui:
                _display_thread_running = True
                threading.Thread(target=_live_pnl_display, daemon=True).start()
        return True

# Hoist helper functions out of the loop
def is_fresh(r: dict, now_dt: datetime.datetime) -> bool:
    ts_raw = r.get("scan_timestamp")
    if not ts_raw: return True
    try:
        ts = datetime.datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw
        return (now_dt - ts).total_seconds() < RESULT_STALENESS_SECONDS
    except (ValueError, TypeError): return True

def on_scan_result(r: dict, direction: str) -> None:
    bot_dir = _normalize_choice(bot_core.DIRECTION, {"LONG", "SHORT", "BOTH"}, "BOTH")
    if bot_dir != "BOTH" and direction.upper() != bot_dir: return
    if _entry_pause_active():
        return
    if _is_symbol_blacklisted(r["inst_id"]):
        return
    if _symbol_entry_cooldown_active(r["inst_id"]):
        return
    
    with _fast_track_lock:
        acc = load_live_account()
        if not _has_live_entry_capacity(acc): return
        if r["inst_id"] in _client_managed_positions or r["inst_id"] in _fast_track_opened: return
        if r["score"] < max(FAST_TRACK_SCORE, _effective_live_entry_min_score()): return
        if time.time() - FAST_TRACK_COOLDOWN.get(r["inst_id"], 0) < FAST_TRACK_COOLDOWN_SECONDS: return
        _fast_track_opened.add(r["inst_id"])
        FAST_TRACK_COOLDOWN[r["inst_id"]] = time.time()

    tui_log(f"⚡ FAST-TRACK: {r['inst_id']} score {r['score']}!")
    verified = verify_live_candidate(r["inst_id"], direction, r["score"], runtime=_runtime_snapshot_from_bot_core())
    if verified: execute_setup(verified, direction)
    else:
        with _fast_track_lock:
            if r["inst_id"] in _fast_track_opened: _fast_track_opened.remove(r["inst_id"])


def _run_live_scan_cycle(args: argparse.Namespace, runtime: LiveRuntimeConfig, acc: dict) -> bool:
    balance = acc.get("balance", 0.0)
    free_balance = _account_free_balance(acc)

    if len(_client_managed_positions) >= bot_core.MAX_POSITIONS:
        return False

    if not _has_free_capacity_for_entry(acc):
        _log_low_margin_scan_skip(free_balance)
        return False

    _reset_low_margin_scan_log_state()
    tui_log(
        f"Scanning LIVE market [{runtime.direction}] ({runtime.timeframe})... "
        f"[Free: ${free_balance:.2f} | Usable: ${_entry_margin_from_free_balance(free_balance):.2f} | Balance: ${balance:.2f}]"
    )

    _display_paused.set()
    t0 = time.time()
    try:
        long_r, short_r = bot_core.run_scanner_both(
            _build_live_scan_cfg(runtime),
            args,
            on_result=on_scan_result,
            show_progress=not _no_tui,
        )
    except Exception as exc:
        logger.exception("Live scan cycle failed")
        tui_log(f"{Fore.RED}SCAN ERROR: {type(exc).__name__}: {exc}")
        return False
    finally:
        _display_paused.clear()

    elapsed = time.time() - t0
    tui_log(f"Scan complete in {elapsed:.1f}s — L: {len(long_r)}  S: {len(short_r)}")

    now_dt = datetime.datetime.now()
    fresh_long = [r for r in long_r if is_fresh(r, now_dt)] if runtime.direction in ["LONG", "BOTH"] else []
    fresh_short = [r for r in short_r if is_fresh(r, now_dt)] if runtime.direction in ["SHORT", "BOTH"] else []
    blacklist = _blacklisted_symbols()
    candidates = bot_core.pick_candidates(
        fresh_long,
        fresh_short,
        min_score=_effective_live_entry_min_score(runtime),
        min_score_gap=runtime.min_score_gap,
        direction_filter=runtime.direction,
        in_position=set(_client_managed_positions.keys()),
        available_slots=(bot_core.MAX_POSITIONS - len(_client_managed_positions)),
        blacklist=blacklist,
    )

    if not candidates:
        tui_log("No qualifying setups found.")
        return True

    for res, direction in candidates:
        if len(_client_managed_positions) >= bot_core.MAX_POSITIONS:
            break
        if _symbol_entry_cooldown_active(res["inst_id"]):
            continue
        current_acc = fetch_live_account_state()
        current_free = _account_free_balance(current_acc)
        if not _has_free_capacity_for_entry(current_acc):
            tui_log(
                f"Usable free margin ${_entry_margin_from_free_balance(current_free):.2f} "
                f"is below minimum ${MIN_ENTRY_MARGIN_USDT:.2f}; stopping new entry attempts."
            )
            break
        verified = verify_live_candidate(res["inst_id"], direction, res["score"], runtime=runtime)
        if verified:
            execute_setup(verified, direction, dry_run=args.dry_run)

    return True

def bot_loop(args):
    """The main scan-and-execute loop for the live bot."""
    load_live_cooldowns()
    _load_positions_from_disk()
    fetch_live_account_state()
    _ensure_ws_started()
    last_scan_started_at = 0.0
    error_streak = 0

    with _display_lock:
        global _display_thread_running
        if not _display_thread_running and not _no_tui:
            _display_thread_running = True
            threading.Thread(target=_live_pnl_display, daemon=True).start()

    # Initial Connection & Credential Test
    time.sleep(0.1 if _no_tui else 1) # Wait for TUI to start
    if not API_KEY or len(API_KEY) < 10:
        tui_log(f"{Fore.RED}CRITICAL: API_KEY is missing or too short!")
    if not API_SECRET or len(API_SECRET) < 10:
        tui_log(f"{Fore.RED}CRITICAL: API_SECRET is missing or too short!")
    
    tui_log(f"{Fore.CYAN}Connecting to Phemex Unified API...")
    acc_test = fetch_live_account_state()
    if acc_test.get("balance", 0.0) > 0:
        tui_log(f"{Fore.GREEN}Check OK. Live Balance: ${acc_test['balance']:.2f}")
    else:
        tui_log(f"{Fore.YELLOW}Check finished. Balance is $0.00 (or fetch failed).")

    while True:
        try:
            load_dotenv()
            runtime = _load_live_runtime_config(args)
            update_pnl_and_stops()

            if not runtime.enabled:
                _log_loop_state_once("disabled", "Bot is DISABLED. Sleeping...")
                error_streak = 0
                _wait_for_engine_wake(15)
                continue

            pause_until, pause_reason = _entry_pause_state()
            if time.time() < pause_until:
                remaining = max(int(math.ceil((pause_until - time.time()) / 60.0)), 1)
                _log_loop_state_once(
                    f"pause:{pause_reason}",
                    f"Safety pause active for {remaining}m: {pause_reason}",
                )
                error_streak = 0
                _wait_for_engine_wake(15)
                continue

            _clear_loop_state_notice()

            acc = fetch_live_account_state()
            scan_due = _scan_due(last_scan_started_at, runtime.interval)
            scan_executed = False
            if scan_due:
                scan_started_at = time.time()
                scan_executed = _run_live_scan_cycle(args, runtime, acc)
                if scan_executed:
                    last_scan_started_at = scan_started_at

            with _fast_track_lock:
                _fast_track_opened.clear()

            error_streak = 0
            _wait_for_engine_wake(
                _next_loop_wait_seconds(
                    last_scan_started_at,
                    runtime.interval,
                    scan_due=scan_due,
                    scan_executed=scan_executed,
                )
            )
        except Exception as exc:
            error_streak += 1
            retry_delay = _loop_error_backoff_seconds(error_streak)
            error_message = f"{type(exc).__name__}: {exc}"
            logger.exception("bot_loop iteration failed")
            _log_loop_state_once(
                f"error:{error_message}",
                f"{Fore.RED}BOT LOOP ERROR: {error_message}. Retrying in {int(math.ceil(retry_delay))}s.",
            )
            with _fast_track_lock:
                _fast_track_opened.clear()
            _wait_for_engine_wake(retry_delay)

# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Phemex Automated Trading Bot (LIVE)")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--min-score", type=int, default=125)
    parser.add_argument("--min-score-gap", type=int, default=30)
    parser.add_argument("--direction", default="BOTH", choices=["LONG", "SHORT", "BOTH"])
    parser.add_argument("--timeframe", default="4H")
    parser.add_argument("--min-vol", type=int, default=1_000_000)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--rate", type=float, default=50.0)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-entity", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-tui", action="store_true", help="Disable TUI dashboard for background running")
    args = parser.parse_args()

    print(Fore.RED + Style.BRIGHT + "  🚀 Phemex LIVE Bot Starting")
    print(f"  Balance gated entries ($10 min)")
    if not args.no_tui:
        print(f"  TUI Dashboard enabled\n")
    else:
        print(f"  TUI Dashboard disabled (Background Mode)\n")

    global _no_tui
    _no_tui = args.no_tui

    try:
        bot_loop(args)
    except KeyboardInterrupt:
        print("\nBot stopped.")

if __name__ == "__main__":
    main()
