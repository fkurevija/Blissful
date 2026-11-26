# ⚙️ Configuration Guide

Complete guide to configuring Blissful for your needs.

---

## 🎯 Configuration Overview

Blissful has several configuration tabs:

| Tab | Purpose |
|-----|---------|
| **Lidarr** | Connect to your Lidarr instance |
| **Downloads** | Configure download settings |
| **Paths** | Set up path mapping |
| **Sources** | Manage download sources |
| **Requests** | Configure user request system |
| **Userscript** | Download browser extension |
| **Tools** | System utilities and tests |

---

## 🔗 Lidarr Configuration

### **Basic Settings**

```json
{
  "lidarr_url": "http://localhost:8686",
  "lidarr_api_key": "your-api-key-here"
}
```

#### **Finding Your API Key**

1. Open Lidarr web interface
2. Go to: Settings → General
3. Scroll to **Security** section
4. Copy the **API Key**

#### **Testing Connection**

Click **Test Connection** to verify:
- ✅ Lidarr is reachable
- ✅ API key is valid
- ✅ Version is compatible

### **Advanced Settings**

#### **Root Folders**

Lidarr root folders are detected automatically:
- Click **Get Root Folders**
- Select primary folder for downloads
- Used for path construction

#### **Quality Profile**

Default quality profile for new artists:
- Select from dropdown
- Used when adding via requests
- Can be changed later in Lidarr

---

## ⬇️ Download Configuration

### **Output Format**

Choose audio format for downloads:

| Format | Quality | Compatibility | File Size |
|--------|---------|---------------|-----------|
| **MP3** | Good | Excellent | Medium |
| **FLAC** | Lossless | Good | Large |
| **M4A** | Good | Excellent | Medium |
| **OGG** | Good | Fair | Small |
| **OPUS** | Excellent | Fair | Small |

**Recommendation:** MP3 for compatibility, FLAC for audiophiles

### **Quality/Bitrate**

| Bitrate | Quality | Use Case |
|---------|---------|----------|
| **128k** | Acceptable | Mobile, streaming |
| **192k** | Good | General listening |
| **256k** | Very Good | Home audio |
| **320k** | Excellent | High-quality audio |
| **V0** | Variable | Smart compression |

**Recommendation:** 320k for best quality, 192k for balanced

### **Download Location**

```
Default: ./downloads/
```

Options:
- **Relative path:** `downloads/` (relative to Blissful)
- **Absolute path:** `/home/user/music/` (full path)

Files are organized as:
```
downloads/
  └── Artist Name/
      └── Album Name/
          ├── 01 - Track Title.mp3
          ├── 02 - Track Title.mp3
          └── ...
```

### **Conversion Settings**

#### **Sample Rate**
- **44100 Hz** - CD quality (recommended)
- **48000 Hz** - Studio quality
- **96000 Hz** - High-resolution

#### **Channels**
- **Stereo (2)** - Standard (recommended)
- **Mono (1)** - Save space
- **Surround** - Multi-channel audio

---

## 🗺️ Path Mapping

Path mapping translates local paths to remote paths.

### **When to Use Path Mapping**

Use path mapping when:
- ✅ Blissful runs on different machine than Lidarr
- ✅ Using Docker with bind mounts
- ✅ Network shares with different mount points
- ✅ Windows ↔ Linux path differences

### **Example Scenarios**

#### **Scenario 1: Docker**

**Blissful sees:**
```
/app/downloads/Artist/Album/track.mp3
```

**Lidarr sees:**
```
/music/Artist/Album/track.mp3
```

**Mapping:**
```
Blissful Path: /app/downloads
Lidarr Path: /music
```

#### **Scenario 2: Network Share**

**Blissful (Windows):**
```
\\server\music\Artist\Album\track.mp3
```

**Lidarr (Linux):**
```
/mnt/music/Artist/Album/track.mp3
```

**Mapping:**
```
Blissful Path: \\server\music
Lidarr Path: /mnt/music
```

#### **Scenario 3: Remote Server**

**Blissful (Local):**
```
D:\Blissful\downloads\Artist\Album\track.mp3
```

**Lidarr (Remote):**
```
/home/user/media/music/Artist/Album/track.mp3
```

**Mapping:**
```
Blissful Path: D:\Blissful\downloads
Lidarr Path: /home/user/media/music
```

### **Adding Path Mappings**

1. Go to **Paths** tab
2. Click **Add Mapping**
3. Enter:
   - **Blissful Path:** Path on Blissful server
   - **Lidarr Path:** Path on Lidarr server
4. Click **Save**

### **Testing Path Mapping**

