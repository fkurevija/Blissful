# 🚀 Getting Started with Blissful

This guide will help you install, configure, and start using Blissful in just a few minutes.

---

## 📋 Prerequisites

Before you begin, make sure you have:

✅ **Python 3.8+** installed  
✅ **Lidarr** running and accessible  
✅ **FFmpeg** installed (for audio conversion)  
✅ **Internet connection**

---

## 🔑 Important: YouTube / YouTube Music 403s

A plain yt-dlp install increasingly gets **HTTP 403** from YouTube and YouTube
Music. Two pieces are required to avoid this:

- **Deno 2.x** — the JavaScript runtime yt-dlp uses for YouTube's JS challenges.
- **`blissful-pot`** — the `brainicism/bgutil-ytdlp-pot-provider` sidecar that
  serves PO tokens. It runs on the **same Docker network** as Blissful and is
  reached at `http://blissful-pot:4416`; it publishes **no host port**.

**If you build from this repository, you don't have to do anything.** The
Dockerfile installs Deno 2.x, `yt-dlp>=2026.10.26` and
`bgutil-ytdlp-pot-provider>=2.0.2`, `yt-dlp.conf` points at
`/usr/local/bin/deno` and the sidecar, and `docker-compose.yml` starts the
sidecar automatically. This fixes YouTube **and** YouTube Music 403s out of
the box.

**If you use an image built from an older release rather than this fork**, bootstrap
once after the container has started:

```bash
docker cp scripts/setup-ytdlp-runtime.sh blissful:/tmp/setup-ytdlp-runtime.sh
docker exec -u 0 blissful sh /tmp/setup-ytdlp-runtime.sh
```

It installs Deno into `/app/downloads/deno`, the Python packages into
`/app/downloads/pylib`, and writes `/app/downloads/yt-dlp.conf` pointing at
those paths and the `POT_PROVIDER_URL` (default
`http://blissful-pot:4416`). It is idempotent and safe to re-run.

**Verify the runtime:**

```bash
curl -s http://localhost:7373/api/health
# js_runtime_available: true
# pot_provider_reachable: true
```

These fields are added by the runtime update. If either is `false`, check that
both containers share the `blissful-network` and that `yt-dlp.conf` is mounted
read-only at `/app/downloads/yt-dlp.conf`.

> ⚠️ PO tokens **reduce** 403s but do **not guarantee** they never occur.
> Keep yt-dlp updated and leave fallback sources enabled.

---

## 🔧 Installation

### **Method 1: Standard Installation**

```bash
# 1. Clone the repository
git clone https://github.com/fkurevija/Blissful.git
cd Blissful

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install FFmpeg (if not already installed)
# Windows: Download from https://ffmpeg.org/download.html
# Linux: sudo apt install ffmpeg
# macOS: brew install ffmpeg

# 4. Start Blissful
python run.py
```

### **Method 2: Docker Installation (Recommended)**

**Default: build from the repository (self-contained, fixes 403s automatically):**

```bash
git clone https://github.com/fkurevija/Blissful.git
cd Blissful/Blissful

# Build the image and start Blissful + the blissful-pot sidecar
docker compose up -d --build

# View logs
docker compose logs -f blissful
docker compose logs -f blissful-pot
```

`docker-compose.yml` builds the image from the repo, runs both services on the
shared `blissful-network`, mounts `yt-dlp.conf` read-only, and maps the music
library at `/media/Music`. The `blissful-pot` service publishes no host port.

**Alternative: use the image published from this fork**
(`fkurevija/blissful:latest`, built by GitHub Actions):

```bash
# In docker-compose.yml, comment out `build: .` and uncomment `image:`
docker compose up -d

# Bootstrap Deno + PO provider once (see the 403 section above)
docker cp scripts/setup-ytdlp-runtime.sh blissful:/tmp/setup-ytdlp-runtime.sh
docker exec -u 0 blissful sh /tmp/setup-ytdlp-runtime.sh
```

**Access:** http://localhost:7373

### **Method 3: Windows Quick Start**

```powershell
# Double-click start.bat
# Or run from PowerShell:
.\start.bat
```

---

## ⚙️ Initial Configuration

### **Step 1: Access Web Interface**

Open your browser and navigate to:
```
http://localhost:7373
```

You should see the Blissful configuration interface.

### **Step 2: Configure Lidarr**

1. Click the **Lidarr** tab
2. Enter your Lidarr details:
   - **URL:** `http://localhost:8686` (or your Lidarr URL)
   - **API Key:** Found in Lidarr → Settings → General → Security
3. Click **Test Connection**
4. If successful, click **Save Settings**

### **Step 3: Configure Downloads**

1. Click the **Downloads** tab
2. Configure your preferences:
   - **Output Format:** MP3, FLAC, M4A, etc.
   - **Quality:** 128k, 192k, 320k, etc.
   - **Download Location:** Where files are saved
3. Click **Save Settings**

### **Step 4: Test the System**

1. Click the **Tools** tab
2. Scroll to "Test Download"
3. Enter a test track:
   - **Artist:** Metallica
   - **Title:** Enter Sandman
4. Click **Test Download**
5. Check the results

---

## 🎵 Your First Download

### **Via Userscript (Recommended)**

#### **1. Install Userscript Manager**

