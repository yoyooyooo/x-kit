#!/usr/bin/env python3
"""X.com 用户推文列表采集.

用法:
    # 抓取某用户最近推文（默认 20 条）
    uv run user_tweets.py HiTw93

    # 抓取多页（翻 3 页 ≈ 60 条）
    uv run user_tweets.py HiTw93 --pages 3

    # 保存为 JSON
    uv run user_tweets.py HiTw93 --pages 5 --out tweets.json

    # 直接用 user_id（跳过解析步骤）
    uv run user_tweets.py --user-id 1521688129559613440
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from user import USER_FEATURES, fetch_user
from utils.session_manager import get_client, load_cookies_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config" / "settings.json"

TIMELINE_FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "rweb_cashtags_composer_attachment_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "rweb_conversational_replies_downvote_enabled": False,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": True,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def extract_screen_name(raw: str) -> str:
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)", raw)
    if m:
        return m[1]
    return raw.lstrip("@")


def _parse_tweet(result: dict) -> dict | None:
    """从 tweet_results.result 提取关键字段."""
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})
    legacy = result.get("legacy", {})
    if not legacy:
        return None

    # note_tweet（长推文）优先取完整文本
    note = (
        result.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
        .get("text")
    )
    text = note or legacy.get("full_text", "")

    media = [
        {
            "type": m.get("type"),
            "url": m.get("media_url_https") or m.get("expanded_url"),
        }
        for m in legacy.get("extended_entities", {}).get("media", [])
    ]

    return {
        "id": result.get("rest_id", legacy.get("id_str", "")),
        "text": text,
        "created_at": legacy.get("created_at", ""),
        "favorite_count": legacy.get("favorite_count", 0),
        "retweet_count": legacy.get("retweet_count", 0),
        "reply_count": legacy.get("reply_count", 0),
        "quote_count": legacy.get("quote_count", 0),
        "bookmark_count": legacy.get("bookmark_count", 0),
        "views": result.get("views", {}).get("count", ""),
        "lang": legacy.get("lang", ""),
        "is_retweet": "retweeted_status_result" in legacy,
        "is_quote": legacy.get("is_quote_status", False),
        "media": media,
        "url": f"https://x.com/i/status/{result.get('rest_id', '')}",
    }


def fetch_page(client, user_id: str, cfg: dict, cursor: str | None) -> tuple[list[dict], str | None]:
    """抓取一页推文，返回 (推文列表, 下一页 cursor)。自动处理限速 429。"""
    query_id = cfg["api"].get("user_tweets_query_id", "PNd0vlufvrcIwrAnBYKE9g")
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/UserTweets"

    variables = {
        "userId": user_id,
        "count": 20,
        "includePromotedContent": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
    }
    if cursor:
        variables["cursor"] = cursor

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(TIMELINE_FEATURES),
        "fieldToggles": json.dumps({"withArticlePlainText": False}),
    }

    # 限速重试循环
    for attempt in range(5):
        r = client.get(url, params=params)

        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset", 0))
            wait = max(reset - int(time.time()), 1) + 2 if reset else 60
            print(f"    [⏳] 撞到限速 429，等待 {wait} 秒到窗口重置 ...")
            time.sleep(wait)
            continue

        if r.status_code != 200:
            print(f"[✗] 请求失败: HTTP {r.status_code} - {r.text[:200]}")
            sys.exit(1)

        # 主动限速：剩余配额低时提前等待
        remaining = int(r.headers.get("x-rate-limit-remaining", 99))
        if remaining <= 2:
            reset = int(r.headers.get("x-rate-limit-reset", 0))
            wait = max(reset - int(time.time()), 1) + 2 if reset else 60
            print(f"    [⏳] 配额仅剩 {remaining}，主动等待 {wait} 秒避免触发 429 ...")
            time.sleep(wait)

        break
    else:
        print(f"[✗] 多次限速重试失败")
        sys.exit(1)

    data = r.json()
    instructions = (
        data.get("data", {})
        .get("user", {})
        .get("result", {})
        .get("timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )

    tweets = []
    next_cursor = None
    for instr in instructions:
        # 置顶推文（单独 entry）
        if instr.get("type") == "TimelinePinEntry":
            entry = instr.get("entry", {})
            result = (
                entry.get("content", {})
                .get("itemContent", {})
                .get("tweet_results", {})
                .get("result", {})
            )
            t = _parse_tweet(result)
            if t:
                t["pinned"] = True
                tweets.append(t)
        # 普通推文列表
        for entry in instr.get("entries", []):
            entry_id = entry.get("entryId", "")
            if entry_id.startswith("tweet-"):
                result = (
                    entry.get("content", {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result", {})
                )
                t = _parse_tweet(result)
                if t:
                    tweets.append(t)
            elif entry_id.startswith("cursor-bottom-"):
                next_cursor = entry.get("content", {}).get("value")

    return tweets, next_cursor


CHECKPOINT_DIR = SCRIPT_DIR / "data" / "checkpoints"


def _checkpoint_path(user_id: str) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"user_{user_id}.json"


def load_checkpoint(user_id: str) -> dict | None:
    p = _checkpoint_path(user_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_checkpoint(user_id: str, tweets: list[dict], cursor: str | None, page: int) -> None:
    p = _checkpoint_path(user_id)
    p.write_text(
        json.dumps(
            {"user_id": user_id, "cursor": cursor, "page": page, "tweets": tweets},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def clear_checkpoint(user_id: str) -> None:
    p = _checkpoint_path(user_id)
    if p.exists():
        p.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="X.com 用户推文列表采集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run user_tweets.py HiTw93 --pages 3            # 抓 3 页
  uv run user_tweets.py HiTw93 --all -o all.json    # 抓全部（自动限速+断点续采）
  uv run user_tweets.py HiTw93 --all                # 中断后再跑同命令即自动续采

注意:
  - X 用户时间线有 ~3,200 条历史上限，--all 抓到上限即停
  - UserTweets 限速 50/15分钟，--all 会自动等限速窗口
        """,
    )
    parser.add_argument("user", nargs="?", help="用户名 / @用户名 / 主页 URL")
    parser.add_argument("--user-id", help="直接指定用户数字 ID（跳过解析）")
    parser.add_argument("--pages", "-p", type=int, default=1, help="翻页数（默认 1 页 ≈ 20 条）")
    parser.add_argument("--all", "-a", action="store_true", help="抓取全部推文（到时间线上限），自动限速+断点续采")
    parser.add_argument("--out", "-o", help="保存为 JSON 文件")
    parser.add_argument("--delay", type=float, default=2.0, help="翻页间隔秒数（默认 2）")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，从头开始")
    parser.add_argument("--cookies", help="cookie 文件路径")
    parser.add_argument("--auth-token", help="auth_token cookie")
    parser.add_argument("--ct0", help="ct0 cookie")
    args = parser.parse_args()

    if not args.user and not args.user_id:
        parser.error("需要提供用户名或 --user-id")

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

    cfg = load_config()

    # 解析 user_id
    if args.user_id:
        user_id = args.user_id
        display = f"id={user_id}"
    else:
        screen_name = extract_screen_name(args.user)
        print(f"[*] 解析用户 @{screen_name} ...")
        user_result = fetch_user(client, screen_name, cfg)
        user_id = user_result.get("rest_id")
        display = f"@{screen_name} (id={user_id})"
        print(f"    -> {user_id}")

    # 翻页采集
    all_tweets = []
    seen_ids = set()
    cursor = None
    start_page = 0

    # 断点续采（仅 --all 模式）
    if args.all and not args.no_resume:
        ckpt = load_checkpoint(user_id)
        if ckpt and ckpt.get("cursor"):
            all_tweets = ckpt["tweets"]
            seen_ids = {t["id"] for t in all_tweets}
            cursor = ckpt["cursor"]
            start_page = ckpt["page"]
            print(f"[*] 发现断点，从第 {start_page + 1} 页续采（已有 {len(all_tweets)} 条）")

    max_pages = 10_000 if args.all else args.pages
    page = start_page
    while page < max_pages:
        label = f"{page + 1}" if args.all else f"{page + 1}/{args.pages}"
        print(f"[*] 抓取第 {label} 页 ...")
        tweets, cursor = fetch_page(client, user_id, cfg, cursor)

        # 去重
        new = [t for t in tweets if t["id"] not in seen_ids]
        for t in new:
            seen_ids.add(t["id"])
        all_tweets.extend(new)
        print(f"    +{len(new)} 条新（累计 {len(all_tweets)}）")

        page += 1

        if not cursor:
            print(f"    已到末尾（时间线上限或无更多）")
            break
        # --all 模式无新增连续 2 页则停（已到时间线尽头）
        if args.all and not new:
            print(f"    连续无新增，停止")
            break

        # 保存断点
        if args.all:
            save_checkpoint(user_id, all_tweets, cursor, page)

        if page < max_pages:
            time.sleep(args.delay)

    print(f"\n[+] 共采集 {len(all_tweets)} 条推文（{display}）")

    if args.all:
        clear_checkpoint(user_id)

    out_path = args.out
    if args.all and not out_path:
        out_path = f"tweets_{user_id}.json"

    if out_path:
        Path(out_path).write_text(
            json.dumps(all_tweets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[+] 已保存到 {out_path}")
    else:
        # 终端预览
        for t in all_tweets:
            flag = "📌" if t.get("pinned") else "  "
            text_preview = t["text"].replace("\n", " ")[:80]
            print(f"{flag} [{t['favorite_count']:>5}♥] {text_preview}")


if __name__ == "__main__":
    main()
