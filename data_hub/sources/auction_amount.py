"""集合竞价成交额数据源（多源容错 + 近5日回溯）。

实时优先级：东财 akshare → 腾讯 qt.gtimg.cn → 新浪快照。
历史回溯：东财分钟线 9:30 首根成交额（近似竞价+开盘集合量，仅近 ~5 个交易日）。
任一路径异常均降级，不影响主流程。
"""
from __future__ import annotations


def _to_bs(code: str) -> str:
    """6 位代码 → baostock 风格 sh./sz. 前缀。"""
    code = str(code).strip().zfill(6)
    return ('sh.' if code[0] in '69' else 'sz.') + code


def _to_tencent(bs_code: str) -> str:
    """sh.600519 → sh600519（腾讯格式）。"""
    return bs_code.replace('.', '')


class AuctionSource:
    name = 'auction_amount'

    def get_auction_amount(self, codes=None) -> dict:
        """返回竞价/实时成交额快照 {bs_code: {'amount':元, 'volume_ratio':量比}}。

        多源串行 fallback：东财 → 腾讯 → 新浪。任一源非空即返回。全失败返回 {}。
        """
        for fetch in (self._fetch_eastmoney, self._fetch_tencent, self._fetch_sina):
            try:
                result = fetch(codes)
            except Exception:
                result = {}
            if result:
                return result
        return {}

    # ---------- 东财 ----------
    def _fetch_eastmoney(self, codes=None) -> dict:
        try:
            import akshare as ak
        except ImportError:
            return {}
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty or '代码' not in df.columns:
            return {}
        amount_col = '成交额' if '成交额' in df.columns else None
        ratio_col = '量比' if '量比' in df.columns else None
        if amount_col is None:
            return {}
        want = set(codes) if codes else None
        out: dict = {}
        for _, row in df.iterrows():
            bs = _to_bs(row['代码'])
            if want is not None and bs not in want:
                continue
            try:
                amount = float(row[amount_col])
            except (TypeError, ValueError):
                continue
            if amount != amount:
                continue
            entry = {'amount': amount}
            if ratio_col is not None:
                try:
                    vr = float(row[ratio_col])
                    if vr == vr:
                        entry['volume_ratio'] = vr
                except (TypeError, ValueError):
                    pass
            out[bs] = entry
        return out

    # ---------- 腾讯 ----------
    def _fetch_tencent(self, codes=None) -> dict:
        """腾讯快照。仅当指定 codes 时可用（需要明确代码列表构造 URL）。

        返回串格式：v_sh600519="1~名称~代码~现价~昨收~今开~成交量(手)~外盘~内盘~...
                    ~成交额(万)~..."；成交额位于索引 [37]。
        """
        if not codes:
            return {}
        import requests
        want = list(codes)
        out: dict = {}
        for i in range(0, len(want), 50):
            group = want[i:i + 50]
            q = ','.join(_to_tencent(c) for c in group)
            url = 'https://qt.gtimg.cn/q=' + q
            resp = requests.get(url, timeout=5,
                                headers={'Referer': 'https://gu.qq.com/'})
            resp.encoding = 'gbk'
            for line in resp.text.strip().split(';'):
                line = line.strip()
                if not line or '="' not in line:
                    continue
                payload = line.split('="', 1)[1].rstrip('"')
                fields = payload.split('~')
                if len(fields) < 38:
                    continue
                code6 = fields[2]
                bs = _to_bs(code6)
                try:
                    amount_wan = float(fields[37])  # 成交额，单位万元
                except (TypeError, ValueError, IndexError):
                    continue
                if amount_wan != amount_wan or amount_wan <= 0:
                    continue
                entry = {'amount': amount_wan * 1e4}
                # 量比位于索引 [49]（不同版本可能偏移，缺失则跳过）
                try:
                    vr = float(fields[49])
                    if vr == vr:
                        entry['volume_ratio'] = vr
                except (TypeError, ValueError, IndexError):
                    pass
                out[bs] = entry
        return out

    # ---------- 新浪 ----------
    def _fetch_sina(self, codes=None) -> dict:
        """复用项目 SinaSource 快照，取累计成交额。"""
        from data_hub.api import get_market_snapshot
        snap = get_market_snapshot(list(codes) if codes else None)
        if not snap:
            return {}
        out: dict = {}
        for bs, rec in snap.items():
            amount = rec.get('amount')
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                continue
            if amount != amount or amount <= 0:
                continue
            out[bs] = {'amount': amount}
        return out

    # ---------- 历史回溯（近5日）----------
    def get_auction_amount_hist(self, code: str, date: str) -> float | None:
        """取指定日期 9:30 首根 1 分钟 K 线成交额（近似竞价+开盘集合量）。

        date 为 YYYY-MM-DD。东财分钟历史仅近 ~5 个交易日；超出或停牌返回 None。
        """
        try:
            import akshare as ak
        except ImportError:
            return None
        code6 = code.replace('sh.', '').replace('sz.', '')
        try:
            df = ak.stock_zh_a_hist_min_em(
                symbol=code6,
                start_date=f'{date} 09:30:00',
                end_date=f'{date} 09:31:00',
                period='1', adjust='')
        except Exception:
            return None
        if df is None or df.empty or '成交额' not in df.columns:
            return None
        df['时间'] = df['时间'].astype(str)
        first = df[df['时间'].str.contains('09:30:00')]
        if first.empty:
            return None
        try:
            amount = float(first.iloc[0]['成交额'])
        except (TypeError, ValueError):
            return None
        return amount if amount == amount and amount > 0 else None
