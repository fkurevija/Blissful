# 🔎 Wanted Search & Stale Torrent Cleanup

The **Wanted** tab in Blissful's web UI lets you trigger Lidarr searches directly
and clean up torrents that are stuck. Every manual action is **dry-run by
default** — tick *Apply* to actually queue searches or delete queue entries.
A sticky toast in the corner shows progress (phase, elapsed time and counts
during stale cleanup) and finishes with a success or failure message. Only one
search or cleanup may run at a time; the action buttons are disabled while a run
is active (including runs started by the scheduler or another tab).

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

## Wanted / missing albums

1. Click **Load list** (Lidarr's Wanted → Missing list, paginated at 200/page).
2. Tick specific albums, or use **Search all missing**.
3. With *Apply* unchecked you get a preview of what would be searched. With it
   checked, Blissful queues `AlbumSearch` for the selected album IDs, or
   `MissingAlbumSearch` for all missing albums, then waits for the Lidarr command
   to finish. The progress toast stays up during that wait and a second search
   or cleanup is blocked until it completes.

## Stale torrents

Stale records come from the paginated Lidarr Activity Queue. Items whose status
text mentions stalled connections, no eligible files, communication/download
client problems, metadata downloading or generic stalls are listed with
checkboxes.

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