```
Test Input: D:\Blissful\downloads\Metallica\Metallica\01 - Enter Sandman.mp3
Expected Output: /music/Metallica/Metallica/01 - Enter Sandman.mp3
```

---

## 🌐 Source Configuration

### **Source Priorities**

Control which sources are tried first:

1. **Drag and drop** to reorder
2. **Top sources** are tried first
3. **Disabled sources** are skipped

### **Source Categories**

| Category | Examples | Quality | Speed |
|----------|----------|---------|-------|
| **Music Services** | Deezer, SoundCloud | Excellent | Fast |
| **Video Platforms** | YouTube, Vimeo | Good | Fast |
| **Podcasts** | Apple Podcasts | Good | Medium |
| **Archives** | Internet Archive | Variable | Slow |
| **Free Music** | Jamendo, Free Music Archive | Good | Fast |

### **Recommended Source Order**

1. **SoundCloud** - High quality, reliable
2. **YouTube Music** - Large library, good quality
3. **YouTube** - Fallback, always available
4. **Bandcamp** - High quality, artist-friendly

### **Metadata Providers**

Metadata providers never serve audio. Each has its own checkbox under
**Sources → Metadata Providers** and is off by default.

| Provider | What it does | Credentials |
| --- | --- | --- |
| Spotify | Refines the pre-download query with artist/title/album/year. | Client ID + secret |
| Discogs | Looks up the release in the Discogs database and adds its year/edition to the query. | Personal access token, or consumer key + secret |
| AcoustID | After download, fingerprints the file with Chromaprint (`fpcalc`) and rejects it when the identified recording does not match. | Application key (`client`); user key required from 1 Jan 2027 |
| MusicBrainz | Resolves the exact recording, release and year to refine the query. No account needed. | None (identifying User-Agent required; 1 request/second) |

> **AcoustID has no text search.** Its API only looks up audio fingerprints, so
> it cannot refine a query before a file exists. With its checkbox enabled,
> Blissful fingerprints each otherwise-accepted candidate; a low score or a
> mismatched artist/title deletes that candidate and the next source is tried.
> Artwork-only differences are ignored. Spotify, Discogs and MusicBrainz are
> the providers that refine the search query.

- `fpcalc` comes from `libchromaprint-tools`, baked into the published image.
  For local installs, install that package or set `acoustid_fpcalc_path`.
- `acoustid_min_score` (default `0.75`) sets the score threshold; the identified
  artist and title must also match the expected track.
- Keys can be entered in the UI or supplied via environment variables:
  `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `DISCOGS_TOKEN`,
  `DISCOGS_CONSUMER_KEY`, `DISCOGS_CONSUMER_SECRET`, `ACOUSTID_API_KEY`,
  `ACOUSTID_USER_KEY`, `MUSICBRAINZ_METADATA_ENABLED`. Environment values win
  over saved config, and all
  secrets are masked in `/api/config`.
- Providers are independent and optional: enable only the ones you have keys for.

### **Search Depth**

`search_results_per_source` (default `3`, allowed range 1-10) controls how many
candidates each searchable source returns — `ytsearch3:` instead of `ytsearch1:`,
and likewise for SoundCloud and Deezer. Raising it gives Blissful more candidates
to try before giving up, at the cost of slower searches and more yt-dlp requests.
It can also be set with `SEARCH_RESULTS_PER_SOURCE`; the environment value wins.


### **Filtering Sources**

- **By Category:** Show only music services
- **By Tier:** Filter by reliability (1-4)
- **By Search:** Find specific sources

---

## 🎵 Request System Configuration

### **Enabling Requests**

1. Go to **Requests** tab
2. Check **Enable Music Request System**
3. Configure authentication method(s)
4. Save settings

### **Jellyfin Authentication**

#### **Step 1: Get API Key**

```bash
# In Jellyfin web interface:
Dashboard → Advanced → API Keys → New API Key
Name: "Blissful"
Copy the generated key
```

#### **Step 2: Configure Blissful**

```json
{
  "enable_jellyfin": true,
  "jellyfin_url": "https://jellyfin.example.com",
  "jellyfin_api_key": "your-jellyfin-api-key"
}
```

#### **Step 3: Test**

1. Open: `http://localhost:7373/request`
2. Click "Login with Jellyfin"
3. Enter any Jellyfin user credentials
4. Should authenticate successfully ✅

### **Emby Authentication**

Same as Jellyfin:

```json
{
  "enable_emby": true,
  "emby_url": "https://emby.example.com",
  "emby_api_key": "your-emby-api-key"
}
```

### **Plex Authentication**

Simpler setup (uses Plex.tv):

```json
{
  "enable_plex": true
}
```

No API key needed! Users authenticate directly with Plex.

