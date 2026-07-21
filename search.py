#!/usr/bin/env python3
"""X.com 搜索采集（SearchTimeline）.

用 search 接口绕过用户时间线 ~3200 条上限，可抓取更早的历史推文。
通过 from:user + 日期分段（until/since）翻页，理论上能覆盖全部历史。

用法:
    # 搜索某用户全部历史推文（日期自动分段，绕过 3200 上限）
    uv run search.py --from HiTw93 --all -o hitw93_full.json

    # 关键词搜索
    uv run search.py "Mole for Mac" --pages 3

    # 指定时间范围
    uv run search.py --from HiTw93 --since 2022-01-01 --until 2023-01-01

    # 热门 / 最新
    uv run search.py "AI coding" --product Top
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from user_tweets import _parse_tweet  # 复用推文解析
from utils.session_manager import get_client, load_cookies_from_file

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config" / "settings.json"

SEARCH_FEATURES = {
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


def search_page(
    client, raw_query: str, cfg: dict, cursor: str | None, product: str
) -> tuple[list[dict], str | None]:
    """搜索一页，返回 (推文列表, 下一页 cursor)。自动处理限速 429。"""
    query_id = cfg["api"].get("search_timeline_query_id", "-TFXKoMnMTKdEXcCn-eahw")
    url = f"{cfg['api']['base_url']}/graphql/{query_id}/SearchTimeline"

    variables = {
        "rawQuery": raw_query,
        "count": 20,
        "querySource": "typed_query",
        "product": product,
        "withGrokTranslatedBio": False,
        "withQuickPromoteEligibilityTweetFields": False,
    }
    if cursor:
        variables["cursor"] = cursor

    params = {
        "variables": json.dumps(variables),
        "features": json.dumps(SEARCH_FEATURES),
    }

    for attempt in range(8):
        try:
            r = client.get(url, params=params)
        except httpx.HTTPError as e:
            # 网络瞬断（RemoteProtocolError / 超时 / 连接重置）→ 退避重试
            backoff = min(2 ** attempt, 60)
            print(f"    [↻] 网络错误（{type(e).__name__}），{backoff} 秒后重试 ...")
            time.sleep(backoff)
            continue

        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset", 0))
            wait = max(reset - int(time.time()), 1) + 2 if reset else 60
            print(f"    [⏳] 限速 429，等待 {wait} 秒 ...")
            time.sleep(wait)
            continue

        if r.status_code in (500, 502, 503, 504):
            # 服务端瞬时错误 → 退避重试
            backoff = min(2 ** attempt, 60)
            print(f"    [↻] 服务端 {r.status_code}，{backoff} 秒后重试 ...")
            time.sleep(backoff)
            continue

        if r.status_code in (403, 404):
            # 通常是 x-client-transaction-id 瞬时失效/缺失导致 → 重置后重试
            from utils.transaction_id import reset as reset_tid

            backoff = min(2 ** attempt, 30)
            print(f"    [↻] HTTP {r.status_code}（疑似 transaction-id 失效），重置后 {backoff} 秒重试 ...")
            reset_tid()
            time.sleep(backoff)
            continue

        if r.status_code != 200:
            print(f"[✗] 请求失败: HTTP {r.status_code} - {r.text[:200]}")
            sys.exit(1)

        remaining = int(r.headers.get("x-rate-limit-remaining", 99))
        if remaining <= 2:
            reset = int(r.headers.get("x-rate-limit-reset", 0))
            wait = max(reset - int(time.time()), 1) + 2 if reset else 60
            print(f"    [⏳] 配额剩 {remaining}，主动等 {wait} 秒 ...")
            time.sleep(wait)
        break
    else:
        print(f"[✗] 多次重试仍失败，放弃本页")
        sys.exit(1)

    data = r.json()
    instructions = (
        data.get("data", {})
        .get("search_by_raw_query", {})
        .get("search_timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )

    tweets = []
    next_cursor = None
    for instr in instructions:
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


def _oldest_date(tweets: list[dict]) -> str | None:
    """从推文列表中找最早的日期（YYYY-MM-DD）."""
    dates = []
    for t in tweets:
        try:
            dt = datetime.strptime(t["created_at"], "%a %b %d %H:%M:%S %z %Y")
            dates.append(dt)
        except (ValueError, KeyError):
            continue
    if not dates:
        return None
    return min(dates).strftime("%Y-%m-%d")


def collect(client, base_query: str, cfg: dict, product: str,
            since: str | None, until: str | None,
            all_mode: bool, max_pages: int, delay: float,
            checkpoint_path: Path | None = None,
            resume: bool = True) -> list[dict]:
    """采集主逻辑。all_mode 时用日期分段绕过单次搜索上限。

    checkpoint_path: 每段结束后把进度（已采推文 + 当前 until）写盘，
                     崩溃后可从断点恢复，避免长任务前功尽弃。
    """
    all_tweets = []
    seen_ids = set()
    cur_until = until
    prev_oldest = None

    # 断点恢复
    if all_mode and resume and checkpoint_path and checkpoint_path.exists():
        ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if ckpt.get("base_query") == base_query and ckpt.get("cur_until"):
            all_tweets = ckpt["tweets"]
            seen_ids = {t["id"] for t in all_tweets}
            cur_until = ckpt["cur_until"]
            prev_oldest = ckpt.get("prev_oldest")
            print(f"[*] 发现断点，从 until:{cur_until} 续采（已有 {len(all_tweets)} 条）")

    # --all 模式必须有初始 until，否则首段从"今天"开始，
    # oldest+1=明天 无法排除任何推文 → 第二段重复 → 卡死。
    # 设为明天保证分段确定性。
    if all_mode and not cur_until:
        cur_until = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    def _save_ckpt():
        if all_mode and checkpoint_path:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(
                    {"base_query": base_query, "cur_until": cur_until,
                     "prev_oldest": prev_oldest, "tweets": all_tweets},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    segment = 0
    while True:
        segment += 1
        # 构造本段查询
        q = base_query
        if since:
            q += f" since:{since}"
        if cur_until:
            q += f" until:{cur_until}"

        if all_mode:
            print(f"[*] 第 {segment} 段: {q!r}")

        cursor = None
        page = 0
        seg_oldest = None
        seg_new_total = 0
        seg_tweet_total = 0
        while page < (10_000 if all_mode else max_pages):
            page += 1
            tweets, cursor = search_page(client, q, cfg, cursor, product)
            seg_tweet_total += len(tweets)
            new = [t for t in tweets if t["id"] not in seen_ids]
            for t in new:
                seen_ids.add(t["id"])
            all_tweets.extend(new)
            seg_new_total += len(new)
            d = _oldest_date(tweets)
            if d:
                seg_oldest = d
            print(f"    第 {page} 页 +{len(new)} 新（累计 {len(all_tweets)}）{('到 ' + d) if d else ''}")

            if not cursor or not tweets:
                break
            if all_mode and not new:
                break
            time.sleep(delay)

        if not all_mode:
            break

        # 本段完全没有推文 → 该日期之前没有内容，结束
        if seg_tweet_total == 0 or not seg_oldest:
            print(f"    该时间段之前已无推文，结束")
            break

        # 日期推进：until 是"严格早于该日"。
        # 默认用 oldest+1（含 oldest 当天，重叠靠去重消除）。
        # 若最早日期连续两段不变（卡在某天的大推文簇上，cursor 翻不完），
        # 强制把 until 设到 oldest 当天以跳过，突破卡点。
        if seg_oldest == prev_oldest:
            cur_until = seg_oldest  # 强制跳过当天，突破卡点
            print(f"    [!] 卡在 {seg_oldest}，强制跳过当天继续")
        else:
            cur_until = (datetime.strptime(seg_oldest, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        prev_oldest = seg_oldest
        _save_ckpt()  # 每段存盘，崩溃可恢复
        time.sleep(delay)

    # 正常完成，清除断点
    if all_mode and checkpoint_path and checkpoint_path.exists():
        checkpoint_path.unlink()

    return all_tweets


def main():
    parser = argparse.ArgumentParser(
        description="X.com 搜索采集（SearchTimeline，可绕过 3200 上限）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run search.py --from HiTw93 --all -o full.json   # 某用户全部历史（日期分段）
  uv run search.py "Mole for Mac" --pages 3           # 关键词搜索
  uv run search.py --from HiTw93 --since 2022-01-01 --until 2023-01-01
  uv run search.py "AI" --product Top                 # 热门结果

说明:
  --all 用日期分段（until 逐段前移）绕过单次搜索的翻页上限，
  理论上能覆盖账号全部历史（含回复），比 user_tweets.py 的 3200 上限更全。
        """,
    )
    parser.add_argument("query", nargs="?", default="", help="搜索关键词")
    parser.add_argument("--from", dest="from_user", help="限定某用户（等价 from:user）")
    parser.add_argument("--since", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--until", help="截止日期 YYYY-MM-DD")
    parser.add_argument("--product", default="Latest", choices=["Latest", "Top", "Media"], help="结果类型（默认 Latest 按时间）")
    parser.add_argument("--all", "-a", action="store_true", help="日期分段抓全部历史（绕过上限）")
    parser.add_argument("--pages", "-p", type=int, default=1, help="非 --all 模式翻页数")
    parser.add_argument("--out", "-o", help="保存为 JSON 文件")
    parser.add_argument("--delay", type=float, default=2.0, help="请求间隔秒数")
    parser.add_argument("--no-resume", action="store_true", help="忽略已有断点，从头开始")
    parser.add_argument("--cookies", help="cookie 文件路径")
    parser.add_argument("--auth-token", help="auth_token cookie")
    parser.add_argument("--ct0", help="ct0 cookie")
    args = parser.parse_args()

    # 构造基础查询
    parts = []
    if args.from_user:
        parts.append(f"from:{args.from_user.lstrip('@')}")
    if args.query:
        parts.append(args.query)
    base_query = " ".join(parts).strip()
    if not base_query:
        parser.error("需要提供搜索关键词或 --from 用户名")

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

    # 断点文件路径（基于查询内容）
    ckpt_dir = SCRIPT_DIR / "data" / "checkpoints"
    safe_q = "".join(c if c.isalnum() else "_" for c in base_query)[:60]
    ckpt_path = ckpt_dir / f"search_{safe_q}.json"

    print(f"[*] 搜索: {base_query!r} (product={args.product})")
    tweets = collect(
        client, base_query, cfg, args.product,
        args.since, args.until, args.all, args.pages, args.delay,
        checkpoint_path=ckpt_path, resume=not args.no_resume,
    )

    print(f"\n[+] 共采集 {len(tweets)} 条推文")

    out_path = args.out
    if args.all and not out_path:
        safe = (args.from_user or args.query or "search").replace(" ", "_")
        out_path = f"search_{safe}.json"

    if out_path:
        Path(out_path).write_text(
            json.dumps(tweets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[+] 已保存到 {out_path}")
    else:
        for t in tweets[:50]:
            text_preview = t["text"].replace("\n", " ")[:80]
            date = t["created_at"][:16] if t.get("created_at") else ""
            print(f"  [{t['favorite_count']:>5}♥] {date} {text_preview}")
        if len(tweets) > 50:
            print(f"  ... 还有 {len(tweets) - 50} 条（用 -o 保存全部）")


if __name__ == "__main__":
    main()
