#!/usr/bin/env python3
"""
Bot Core
========
Shared logic, configuration, and utilities for both the live and simulation bots.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests
from colorama import init, Fore, Style

# ── Scanner imports ──────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Add project root to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

try:
    from legacy import phemex_common as pc
    from scanners import long as scanner_long
    from scanners import short as scanner_short
except ImportError:
    try:
        from ..scanners import long as scanner_long
        from ..scanners import short as scanner_short
    except (ImportError, ValueError):
        from scanners import long as scanner_long, short as scanner_short
except ImportError as e:
    print(Fore.RED + f"[ERROR] Could not import scanner modules: {e}")
    print("Make sure scanner modules are available.")
    sys.exit(1)

init(autoreset=True)
logger = logging.getLogger("bot_core")

# ────────────────────────────────────────────────────────────────────
# Core Configuration & Strategy Parameters
# ────────────────────────────────────────────────────────────────────
MARGIN_USDT    = float(os.getenv("BOT_MARGIN_USDT", "10.0"))
LEVERAGE       = int(os.getenv("BOT_LEVERAGE", "30"))
TRAIL_PCT      = float(os.getenv("BOT_TRAIL_PCT", "0.006"))
TAKE_PROFIT_PCT = float(os.getenv("BOT_TAKE_PROFIT_PCT", "0.04"))
MAX_POSITIONS  = 10

SCAN_INTERVAL  = int(os.getenv("BOT_SCAN_INTERVAL", "300"))
MIN_SCORE      = int(os.getenv("BOT_MIN_SCORE", "125"))
MIN_SCORE_GAP  = int(os.getenv("BOT_MIN_SCORE_GAP", "30"))
DIRECTION      = os.getenv("BOT_DIRECTION", "SHORT")
TIMEFRAME      = os.getenv("BOT_TIMEFRAME", "4H")
MIN_VOLUME     = int(os.getenv("BOT_MIN_VOLUME", "1000000"))
MAX_WORKERS    = int(os.getenv("BOT_MAX_WORKERS", "100"))
RATE_LIMIT_RPS = float(os.getenv("BOT_RATE_LIMIT_RPS", "50.0"))
SHOW_PROGRESS  = os.getenv("BOT_SHOW_PROGRESS", "true").lower() == "true"

# Entity API Configuration
ENTITY_API_KEY      = os.getenv("ENTITY_API_KEY", "234a39318e4f46fd83f0e808ea3b0fcf")
ENTITY_API_BASE_URL = os.getenv("ENTITY_API_BASE_URL", "https://acoustic-trade-scan-now.base44.app")
ENTITY_APP_ID       = os.getenv("ENTITY_APP_ID", "69bb28076f7700ac770deb5e")
SESSION_ID          = f"sess-{int(time.time())}"
ENABLE_ENTITY       = True


def get_score_leverage(score: int) -> int:
    """
    Returns dynamic leverage multiplier based on scan score.
    """
    if score < 125: return 10
    if score < 135: return 20
    if score < 145: return 30
    if score < 155: return 40
    return 50

def get_cooldown_duration(score: int) -> int:
    """
    Returns cooldown duration in seconds based on score.
    """
    if score >= 150: return 20 * 60
    if score >= 140: return 30 * 60
    if score >= 130: return 45 * 60
    return 60 * 60


def build_trade_protection(
    entry_price: float,
    total_qty: float,
    direction: str,
    qty_rounder: Optional[Callable[[float], str]] = None,
) -> dict:
    """
    Build the trailing-stop anchor and 3-stage take-profit plan.

    When a qty rounder is provided, stage sizes are rounded using exchange-
    compatible sizing so live and local state stay aligned.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if total_qty <= 0:
        raise ValueError("total_qty must be positive")

    direction = direction.upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported direction: {direction}")

    if qty_rounder is None:
        q1 = round(total_qty * 0.5, 8)
        q2 = round(total_qty * 0.25, 8)
        q3 = round(total_qty - q1 - q2, 8)
    else:
        q1 = float(qty_rounder(total_qty * 0.5))
        q2_target = min(total_qty * 0.25, max(total_qty - q1, 0.0))
        q2 = float(qty_rounder(q2_target))
        q3 = max(total_qty - q1 - q2, 0.0)
        # Re-round the remainder so the final stage stays exchange-valid.
        q3 = float(qty_rounder(q3)) if q3 > 0 else 0.0
        # Keep any tiny float drift on the last stage so totals still reconcile.
        remainder = total_qty - q1 - q2 - q3
        if remainder > 1e-9:
            q3 += remainder

    tp1_mult = TAKE_PROFIT_PCT * 0.5
    tp2_mult = TAKE_PROFIT_PCT * 0.75
    tp3_mult = TAKE_PROFIT_PCT

    if direction == "LONG":
        stop_px = entry_price * (1.0 - TRAIL_PCT)
        tp1_px = entry_price * (1.0 + tp1_mult)
        tp2_px = entry_price * (1.0 + tp2_mult)
        tp3_px = entry_price * (1.0 + tp3_mult)
        high_water = entry_price
        low_water = None
    else:
        stop_px = entry_price * (1.0 + TRAIL_PCT)
        tp1_px = entry_price * (1.0 - tp1_mult)
        tp2_px = entry_price * (1.0 - tp2_mult)
        tp3_px = entry_price * (1.0 - tp3_mult)
        high_water = None
        low_water = entry_price

    stages = [
        {"price": tp1_px, "qty": q1, "hit": False},
        {"price": tp2_px, "qty": q2, "hit": False},
        {"price": tp3_px, "qty": q3, "hit": False},
    ]

    return {
        "stop_price": stop_px,
        "original_stop": stop_px,
        "take_profit": tp3_px,
        "high_water": high_water,
        "low_water": low_water,
        "tp_stages": stages,
    }

