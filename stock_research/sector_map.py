"""按 baostock 代码前缀映射板块"""
from __future__ import annotations


def code_to_sector(code: str) -> str:
    if not code or '.' not in code:
        return '其他'
    market, num = code.split('.', 1)
    market = market.lower()
    if market == 'sh':
        if num.startswith('60'):
            return '沪市主板'
        if num.startswith('68'):
            return '科创板'
        return '沪其他'
    if market == 'sz':
        if num.startswith('00'):
            return '深市主板'
        if num.startswith('30'):
            return '创业板'
        return '深其他'
    if market == 'bj':
        return '北交所'
    return '其他'


def add_sector(df, code_col: str = 'code'):
    """给 DataFrame 增加 sector 列（原地）"""
    df = df.copy()
    df['sector'] = df[code_col].map(code_to_sector)
    return df


if __name__ == '__main__':
    for c in ['sh.600519', 'sh.688981', 'sz.000001', 'sz.300750', 'bj.832000']:
        print(c, '->', code_to_sector(c))
