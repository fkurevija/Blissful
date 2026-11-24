# 🔁 Retry Failed Imports (native)

Blissful can recover Lidarr's unhealthy/failed imports without the old external
bridge script. It reads Lidarr's paginated **Activity Queue**
(`GET /api/v1/queue`) as its only candidate feed — never History,
Wanted/Missing, or qBittorrent directly — downloads only the missing tracks
that Lidarr can actually link, verifies duration and tags, and creates a
`ManualImport` command. The feature is built into the image — no mounted
script or direct access to Lidarr's SQLite database is needed.

## Safety defaults

- **Dry-run by default.** Nothing is downloaded unless `--apply` is passed.
- Unhealthy-download failures only: `stalled with no connections`,
  `no files found are eligible`, `unable to communicate`, `download client`.
- Unsupported compilation failures (`Sequence contains no matching element`,
  `Album match is not close enough`, `Has missing tracks`, etc.) are **reported
  but never downloaded**.
- Unmonitored albums, albums with no missing tracks, and albums already in the
  state file are skipped.
- Every file is checked before linking: it must exist at Lidarr's naming path,
  its duration must be within 10% of Lidarr's expected duration, and it must
  carry title/artist/album-artist/album/track/disc/date tags. Bad files are
  deleted and never linked.

## Usage

Run inside the Blissful container (or from the app directory with Lidarr
configured in `config.json` / `LIDARR_URL` + `LIDARR_API_KEY`):

Inside the container, do **not** pass `--host-prefix /mnt/Storage/Music` —
Lidarr paths are already container-native (`/media/Music`) and that override
makes every file look missing.

```bash
# See what would be attempted (safe)
python Blissful.py --retry-failed-imports

# Limit to one album while testing
python Blissful.py --retry-failed-imports --album-id 1746

# Actually download, verify and import
python Blissful.py --retry-failed-imports --apply

# Clear the "already handled" state
python Blissful.py --retry-failed-imports --reset
```

With Docker Compose:

```bash
docker compose exec blissful python Blissful.py --retry-failed-imports
docker compose exec blissful python Blissful.py --retry-failed-imports --apply
```

The command prints a JSON report: queue total, failures, unsupported items and
per-album status (`skipped`, `imported`, `failed`). Exit code is 1 when any
album failed. Add `--json-only` to suppress startup logs entirely (also done
automatically when stdout is piped), so even merged stdout/stderr is pure JSON.

## State and paths

- State file: `/app/downloads/failed-imports-state.json` (override with
  `FAILED_IMPORTS_STATE` or `--state-path`). An album is recorded only after a
  successful import, so a second run never re-sends it.
- Target paths come from Lidarr's own naming template (`standardTrackFormat`
  or `multiDiscTrackFormat`), never from the torrent title. Vinyl positions
  such as `A1` are preserved; unknown years do not leave empty `()`.
- Lidarr reports durations in milliseconds. Blissful converts them to seconds
  internally for both the download filter and the post-download ffprobe check;
  there is no mixed-unit comparison.
- If Blissful checks files through a host-side mount, set
  `FAILED_IMPORTS_HOST_PREFIX=/mnt/Storage/Music` (or `--host-prefix`) so
  `/media/Music/...` paths are translated for existence checks only.
  `ManualImport` always receives Lidarr's `/media/Music/...` paths.

> Do not bulk-monitor or unmonitor albums as part of this workflow. Chronic
> compilation offenders are separate cleanup.

**Back to:** [Documentation Home](#!/documentation?doc=README)
