# 🎵 Blissful - Lidarr Music Downloader

A powerful microservice that automatically downloads missing music tracks for your Lidarr library using YouTube, SoundCloud, and 1000+ other sources.

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![License](https://img.shields.io/badge/license-Unlicense-blue.svg)
![Docker](https://img.shields.io/badge/docker-build%20from%20source-blue?logo=docker)

---

## 🔑 YouTube / YouTube Music 403s — read this first

YouTube and YouTube Music regularly return **HTTP 403** to a bare yt-dlp install. Fixing it needs two things:

1. **A JavaScript runtime** — Deno 2.x, which yt-dlp uses to solve YouTube's JS challenges.
2. **A PO-token provider** — the `blissful-pot` sidecar (`brainicism/bgutil-ytdlp-pot-provider`), which supplies the proof-of-origin tokens YouTube now expects.

**Building from this repository fixes both automatically.** The Dockerfile bakes in Deno 2.x, `yt-dlp>=2026.10.26` and `bgutil-ytdlp-pot-provider>=2.0.2`; `yt-dlp.conf` points at `/usr/local/bin/deno` and `http://blissful-pot:4416`; and `docker-compose.yml` starts the sidecar on the **same Docker network** with no published host port. Just `docker compose up -d --build` — no manual patching, no bind-mounting a patched Python file.

**Using an image built from an older release rather than this fork?** Bootstrap the runtime once into your persistent downloads directory:

```bash
docker cp scripts/setup-ytdlp-runtime.sh blissful:/tmp/setup-ytdlp-runtime.sh
docker exec -u 0 blissful sh /tmp/setup-ytdlp-runtime.sh
```

The script is idempotent and installs Deno + the Python packages under `YT_DLP_HOME` (default `/app/downloads/pylib`) and writes a matching `yt-dlp.conf`. See [docs/getting-started.md](docs/getting-started.md) for details.

**Verify it:**

```bash
curl -s http://localhost:7373/api/health
# With the runtime update this reports:
#   "js_runtime_available": true,
#   "pot_provider_reachable": true
```

> ⚠️ PO tokens **reduce** 403s but do **not guarantee** they never happen. YouTube changes its defenses; keep yt-dlp updated and expect occasional failures to fall through to your other sources.

---

## 📸 Screenshots & Videos

### 🎬 Demo Videos

<table>
  <tr>
    <td width="50%">
      <h4>Blissful Interface Overview</h4>
      <a href="promo/blissful.mp4">
        <img src="https://img.shields.io/badge/▶️-Watch_Demo-blue?style=for-the-badge" alt="Watch Demo">
      </a>
      <p><i>Complete walkthrough of the Blissful interface and features</i></p>
    </td>
    <td width="50%">
      <h4>Lidarr Integration Demo</h4>
      <a href="promo/lidarr.mp4">
        <img src="https://img.shields.io/badge/▶️-Watch_Demo-blue?style=for-the-badge" alt="Watch Demo">
      </a>
      <p><i>See how Blissful integrates seamlessly with Lidarr</i></p>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h4>Drag & Drop Source Priority</h4>
      <a href="promo/draganddrop.mp4">
        <img src="https://img.shields.io/badge/▶️-Watch_Demo-blue?style=for-the-badge" alt="Watch Demo">
      </a>
      <p><i>Easily customize download source priorities</i></p>
    </td>
    <td width="50%">
      <h4>Request System</h4>
      <img src="promo/requestspage.png" alt="Request Page Screenshot" width="100%">
      <p><i>User-friendly request page for music requests</i></p>
    </td>
  </tr>
</table>

---

## ✨ Features

- 🎵 **Automatic Music Downloads** - Download missing tracks from YouTube, SoundCloud, Bandcamp, and more
- 🔄 **Lidarr Integration** - Seamlessly integrates with your existing Lidarr setup
- 🎯 **High Quality Audio** - Configurable quality settings (up to 320kbps)
- 🔌 **Browser Userscript** - One-click downloads directly from Lidarr's web interface
- 👥 **Request System** - Let users request artists via Jellyfin/Emby/Plex authentication
- 🎛️ **Audio Processing** - Normalization, format conversion, metadata embedding
- 🗺️ **Path Mapping** - Support for remote/Docker Lidarr instances
- 🔍 **Source Priorities** - Configure preferred download sources

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- FFmpeg (for audio conversion)
- Lidarr (running and accessible)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/fkurevija/Blissful.git
cd Blissful

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start Blissful
python run.py
```

The application will start on **http://localhost:7373**

---

## ⚙️ Configuration

1. **Open the web interface:** http://localhost:7373
2. **Configure Lidarr:**
   - Go to the **Lidarr** tab
   - Enter your Lidarr URL and API key
   - Click **Test Connection**
3. **Configure Download Settings:**
   - Go to the **Settings** tab
   - Choose your preferred format (MP3, FLAC, etc.)
   - Set quality (128k - 320k)
4. **Save your settings!**

---

## 🎬 Using the Userscript

### Install the Userscript

1. Install a userscript manager:
   - [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Firefox, Edge, Safari)
   - [Greasemonkey](https://www.greasespot.net/) (Firefox)

2. In Blissful, go to the **Userscript** tab
3. Click **Download Userscript**
4. Your userscript manager will open - click **Install**

### Using It

1. Go to any album page in Lidarr
2. You'll see 🎵 icons next to missing tracks
3. Click an icon to download that track
4. Blissful handles the rest automatically!

---

## 🐳 Docker

### Quick Start with Docker Compose (Recommended)

The repository's `docker-compose.yml` builds a **self-contained** image and starts
the `blissful-pot` PO-token sidecar on the same network. This is what fixes
YouTube **and** YouTube Music 403s automatically.

```bash
git clone https://github.com/fkurevija/Blissful.git
cd Blissful/Blissful

# Build from the repo (default) and start both containers
docker compose up -d --build

# View logs
docker compose logs -f blissful
docker compose logs -f blissful-pot
```

The compose file also includes a commented `image:` line for an image you have published from this fork
option if you prefer the published image.

### Using the published image

The published image does **not** ship Deno or the PO-token provider. Bootstrap
them once into your persistent downloads directory:

```bash
# Compose ships the bootstrap script in ./scripts
docker cp scripts/setup-ytdlp-runtime.sh blissful:/tmp/setup-ytdlp-runtime.sh
docker exec -u 0 blissful sh /tmp/setup-ytdlp-runtime.sh

# Confirm the runtime is healthy
curl -s http://localhost:7373/api/health
# js_runtime_available: true, pot_provider_reachable: true
```

The script is safe to re-run: it skips steps already completed and honours
`YT_DLP_HOME`, `POT_PROVIDER_URL`, `DENO_VERSION` and the `FORCE_*` overrides.

### Build from Source (Optional)

```bash
git clone https://github.com/fkurevija/Blissful.git
cd Blissful/Blissful

# The Dockerfile installs ffmpeg, curl/unzip, Deno 2.x, yt-dlp and the
# PO-token provider, and runs as PUID:PGID (default 1000:1000).
docker build -t blissful .
```


---

## 📚 Documentation

Comprehensive documentation is available in the **Docs** tab of the web interface:

- **📋 Overview** - Introduction and features
- **🚀 Getting Started** - Detailed installation guide
- **⚙️ Configuration** - Advanced settings and options
- **🎵 Request System** - Setting up user requests
- **🔧 Troubleshooting** - Common issues and solutions

---

## 🎯 Use Cases

### Home Media Server
Download missing tracks from your music collection automatically.

### Multi-User Setup
Allow family/friends to request artists via Jellyfin/Emby authentication.

### Remote Server
Use path mapping to handle Lidarr running on a different machine or Docker.

---

## 🛠️ Technology Stack

- **Backend:** Flask (Python)
- **Download Engine:** yt-dlp
- **Audio Processing:** FFmpeg
- **Frontend:** HTML5, CSS3, JavaScript
- **Markdown Rendering:** marked.js

---

## 📁 Project Structure

```
Blissful/
├── Blissful.py           # Main application
├── Dockerfile            # Self-contained image (ffmpeg, Deno, yt-dlp, PO provider)
├── docker-compose.yml    # Blissful + blissful-pot sidecar on one network
├── yt-dlp.conf           # Deno + PO-token provider runtime options
├── entrypoint.sh         # Fixes bind-mount ownership, drops to PUID:PGID
├── requirements.txt      # yt-dlp>=2026.10.26, bgutil-ytdlp-pot-provider>=2.0.2
├── scripts/
│   └── setup-ytdlp-runtime.sh  # Bootstrap for the published image
├── extend/               # Modular managers
│   ├── config_manager.py
│   ├── download_manager.py
│   ├── lidarr_client.py
│   ├── auth_manager.py
│   └── ...
├── templates/            # HTML templates
│   └── tabs/            # Tab components
├── static/              # Static assets
│   ├── css/
│   ├── js/
│   └── lidarr-userscript.user.js
├── docs/                # Documentation
├── downloads/           # Download directory
└── config.json         # Configuration file
```

---

## ⚡ API Endpoints

### Download Track
```bash
POST /api/download-track
Content-Type: application/json

{
  "artist": "Metallica",
  "title": "Enter Sandman",
  "album": "Metallica"
}
```

### Download Album
```bash
POST /api/download-album
Content-Type: application/json

{
  "artist": "Metallica",
  "album": "Metallica",
  "tracks": [
    {"title": "Enter Sandman"},
    {"title": "Sad But True"}
  ]
}
```

### Health Check
```bash
GET /api/health
```

With the runtime update the response also includes:

```json
{
  "status": "healthy",
  "ffmpeg_available": true,
  "ytdlp_available": true,
  "js_runtime_available": true,
  "pot_provider_reachable": true
}
```

`js_runtime_available` confirms Deno is callable; `pot_provider_reachable`
confirms Blissful can reach the `blissful-pot` sidecar on the shared network.

---

## 🔧 Configuration File

The `config.json` file stores all your settings:

```json
{
  "lidarr_url": "http://localhost:8686",
  "lidarr_api_key": "your-api-key",
  "output_format": "mp3",
  "quality": "320k",
  "enable_requests": true,
  "source_priorities": [
    "soundcloud",
    "youtube-music",
    "youtube",
    "bandcamp"
  ]
}
```

---

## 🔒 API security

An API token is optional and off by default. Set it under **Tools → API Security**
or with `BLISSFUL_AUTH_TOKEN` before exposing Blissful beyond LAN/VPN. With the
token on, cross-origin API calls need `Authorization: Bearer <token>`; the
bundled UI and `/api/health` stay public. The generated userscript carries the
token automatically. CORS is limited to same-origin plus configured Lidarr /
`BLISSFUL_ALLOWED_ORIGINS` origins, and the credential-returning
`/api/get-api-key` endpoint has been removed. See
[docs/configuration.md](docs/configuration.md#api-security-bliss-8).

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. 🐛 **Report bugs** - Open an issue with details
2. 💡 **Suggest features** - Share your ideas
3. 📝 **Improve documentation** - Help make it better
4. 🔧 **Submit pull requests** - Fix bugs or add features

---

## 🙏 Credits

**Maintained by:** [fkurevija](https://github.com/fkurevija)<br>
**Documentation:** this fork's `docs/` directory

### Built With:
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Download engine
- [FFmpeg](https://ffmpeg.org/) - Audio conversion
- [Lidarr](https://lidarr.audio/) - Music library management

---

## 📞 Support

Need help?

- 📖 **Documentation** - Check the Docs tab in the web interface
- 🐛 **Bug Reports** - [Open an issue](https://github.com/fkurevija/Blissful/issues)
- 💬 **Questions** - [Open an issue in this fork](https://github.com/fkurevija/Blissful/issues)

---

## 📄 License

This project is released into the **public domain** using [The Unlicense](https://unlicense.org/).

You can copy, modify, distribute and perform the work, even for commercial purposes, all without asking permission.

See the [UNLICENSE](UNLICENSE) file for details.

**TL;DR:** Do whatever you want with this code. No warranty, no liability, no strings attached.

