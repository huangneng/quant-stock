#!/bin/bash
# Daily stock selection + push script (for launchd)
# Triggered at 15:10（收盘后尽早存快照），16:15 再触发一次作失败重试；
# 内部用 stamp 文件防重复。

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

# 3. Do not run before 15:10
#    收盘 15:00 后留几分钟让成交额定型；更早快照还是盘中值，补不了当日。
hhmm=$(date '+%H%M')
if [ "$hhmm" -lt 1510 ]; then
    log "before 15:10 ($hhmm), skip; will retry on next trigger."
    exit 0
fi

# Raise fd limit: pandas/report generation previously hit EMFILE (Errno 24)
ulimit -n 4096 2>/dev/null || true

# 行情源（新浪/腾讯/baostock）均为境内直连；定时环境若继承了失效代理
# （如 127.0.0.1:8888）会让快照请求 0.1s 内 0% 覆盖率、退回慢速腾讯兜底又全挂——
# 2026-10-13/10-14 两天的数据就是这么丢的。这里强制清代理走直连。
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export no_proxy='*'

# 4. KlineDB 当日同步：sync_today「快照优先」——先用新浪快照批量补当日
#    （秒级、精确成交额、不碰腾讯 WAF）。快照偶发取不到多为网络抖动，重试一次；
#    两次都没拿到才落到 sync_today 内部的腾讯逐票兜底。
log ">>> sync_today (快照优先)"
sync_ok=0
for attempt in 1 2; do
    out=$("$PYTHON" -m data_hub sync_today 2>&1)
    echo "$out" >> "$LOG_FILE"
    if echo "$out" | grep -q "快照成功"; then
        sync_ok=1
        break
    fi
    [ "$attempt" -lt 2 ] && { log "sync_today attempt $attempt 未取到快照，10s 后重试"; sleep 10; }
done
[ "$sync_ok" -eq 1 ] || log "sync_today 两次均未拿到快照（已走内部腾讯兜底，非致命）"

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

# 7. 自动提交并推送选股产物。index.html 每次生成都会刷新「更新: <时间戳>」
#    （tracker_report.py:1500 用 datetime.now()），因此每天都有改动、每天都提交，
#    让页面上的更新时间反映最新一次跑批——不做「无改动则跳过」判断。
log ">>> git 自动提交"
git add stock_data/selections.json tracker_report/index.html 2>>"$LOG_FILE"
if git commit -m "chore: 更新 $today 行情与选股（例行自动提交）" >>"$LOG_FILE" 2>&1; then
    if git push origin main >>"$LOG_FILE" 2>&1; then
        log "已提交并推送 origin main"
    else
        log "已提交但 push 失败（本地已存，需手动 push）"
    fi
else
    log "git commit 无改动或失败，跳过推送"
fi

# 8. Mark as done
echo "$today" > "$STAMP"
log "==== done ===="