Install a userscript manager for your browser:
- **Chrome:** [Tampermonkey](https://chrome.google.com/webstore/detail/tampermonkey/dhdgffkkebhmkfjojejmpbldmpobfkfo)
- **Firefox:** [Tampermonkey](https://addons.mozilla.org/en-US/firefox/addon/tampermonkey/) or [Greasemonkey](https://addons.mozilla.org/en-US/firefox/addon/greasemonkey/)
- **Edge:** [Tampermonkey](https://microsoftedge.microsoft.com/addons/detail/tampermonkey/iikmkjmpaadaobahmlepeloendndfphd)
- **Safari:** [Userscripts](https://apps.apple.com/us/app/userscripts/id1463298887)

#### **2. Install Blissful Userscript**

1. Go to Blissful → **Userscript** tab
2. Click **Download Userscript**
3. Your userscript manager will open
4. Click **Install**

#### **3. Use the Userscript**

1. Go to your Lidarr web interface
2. Navigate to any album page
3. You'll see new buttons:
   - **Download Missing Tracks** - Download all missing tracks
   - **Download Album** - Download entire album
4. Click the button and watch the magic happen! ✨

### **Via API**

```bash
# Download a single track
curl -X POST http://localhost:7373/api/download-track \
  -H "Content-Type: application/json" \
  -d '{
    "artist": "Metallica",
    "title": "Enter Sandman",
    "album": "Metallica"
  }'

# Download with Lidarr integration
curl -X POST http://localhost:7373/api/download-track \
  -H "Content-Type: application/json" \
  -d '{
    "artist": "Metallica",
    "title": "Enter Sandman",
    "album_id": 123,
    "track_number": 5
  }'
```

---

## 🎯 Advanced Setup

### **Path Mapping (For Remote Servers)**

If your Lidarr runs on a different machine:

1. Go to **Paths** tab
2. Add path mapping:
   - **Blissful Path:** `/home/user/music`
   - **Lidarr Path:** `D:\Music`
3. Click **Add Mapping**
4. Save settings

Now files will be moved to the correct location automatically!

### **Source Priorities**

Choose which sources to try first:

1. Go to **Sources** tab
2. Drag and drop to reorder
3. Top sources are tried first
4. Save settings

### **Quality Settings**

Configure audio quality:

- **Format:** MP3 (most compatible), FLAC (lossless), M4A (Apple)
- **Bitrate:** 128k (low), 192k (medium), 320k (high)
- **Sample Rate:** 44100 Hz (CD quality), 48000 Hz (studio)

---

## 🔐 Setting Up Requests (Optional)

Allow users to request artists:

### **1. Get Jellyfin API Key**

1. Login to Jellyfin as admin
2. Go to Dashboard → Advanced → API Keys
3. Click "+ New API Key"
4. Name: "Blissful"
5. Copy the generated key

### **2. Configure in Blissful**

1. Go to **Requests** tab
2. Enable **Music Request System**
3. Enable **Jellyfin Authentication**
4. Enter:
   - **Jellyfin URL:** Your Jellyfin server URL
   - **API Key:** The key you just generated
5. Save settings

### **3. Test User Login**

1. Open: `http://localhost:7373/request`
2. Click "Login with Jellyfin"
3. Enter username and password
4. Should work! ✅

---

## 🐛 Troubleshooting

### **Application Won't Start**

```bash
# Check Python version
python --version  # Should be 3.8+

# Check for errors
python Blissful.py

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### **Can't Connect to Lidarr**

- ✅ Verify Lidarr is running
- ✅ Check Lidarr URL is correct
- ✅ Verify API key is correct
- ✅ Check firewall settings

### **Downloads Not Working**

```bash
# Test yt-dlp
yt-dlp --version

# Update yt-dlp
pip install --upgrade yt-dlp

# Test FFmpeg
ffmpeg -version
```

**For YouTube / YouTube Music 403s specifically**, check the runtime:

```bash
curl -s http://localhost:7373/api/health
# Look for js_runtime_available and pot_provider_reachable

# In Docker, ensure the sidecar is up and on the same network
docker compose ps
docker compose logs blissful-pot
```

If `js_runtime_available` is false, pull/rebuild from this fork (the runtime is
baked in), or run the bootstrap script on an older image. If `pot_provider_reachable` is false, confirm both
containers use `blissful-network` and that `yt-dlp.conf` is mounted at
`/app/downloads/yt-dlp.conf`.

### **Userscript Not Showing**

- ✅ Verify userscript manager is installed
- ✅ Check userscript is enabled
- ✅ Refresh the Lidarr page
- ✅ Check browser console for errors (F12)

---

## 📊 System Check

Run this checklist to verify everything:

```bash
# 1. Check Python
python --version

# 2. Check dependencies
pip list | grep -E "(flask|requests|yt-dlp)"

# 3. Check FFmpeg
ffmpeg -version

# 4. Check yt-dlp
yt-dlp --version

# 5. Start Blissful
python run.py
```

---

## 🎉 You're Ready!

Congratulations! You've successfully set up Blissful. Here's what you can do now:

✅ **Download music** from 1000+ sources  
✅ **Integrate with Lidarr** for automatic organization  
✅ **Use the userscript** for one-click downloads  
✅ **Enable requests** for users to request artists  
✅ **Customize settings** to your preferences

---

## 📚 Next Steps

- **[Configuration Guide](#!/documentation?doc=configuration)** - Advanced settings
- **[Request System](#!/documentation?doc=request-system)** - Set up user requests
- **[Troubleshooting](#!/documentation?doc=troubleshooting)** - Common issues

---

## 💡 Tips

### **Performance**
- Use SSD for downloads (faster)
- Configure quality based on your needs
- Enable only needed sources

### **Organization**
- Use path mapping for clean structure
- Let Lidarr handle file naming
- Enable auto-rescan after downloads

### **Security**
- Keep API keys secret
- Use strong passwords
- Update regularly

---

**Need help?** Check the [Troubleshooting Guide](#!/documentation?doc=troubleshooting) or open an issue!

**Happy downloading!** 🎵
