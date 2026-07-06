"""同花顺创新高榜数据源（选股安全网）。

提供"当日创新高"个股集合，用于绕过成交额预筛、兜住被误筛的创新高票。
接口断连时返回空集合，安全网降级，不影响主选股流程。
"""
from __future__ import annotations


def _to_bs(code: str) -> str:
    """6 位代码 → baostock 风格 sh./sz. 前缀。"""
    code = str(code).strip().zfill(6)
    return ('sh.' if code[0] in '69' else 'sz.') + code


class NewHighSource:
    name = 'ths_newhigh'

    def get_new_high(self, symbols=('历史新高', '一年新高')) -> set:
        """返回当日创新高个股代码集合（sh./sz. 前缀）。

        symbols 可选档位：创月新高 / 半年新高 / 一年新高 / 历史新高。
        任一档接口异常时跳过该档，整体异常返回空集。
        """
        try:
            import akshare as ak
        except ImportError:
            return set()
        out: set = set()
        for sym in symbols:
            try:
                df = ak.stock_rank_cxg_ths(symbol=sym)
            except Exception:
                continue
            if df is None or df.empty or '股票代码' not in df.columns:
                continue
            for c in df['股票代码'].astype(str):
                out.add(_to_bs(c))
        return out
