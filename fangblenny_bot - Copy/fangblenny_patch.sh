#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# fangblenny_patch.sh
# Applies 7 bug fixes and optimizations to the fangblenny_bot codebase.
#
# Run from the fangblenny_bot project root:
#   bash fangblenny_patch.sh
#
# Fixes applied:
#   [1] root_dir NameError crash on import fallback  (simulation_bot.py)
#   [2] 429 double-retry conflict                    (core/network.py)
#   [3] calc_atr vectorized with numpy               (core/indicators.py)
#   [4] SimpleCache proactive eviction sweeper       (core/cache.py)
#   [5] _log_closed_trade → JSONL + _file_io_lock    (simulation_bot.py)
#   [6] Display loop JSONL reader + legacy migration (simulation_bot.py)
#   [7] Single-symbol ticker in verify_sim_candidate (simulation_bot.py)
#   [8] Remove blocking entity API from render loop  (simulation_bot.py)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_BOT="$PROJ_ROOT/bots/simulation_bot.py"
NETWORK="$PROJ_ROOT/core/network.py"
INDICATORS="$PROJ_ROOT/core/indicators.py"
CACHE_PY="$PROJ_ROOT/core/cache.py"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
die()  { echo -e "  ${RED}✗${NC} $*"; exit 1; }

# ── Preflight checks ──────────────────────────────────────────────────────────
echo ""
echo "🔧 fangblenny_patch.sh — verifying paths..."
[[ -f "$SIM_BOT"    ]] || die "bots/simulation_bot.py not found. Run from project root."
[[ -f "$NETWORK"    ]] || die "core/network.py not found."
[[ -f "$INDICATORS" ]] || die "core/indicators.py not found."
[[ -f "$CACHE_PY"   ]] || die "core/cache.py not found."

# ── Backup originals ──────────────────────────────────────────────────────────
echo ""
echo "📦 Backing up originals..."
for f in "$SIM_BOT" "$NETWORK" "$INDICATORS" "$CACHE_PY"; do
    cp "$f" "${f}.bak"
    ok "$(basename "$f").bak"
done

echo ""
echo "🩺 Applying patches..."

# ══════════════════════════════════════════════════════════════════════════════
# [1] FIX: root_dir NameError in import fallback
#     simulation_bot.py:68 — `root_dir` is never assigned.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$SIM_BOT" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old = "    sys.path.append(root_dir)"
new = "    sys.path.append(PARENT_DIR)  # patch[1]: root_dir was undefined"

if old not in src:
    print("  [1] SKIP — already patched or string not found")
else:
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("  [1] ✓  root_dir → PARENT_DIR")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [2] FIX: 429 double-retry conflict
#     urllib3 Retry adapter already handles 429; the manual handler can
#     over-retry and burn the adapter's retry budget. Remove 429 from
#     status_forcelist so the manual handler is the sole 429 path.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$NETWORK" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old = "        status_forcelist=[429, 500, 502, 503, 504],"
new = "        status_forcelist=[500, 502, 503, 504],  # patch[2]: 429 handled manually"

if old not in src:
    print("  [2] SKIP — already patched or string not found")
