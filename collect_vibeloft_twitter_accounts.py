#!/usr/bin/env python3
"""Collect public Twitter/X accounts recorded by VibeLoft profiles."""

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "vibeloft_twitter_accounts.json"
API_BASE = "https://api.vibeloft.ai/api/v1"
SITE_BASE = "https://vibeloft.ai"
PAGE_SIZE = 100

URL_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^\s<>'\")]+", re.I)
HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
TWITTER_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com"}
RESERVED_PATHS = {
    "compose",
    "explore",
    "hashtag",
    "home",
    "i",
    "intent",
    "messages",
    "notifications",
    "search",
    "settings",
    "share",
}


def build_client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        timeout=30,
        follow_redirects=True,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": SITE_BASE,
            "Referer": f"{SITE_BASE}/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        },
    )


def require_success(response: httpx.Response) -> dict:
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"VibeLoft API error {payload.get('code')}: {payload.get('message')}")
    return payload


def fetch_user_page(client: httpx.Client, page: int) -> tuple[list[dict], dict]:
    payload = require_success(
        client.post("/user/list", json={"page": page, "page_size": PAGE_SIZE})
    )
    data = payload.get("data") or {}
    return data.get("items") or [], data.get("pagination") or {}


def iter_users(client: httpx.Client, delay: float) -> tuple[list[dict], dict]:
    users: list[dict] = []
    page = 1
    last_pagination: dict = {}

    while True:
        items, pagination = fetch_user_page(client, page)
        last_pagination = pagination
        users.extend(items)

        if not items or not pagination.get("has_more"):
            break

        page += 1
        if delay > 0:
            time.sleep(delay)

    return users, last_pagination


def normalize_twitter_ref(raw: str) -> tuple[str, str] | None:
    value = str(raw or "").strip().rstrip(".,;")
    if not value:
        return None

    if value.startswith("@"):
        handle = value[1:].strip()
        if HANDLE_RE.fullmatch(handle):
            return handle, f"https://x.com/{handle}"
        return None

    if "://" not in value and ("x.com/" in value or "twitter.com/" in value):
        value = f"https://{value}"

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    host = parsed.netloc.lower().removeprefix("www.")
    if host not in TWITTER_HOSTS:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None

    handle = path_parts[0].lstrip("@")
    if handle.lower() == "intent":
        query = parse_qs(parsed.query)
        handle = (query.get("screen_name") or [""])[0].lstrip("@")

    if handle.lower() in RESERVED_PATHS or not HANDLE_RE.fullmatch(handle):
        return None

    return handle, f"https://x.com/{handle}"


def iter_twitter_sources(user: dict) -> list[dict]:
    sources: list[dict] = []

    for index, link in enumerate(user.get("social_links") or []):
        if not isinstance(link, dict):
            continue
        raw_url = str(link.get("url") or "").strip()
        platform = str(link.get("platform") or "").strip().lower()
        if platform in {"twitter", "x"} or normalize_twitter_ref(raw_url):
            sources.append(
                {
                    "field": f"social_links[{index}]",
                    "raw_url": raw_url,
                    "raw_link": link,
                }
            )

    website = str(user.get("website") or "").strip()
    if normalize_twitter_ref(website):
        sources.append({"field": "website", "raw_url": website})

    bio = str(user.get("bio") or "")
    for match in URL_RE.findall(bio):
        sources.append({"field": "bio", "raw_url": match})

    return sources


def collect_accounts(users: list[dict]) -> list[dict]:
    accounts: dict[tuple[str, str], dict] = {}

    for user in users:
        for source in iter_twitter_sources(user):
            normalized = normalize_twitter_ref(source.get("raw_url", ""))
            if not normalized:
                continue

            handle, canonical_url = normalized
            key = (str(user.get("id") or ""), handle.lower())
            if key in accounts:
                accounts[key]["sources"].append(source)
                continue

            accounts[key] = {
                "handle": handle,
                "url": canonical_url,
                "vibeloft_profile": {
                    "id": user.get("id"),
                    "username": user.get("username"),
                    "nickname": user.get("nickname"),
                    "url": f"{SITE_BASE}/profile/{user.get('username')}",
                    "is_verified": user.get("is_verified"),
                    "followers_count": user.get("followers_count"),
                    "following_count": user.get("following_count"),
                    "posts_count": user.get("posts_count"),
                    "product_count": user.get("product_count"),
                    "primary_product_name": user.get("primary_product_name"),
                    "location": user.get("location"),
                    "created_at": user.get("created_at"),
                    "updated_at": user.get("updated_at"),
                },
                "sources": [source],
            }

    return sorted(
        accounts.values(),
        key=lambda item: (
            str(item["vibeloft_profile"].get("username") or "").lower(),
            item["handle"].lower(),
        ),
    )


def build_output(users: list[dict], pagination: dict) -> dict:
    accounts = collect_accounts(users)
    unique_handles = {account["handle"].lower() for account in accounts}

    return {
        "source": SITE_BASE,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "collection_method": {
            "api_base": API_BASE,
            "profile_list_endpoint": "POST /api/v1/user/list",
            "page_size": PAGE_SIZE,
            "note": "Public VibeLoft profile list; Twitter/X links are extracted from public profile fields.",
        },
        "stats": {
            "profiles_scanned": len(users),
            "api_total_profiles": pagination.get("total"),
            "accounts": len(accounts),
            "unique_handles": len(unique_handles),
        },
        "accounts": accounts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Twitter/X accounts from public VibeLoft profiles."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path, default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between pages.")
    args = parser.parse_args()

    try:
        with build_client() as client:
            users, pagination = iter_users(client, delay=args.delay)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"[x] Failed to collect VibeLoft profiles: {exc}", file=sys.stderr)
        sys.exit(1)

    output = build_output(users, pagination)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")

    stats = output["stats"]
    print(
        "Collected "
        f"{stats['accounts']} Twitter/X links "
        f"({stats['unique_handles']} unique handles) "
        f"from {stats['profiles_scanned']} VibeLoft profiles."
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
