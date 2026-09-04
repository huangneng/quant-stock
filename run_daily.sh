#!/bin/bash
# Daily stock selection + push script (for launchd)
# Triggered at 16:15; writes stamp to prevent duplicate runs.

set -u

PROJECT_DIR="/Users/huangneng/ComateProjects/QuackStock"
PYTHON="/opt/homebrew/bin/python3"
STAMP="$PROJECT_DIR/stock_data/.last_run_date"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily.log"

mkdir -p "$LOG_DIR"
mkdir -p "$PROJECT_DIR/stock_data"

cd "$PROJECT_DIR" || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

today=$(date '+%Y-%m-%d')

log "==== trigger today=$today ===="

# 1. Trading day check
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

# 推送脚本未收到 PUSH_DATE 时会自己取 date.today()。同步慢的时候整轮能跑到
# 次日（2026-09-03 那轮 16:26 启动、次日 09:12 才走到推送），那时 date.today()
# 已经翻页，推送去找次日的 CSV，必然扑空——09-01 和 09-03 两次通知就是这么丢的。
# 这里固定成跑批当日，与下面传给 daily_select 的 --date 保持同一个值。
export PUSH_DATE="$today"

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

# Raise fd limit: pandas/report generation previously hit EMFILE (Errno 24)
ulimit -n 4096 2>/dev/null || true

# 4. KlineDB incremental sync
log ">>> sync_kline_db --incremental"
"$PYTHON" -m data_hub sync_today >> "$LOG_FILE" 2>&1 || log "sync_kline_db failed (non-fatal)"

# 5. Run daily selection (explicit --date to avoid key mismatch on late/next-day runs)
log ">>> daily_select.py --date $today"
"$PYTHON" -u daily_select.py --date "$today" >> "$LOG_FILE" 2>&1
RET_CODE=$?
if [ $RET_CODE -ne 0 ]; then
    log "!!! daily_select.py failed rc=$RET_CODE (skip push)"
    exit $RET_CODE
fi

# 6. Push notifications
log ">>> push_email.py"
"$PYTHON" scripts/push_email.py >> "$LOG_FILE" 2>&1 || log "push_email failed"

log ">>> push_serverchan.py"
"$PYTHON" scripts/push_serverchan.py >> "$LOG_FILE" 2>&1 || log "push_serverchan failed"

# 7. Mark as done
echo "$today" > "$STAMP"
log "==== done ===="
