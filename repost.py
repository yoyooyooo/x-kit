#!/usr/bin/env python3
"""X.com 转发/引用/抄送推文.

用法:
    # 抄送 -- 读原文+图，作为自己原创推文发出
    uv run repost.py --copy https://x.com/user/status/123

    # 抄送并改写
    uv run repost.py --copy https://x.com/user/status/123 -t "my version"

    # 简单转发（retweet）
    uv run repost.py --retweet https://x.com/user/status/123

    # 引用推文（quote tweet）
    uv run repost.py https://x.com/user/status/123 -t "my thoughts"
"""

import argparse
import json
import re
import sys
from pathlib import Path

from utils.session_manager import get_client, human_delay, load_cookies_from_file, save_cookies_to_config

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config" / "settings.json"


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def extract_tweet_id(raw: str) -> str:
    m = re.search(r"/status/(\d+)", raw)
    if m:
        return m[1]
    if raw.isdigit():
        return raw
    print(f"[✗] 无法解析推文 ID: {raw}")
    sys.exit(1)


def build_tweet_url(tweet_id: str, screen_name: str = "i") -> str:
    return f"https://x.com/{screen_name}/status/{tweet_id}"


# ── 推文读取 ──────────────────────────────────────────────────


def fetch_tweet_content(client, tweet_id: str, cfg: dict) -> tuple[str, list[str]]:
    """获取推文原文和图片 URL 列表."""
    query_id = cfg["api"].get("tweet_detail_query_id", "6uCvnic3m5reVuehkvHa3w")
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/TweetDetail"

    variables = {
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
    }

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(cfg["features"]),
        "fieldToggles": json.dumps({
            "withArticleRichContentState": True,
            "withArticlePlainText": False,
            "withArticleSummaryText": True,
            "withArticleVoiceOver": True,
            "withGrokAnalyze": False,
            "withDisallowedReplyControls": False,
        }),
    }

    r = client.get(url, params=params)
    if r.status_code != 200:
        print(f"[✗] 获取推文失败: HTTP {r.status_code}")
        sys.exit(1)

    data = r.json()
    instructions = (
        data.get("data", {})
        .get("threaded_conversation_with_injections_v2", {})
        .get("instructions", [])
    )
    for instr in instructions:
        if instr.get("entries"):
            for entry in instr["entries"]:
                if entry.get("entryId", "").startswith("tweet-"):
                    result = (
                        entry.get("content", {})
                        .get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result", {})
                    )
                    if result:
                        legacy = result.get("legacy", {})
                        text = legacy.get("full_text", "")
                        media_list = legacy.get("extended_entities", {}).get("media", [])
                        image_urls = [
                            m.get("media_url_https", "")
                            for m in media_list
                            if m.get("type") == "photo"
                        ]
                        return text, image_urls

    print("[✗] 未找到推文数据")
    sys.exit(1)


# ── 图片下载 ──────────────────────────────────────────────────


def download_images(client, urls: list[str]) -> list[str]:
    """下载图片到临时目录，返回本地路径列表."""
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="x_images_"))
    paths = []
    for i, url in enumerate(urls):
        ext = url.rsplit(".", 1)[-1].split("?")[0] or "jpg"
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            ext = "jpg"
        fpath = tmpdir / f"img_{i}.{ext}"
        r = client.get(url)
        if r.status_code == 200:
            fpath.write_bytes(r.content)
            paths.append(str(fpath))
            print(f"  -> 下载图片: {fpath}")
        else:
            print(f"  [!] 图片下载失败: {url}")
    return paths


# ── 原创发帖 ──────────────────────────────────────────────────


