# Full User Tweet Exports

Selected full-user tweet exports collected before the Python-only migration.

| File | Account | Rows |
|------|---------|------|
| `hitw93_full.json` | `@HiTw93` | 7632 |
| `waylybaye_full.json` | `@waylybaye` | 7501 |
| `zarazhangrui_tweets.json` | `@zarazhangrui` | 588 |

These files use the normalized tweet shape emitted by `search.py` / `user_tweets.py`.


## VibeLoft sequential collection

The CronBox-backed sequence writes runtime state into this directory:

| Path | Purpose |
|------|---------|
| `latest_collection_status.json` | Per-user status: collection completion time, newest tweet time, oldest tweet time, tweet count, data file, and error/pause reason. |
| `sequence_state.json` | Global sequence cursor: current user, next index, pause state, and X rate-limit reset time. |
| `checkpoints/vibeloft_<handle>.json` | Per-user cursor used to resume an unfinished full-history collection. |
| `vibeloft/<handle>.json` | Collected tweets for one VibeLoft Twitter/X account. |

Useful commands:

```bash
uv run python scripts/twitter_collection_status.py                 # sequence summary
uv run python scripts/twitter_collection_status.py <twitterHandle> # one user
uv run python scripts/collect_vibeloft_twitter_sequence.py         # run sequence now
```