### **Request Settings**

#### **Auto-Monitor**

```json
{
  "auto_monitor_requests": false
}
```

- **false** - Artists added unmonitored (admin approval)
- **true** - Artists automatically monitored (auto-download)

#### **Request Notifications**

Configure webhooks for new requests:

```json
{
  "webhook_url": "https://discord.com/api/webhooks/..."
}
```

---

## 🔧 Advanced Configuration

### **Environment Variables**

Override settings with environment variables:

```bash
export BLISSFUL_PORT=7373
export BLISSFUL_HOST=0.0.0.0
export BLISSFUL_DEBUG=false        # keep debug OFF in production
export LIDARR_URL=http://localhost:8686
export LIDARR_API_KEY=your-key
```

#### **Container / yt-dlp runtime variables**

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `7373` | Web/API port |
| `PUID` / `PGID` | `1000` / `1000` | Runtime UID/GID; entrypoint chowns `/app/config` and `/app/downloads` then drops privileges |
| `TZ` | — | Container timezone (compose sets `America/Toronto`) |
| `PYTHONPATH` | `/app/downloads/pylib` | Makes the persistent yt-dlp + PO-provider install importable |
| `YT_DLP_HOME` | `/app/downloads` | Persistent runtime dir (Deno, `pylib`, `yt-dlp.conf`) |
| `DENO_PATH` | `/usr/local/bin/deno` | Deno location baked into the repo image; the published-image bootstrap uses `/app/downloads/deno` |
| `POT_PROVIDER_URL` | `http://blissful-pot:4416` | In-network PO-token sidecar URL (no host port) |
| `FAILED_IMPORTS_STATE` | `/app/downloads/failed-imports-state.json` | State file for native failed-import recovery |
| `FAILED_IMPORTS_HOST_PREFIX` | _(unset)_ | Host prefix for file checks, e.g. `/mnt/Storage/Music` |
| `WANTED_SEARCH_ENABLED` | `false` | Enables the Wanted tab search endpoints |
| `STALE_CLEANUP_ENABLED` | `false` | Enables the scheduled stale-torrent cleanup worker |
| `PREFER_BLISSFUL_FOR_STALE` | `true` | Use Blissful's gap-fill instead of Lidarr `AlbumSearch` for stale items |
| `GAPFILL_JOB_TIMEOUT_MINUTES` | `15` | How long to wait for a multi-track gap-fill job before moving on |
| `STALE_CLEANUP_REMOVE_FROM_CLIENT` | `true` | Let Lidarr remove the torrent and its data from qBittorrent when deleting a stale queue item |
| `WANTED_SEARCH_TIMEOUT_MINUTES` | `10` | How long to wait for a Lidarr search command to finish |
| `PREFER_BLISSFUL_FOR_WANTED` | `true` | After Lidarr search, gap-fill still-missing albums via Blissful |

#### **YouTube / YouTube Music 403 configuration**

`yt-dlp.conf` (mounted read-only at `/app/downloads/yt-dlp.conf` in Compose)
carries the two options that stop 403s:

```
--js-runtimes deno:/usr/local/bin/deno
--extractor-args youtubepot-bgutilhttp:base_url=http://blissful-pot:4416
```

Building from the repo installs Deno 2.x and both Python packages into the
image, so **YouTube and YouTube Music 403s are fixed automatically**. The
`blissful-pot` service must be on the **same Docker network** as Blissful —
it has no published host port and is addressed by service name.

The fork's published image (`fkurevija/blissful:latest`) already contains the
runtime. Only older images need `scripts/setup-ytdlp-runtime.sh` once; it writes
the equivalent config using your `POT_PROVIDER_URL` and the local Deno path. All values are overridable: edit the host `yt-dlp.conf`, pass
`--config-location`, or set the environment variables above.

Verify with `curl -s http://localhost:7373/api/health` — the runtime update
adds `js_runtime_available` and `pot_provider_reachable` booleans. PO tokens
**reduce** but do **not guarantee** avoiding 403s; keep fallback sources on.

### **config.json**

Manual configuration file:

```json
{
  "lidarr_url": "http://localhost:8686",
  "lidarr_api_key": "your-api-key",
  "output_format": "mp3",
  "quality": "320k",
  "download_path": "./downloads/",
  "enable_requests": true,
  "enable_jellyfin": true,
  "jellyfin_url": "https://jellyfin.example.com",
  "jellyfin_api_key": "jellyfin-api-key",
  "lidarr_path_mapping": {
    "/app/downloads": "/music"
  },
  "source_priorities": [
    {"name": "YouTube Music", "search": "music.youtube.com", "enabled": true},
    {"name": "SoundCloud", "search": "soundcloud.com", "enabled": true},
    {"name": "YouTube", "search": "youtube.com", "enabled": true},
    {"name": "Bandcamp", "search": "bandcamp.com", "enabled": true}
  ]
}
```

