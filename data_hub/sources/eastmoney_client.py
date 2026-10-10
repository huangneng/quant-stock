"""东方财富 HTTP 客户端。

统一处理限流、重试、空响应和连接异常，降低东财接口风控影响。
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

_DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}

_LAST_REQUEST_AT = 0.0


def _min_interval() -> float:
    try:
        return float(os.environ.get('EM_MIN_INTERVAL', '0.8'))
    except ValueError:
        return 0.8


def _wait_turn(min_interval: float) -> None:
    global _LAST_REQUEST_AT
    now = time.time()
    wait = min_interval - (now - _LAST_REQUEST_AT)
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST_AT = time.time()


def em_get(url: str, *, params: dict | None = None, headers: dict | None = None,
           timeout: int = 12, retries: int = 3,
           min_interval: Optional[float] = None) -> requests.Response | None:
    if min_interval is None:
        min_interval = _min_interval()
    req_headers = dict(_DEFAULT_HEADERS)
    if headers:
        req_headers.update(headers)

    for attempt in range(max(1, retries)):
        _wait_turn(min_interval)
        try:
            resp = requests.get(url, params=params, headers=req_headers, timeout=timeout)
            if not (200 <= resp.status_code < 300):
                raise requests.HTTPError(f'HTTP {resp.status_code}')
            if not resp.text:
                raise ValueError('empty response')
            return resp
        except Exception:
            if attempt >= retries - 1:
                return None
            time.sleep(0.5 * (2 ** attempt))
    return None


def em_get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
                timeout: int = 12, retries: int = 3) -> dict | None:
    resp = em_get(url, params=params, headers=headers, timeout=timeout, retries=retries)
    if resp is None:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
