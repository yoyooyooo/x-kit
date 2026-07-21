#!/usr/bin/env python3
"""X.com (Twitter) 发帖工具.

用法:
    # 纯文本发帖
    uv run tweet.py "hello world"

    # 带图片发帖
    uv run tweet.py "hello with image" --image ./photo.png

    # 从文件导入 cookie
    uv run tweet.py --cookies ./cookies.json "hello"

    # 直接传入 cookie
    uv run tweet.py --auth-token xxx --ct0 yyy "hello"

依赖:
    httpx
"""

import argparse
import hashlib
import json
import mimetypes
import sys
from pathlib import Path

import httpx

from utils.session_manager import get_client, human_delay, load_cookies_from_file, save_cookies_to_config

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config" / "settings.json"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


# ── media upload ──────────────────────────────────────────────


class MediaUploadError(Exception):
    pass


def upload_media(client: httpx.Client, file_path: str, cfg: dict) -> str:
    """上传图片/视频，返回 media_id 字符串."""
    f = Path(file_path)
    if not f.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    total_bytes = f.stat().st_size
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/png"

    category = "tweet_image" if mime_type.startswith("image/") else "tweet_video"
    upload_url = cfg["api"]["upload_url"]

    # 1. INIT
    print(f"[*] 初始化上传 ({f.name}, {total_bytes} bytes, {mime_type})")
    r = client.post(
        f"{upload_url}/upload.json",
        params={
            "command": "INIT",
            "total_bytes": total_bytes,
            "media_type": mime_type,
            "media_category": category,
        },
    )
    if r.status_code not in (200, 202):
        raise MediaUploadError(f"INIT 失败: {r.status_code} {r.text}")
    init_data = r.json()
    media_id = init_data["media_id"]
    media_id_str = init_data["media_id_string"]
    print(f"  -> media_id: {media_id_str}")

    # 2. APPEND
    chunk_size = 1024 * 1024  # 1MB chunks
    content = f.read_bytes()
    segments = (total_bytes + chunk_size - 1) // chunk_size
    for seg_idx in range(segments):
        start = seg_idx * chunk_size
        end = min(start + chunk_size, total_bytes)
        print(f"[*] 上传分片 {seg_idx + 1}/{segments} ({end - start} bytes)")
        # APPEND 需要 raw binary body，不能用 json client
        segment = content[start:end]
        raw_client = httpx.Client(timeout=60)
        r = raw_client.post(
            f"{upload_url}/upload.json",
            params={
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": seg_idx,
            },
            content=segment,
        )
        if r.status_code not in (200, 202, 204):
            raise MediaUploadError(f"APPEND 失败: {r.status_code} {r.text}")

    # 3. FINALIZE
    print(f"[*] 完成上传 (MD5: {hashlib.md5(content).hexdigest()})")
    r = client.post(
        f"{upload_url}/upload.json",
        params={
            "command": "FINALIZE",
            "media_id": media_id,
            "original_md5": hashlib.md5(content).hexdigest(),
            "allow_async": "true",
        },
    )
    if r.status_code not in (200, 201, 202):
        raise MediaUploadError(f"FINALIZE 失败: {r.status_code} {r.text}")

    # 等待异步处理完成（视频需要）
    finalize_data = r.json()
    if finalize_data.get("processing_info"):
        state = finalize_data["processing_info"]["state"]
        check_after = finalize_data["processing_info"].get("check_after_secs", 1)
        while state in ("pending", "in_progress"):
            import time

            time.sleep(check_after)
            r = client.get(
                f"{upload_url}/upload.json",
                params={"command": "STATUS", "media_id": media_id},
            )
            if r.status_code == 200:
                status_data = r.json()
                state = status_data.get("processing_info", {}).get("state", "done")
                if state in ("pending", "in_progress"):
                    check_after = status_data["processing_info"].get(
                        "check_after_secs", 1
                    )
            else:
                break
        print(f"  -> 处理状态: {state}")

    # 4. media metadata
    print(f"[*] 设置媒体元数据")
    r = client.post(
        "https://x.com/i/api/1.1/media/metadata/create.json",
        json={
            "media_id": media_id_str,
            "allow_download_status": {"allow_download": "true"},
        },
    )
    if r.status_code != 200:
        print(f"  [!] 元数据设置返回 {r.status_code}（非致命）")

    print(f"[+] 上传完成: {media_id_str}")
    return media_id_str


