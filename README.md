# x-kit

Pure-Python protocol tools and research notes for the X.com web client.

This repository now uses the Python protocol implementation as the source of truth. The previous Bun/TypeScript automation and checked-in tweet data have been removed.

## Capabilities

- Read tweet details through `TweetDetail`.
- Resolve user profiles through `UserByScreenName`.
- Collect user timelines through `UserTweets`.
- Collect search results through `SearchTimeline`, including date-window pagination for deeper history.
- Create tweets with optional media upload.
- Retweet, quote tweet, or copy public tweet text/media into a new tweet.
- Automatically inject `x-client-transaction-id` for `/i/api/` requests.

## Setup

```bash
uv sync
cp config/settings.example.json config/settings.json
```

Edit `config/settings.json` and fill:

- `auth.auth_token`
- `auth.ct0`

Both values come from an authenticated browser session on `x.com`. `config/settings.json` is ignored by Git.

You can also pass credentials at runtime:

```bash
uv run user.py HiTw93 --auth-token "$AUTH_TOKEN" --ct0 "$CT0"
```

## Commands

```bash
# User profile
uv run user.py HiTw93

# Recent user tweets
uv run user_tweets.py HiTw93 --pages 3 -o tweets.json

# Fuller history via search date windows
uv run search.py --from HiTw93 --all -o hitw93_full.json

# Tweet detail
uv run read.py https://x.com/i/status/2062521510938779729

# Create a text tweet
uv run tweet.py "hello world"

# Create a tweet with media
uv run tweet.py "hello with image" --image ./photo.png

# Retweet or quote
uv run repost.py --retweet https://x.com/user/status/123
uv run repost.py https://x.com/user/status/123 -t "comment"

# Collect public Twitter/X accounts recorded by VibeLoft
uv run collect_vibeloft_twitter_accounts.py

# Collect Twitter/X-side post and follower counts for those accounts
uv run collect_twitter_profile_stats.py
```

## Notes

- `ANALYSIS.md` records the reverse-engineering findings and current GraphQL operation IDs.
- `data/vibeloft_twitter_accounts.json` records public VibeLoft profiles that expose Twitter/X links.
- `data/vibeloft_twitter_x_stats.json` records Twitter/X-side post and follower counts for the VibeLoft Twitter cohort.
- Query IDs and feature flags are deployment artifacts. Refresh them if X.com changes its web bundle.
- Write operations can trigger account-level limits and risk controls. Use deliberate delays and avoid automation bursts.
- Do not commit cookies, captured private payloads, or personal datasets.
