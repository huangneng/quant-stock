"""Server酱 Turbo 推送脚本

读取 stock_research/output/daily_selections_{YYYY-MM-DD}.csv 渲染 Markdown，推送到个人微信。
正文规则：
  - 入选股票全部进入正文（每个星级一段表格）
  - 4★ / 5★ 默认展开
  - ≤3★ 包在 <details> 内默认折叠
  - 0 候选时报"今日 0 只候选"

策略：仅在选股成功且 CSV 可读时推送；失败/缺失场景一律静默退出，仅写 stderr。

环境变量：
  SERVERCHAN_KEY  Server酱 SendKey
  PUSH_DATE       覆盖推送日期（YYYY-MM-DD）

未配置 SERVERCHAN_KEY 时静默退出（exit 0）。
"""
import argparse
import os
import sys
import requests
from datetime import date

import pandas as pd

OUTPUT_DIR = 'stock_research/output'
REPORT_URL = 'https://huangneng.github.io/quant-stock/tracker_report/'
TIMEOUT = 15

SIGNAL_LABEL = {
    'limit_up': '涨停',
    'gap_up': '跳空',
    'breakthrough': '突破',
}


def render_markdown(date_iso: str, df: pd.DataFrame, intraday: bool = False) -> str:
    intraday_note = ''
    if intraday:
        intraday_note = '> ⚠️ 盘中 14:30 预警扫描，最终请以 16:15 盘后扫描为准。\n\n'
    if df is None or df.empty:
        return (
            intraday_note +
            f"### 📊 {date_iso} 选股结果\n\n"
            f"> 今日 0 只候选\n\n"
            f"预筛或信号判定未触发。"
        )

    df = df.copy()
    if 'star' not in df.columns:
        df['star'] = 0
    df['star'] = df['star'].fillna(0).astype(int)
    df = df.sort_values(['star', 'score'], ascending=[False, False])

    n_total = len(df)
    n5 = int((df['star'] == 5).sum())
    n4 = int((df['star'] == 4).sum())

    lines = [
        intraday_note +
        f"### 📊 {date_iso} 今日选股 {n_total} 只（5★ {n5} / 4★ {n4}）\n",
        "| 星级 | 名称 | 代码 | 现价 | 涨幅 | 类型 | 成交额 | 评分 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, s in df.iterrows():
        sig = SIGNAL_LABEL.get(s['signal_type'], s['signal_type'])
        star = int(s['star'])
        star_str = '★' * star if star > 0 else '-'
        lines.append(
            f"| {star_str} | **{s['name']}** | `{s['code']}` "
            f"| {float(s['price']):.2f} | {float(s['pct']):+.2f}% "
            f"| {sig} | {float(s['amount_yi']):.1f}亿 | {float(s['score']):.2f} |"
        )

    lines.append(f"\n---\n\n**[👉 查看全部持仓与历史走势]({REPORT_URL})**")
    lines.append("\n> 本地 launchd 自动推送")
    return "\n".join(lines)


def send_serverchan(title: str, content: str):
    key = os.environ.get('SERVERCHAN_KEY', '').strip()
    if not key:
        print('[push_serverchan] 未配置 SERVERCHAN_KEY，跳过', file=sys.stderr)
        sys.exit(0)
    url = f'https://sctapi.ftqq.com/{key}.send'
    r = requests.post(url, data={'title': title, 'desp': content}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get('code') != 0:
        raise RuntimeError(f'Server酱返回错误: {data}')
    print(f'[push_serverchan] 推送成功（title={title}）')


def push_today(intraday: bool = False):
    date_iso = os.environ.get('PUSH_DATE', '').strip() or date.today().strftime('%Y-%m-%d')
    prefix = 'intraday_selections_' if intraday else 'daily_selections_'
    csv_path = os.path.join(OUTPUT_DIR, f'{prefix}{date_iso}.csv')

    if not os.path.exists(csv_path):
        print(f'[push_serverchan] 跳过：CSV 不存在 {csv_path}', file=sys.stderr)
        return

    try:
        df = pd.read_csv(csv_path, dtype={'code': str})
    except Exception as e:
        print(f'[push_serverchan] 跳过：CSV 解析失败 {csv_path}: {e}', file=sys.stderr)
        return

    n = 0 if df is None or df.empty else len(df)
    n5 = 0 if df is None or df.empty else int((df['star'] == 5).sum())
    tag = '[盘中] ' if intraday else ''
    title = f'{tag}【{date_iso}】今日选股 {n} 只 / {n5} 只 5★' if n else f'{tag}【{date_iso}】今日 0 只候选'
    content = render_markdown(date_iso, df, intraday=intraday)
    send_serverchan(title, content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--intraday', action='store_true')
    args = parser.parse_args()
    push_today(intraday=args.intraday)


if __name__ == '__main__':
    main()
