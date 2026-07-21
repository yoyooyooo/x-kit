import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def insecure_tls_enabled() -> bool:
    return os.environ.get("XKIT_INSECURE_TLS", "").lower() in {"1", "true", "yes", "on"}


def _load_config() -> dict:
    settings_path = CONFIG_DIR / "settings.json"
    if not settings_path.exists():
        raise ValueError(
            f"{settings_path} 不存在。请先复制 config/settings.example.json "
            "为 config/settings.json，并填入 auth_token 和 ct0。"
        )
    with open(settings_path) as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    with open(CONFIG_DIR / "settings.json", "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _add_transaction_id(request: httpx.Request) -> None:
    """httpx 请求钩子：为 x.com API 请求注入 x-client-transaction-id.

    这是 X 反自动化的关键信号，缺失会被判定为 bot（错误码 226）。
    仅对 /i/api/ 路径注入；首次调用会触发首页资源拉取（较慢）。
    """
    path = request.url.path
    if "/i/api/" not in path:
        return
    try:
        from utils.transaction_id import get_transaction_id

        tid = get_transaction_id(request.method, path)
        request.headers["x-client-transaction-id"] = tid
    except Exception as e:
        # 生成失败不阻塞请求，但提示
        print(f"[!] x-client-transaction-id 生成失败（降级无此头）: {e}")


def get_client(
    auth_token: Optional[str] = None,
    ct0: Optional[str] = None,
    with_transaction_id: bool = True,
    verify: Optional[bool] = None,
) -> httpx.Client:
    cfg = _load_config()

    token = auth_token or cfg["auth"]["auth_token"]
    csrf = ct0 or cfg["auth"]["ct0"]

    if not token or not csrf:
        raise ValueError(
            "auth_token 或 ct0 未设置。"
            "请从浏览器 cookie 中获取并填入 config/settings.json，"
            "或通过参数传入。"
        )

    event_hooks = {"request": [_add_transaction_id]} if with_transaction_id else {}
    if verify is None:
        verify = not insecure_tls_enabled()

    client = httpx.Client(
        headers={
            "authorization": f"Bearer {cfg['auth']['bearer_token']}",
            "x-csrf-token": csrf,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "user-agent": cfg["api"]["user_agent"],
            "content-type": "application/json",
            "origin": "https://x.com",
            "referer": "https://x.com/home",
        },
        cookies={
            "auth_token": token,
            "ct0": csrf,
        },
        event_hooks=event_hooks,
        timeout=30,
        verify=verify,
    )
    return client


def load_cookies_from_file(path: str | Path) -> tuple[str, str]:
    """从 Netscape 格式 cookie 文件或 JSON 中提取 auth_token 和 ct0."""
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            return data.get("auth_token", ""), data.get("ct0", "")
        return "", ""

    # Netscape format
    auth_token = ""
    ct0 = ""
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name, value = parts[5], parts[6]
            if name == "auth_token":
                auth_token = value
            elif name == "ct0":
                ct0 = value
    return auth_token, ct0


def save_cookies_to_config(auth_token: str, ct0: str) -> None:
    """持久化 cookie 到配置文件."""
    cfg = _load_config()
    cfg["auth"]["auth_token"] = auth_token
    cfg["auth"]["ct0"] = ct0
    _save_config(cfg)
    print(f"[+] cookie 已保存到 {CONFIG_DIR / 'settings.json'}")


def human_delay(min_sec: float = 2.0, max_sec: float = 6.0) -> None:
    """随机停顿，模拟人类操作节奏，降低反自动化风控触发概率."""
    import random

    d = random.uniform(min_sec, max_sec)
    time.sleep(d)