def make_entity_request(entity_name: str, method: str = "POST", data: dict = None, entity_id: str = None):
    """
    Sends data to the Entity API for persistence.
    """
    if not ENABLE_ENTITY:
        return None
    
    url = f"{ENTITY_API_BASE_URL}/api/apps/{ENTITY_APP_ID}/entities/{entity_name}"
    if entity_id:
        url += f"/{entity_id}"
        
    headers = {
        "api_key": ENTITY_API_KEY,
        "Content-Type": "application/json"
    }
    
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=data, timeout=10)
        elif method.upper() == "PUT":
            resp = requests.put(url, headers=headers, json=data, timeout=10)
        elif method.upper() == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=10)
        else:
            resp = requests.post(url, headers=headers, json=data, timeout=10)
        
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.debug("Entity API %s %s failed: %s", method, entity_name, e)
        return None

_log_lock = threading.Lock()
def log_trade(entry: dict, log_file: Path):
    with _log_lock:
        trades = []
        if log_file.exists():
            try:
                trades = json.loads(log_file.read_text())
            except (json.JSONDecodeError, IOError):
                trades = []
        trades.append(entry)
        log_file.write_text(json.dumps(trades, indent=2))

def run_scanner_both(cfg: dict, args, on_result=None, show_progress=True) -> Tuple[List[dict], List[dict]]:
    """Run scanners based on direction filter (no printing), return (long_results, short_results)."""
    import concurrent.futures
    
    def _scan(module, direction):
        return _scan_one(module, direction, cfg, args, on_result=on_result, show_progress=show_progress)
        
    scan_lock_path = Path(__file__).parent / ".scan.lock"
    if scan_lock_path.exists():
        logger.info("Scan lock active (backtester running). Pausing live scan...")
        if show_progress:
            print(Fore.YELLOW + " ⏳ Paused: Backtester is running... ", end="", flush=True)
        while scan_lock_path.exists():
            time.sleep(2)
        if show_progress:
            print(Fore.GREEN + "Resuming.")

    direction_filter = getattr(args, "direction", "BOTH").upper()
    
    if show_progress:
        if direction_filter in ["LONG", "BOTH"]:
            print()
        if direction_filter in ["SHORT", "BOTH"]:
            print()
        
        lines_to_up = 2 if direction_filter == "BOTH" else 1
        sys.stdout.write(f"\033[{lines_to_up}F")
        sys.stdout.flush()

    res_long = []
    res_short = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as exe:
        futs = {}
        if direction_filter in ["LONG", "BOTH"]:
            futs["LONG"] = exe.submit(_scan, scanner_long,  "LONG")
        if direction_filter in ["SHORT", "BOTH"]:
            futs["SHORT"] = exe.submit(_scan, scanner_short, "SHORT")
            
        if "LONG" in futs:
            res_long = futs["LONG"].result()
        if "SHORT" in futs:
            res_short = futs["SHORT"].result()
    
    if show_progress:
        lines_to_down = "\n\n" if direction_filter == "BOTH" else "\n"
        sys.stdout.write(lines_to_down)
        sys.stdout.flush()
        
    return res_long, res_short


_print_lock = threading.Lock()

