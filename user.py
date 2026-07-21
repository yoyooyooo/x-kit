#!/usr/bin/env python3
"""X.com 用户账号信息查询.

用法:
    # 通过用户名
    uv run user.py HiTw93
    uv run user.py @HiTw93
    uv run user.py https://x.com/HiTw93

    # JSON 输出
    uv run user.py HiTw93 --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from utils.session_manager import get_client, load_cookies_from_file, save_cookies_to_config

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config" / "settings.json"

USER_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def extract_screen_name(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)", raw)
    if m:
        return m[1]
    return raw.lstrip("@")


def fetch_user(client, screen_name: str, cfg: dict) -> dict:
    query_id = cfg["api"].get("user_by_screenname_query_id", "IGgvgiOx4QZndDHuD3x9TQ")
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/UserByScreenName"

    params = {
        "variables": json.dumps({"screen_name": screen_name, "withGrokTranslatedBio": True}),
        "features": json.dumps(USER_FEATURES),
        "fieldToggles": json.dumps({"withPayments": False, "withAuxiliaryUserLabels": True}),
    }

    r = client.get(url, params=params)
    if r.status_code != 200:
        print(f"[✗] 请求失败: HTTP {r.status_code}")
        print(f"    响应: {r.text[:300]}")
        sys.exit(1)

    data = r.json()
    result = data.get("data", {}).get("user", {}).get("result")
    if not result:
        print(f"[✗] 用户不存在或无权访问: {screen_name}")
        if data.get("errors"):
            print(f"    {data['errors'][0].get('message', '')}")
        sys.exit(1)
    return result


def format_user(result: dict) -> str:
    core = result.get("core", {})
    legacy = result.get("legacy", {})

    name = core.get("name", "?")
    screen_name = core.get("screen_name", "?")
    created_at = core.get("created_at", "")
    rest_id = result.get("rest_id", "?")
    blue = result.get("is_blue_verified", False)
    professional = result.get("professional", {}).get("professional_type", "")
    location = result.get("location", {}).get("location", "")

    lines = []
    lines.append("=" * 60)
    lines.append(f"  {name}  @{screen_name}  {'✓蓝V' if blue else ''}")
    lines.append("=" * 60)
    lines.append(f"  用户 ID  : {rest_id}")
    lines.append(f"  注册时间 : {created_at}")
    if location:
        lines.append(f"  位置     : {location}")
    if professional:
        lines.append(f"  账号类型 : {professional}")
    lines.append(f"  简介     : {legacy.get('description', '')}")
    url_entities = legacy.get("entities", {}).get("url", {}).get("urls", [])
    if url_entities:
        lines.append(f"  链接     : {url_entities[0].get('expanded_url', '')}")
    lines.append("=" * 60)
    lines.append(f"  粉丝     : {legacy.get('followers_count', 0):,}")
    lines.append(f"  关注     : {legacy.get('friends_count', 0):,}")
    lines.append(f"  发帖     : {legacy.get('statuses_count', 0):,}")
    lines.append(f"  喜欢     : {legacy.get('favourites_count', 0):,}")
    lines.append(f"  媒体     : {legacy.get('media_count', 0):,}")
    lines.append(f"  被列表   : {legacy.get('listed_count', 0):,}")
    lines.append("=" * 60)
    lines.append(f"  受保护   : {'是' if legacy.get('protected') else '否'}")
    pinned = legacy.get("pinned_tweet_ids_str", [])
    if pinned:
        lines.append(f"  置顶推文 : {pinned[0]}")
    lines.append(f"  头像     : {result.get('avatar', {}).get('image_url', '')}")
    if legacy.get("profile_banner_url"):
        lines.append(f"  横幅     : {legacy.get('profile_banner_url')}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="X.com 用户账号信息查询")
    parser.add_argument("user", help="用户名 / @用户名 / 主页 URL")
    parser.add_argument("--json", "-j", action="store_true", help="输出原始 JSON")
    parser.add_argument("--cookies", help="cookie 文件路径")
    parser.add_argument("--auth-token", help="auth_token cookie")
    parser.add_argument("--ct0", help="ct0 cookie")
    parser.add_argument("--save-cookies", action="store_true", help="持久化 cookie")
    args = parser.parse_args()

    screen_name = extract_screen_name(args.user)

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
    result = fetch_user(client, screen_name, cfg)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_user(result))


if __name__ == "__main__":
    main()
