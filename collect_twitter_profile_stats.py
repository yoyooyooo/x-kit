#!/usr/bin/env python3
"""Collect Twitter/X profile tweet and follower counts from public profile HTML."""

import argparse
import csv
import html
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "data" / "vibeloft_twitter_account_stats.json"
DEFAULT_JSON_OUTPUT = SCRIPT_DIR / "data" / "vibeloft_twitter_x_stats.json"
DEFAULT_CSV_OUTPUT = SCRIPT_DIR / "data" / "vibeloft_twitter_x_stats.csv"


def parse_compact_number(value: str) -> int | None:
    value = html.unescape(str(value or "")).strip().replace(",", "")
    match = re.fullmatch(r"([\d.]+)\s*([KMB]?)", value, re.I)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(number * multiplier)


def extract_stats_from_html(body: str, handle: str) -> dict:
    quoted = re.escape(handle)
    profile_pattern = re.compile(
        rf"\{{[^{{}}]{{0,5000}}screenName:\"{quoted}\"[^{{}}]{{0,2000}}\}}",
        re.I | re.S,
    )
    match = profile_pattern.search(body)

    if match:
        block = match.group(0)
        followers_match = re.search(r"followers:(\d+)", block)
        following_match = re.search(r"following:(\d+)", block)
        tweets_match = re.search(r"tweets:(\d+)", block)
        name_match = re.search(r'name:"([^"]*)"', block)
        rest_id_match = re.search(r'restId:"([^"]*)"', block)
        if followers_match and tweets_match:
            return {
                "ok": True,
                "source": "x_ssr_hydration",
                "twitter_name": html.unescape(name_match.group(1)) if name_match else "",
                "twitter_rest_id": rest_id_match.group(1) if rest_id_match else "",
                "tweets_count": int(tweets_match.group(1)),
                "followers_count": int(followers_match.group(1)),
                "following_count": int(following_match.group(1)) if following_match else None,
            }

    # Fallback to rendered HTML and meta tags. This is less precise for compact values.
    posts_match = re.search(
        r'<meta name="twitter:label1" content="Posts"[^>]*>'
        r'\s*<meta name="twitter:data1" content="([^"]+)"',
        body,
        re.S,
    )
    followers_match = re.search(
        rf'href="/{quoted}/(?:verified_)?followers"[^>]*>.*?font-bold">([^<]+)</div>'
        r".*?>Followers</div>",
        body,
        re.I | re.S,
    )
    if posts_match and followers_match:
        tweets = parse_compact_number(posts_match.group(1))
        followers = parse_compact_number(followers_match.group(1))
        if tweets is not None and followers is not None:
            return {
                "ok": True,
                "source": "x_rendered_html",
                "twitter_name": "",
                "twitter_rest_id": "",
                "tweets_count": tweets,
                "followers_count": followers,
                "following_count": None,
            }

    title_match = re.search(r"<title>(.*?)</title>", body, re.S)
    return {
        "ok": False,
        "error": "stats_not_found",
        "page_title": html.unescape(title_match.group(1).strip()) if title_match else "",
    }


def fetch_profile_stats(client: httpx.Client, handle: str) -> dict:
    response = client.get(f"https://x.com/{handle}")
    if response.status_code != 200:
        return {"ok": False, "error": f"http_{response.status_code}"}
    return extract_stats_from_html(response.text, handle)


def load_input_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    return payload.get("rows") or []


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "twitter_handle",
        "twitter_url",
        "twitter_name",
        "twitter_rest_id",
        "tweets_count",
        "followers_count",
        "following_count",
        "vibeloft_username",
        "vibeloft_nickname",
        "vibeloft_profile_url",
        "ok",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Twitter/X tweet and follower counts for VibeLoft Twitter users."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    source_rows = load_input_rows(args.input)
    rows: list[dict] = []

    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        },
    ) as client:
        for index, source in enumerate(source_rows, 1):
            handle = source["twitter_handle"]
            print(f"[{index}/{len(source_rows)}] @{handle}", file=sys.stderr)
            stats = fetch_profile_stats(client, handle)
            rows.append(
                {
                    **source,
                    "twitter_name": stats.get("twitter_name", ""),
                    "twitter_rest_id": stats.get("twitter_rest_id", ""),
                    "tweets_count": stats.get("tweets_count"),
                    "followers_count": stats.get("followers_count"),
                    "following_count": stats.get("following_count"),
                    "ok": stats.get("ok", False),
                    "source": stats.get("source", ""),
                    "error": stats.get("error", ""),
                    "page_title": stats.get("page_title", ""),
                }
            )
            if args.delay > 0 and index < len(source_rows):
                time.sleep(args.delay)

    ok_rows = [row for row in rows if row.get("ok")]
    rows.sort(
        key=lambda row: (
            -(row.get("followers_count") or -1),
            -(row.get("tweets_count") or -1),
            str(row.get("twitter_handle") or "").lower(),
        )
    )

    output = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "https://x.com/{handle}",
        "input_file": str(args.input),
        "stats": {
            "requested": len(source_rows),
            "ok": len(ok_rows),
            "failed": len(source_rows) - len(ok_rows),
            "total_tweets_count": sum(row.get("tweets_count") or 0 for row in ok_rows),
            "total_followers_count": sum(row.get("followers_count") or 0 for row in ok_rows),
        },
        "rows": rows,
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    write_csv(args.csv_output, rows)

    print(json.dumps(output["stats"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.json_output}")
    print(f"Wrote {args.csv_output}")


if __name__ == "__main__":
    main()
