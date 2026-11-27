# 🔎 Wanted Search & Stale Torrent Cleanup

The **Wanted** tab in Blissful's web UI lets you trigger Lidarr searches directly
and clean up torrents that are stuck. Every manual action is **dry-run by
default** — tick *Apply* to actually queue searches or delete queue entries.
A sticky toast in the corner shows a short progress summary and finishes with a
success or failure message plus a **View downloads** link. Full queue details,
history and retry controls (retry appears only on failed rows) live on the new
**Downloads** tab, whose columns can be sorted. Failed jobs record a reason per
track (including duration-guard rejections and source attempts); hover the Detail
cell for the full list. Older failed jobs show a note that per-track reasons were
not recorded. Table header rows use a solid background. Job history is stored in `/app/downloads/jobs.json`, so it survives
container recreation.
one search or cleanup may run at a time; the action buttons are disabled while a
run is active (including runs started by the scheduler or another tab).

## Controls

- **Enable wanted search controls** — gates the search endpoints. Off by default.
- **Enable scheduled stale-torrent cleanup** — off by default. When on, Blissful
  periodically searches stale torrents and removes each queue entry only after
  Lidarr reports its album fully imported.
- **Use Blissful's yt-dlp gap-fill** — on by default (`prefer_blissful_for_stale`).
  Stale torrents are stuck *because* Lidarr search failed, so cleanup uses the same
  download → tag → place → `ManualImport` engine as `--retry-failed-imports`.
  Turn it off to restore the older `AlbumSearch` flow.
- **Cleanup interval (hours)** — default 6; **Import wait per album (minutes)** —
  default 10. Changes to the interval are picked up on restart.

### Progress during a search

Each source can inspect up to `search_results_per_source` candidates (default 3).
While yt-dlp walks that list, the active status reports
`download_candidate_current` / `download_candidate_total`, so the toast and job
details keep moving instead of appearing frozen between source attempts.
Only the selected candidate is downloaded — the search page is inspected once,
then that result is processed, so a depth of 10 no longer fetches 10 videos.

### Already-imported albums

Cleanup records an album as imported as soon as gap-fill succeeds, before the
Lidarr queue entry is deleted. A later run also skips any album with a
successful album job in the last 24 hours, so a slow Lidarr library scan cannot
cause the same album to be downloaded twice. The stale queue row is still
removed in that case — skipping the re-download does not skip Lidarr cleanup.
Queue entries are deleted only after import is confirmed.

## Wanted / missing albums

1. Click **Load list** (Lidarr's Wanted → Missing list, paginated at 200/page).
2. Tick specific albums, or use **Search all missing**.
3. With *Apply* unchecked you get a preview of what would be searched. With it
   checked, Blissful first triggers Lidarr's `MissingAlbumSearch` (or
   `AlbumSearch` for a selection) and waits for it to finish. Any album that
   still has missing tracks is then handed to Blissful's own yt-dlp bridge —
   Lidarr tries torrents first, Blissful fills what it could not find. The
   progress toast stays up through both phases and a second search or cleanup
   is blocked until it completes. The search itself is recorded as a job on the
   **Downloads** tab; clicking **View downloads** only switches tabs and never
   cancels the request. Set `PREFER_BLISSFUL_FOR_WANTED=false` to skip the Blissful
   fallback.

## Stale torrents

> **Source of truth:** Blissful only ever picks up stale torrents from
> Lidarr's **Activity → Queue** (`GET /api/v1/queue`, paginated 200/page).
> It does **not** read Lidarr's History, the Wanted/Missing list, or
> qBittorrent directly for stale-torrent detection. Only records that are
> live queue downloads (they carry Lidarr's queue `id` and `downloadId`)
> are considered; a record must also have status text mentioning stalled
> connections, no eligible files, communication/download client problems,
> metadata downloading or a generic stall. Each eligible download appears
> once, deduplicated by `downloadId`.

Items whose status text matches one of those unhealthy patterns are listed
with checkboxes.

With *Apply* checked, for each selected stale item Blissful:

1. Reads the album's tracks and skips it if nothing is missing or it was already
   handled (state file).
2. Queues `AlbumSearch` for that album and waits for the Lidarr command.
3. Polls the album's tracks until every track has `hasFile: true`, bounded by the
   configured wait.
4. Only then deletes the original queue entry with `deleteFiles=false` and
   `addImportExclusion=false`, and records the album in state so it is never
   re-searched.

If the gap-fill or import does not complete, the queue entry is **kept** with
the reported reason and the run continues to the next album. Nothing is deleted
from disk by this feature.

With **Let Lidarr remove the torrent from the download client** enabled (default),
deleting the queue item also asks Lidarr to remove the torrent and its data from
qBittorrent, exactly as deleting the item in Lidarr's UI does; `skipRedownload`
is set so Lidarr does not immediately re-search it. Turn it off to remove only
the Lidarr queue entry and leave qBittorrent untouched.

## CLI equivalents

```bash
python Blissful.py --wanted-search                 # preview search all missing
python Blissful.py --wanted-search --apply         # actually queue the search
python Blissful.py --stale-cleanup                 # dry-run stale cleanup
python Blissful.py --stale-cleanup --apply         # search + delete after import
python Blissful.py --wanted-search --json-only    # pure JSON report for automation
```

Logs go to stderr and are suppressed automatically when stdout is piped; use
`--json-only` to force this even when attached to a terminal.

State lives in `/app/downloads/wanted-search-state.json`; use the **Reset state**
button to clear it after you have manually resolved an album.

**Back to:** [Documentation Home](#!/documentation?doc=README)
