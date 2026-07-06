#!/bin/bash
# Daily stock selection + push script (for launchd)
#
# Modes:
#   ./run_daily.sh           盘后扫描（默认，16:15 触发；写 stamp 防重复）
#   ./run_daily.sh intraday  盘中扫描（14:30 触发；不写 stamp，独立产物）

set -u

MODE="${1:-daily}"

PROJECT_DIR="/Users/huangneng/ComateProjects/comate-zulu-demo-1778467204389"
PYTHON="/opt/homebrew/bin/python3"
STAMP="$PROJECT_DIR/stock_data/.last_run_date"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily.log"

mkdir -p "$LOG_DIR"
mkdir -p "$PROJECT_DIR/stock_data"

cd "$PROJECT_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

today=$(date '+%Y-%m-%d')

log "==== trigger mode=$MODE today=$today ===="

# 1. Trading day check (both modes)
"$PYTHON" -c "
import sys
sys.path.insert(0, 'scripts')
from datetime import date
from check_trade_date import is_trade_day
sys.exit(0 if is_trade_day(date.today()) else 1)
" >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    log "$today is NOT a trading day, skip."
    exit 0
fi

# Load environment variables
if [ -f "$HOME/.quant.env" ]; then
    set -a
    source "$HOME/.quant.env"
    set +a
fi

if [ "$MODE" = "intraday" ]; then
    # 盘中模式：14:00-15:00 时段守卫；不读/不写 stamp
    hhmm=$(date '+%H%M')
    if [ "$hhmm" -lt 1400 ] || [ "$hhmm" -gt 1500 ]; then
        log "intraday: out of window ($hhmm), skip."
        exit 0
    fi
    log ">>> daily_select.py --intraday"
    "$PYTHON" -u daily_select.py --intraday >> "$LOG_FILE" 2>&1
    RET_CODE=$?
    if [ $RET_CODE -ne 0 ]; then
        log "!!! intraday daily_select.py failed rc=$RET_CODE (skip push)"
        exit $RET_CODE
    fi
    log ">>> push_email.py --intraday"
    "$PYTHON" scripts/push_email.py --intraday >> "$LOG_FILE" 2>&1 || log "intraday push_email failed"
    log ">>> push_serverchan.py --intraday"
    "$PYTHON" scripts/push_serverchan.py --intraday >> "$LOG_FILE" 2>&1 || log "intraday push_serverchan failed"
    log "==== intraday done ===="
    exit 0
fi

# ============ 盘后默认模式 ============

# 2. Skip if already ran today
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$today" ]; then
    log "already ran today, skip."
    exit 0
fi

# 3. Do not run before 16:15
hhmm=$(date '+%H%M')
if [ "$hhmm" -lt 1615 ]; then
    log "before 16:15 ($hhmm), skip; will retry on next trigger."
    exit 0
fi

# 4. 盘前/盘后 KlineDB 增量同步（兜底：每天至少 sync 一次，确保次日选股不缺数据）
log ">>> sync_kline_db --incremental"
"$PYTHON" -m data_hub sync_today >> "$LOG_FILE" 2>&1 || log "sync_kline_db failed (non-fatal)"

# 5. Run daily selection
log ">>> daily_select.py"
"$PYTHON" -u daily_select.py >> "$LOG_FILE" 2>&1
RET_CODE=$?
if [ $RET_CODE -ne 0 ]; then
    log "!!! daily_select.py failed rc=$RET_CODE (skip push)"
    exit $RET_CODE
fi

# 5. Push notifications
log ">>> push_email.py"
"$PYTHON" scripts/push_email.py >> "$LOG_FILE" 2>&1 || log "push_email failed"

log ">>> push_serverchan.py"
"$PYTHON" scripts/push_serverchan.py >> "$LOG_FILE" 2>&1 || log "push_serverchan failed"

# 6. Mark as done
echo "$today" > "$STAMP"
log "==== done ===="