### **Docker Environment**

```yaml
# docker-compose.yml (excerpt)
services:
  blissful:
    build: .
    depends_on:
      - blissful-pot
    environment:
      - TZ=America/Toronto
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
      - PYTHONPATH=/app/downloads/pylib
      - YT_DLP_HOME=/app/downloads
      - POT_PROVIDER_URL=http://blissful-pot:4416
      - LIDARR_URL=http://lidarr:8686
    volumes:
      - ./config.json:/app/config.json
      - ./downloads:/app/downloads
      - ./yt-dlp.conf:/app/downloads/yt-dlp.conf:ro
      - /mnt/Storage/Music:/media/Music
    networks:
      - blissful-network

  blissful-pot:  # no host port; fixes YouTube + YouTube Music 403s
    image: brainicism/bgutil-ytdlp-pot-provider:latest
    networks:
      - blissful-network
```

---

## 🔍 Configuration Best Practices

### **Security**

✅ **Do:**
- Keep API keys secret
- Use environment variables for sensitive data
- Don't commit `config.json` to version control
- Rotate API keys regularly

❌ **Don't:**
- Share API keys publicly
- Use default passwords
- Expose Blissful to internet without auth

### **Performance**

✅ **Do:**
- Use SSD for downloads
- Enable only needed sources
- Set appropriate quality for your needs
- Use path mapping efficiently

❌ **Don't:**
- Enable all sources
- Use unnecessarily high quality
- Download to slow network drives

### **Organization**

✅ **Do:**
- Use consistent path mapping
- Let Lidarr handle organization
- Keep config backed up
- Document custom settings

❌ **Don't:**
- Manually move downloaded files
- Mix different quality settings
- Change settings frequently

---

## 🎓 Configuration Templates

### **Home Server (Basic)**

```json
{
  "lidarr_url": "http://localhost:8686",
  "lidarr_api_key": "your-key",
  "output_format": "mp3",
  "quality": "320k"
}
```

### **Multi-User (Requests)**

```json
{
  "enable_requests": true,
  "enable_jellyfin": true,
  "jellyfin_url": "https://jellyfin.local",
  "jellyfin_api_key": "your-key",
  "auto_monitor_requests": false
}
```

### **Remote Server (Docker)**

```json
{
  "lidarr_url": "http://lidarr:8686",
  "lidarr_path_mapping": {
    "/app/downloads": "/music"
  }
}
```

### **Audiophile (High Quality)**

```json
{
  "output_format": "flac",
  "quality": "best",
  "sample_rate": 96000
}
```

---

## 📝 Configuration Checklist

Before going live:

- [ ] Lidarr connection tested
- [ ] Download location configured
- [ ] Path mapping set up (if needed)
- [ ] Source priorities configured
- [ ] Request system enabled (if needed)
- [ ] Authentication tested (if using requests)
- [ ] Userscript installed
- [ ] Test download completed successfully

---

**Next:** [Request System Guide](#!/documentation?doc=request-system)


---

## API security (BLISS-8)

Blissful has an **optional API token**, off by default. Set `auth_token` under
**Tools → API Security**, or supply `BLISSFUL_AUTH_TOKEN` in the container
environment (the environment value wins). When enabled:

- Every `/api/` route except `/api/health` requires `Authorization: Bearer <token>`
  (or `X-Blissful-Token`) for **cross-origin** requests.
- Requests from the bundled web UI (same origin) work without a token; a page
  on another site cannot call Blissful's API. The login-free health check stays
  public for Docker/uptime monitors.
- The generated userscript carries the token, so reinstall it after changing
  the token. Set `BLISSFUL_ALLOWED_ORIGINS` (comma-separated origins) if your
  Lidarr URL is on a different host and the userscript needs CORS access.
- `/api/get-api-key` has been removed; the Lidarr "test connection" and path
  detection calls resolve saved keys server-side and never return them.

The Flask debug server is also disabled (`debug=False`). If you expose Blissful
beyond a LAN/VPN, enable the token and use a reverse proxy with HTTPS.

## Download jobs (BLISS-11/13)

`POST /api/download-album` now enqueues a job instead of blocking the request.
Track `GET /api/jobs` and retry with `POST /api/jobs/<id>/retry`; Lidarr can also
POST to `/api/lidarr/webhook`. Jobs persist in `config/jobs.json`, are deduped by
album, and a single background worker drains them. Set `enable_jobs: false` in
config.json to restore synchronous album downloads.
