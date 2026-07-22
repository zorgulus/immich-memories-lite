# immich-memories-lite

A small, fast "on this day" memory video generator for [Immich](https://immich.app), built as a lightweight alternative to heavier third-party generators.

## Why

Existing memory-video generators for Immich can take **60–90+ minutes** per video on modest hardware, and impose a fixed look (title screens, large on-screen dates, generated background music). This project trades those features for speed and simplicity:

- Pulls "on this day" assets directly from Immich's built-in `/api/memories` endpoint — no need to reimplement date-matching logic.
- Assembles a slideshow with `ffmpeg`, either as hard cuts or crossfades.
- Optional small, unobtrusive year label instead of a title screen.
- Uploads the result back into Immich as a normal asset.
- On a 4-core, GPU-less NAS: **~2 minutes for an 18-clip / 46s 720p video**, vs. ~90 minutes with a full-featured generator on the same hardware.

Trade-off: this does one thing (a single daily "on this day" slideshow). It doesn't do face-based memories, weekly collages, trip highlights, or AI-generated music. If you want those, look at a full-featured generator instead.

## How it works

1. `generate.py` queries `GET /api/memories`, filters entries with `type: on_this_day` matching today's date, and picks up to `MAX_PER_YEAR` assets per year found (capped at `MAX_ITEMS` total).
2. Each asset is downloaded and rendered into a fixed-length clip via `ffmpeg` (scaled/padded to a common resolution, optional year overlay).
3. Clips are joined either with the `concat` demuxer (hard cuts, default) or `xfade` (crossfade, set `TRANSITION=fade`).
4. The final video is uploaded to Immich via `POST /api/assets`.
5. `purge.py` (run separately, e.g. daily after generation) deletes previously-generated videos older than `RETENTION_DAYS` — **unless you've marked them as a favorite in the Immich app**, in which case they're kept indefinitely and dropped from tracking.

## Requirements

- Immich **v3+** (needs the `/api/memories` endpoint).
- Docker.
- An Immich API key for the account whose library you want to pull memories from.

## Setup

```bash
git clone https://github.com/zorgulus/immich-memories-lite.git
cd immich-memories-lite
docker build -t immich-memories-lite:latest .
```

Run once manually to test:

```bash
docker run --rm --network host \
  -e IMMICH_API_KEY=your-api-key \
  -e IMMICH_URL=http://localhost:2283 \
  -v /path/to/output:/app/output \
  immich-memories-lite:latest
```

For daily automation with notifications and purging, see `daily.sh.example` — adapt the paths, ntfy topic, and API key handling to your setup, then run it from cron.

### Native deep links (optional)

The Immich mobile app only opens links on the `my.immich.app` domain natively — a link to your own domain/IP opens in the browser instead, even with a valid certificate. To get a tap-to-open notification regardless of your server's domain, use the app's custom URL scheme instead:

```
immich://asset?id=<assetId>
```

This is what `daily.sh.example` uses with an ntfy `Click:` header.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `IMMICH_API_KEY` | *(required)* | API key for the target Immich account |
| `IMMICH_URL` | `http://localhost:2283` | Immich server base URL |
| `OUTPUT_DIR` | `/app/output` | Where the generated video is saved (also mount this) |
| `CLIP_DURATION` | `3.5` | Seconds per photo/video clip |
| `TRANSITION` | `cut` | `cut` (hard cut) or `fade` (crossfade) |
| `XFADE_DURATION` | `1.0` | Crossfade length in seconds (only used when `TRANSITION=fade`) |
| `MAX_ITEMS` | `18` | Max number of media items per generated video |
| `MAX_PER_YEAR` | `2` | Max items pulled from any single year |
| `WIDTH` / `HEIGHT` | `1280` / `720` | Output resolution |
| `SHOW_YEAR` | `true` | Show a small year label in the corner of each clip |
| `RETENTION_DAYS` | `7` | (`purge.py` only) Days to keep a generated video before deleting it, unless favorited |
| `STATE_FILE` | `/state/generated-assets.log` | (`purge.py` only) Tracking file of `date asset_id` pairs |

## License

MIT
