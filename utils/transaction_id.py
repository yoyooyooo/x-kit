"""x-client-transaction-id 生成器.

封装 x_client_transaction 库，缓存初始化结果。
该 header 是 X 反自动化的关键信号，缺失会被判定为 bot（错误码 226）。

算法依赖 x.com 首页的 SVG 动画 + ondemand.s.js，
本模块在首次调用时获取并缓存这些资源。
"""

import threading
import time
from urllib.parse import urlparse

import bs4
import requests
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import generate_headers, get_ondemand_file_url, handle_x_migration

_lock = threading.Lock()
_ct: ClientTransaction | None = None


def _init_client_transaction() -> ClientTransaction:
    """获取首页 + ondemand 文件，初始化 ClientTransaction（一次性，较慢）。

    带重试：首页/ondemand 拉取若遇网络瞬断会退避重试，
    避免单次 SSL/连接错误导致后续所有请求缺头 → 404。
    """
    last_err = None
    for attempt in range(5):
        try:
            session = requests.Session()
            session.headers = generate_headers()

            # 1. 获取首页（含验证 meta + 动画 SVG）
            home_page = handle_x_migration(session)

            # 2. 获取 ondemand.s.js（含密钥字节索引）
            ondemand_url = get_ondemand_file_url(response=home_page)
            ondemand_resp = session.get(ondemand_url, timeout=15)
            ondemand_file = bs4.BeautifulSoup(ondemand_resp.content, "html.parser")

            return ClientTransaction(
                home_page_response=home_page,
                ondemand_file_response=ondemand_file,
            )
        except Exception as e:
            last_err = e
            wait = min(2 ** attempt, 30)
            time.sleep(wait)
    raise RuntimeError(f"transaction_id 初始化失败（已重试 5 次）: {last_err}")


def get_transaction_id(method: str, url_or_path: str) -> str:
    """为指定请求生成 x-client-transaction-id.

    Args:
        method: HTTP 方法（GET/POST）
        url_or_path: 完整 URL 或路径（仅取 path 部分参与计算）
    """
    global _ct
    with _lock:
        if _ct is None:
            _ct = _init_client_transaction()

    if url_or_path.startswith("http"):
        path = urlparse(url_or_path).path
    else:
        path = url_or_path.split("?")[0]

    return _ct.generate_transaction_id(method=method.upper(), path=path)


def reset() -> None:
    """清除缓存，下次调用时重新初始化（首页资源过期时使用）."""
    global _ct
    with _lock:
        _ct = None