def create_tweet(client, text: str, cfg: dict, image_paths: list[str] | None = None) -> dict:
    """发原创推文，可选带图。"""
    from tweet import upload_media

    media_ids = []
    if image_paths:
        for p in image_paths:
            mid = upload_media(client, p, cfg)
            media_ids.append(mid)

    query_id = cfg["api"]["create_tweet_query_id"]
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/CreateTweet"

    body = {
        "variables": {
            "tweet_text": text,
            "media": {
                "media_entities": [{"media_id": mid, "tagged_users": []} for mid in media_ids],
                "possibly_sensitive": False,
            },
            "semantic_annotation_ids": [],
            "disallowed_reply_options": None,
            "semantic_annotation_options": {"source": "Unknown"},
        },
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

    print(f"[+] 发送成功!")
    print(f"    {tweet_url}")
    return result


# ── retweet / quote ───────────────────────────────────────────


def retweet(client, tweet_id: str, cfg: dict) -> dict:
    """简单转发（retweet）."""
    query_id = cfg["api"].get("create_retweet_query_id", "mbRO74GrOvSfRcJnlMapnQ")
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/CreateRetweet"

    body = {"variables": {"tweet_id": tweet_id}, "queryId": query_id}

    print(f"[*] 转发推文 {tweet_id}...")
    human_delay()
    r = client.post(url, json=body)

    if r.status_code != 200:
        print(f"[✗] 转发失败: HTTP {r.status_code}")
        print(f"    响应: {r.text[:500]}")
        sys.exit(1)

    data = r.json()
    errors = data.get("errors", [])
    if errors:
        msg = errors[0].get("message", str(errors))
        if "already retweeted" in msg.lower():
            print(f"[!] 已经转发过了")
            return data
        print(f"[✗] 转发失败: {msg}")
        sys.exit(1)

    result = data.get("data", {}).get("create_retweet", {}).get("retweet_results", {}).get("result")
    if result and result.get("rest_id"):
        print(f"[+] 转发成功! tweet_id: {result.get('rest_id')}")
    else:
        print(f"[+] 转发成功!")
    return data


def quote_tweet(client, text: str, tweet_url: str, cfg: dict) -> dict:
    """引用推文（quote tweet）."""
    query_id = cfg["api"]["create_tweet_query_id"]
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/CreateTweet"

    body = {
        "variables": {
            "tweet_text": text,
            "attachment_url": tweet_url,
            "media": {"media_entities": [], "possibly_sensitive": False},
            "semantic_annotation_ids": [],
            "disallowed_reply_options": None,
            "semantic_annotation_options": {"source": "Unknown"},
        },
        "features": cfg["features"],
        "queryId": query_id,
    }

    print(f"[*] 引用推文...")
    human_delay()
    r = client.post(url, json=body)

    if r.status_code != 200:
        print(f"[✗] 引用失败: HTTP {r.status_code}")
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
    print(f"[+] 引用成功!")
    print(f"    https://x.com/{screen_name}/status/{tweet_id}")
    return result


# ── CLI ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="X.com 转发/引用/抄送推文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run repost.py --copy https://x.com/user/status/123        # 抄送（原文+图→原创）
  uv run repost.py --copy https://x.com/user/status/123 -t ""  # 抄送并改写
  uv run repost.py --retweet https://x.com/user/status/123     # 简单转发
  uv run repost.py https://x.com/user/status/123 -t "comment"  # 引用推文
        """,
    )
    parser.add_argument("target", help="推文 URL 或 ID")
    parser.add_argument("--copy", "-c", action="store_true", help="抄送模式：读原文内容当原创发出")
    parser.add_argument("--text", "-t", default=None, help="改写文字（copy 替换原文 / 普通模式引用评论）")
    parser.add_argument("--retweet", action="store_true", help="简单转发（retweet）")
    parser.add_argument("--cookies", help="cookie 文件路径")
    parser.add_argument("--auth-token", help="auth_token cookie")
    parser.add_argument("--ct0", help="ct0 cookie")
    parser.add_argument("--save-cookies", action="store_true", help="持久化 cookie")
    args = parser.parse_args()

    tweet_id = extract_tweet_id(args.target)

    auth_token = args.auth_token
    ct0 = args.ct0
    if args.cookies:
        token, csrf = load_cookies_from_file(args.cookies)
        auth_token = auth_token or token
        ct0 = ct0 or csrf

    try:
        client = get_client(auth_token=auth_token, ct0=ct0)
    except ValueError as e:
        print(f"[✗] {e}")
        sys.exit(1)

    if args.save_cookies and auth_token and ct0:
        save_cookies_to_config(auth_token, ct0)

    cfg = load_config()

    if args.copy:
        print(f"[*] 读取推文 {tweet_id} ...")
        original_text, image_urls = fetch_tweet_content(client, tweet_id, cfg)
        print(f"    原文: {original_text[:120]}{'...' if len(original_text) > 120 else ''}")
        print(f"    图片: {len(image_urls)} 张")

        text = args.text if args.text else original_text
        if len(text) > 280:
            print(f"    [!] 原文过长 ({len(text)} 字)，自动截断至 280 字")
            text = text[:277] + "..."
        if args.text:
            print(f"    改写: {text[:120]}{'...' if len(text) > 120 else ''}")

        paths = download_images(client, image_urls) if image_urls else []
        create_tweet(client, text, cfg, paths or None)
    elif args.text:
        quote_tweet(client, args.text, build_tweet_url(tweet_id), cfg)
    else:
        retweet(client, tweet_id, cfg)


if __name__ == "__main__":
    main()
