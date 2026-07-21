#!/usr/bin/env python3
"""Read latest VibeLoft Twitter/X collection status from repo-local JSON."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "data" / "user_tweets" / "latest_collection_status.json"
STATE_FILE = ROOT / "data" / "user_tweets" / "sequence_state.json"
LOCAL_TZ_NAME = "Asia/Shanghai"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)


def utc_iso_to_local(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(LOCAL_TZ).isoformat()
    except ValueError:
        return "-"


def format_time(value: str | None) -> str:
    if not value:
        return "-"
    if value.endswith("Z"):
        return f"{value} / {utc_iso_to_local(value)} {LOCAL_TZ_NAME}"
    return value


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return value.strip().lstrip("@").lower()


def print_user(handle: str, row: dict) -> None:
    print(f"@{row.get('handle') or handle}")
    print(f"  status                  : {row.get('status', '-')}")
    print(f"  collected/completed at  : {format_time(row.get('completed_at') or row.get('updated_at'))}")
    print(f"  latest tweet created at : {format_time(row.get('latest_tweet_created_at'))}")
    print(f"  latest tweet id         : {row.get('latest_tweet_id') or '-'}")
    print(f"  oldest tweet created at : {format_time(row.get('oldest_tweet_created_at'))}")
    print(f"  tweet count             : {row.get('tweet_count', '-')}")
    print(f"  new tweets last run     : {row.get('new_tweets_last_run', '-')}")
    print(f"  data file               : {row.get('data_file') or '-'}")
    if row.get("error"):
        print(f"  error                   : {row.get('error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show latest per-user Twitter/X collection status.")
    parser.add_argument("handle", nargs="?", help="Twitter/X handle, with or without @.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    args = parser.parse_args()

    status = load_json(STATUS_FILE, {"users": {}})
    state = load_json(STATE_FILE, {})
    users = status.get("users") or {}

    if args.handle:
        key = slug(args.handle)
        row = users.get(key)
        if args.json:
            print(json.dumps(row or {}, ensure_ascii=False, indent=2))
            return 0 if row else 1
        if not row:
            print(f"No collection status found for @{key}.")
            return 1
        print_user(key, row)
        return 0

    if args.json:
        print(json.dumps({"state": state, "status": status}, ensure_ascii=False, indent=2))
        return 0

    print("Sequence state")
    print(f"  paused      : {state.get('paused', False)}")
    print(f"  next index  : {state.get('next_index', 0)} / {state.get('account_count', '-')}")
    print(f"  current     : {state.get('current_handle') or '-'}")
    print(f"  reset at    : {format_time(state.get('rate_limit_reset_at'))}")
    print(f"  updated at  : {format_time(state.get('updated_at'))}")
    print("")
    print(f"Users with status: {len(users)}")
    for key, row in sorted(users.items(), key=lambda item: item[0])[:20]:
        print(
            f"  @{row.get('handle') or key:<16} "
            f"{row.get('status', '-'):<18} "
            f"tweets={row.get('tweet_count', '-')} "
            f"latest={format_time(row.get('latest_tweet_created_at'))}"
        )
    if len(users) > 20:
        print(f"  ... {len(users) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