def _scan_one(module, direction: str, cfg: dict, args, on_result=None, show_progress=True) -> List[dict]:
    rps = cfg.get("RATE_LIMIT_RPS", 8.0)
    
    if hasattr(module, "prefetch_all_funding_rates"):
        module.prefetch_all_funding_rates(rps=rps)
        
    tickers = module.get_tickers(rps=rps)
    
    symbols_to_scan = cfg.get("SYMBOLS")
    if symbols_to_scan:
        filtered = [t for t in tickers if t.get("symbol") in symbols_to_scan]
    else:
        filtered = [
            t for t in tickers 
            if float(t.get("turnoverRv") or 0.0) >= cfg["MIN_VOLUME"]
        ]
    
    results = []
    total = len(filtered)
    done = 0
    if total == 0: return []
    
    import concurrent.futures
    workers = min(cfg["MAX_WORKERS"], max(1, len(filtered)))
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as exe:
        futures = {exe.submit(module.analyse, t, cfg, not args.no_ai, not args.no_entity, None): t for t in filtered}
        for fut in concurrent.futures.as_completed(futures):
            ticker_info = futures[fut]
            try:
                r = fut.result()
                if r:
                    r["scan_timestamp"] = datetime.datetime.now()
                    results.append(r)
                    if on_result:
                        threading.Thread(target=on_result, args=(r, direction), daemon=True).start()
            except Exception as e:
                logger.error(f"Error analyzing ticker {ticker_info.get('symbol', 'UNKNOWN')}: {e}", exc_info=True)

            done += 1
            if show_progress:
                with _print_lock:
                    pct = done / total
                    bar_len = 20
                    filled = int(pct * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    color = Fore.GREEN if direction == "LONG" else Fore.RED
                    
                    direction_filter = getattr(args, "direction", "BOTH").upper()
                    
                    if direction_filter == "BOTH":
                        if direction == "LONG":
                            sys.stdout.write(f"\033[s\033[F {color}{direction:5} [{bar}] {done}/{total} ({pct*100:3.0f}%) Setups: {len(results):<3}{Style.RESET_ALL}\033[u")
                        else:
                            sys.stdout.write(f" {color}{direction:5} [{bar}] {done}/{total} ({pct*100:3.0f}%) Setups: {len(results):<3}{Style.RESET_ALL}")
                    else:
                        sys.stdout.write(f" {color}{direction:5} [{bar}] {done}/{total} ({pct*100:3.0f}%) Setups: {len(results):<3}{Style.RESET_ALL}")
                    sys.stdout.flush()
                
    return results


def _effective_score(result: dict) -> float:
    """
    Compute quality-adjusted score for ranking.
    """
    signals = result.get("signals", [])
    base    = result.get("score", 0)
    bonus   = 15 if any("HTF Alignment" in s for s in signals) else 0
    penalty = 20 if any("Low Liquidity" in s for s in signals) else 0
    return base + bonus - penalty


def pick_candidates(
    long_results: List[dict], 
    short_results: List[dict], 
    min_score: int,
    min_score_gap: int,
    direction_filter: str,
    in_position: set,
    available_slots: int,
    blacklist: set = None,
) -> List[Tuple[dict, str]]:
    """
    Merge long + short, filter by score + gap + direction + blacklist, 
    and return up to available_slots candidates.
    """
    blacklist = blacklist or set()
    symbol_scores = {}
    for r in long_results:
        symbol_scores.setdefault(r["inst_id"], {"LONG": 0, "SHORT": 0})["LONG"] = r["score"]
    for r in short_results:
        symbol_scores.setdefault(r["inst_id"], {"LONG": 0, "SHORT": 0})["SHORT"] = r["score"]

    candidates = []
    
    if direction_filter.upper() in ["LONG", "BOTH"]:
        for r in long_results:
            if r["score"] < min_score: continue
            if r["inst_id"] in blacklist: continue
            
            if direction_filter.upper() == "BOTH":
                scores = symbol_scores.get(r["inst_id"], {"LONG": 0, "SHORT": 0})
                if scores["LONG"] - scores["SHORT"] < min_score_gap:
                    continue
            
            candidates.append((r, "LONG"))

    if direction_filter.upper() in ["SHORT", "BOTH"]:
        for r in short_results:
            if r["score"] < min_score: continue
            if r["inst_id"] in blacklist: continue
            
            if direction_filter.upper() == "BOTH":
                scores = symbol_scores.get(r["inst_id"], {"LONG": 0, "SHORT": 0})
                if scores["SHORT"] - scores["LONG"] < min_score_gap:
                    continue
            
            candidates.append((r, "SHORT"))

    candidates.sort(key=lambda x: _effective_score(x[0]), reverse=True)
    
    final_candidates = []
    slots_taken = 0
    for r, d in candidates:
        if r["inst_id"] in in_position:
            final_candidates.append((r, d))
        elif slots_taken < available_slots:
            final_candidates.append((r, d))
            slots_taken += 1
            
    return final_candidates