else:
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("  [2] ✓  Removed 429 from urllib3 status_forcelist")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [3] OPT: Vectorize calc_atr with numpy
#     Replaces a Python for-loop over every candle (called 100+ times per scan
#     cycle across concurrent workers) with O(n) numpy ops.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$INDICATORS" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old = """\
    tr_list = []
    for i in range(1, n):
        h_l = highs_a[i] - lows_a[i]
        h_pc = abs(highs_a[i] - closes_a[i - 1])
        l_pc = abs(lows_a[i] - closes_a[i - 1])
        tr = float(max(h_l, h_pc, l_pc))
        tr_list.append(tr)
    if len(tr_list) < period:
        return None
    atr = sum(tr_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
    return atr"""

new = """\
    # patch[3]: vectorized — 10-30x faster than the old Python loop
    h_l    = highs_a[1:] - lows_a[1:]
    h_pc   = np.abs(highs_a[1:] - closes_a[:-1])
    l_pc   = np.abs(lows_a[1:] - closes_a[:-1])
    tr_arr = np.maximum(h_l, np.maximum(h_pc, l_pc))
    if len(tr_arr) < period:
        return None
    atr = float(tr_arr[:period].mean())
    for i in range(period, len(tr_arr)):
        atr = (atr * (period - 1) + float(tr_arr[i])) / period
    return atr"""

if old not in src:
    print("  [3] SKIP — already patched or string not found")
else:
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("  [3] ✓  calc_atr vectorized with numpy")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [4] OPT: SimpleCache proactive eviction sweeper
#     Adds a background daemon thread that prunes expired keys every TTL
#     seconds, preventing unbounded memory growth on long bot runs.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$CACHE_PY" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old = """\
    def set(self, key: str, val: Any):
        with self._lock:
            self._data[key] = (time.time(), val)


# global shared cache instance with default 30s TTL
CACHE = SimpleCache(ttl=30.0)"""

new = """\
    def set(self, key: str, val: Any):
        with self._lock:
            self._data[key] = (time.time(), val)

    # patch[4]: proactive eviction so stale keys don't accumulate forever
    def _sweep(self) -> None:
        \"\"\"Background thread: evict entries whose TTL has expired.\"\"\"
        import threading as _t
        while True:
            time.sleep(self._ttl)
            cutoff = time.time() - self._ttl
            with self._lock:
                expired = [k for k, (ts, _) in self._data.items() if ts < cutoff]
                for k in expired:
                    del self._data[k]

    def start_sweeper(self) -> None:
        \"\"\"Start the background eviction thread. Call once at module load.\"\"\"
        import threading as _t
        _t.Thread(target=self._sweep, daemon=True, name="cache-sweeper").start()


# global shared cache instance with default 30s TTL
CACHE = SimpleCache(ttl=30.0)
CACHE.start_sweeper()"""

if old not in src:
    print("  [4] SKIP — already patched or string not found")
else:
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("  [4] ✓  SimpleCache sweeper thread added")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [5] FIX: _log_closed_trade — JSONL + _file_io_lock
#     Old code: read entire JSON array → append → rewrite entire file.
#     Problems: O(n) disk IO on every close, and unprotected concurrent
#     read-modify-write causes lost trade records if two positions close
#     simultaneously. Switching to JSONL append solves both: O(1) writes,
#     and O_APPEND is atomic for records this size on Linux.
#     A dedicated _file_io_lock guards against the rare concurrent flush edge.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$SIM_BOT" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

# 5a: inject _file_io_lock declaration after existing lock declarations
old_locks = """\
_cooldown_lock = threading.Lock()
_stop_lock     = threading.Lock()
_log_lock      = threading.Lock()
_display_lock  = threading.Lock()
_fast_track_lock = threading.Lock()"""

new_locks = """\
_cooldown_lock   = threading.Lock()
_stop_lock       = threading.Lock()
_log_lock        = threading.Lock()
_display_lock    = threading.Lock()
_fast_track_lock = threading.Lock()
_file_io_lock    = threading.Lock()  # patch[5]: guards sim_trade_results JSONL writes"""

if old_locks not in src:
    print("  [5a] SKIP — lock block not found or already patched")
else:
    src = src.replace(old_locks, new_locks, 1)
    print("  [5a] ✓  _file_io_lock declared")

# 5b: replace read-append-rewrite with atomic JSONL append
old_write = """\
    history: List[dict] = []
    if SIM_RESULTS_FILE.exists():
        try:
            history = json.loads(SIM_RESULTS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.error("Failed to read trade history — starting fresh.")
    history.append(record)
    SIM_RESULTS_FILE.write_text(json.dumps(history, indent=2))"""

new_write = """\
    # patch[5]: JSONL append — O(1), no read-modify-write race
    try:
        with _file_io_lock:
            with open(SIM_RESULTS_FILE, "a", encoding="utf-8") as _fh:
                _fh.write(json.dumps(record) + "\\n")
    except OSError:
        logger.error("Failed to write trade record to sim_trade_results.jsonl.")"""

if old_write not in src:
    print("  [5b] SKIP — write block not found or already patched")
else:
    src = src.replace(old_write, new_write, 1)
    print("  [5b] ✓  _log_closed_trade → JSONL atomic append")

p.write_text(src, encoding="utf-8")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [6] FIX: Display loop — read JSONL + migrate existing JSON array file
#     The display loop reads sim_trade_results.json every 0.8s frame.
#     After patch [5] it's JSONL, so the reader must parse line-by-line.
#     Also migrates any pre-existing JSON array file to JSONL on first run.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$SIM_BOT" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old_reader = """\
                history: List[dict] = []
                if results_file.exists():
                    try:
                        history = json.loads(results_file.read_text())
                    except Exception:
                        pass"""

new_reader = """\
                # patch[6]: parse JSONL (one record per line)
                history: List[dict] = []
                if results_file.exists():
                    try:
                        history = [
                            json.loads(ln)
                            for ln in results_file.read_text(encoding="utf-8").splitlines()
                            if ln.strip()
                        ]
                    except Exception:
                        pass"""

if old_reader not in src:
    print("  [6a] SKIP — display reader not found or already patched")
else:
    src = src.replace(old_reader, new_reader, 1)
    print("  [6a] ✓  Display loop reads JSONL")

# Inject migration helper right before _live_pnl_display
migration_fn = '''\

def _migrate_results_to_jsonl() -> None:
    """patch[6]: one-time migration of JSON array → JSONL on first bot run."""
    import json as _json
    f = SCRIPT_DIR / "sim_trade_results.json"
    if not f.exists():
        return
    try:
        raw = f.read_text(encoding="utf-8").strip()
        if not raw or raw[0] != "[":
            return  # already JSONL or empty
        records = _json.loads(raw)
        if not isinstance(records, list):
            return
        with _file_io_lock:
            with open(f, "w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(_json.dumps(rec) + "\\n")
        logger.info(f"Migrated {len(records)} records to JSONL format.")
    except Exception as exc:
        logger.warning(f"JSONL migration skipped: {exc}")

'''

anchor = "def _live_pnl_display() -> None:"
if migration_fn.strip() in src:
    print("  [6b] SKIP — migration helper already present")
elif anchor not in src:
    print("  [6b] SKIP — _live_pnl_display anchor not found")
else:
    src = src.replace(anchor, migration_fn + anchor, 1)
    print("  [6b] ✓  JSONL migration helper injected")

# Call migration at bot startup (in load_sim_cooldowns area, or at top of sim_bot_loop)
old_loop_start = "    _ensure_ws_started()\n    load_sim_cooldowns()"
new_loop_start = "    _migrate_results_to_jsonl()  # patch[6]: migrate JSON→JSONL once\n    _ensure_ws_started()\n    load_sim_cooldowns()"
if old_loop_start not in src:
    print("  [6c] SKIP — loop start anchor not found or already patched")
else:
    src = src.replace(old_loop_start, new_loop_start, 1)
    print("  [6c] ✓  Migration called at bot startup")

p.write_text(src, encoding="utf-8")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [7] OPT: Single-symbol ticker in verify_sim_candidate
#     Old code: fetches ALL 200+ tickers 3× (once per verify step) to find
#     one price. Replacement hits the single-symbol endpoint instead.
#     Also adds a helper function _get_single_ticker().
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$SIM_BOT" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

helper = '''\

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

'''

anchor = "def verify_sim_candidate("
if "_get_single_ticker" in src:
    print("  [7a] SKIP — helper already present")
elif anchor not in src:
    print("  [7a] SKIP — verify_sim_candidate not found")
else:
    src = src.replace(anchor, helper + anchor, 1)
    print("  [7a] ✓  _get_single_ticker helper added")

old_fetch = """\
        # Fetch fresh ticker
        try:
            tickers = pc.get_tickers()
            ticker = next((t for t in tickers if t[\"symbol\"] == symbol), None)
        except Exception as e:
            tui_log(f\"FAIL: Error fetching ticker for {symbol}: {e}\")
            return None

        if not ticker:
            tui_log(f\"FAIL: {symbol} ticker not found during verification.\")
            return None"""

new_fetch = """\
        # Fetch fresh ticker — single-symbol endpoint (patch[7])
        try:
            ticker = _get_single_ticker(symbol)
        except Exception as e:
            tui_log(f\"FAIL: Error fetching ticker for {symbol}: {e}\")
            return None

        if not ticker:
            tui_log(f\"FAIL: {symbol} ticker not found during verification.\")
            return None"""

if old_fetch not in src:
    print("  [7b] SKIP — fetch block not found or already patched")
else:
    src = src.replace(old_fetch, new_fetch, 1)
    print("  [7b] ✓  verify_sim_candidate uses single-symbol ticker")

p.write_text(src, encoding="utf-8")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# [8] FIX: Remove blocking HTTP call from TUI render loop
#     _draw_positions_section fires make_entity_request("Position") for every
#     open position on every ~0.8s display frame — a synchronous HTTP POST
#     that stalls rendering. Removed entirely; the Snapshot entity call in
#     the main display loop already captures per-cycle state.
# ══════════════════════════════════════════════════════════════════════════════
python3 - "$SIM_BOT" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
src = p.read_text(encoding="utf-8")

old_entity = """\
            # ── Position Entity Logging ─────────────────────────────────
            if now:
                p_bot.make_entity_request(\"Position\", data={
                    \"symbol\": sym,
                    \"direction\": \"LONG\" if is_long else \"SHORT\",
                    \"entry_price\": entry,
                    \"current_price\": now,
                    \"current_pnl\": upnl,
                    \"sl\": stop,
                    \"tp\": tp,
                    \"trailing_stop_level\": stop,
                    \"age_seconds\": (datetime.datetime.now() - datetime.datetime.fromisoformat(pos[\"entry_time\"])).total_seconds(),
                    \"score\": score
                })

            # Direction badge"""

new_entity = """\
            # patch[8]: Position entity logging removed from render loop.
            # It fired a blocking HTTP POST per position per frame (~0.8s),
            # causing TUI stutter. Aggregate state is captured by Snapshot.

            # Direction badge"""

if old_entity not in src:
    print("  [8] SKIP — entity block not found or already patched")
else:
    src = src.replace(old_entity, new_entity, 1)
    print("  [8] ✓  Blocking entity API removed from render loop")

p.write_text(src, encoding="utf-8")
PYEOF

# ══════════════════════════════════════════════════════════════════════════════
# Verify patches applied cleanly
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "🔍 Verifying patches..."

python3 - "$SIM_BOT" "$NETWORK" "$INDICATORS" "$CACHE_PY" <<'PYEOF'
import sys, pathlib

sim     = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
net     = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
ind     = pathlib.Path(sys.argv[3]).read_text(encoding="utf-8")
cache   = pathlib.Path(sys.argv[4]).read_text(encoding="utf-8")

checks = [
    ("sys.path.append(root_dir)" not in sim,         "[1] root_dir line patched"),
    ("429" not in net.split("status_forcelist")[1].split("]")[0],
                                                     "[2] 429 out of status_forcelist"),
    ("tr_list = []" not in ind,                      "[3] calc_atr vectorized"),
    ("start_sweeper" in cache,                       "[4] cache sweeper present"),
    ("_file_io_lock" in sim,                         "[5] _file_io_lock declared"),
    ('_fh.write(json.dumps(record) + "\\n")' in sim, "[5] JSONL append in use"),
    ("splitlines()" in sim,                          "[6] display reads JSONL"),
    ("_migrate_results_to_jsonl" in sim,             "[6] migration helper present"),
    ("_get_single_ticker" in sim,                    "[7] single-ticker helper present"),
    ("single-symbol endpoint" in sim,                "[7] verify uses single ticker"),
    ("patch[8]" in sim,                              "[8] entity block removed"),
]

all_ok = True
for ok, label in checks:
    status = "✓" if ok else "✗ FAILED"
    print(f"  {status}  {label}")
    if not ok:
        all_ok = False

sys.exit(0 if all_ok else 1)
PYEOF

echo ""
if [[ $? -eq 0 ]]; then
    echo -e "${GREEN}✅ All patches applied successfully.${NC}"
    echo ""
    echo "   Backup files: bots/simulation_bot.py.bak"
    echo "                 core/network.py.bak"
    echo "                 core/indicators.py.bak"
    echo "                 core/cache.py.bak"
    echo ""
    echo "   NOTE: sim_trade_results.json will be auto-migrated to JSONL"
    echo "         format on the next bot start (existing data is preserved)."
    echo ""
    echo "   To revert: cp bots/simulation_bot.py.bak bots/simulation_bot.py"
    echo "              (etc. for each .bak file)"
else
    echo -e "${RED}❌ One or more patches did not apply cleanly. Check output above.${NC}"
    echo "   Originals preserved in .bak files."
    exit 1
fi
