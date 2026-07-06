"""选股结果邮件推送脚本

读取 stock_research/output/daily_selections_{YYYY-MM-DD}.csv 并发送 HTML 邮件。
正文规则：
  - 入选股票全部进入正文（每个星级一段表格）
  - 4★ / 5★ 默认展开
  - ≤3★ 包在 <details> 内默认折叠
  - 0 候选时报"今日 0 只候选"

策略：仅在选股成功且 CSV 可读时推送；失败/缺失场景一律静默退出，仅写 stderr。

环境变量：
  SMTP_HOST  SMTP 服务器地址（如 smtp.qq.com）
  SMTP_PORT  SMTP 端口（SSL 通常为 465）
  SMTP_USER  发件邮箱
  SMTP_PASS  邮箱授权码
  MAIL_TO    收件人邮箱（多个用逗号分隔）
  PUSH_DATE  覆盖推送日期（YYYY-MM-DD）
"""
import argparse
import os
import sys
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

import pandas as pd

OUTPUT_DIR = 'stock_research/output'
REPORT_URL = 'https://huangneng.github.io/quant-stock/tracker_report/'

SIGNAL_LABEL = {
    'limit_up': '涨停',
    'gap_up': '跳空',
    'breakthrough': '突破',
}


def _render_table_html(df: pd.DataFrame) -> str:
    rows = []
    for _, s in df.iterrows():
        sig_main = SIGNAL_LABEL.get(s['signal_type'], s['signal_type'])
        pct = float(s['pct'])
        pct_cls = 'up' if pct >= 0 else 'down'
        star = int(s['star']) if pd.notna(s.get('star')) else 0
        star_html = (
            f'<span class="star">{"★" * star}</span>' if star > 0 else
            '<span class="star-na">-</span>'
        )
        rows.append(
            f'<tr>'
            f'<td class="star-cell">{star_html}</td>'
            f'<td class="code"><b>{s["code"]}</b></td>'
            f'<td class="name">{s["name"]}</td>'
            f'<td class="num">{float(s["price"]):.2f}</td>'
            f'<td class="num {pct_cls}">{pct:+.2f}%</td>'
            f'<td class="sig">{sig_main}</td>'
            f'<td class="num">{float(s["amount_yi"]):.1f}亿</td>'
            f'<td class="num">{float(s["score"]):.2f}</td>'
            f'</tr>'
        )
    return (
        '<table>'
        '<colgroup>'
        '<col style="width:9%"><col style="width:12%"><col style="width:16%">'
        '<col style="width:10%"><col style="width:11%">'
        '<col style="width:10%"><col style="width:13%"><col style="width:9%">'
        '</colgroup>'
        '<thead><tr>'
        '<th>星级</th><th>代码</th><th>名称</th>'
        '<th class="num">现价</th><th class="num">涨幅</th>'
        '<th>类型</th><th class="num">成交额</th><th class="num">评分</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def render_html(date_iso: str, df: pd.DataFrame) -> str:
    """渲染 GitHub Light 风格邮件正文。"""
    if df is None or df.empty:
        body = (
            '<div class="empty">'
            f'<h2>{date_iso} 今日 0 只候选</h2>'
            '<p>预筛或信号判定未触发。</p>'
            '</div>'
        )
    else:
        df = df.copy()
        if 'star' not in df.columns:
            df['star'] = 0
        df['star'] = df['star'].fillna(0).astype(int)
        if 'score' in df.columns:
            df = df.sort_values(['star', 'score'], ascending=[False, False])
        else:
            df = df.sort_values('star', ascending=False)

        n_total = len(df)
        n5 = int((df['star'] == 5).sum())
        n4 = int((df['star'] == 4).sum())
        title = f'{date_iso} 今日选股 {n_total} 只（5★ {n5} / 4★ {n4}）'
        body = f'<h2>{title}</h2>' + _render_table_html(df)

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background:#ffffff; color:#222; padding:24px; margin:0; font-size:14px; line-height:1.5; }}
        h2 {{ color:#1f6feb; border-bottom:2px solid #d0d7de; padding-bottom:8px; margin:0 0 16px; font-size:18px; }}
        table {{ border-collapse: collapse; width:100%; margin-top:6px; table-layout:fixed; }}
        th, td {{ padding:8px 10px; border-bottom:1px solid #eaeef2; vertical-align:middle; }}
        th {{ background:#f6f8fa; color:#1f6feb; font-weight:600; text-align:left; font-size:13px; }}
        th.num {{ text-align:right; }}
        td {{ color:#222; }}
        td.code {{ font-family: "SF Mono", Consolas, "Courier New", monospace; color:#6f42c1; }}
        td.name {{ font-weight:600; }}
        td.sig {{ color:#0969da; }}
        td.num {{ font-family: "SF Mono", Consolas, "Courier New", monospace; text-align:right; font-variant-numeric: tabular-nums; }}
        td.up {{ color:#d1242f; font-weight:600; }}
        td.down {{ color:#1a7f37; font-weight:600; }}
        td.star-cell {{ white-space:nowrap; }}
        .star {{ color:#e3b341; letter-spacing:1px; }}
        .star-na { color:#8c959f; }
        tbody tr:hover { background:#f6f8fa; }
        .empty { padding:24px; background:#f6f8fa; border-radius:6px; text-align:center; color:#57606a; }
        .more { display:inline-block; margin-top:20px; padding:10px 18px; background:#1f6feb; color:#fff !important; text-decoration:none; border-radius:6px; font-weight:600; }
        .footer { color:#8c959f; font-size:12px; margin-top:20px; text-align:right; }
    </style></head><body>
        {body}
        <p><a class="more" href="{REPORT_URL}" target="_blank">查看全部持仓与历史走势 →</a></p>
        <p class="footer">扫描时间: {date_iso} · 本地 launchd 自动推送</p>
    </body></html>"""


def send_email(subject: str, html: str):
    host = os.environ.get('SMTP_HOST', '').strip()
    port = int(os.environ.get('SMTP_PORT', '').strip() or '465')
    user = os.environ.get('SMTP_USER', '').strip()
    pwd = os.environ.get('SMTP_PASS', '').strip()
    to = os.environ.get('MAIL_TO', '').strip()

    if not all([host, user, pwd, to]):
        missing = [k for k, v in [('SMTP_HOST', host), ('SMTP_USER', user),
                                   ('SMTP_PASS', pwd), ('MAIL_TO', to)] if not v]
        print(f'[push_email] 跳过发送：环境变量缺失 {missing}', file=sys.stderr)
        sys.exit(0)

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = formataddr(('选股助手', user))
    msg['To'] = to
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    recipients = [x.strip() for x in to.split(',') if x.strip()]
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, recipients, msg.as_string())
    print(f'[push_email] 已发送邮件 → {to}（subject={subject}）')


def push_today():
    date_iso = os.environ.get('PUSH_DATE', '').strip() or date.today().strftime('%Y-%m-%d')
    csv_path = os.path.join(OUTPUT_DIR, f'daily_selections_{date_iso}.csv')

    if not os.path.exists(csv_path):
        print(f'[push_email] 跳过：CSV 不存在 {csv_path}', file=sys.stderr)
        return

    try:
        df = pd.read_csv(csv_path, dtype={'code': str})
    except Exception as e:
        print(f'[push_email] 跳过：CSV 解析失败 {csv_path}: {e}', file=sys.stderr)
        return

    n = 0 if df is None or df.empty else len(df)
    n5 = 0 if df is None or df.empty else int((df['star'] == 5).sum())
    subject = f'【{date_iso}】今日选股 {n} 只 / {n5} 只 5★' if n else f'【{date_iso}】今日 0 只候选'
    html = render_html(date_iso, df)
    send_email(subject, html)


def main():
    push_today()


if __name__ == '__main__':
    main()