# ── tweet creation ────────────────────────────────────────────


def create_tweet(
    client: httpx.Client,
    text: str,
    media_ids: list[str] | None = None,
    reply_to_tweet_id: str | None = None,
    cfg: dict | None = None,
) -> dict:
    """创建推文。返回 API 响应中的 tweet 对象。"""
    if cfg is None:
        cfg = load_config()

    query_id = cfg["api"]["create_tweet_query_id"]
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/CreateTweet"

    media_entities = []
    if media_ids:
        media_entities = [{"media_id": mid, "tagged_users": []} for mid in media_ids]

    variables: dict = {
        "tweet_text": text,
        "media": {
            "media_entities": media_entities,
            "possibly_sensitive": False,
        },
        "semantic_annotation_ids": [],
        "disallowed_reply_options": None,
        "semantic_annotation_options": {"source": "Htl"},
    }
    if reply_to_tweet_id:
        variables["reply"] = {
            "in_reply_to_tweet_id": reply_to_tweet_id,
            "exclude_reply_user_ids": [],
        }

    body = {
        "variables": variables,
        "features": cfg["features"],
        "queryId": query_id,
    }

    print(f"[*] 发送推文...")
    human_delay()
    r = client.post(url, json=body)

    if r.status_code != 200:
        print(f"[✗] 发帖失败: HTTP {r.status_code}")
        print(f"    响应: {r.text[:500]}")
        sys.exit(1)

    data = r.json()
    result = data.get("data", {}).get("create_tweet", {}).get("tweet_results", {}).get("result", {})
    if not result:
        print(f"[✗] 响应异常: {json.dumps(data, indent=2)[:500]}")
        sys.exit(1)

    tweet_id = result.get("rest_id", "?")
    user_result = result.get("core", {}).get("user_results", {}).get("result", {})
    screen_name = user_result.get("legacy", {}).get("screen_name", "")
    if not screen_name:
        screen_name = user_result.get("rest_id", "?")
    tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"

    print(f"[+] 发帖成功!")
    print(f"    {tweet_url}")
    return result


# ── CLI ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="X.com (Twitter) 发帖工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run tweet.py "hello world"
  uv run tweet.py "check this out" --image ./screenshot.png
  uv run tweet.py --cookies ./cookies.json "hello"
  uv run tweet.py --auth-token xxx --ct0 yyy "hello"
        """,
    )
    parser.add_argument("text", help="推文文本内容")
    parser.add_argument("--image", "-i", action="append", default=[], help="图片路径（可多次指定）")
    parser.add_argument("--cookies", help="cookie 文件路径 (Netscape 或 JSON)")
    parser.add_argument("--auth-token", help="auth_token cookie 值")
    parser.add_argument("--ct0", help="ct0 cookie 值")
    parser.add_argument("--save-cookies", action="store_true", help="将传入的 cookie 保存到配置文件")
    parser.add_argument("--reply-to", help="回复目标推文 ID")
    args = parser.parse_args()

    # 处理 cookie 来源
    auth_token = args.auth_token
    ct0 = args.ct0

    if args.cookies:
        token, csrf = load_cookies_from_file(args.cookies)
        auth_token = auth_token or token
        ct0 = ct0 or csrf
        print(f"[+] 从 {args.cookies} 加载 cookie")

    try:
        client = get_client(auth_token=auth_token, ct0=ct0)
    except ValueError as e:
        print(f"[✗] {e}")
        print("[*] 请从浏览器中获取 cookie:")
        print("    https://x.com → DevTools → Application → Cookies → x.com")
        print("    找到 auth_token 和 ct0，然后:")
        print(f'    uv run tweet.py --auth-token "xxx" --ct0 "yyy" --save-cookies "hello"')
        sys.exit(1)

    if args.save_cookies and auth_token and ct0:
        save_cookies_to_config(auth_token, ct0)

    # 上传媒体
    media_ids = []
    cfg = load_config()
    for img_path in args.image:
        try:
            mid = upload_media(client, img_path, cfg)
            media_ids.append(mid)
        except MediaUploadError as e:
            print(f"[✗] {e}")
            sys.exit(1)

    # 发帖
    create_tweet(client, args.text, media_ids or None, args.reply_to, cfg)


if __name__ == "__main__":
    main()
