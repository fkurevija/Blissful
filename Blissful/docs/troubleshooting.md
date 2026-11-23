# 🔧 Troubleshooting Guide

Common issues and their solutions for Blissful.

---

## 🔑 YouTube / YouTube Music 403s (most common)

If downloads fail with **HTTP 403** on YouTube or YouTube Music, the yt-dlp
runtime is missing one of two pieces:

1. **Deno 2.x** — JavaScript runtime for YouTube's JS challenges.
2. **PO-token provider** — the `blissful-pot` sidecar
   (`brainicism/bgutil-ytdlp-pot-provider`) on the **same Docker network** as
   Blissful, reachable at `http://blissful-pot:4416` with **no host port**.

**Quick diagnosis:**

```bash
curl -s http://localhost:7373/api/health
# js_runtime_available: true
# pot_provider_reachable: true
```

These fields are added by the runtime update. Interpret them like this:

| Field | `false` means | Fix |
|-------|---------------|-----|
| `js_runtime_available` | Deno is missing or at the wrong path | Rebuild from the repo, or run `scripts/setup-ytdlp-runtime.sh` on the published image |
| `pot_provider_reachable` | Sidecar is down or on a different network | Start `blissful-pot` and put both containers on `blissful-network` |

**Fix when building from the repo (automatic):**

```bash
docker compose up -d --build
# The Dockerfile bakes in Deno 2.x, yt-dlp>=2026.10.26 and
# bgutil-ytdlp-pot-provider>=2.0.2; compose starts the sidecar.
```

**Fix when using the published image:**

```bash
docker cp scripts/setup-ytdlp-runtime.sh blissful:/tmp/setup-ytdlp-runtime.sh
docker exec -u 0 blissful sh /tmp/setup-ytdlp-runtime.sh
docker compose restart blissful
```

The script is idempotent, installs into the persistent `YT_DLP_HOME`, and
writes `yt-dlp.conf` with `--js-runtimes deno:<local path>` and
`--extractor-args youtubepot-bgutilhttp:base_url=$POT_PROVIDER_URL`.

> ⚠️ PO tokens **reduce** 403s but do **not guarantee** they never occur.
> YouTube changes its defenses; keep yt-dlp updated and leave fallback
> sources (SoundCloud, Bandcamp) enabled.

---

## 🚨 Common Issues

### **Application Won't Start**

#### **Symptom:**
```
python run.py
# No output or immediate crash
```

#### **Solutions:**

**1. Check Python Version**
```bash
python --version
# Should be 3.8 or higher
```

**2. Check Dependencies**
```bash
pip list | grep -E "(flask|requests|yt-dlp)"

# If missing, reinstall:
pip install -r requirements.txt
```

**3. Check for Port Conflicts**
```bash
# Windows
netstat -ano | findstr :7373

# Linux/Mac
lsof -i :7373

# Change port if needed:
export PORT=7374
python run.py
```

**4. Check File Permissions**
```bash
# Make sure you have write permissions:
ls -la config.json
ls -la downloads/
```

---

### **Can't Connect to Lidarr**

#### **Symptom:**
```
Connection test fails
Error: Cannot reach Lidarr server
```

#### **Solutions:**

**1. Verify Lidarr is Running**
```bash
# Check if Lidarr is accessible:
curl http://localhost:8686/api/v1/system/status

# Or open in browser:
http://localhost:8686
```

**2. Check URL Format**
```
❌ Wrong: localhost:8686
❌ Wrong: http://localhost:8686/
✅ Correct: http://localhost:8686
```

**3. Verify API Key**
```
1. Open Lidarr
2. Settings → General → Security
3. Copy API Key exactly (no spaces)
4. Paste in Blissful
```

**4. Check Firewall**
```bash
# Windows: Allow Python through firewall
# Linux: Check iptables
sudo iptables -L

# Test connectivity:
telnet localhost 8686
```

---

### **Downloads Not Working**

#### **Symptom:**
```
Search succeeds but download fails
Error: Download failed
```

#### **Solutions:**

**1. Test yt-dlp**
```bash
yt-dlp --version

# If not found:
pip install yt-dlp

# Test download:
yt-dlp "ytsearch:metallica enter sandman" --get-title
```

**2. Update yt-dlp**
```bash
pip install --upgrade yt-dlp

# Or use Blissful interface:
Tools tab → Update yt-dlp
```

**3. Test FFmpeg**
```bash
ffmpeg -version

# If not found, install:
# Windows: Download from https://ffmpeg.org
# Linux: sudo apt install ffmpeg
# Mac: brew install ffmpeg
```

**4. Check Disk Space**
```bash
# Windows
dir C:\

# Linux/Mac
df -h
```

**5. Check Download Folder Permissions**
```bash
# Linux/Mac
ls -la downloads/
chmod 755 downloads/

# Windows: Right-click → Properties → Security
```

---

### **Userscript Not Working**

#### **Symptom:**
```
Userscript installed but buttons don't appear
Or: Buttons appear but don't work
```

#### **Solutions:**

**1. Verify Installation**
```
1. Click userscript manager icon
2. Check "Blissful Lidarr Integration" is enabled
3. Check it matches current Lidarr URL
```

**2. Check URL Matching**
```javascript
// Userscript should have:
// @match http://your-lidarr-url/*
// @match https://your-lidarr-url/*

// Update if needed in Blissful → Userscript tab
```

**3. Hard Refresh Lidarr**
```
1. Press Ctrl+Shift+R (Windows/Linux)
2. Or Cmd+Shift+R (Mac)
3. Clears cache and reloads
```

**4. Check Browser Console**
```
1. Press F12
2. Go to Console tab
3. Look for errors
4. Common issues:
   - CORS errors (use correct URL)
   - Network errors (Blissful not running)
   - JavaScript errors (userscript outdated)
```

**5. Reinstall Userscript**
```
1. Remove old userscript
2. Download new one from Blissful
3. Install in userscript manager
4. Refresh Lidarr
```

---

### **Authentication Failures**

#### **Symptom (Jellyfin/Emby):**
```
"Invalid username or password"
"API key not configured"
"Cannot connect to server"
```

#### **Solutions:**

**1. Verify API Key Configured**
```
1. Go to Requests tab
2. Check API key field is not empty
3. Click Save Settings
4. Restart Blissful
```

**2. Test Jellyfin Directly**
```bash
# Test authentication:
curl -X POST "http://jellyfin-url/Users/AuthenticateByName" \
  -H "Content-Type: application/json" \
  -H "X-Emby-Token: your-api-key" \
  -d '{"Username":"testuser","Pw":"testpass"}'
```

**3. Check User Exists**
```
1. Log into Jellyfin as admin
2. Dashboard → Users
3. Verify user exists and is active
4. Try with different user
```

**4. Review Logs**
```bash
# Check Blissful logs:
tail -f logs/blissful.log

# Check Jellyfin logs:
# Dashboard → Logs
```

**5. Common Jellyfin Issues**
```
Issue: "Database concurrency error"
Solution: Just try again, it's a Jellyfin bug

Issue: "User not found"
Solution: Check exact username (case-sensitive)

Issue: "SSL certificate error"
Solution: Use HTTP instead of HTTPS for testing
```

---

### **Path Mapping Issues**

#### **Symptom:**
```
Files download but Lidarr doesn't see them
Or: Files go to wrong location
```

#### **Solutions:**

**1. Verify Mapping Configuration**
```json
{
  "lidarr_path_mapping": {
    "/app/downloads": "/music"
  }
}
```

**2. Test Path Conversion**
```
Input: /app/downloads/Artist/Album/track.mp3
Expected: /music/Artist/Album/track.mp3

Check in Tools tab → Test Path Mapping
```

**3. Check Path Separators**
```
Windows: C:\Music\Artist\Album
Linux:   /music/Artist/Album

Use correct separator for each platform!
```

**4. Verify Mount Points**
```bash
# Docker: Check volume mounts
docker inspect blissful

# Linux: Check mounted filesystems
mount | grep music

# Windows: Check drive mappings
net use
```

---

### **Conversion Failures**

#### **Symptom:**
```
Download succeeds but conversion fails
Error: FFmpeg error
```

#### **Solutions:**

**1. Verify FFmpeg Installation**
```bash
ffmpeg -version

# Should show version info
# If not, install FFmpeg
```

**2. Test Conversion Manually**
```bash
ffmpeg -i input.webm -c:a libmp3lame -b:a 320k output.mp3
```

**3. Check File Format**
```
Some formats require specific codecs:
- MP3: libmp3lame
- FLAC: flac
- M4A: aac
- OGG: libvorbis
```

**4. Check Disk Space**
```bash
# Conversion needs temporary space
df -h

# Clean up if needed:
rm -rf /tmp/ffmpeg-*
```

---

### **Performance Issues**

#### **Symptom:**
```
Downloads are very slow
Interface is laggy
High CPU/Memory usage
```

#### **Solutions:**

**1. Optimize Source Priorities**
```
1. Go to Sources tab
2. Disable unused sources
3. Put fast sources first
4. Save settings
```

**2. Adjust Quality Settings**
```
Lower quality = faster downloads:
- 192k instead of 320k
- MP3 instead of FLAC
```

**3. Check System Resources**
```bash
# Linux/Mac
top
htop

# Windows
Task Manager (Ctrl+Shift+Esc)

# Look for:
- High CPU (>80%)
- High Memory (>80%)
- High Disk I/O
```

**4. Optimize Download Location**
```
✅ Use SSD instead of HDD
✅ Use local drive instead of network
✅ Ensure sufficient space
❌ Don't use slow USB drives
```

**5. Limit Concurrent Downloads**
```python
# In config.json (coming soon):
{
  "max_concurrent_downloads": 3
}
```

---

## 🔍 Diagnostic Tools

### **Health Check**

```bash
# Check all systems (port 7373, not 5000):
curl http://localhost:7373/api/health

# Should return (with the runtime update):
{
  "status": "healthy",
  "ffmpeg_available": true,
  "ytdlp_available": true,
  "js_runtime_available": true,
  "pot_provider_reachable": true
}
```

`js_runtime_available` verifies the Deno JS runtime; `pot_provider_reachable`
verifies that the `blissful-pot` sidecar is reachable over the shared Docker
network. See the 403 section at the top of this guide if either is `false`.

### **System Info**

```bash
# Get system information:
curl http://localhost:7373/api/system/info

# Returns:
{
  "is_docker": false,
  "os": "Linux",
  "python_version": "3.10.0"
}
```

### **Test Download**

```bash
# Test download functionality:
curl -X POST http://localhost:7373/api/download-track \
  -H "Content-Type: application/json" \
  -d '{
    "artist": "Test Artist",
    "title": "Test Track"
  }'
```

---

## 📋 Checklist for New Setup

Before asking for help, verify:

- [ ] Python 3.8+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] FFmpeg installed and in PATH
- [ ] yt-dlp >= 2026.10.26 and bgutil-ytdlp-pot-provider >= 2.0.2 installed
- [ ] Deno 2.x available (`js_runtime_available: true`)
- [ ] `blissful-pot` running on the same Docker network (`pot_provider_reachable: true`)
- [ ] Lidarr running and accessible
- [ ] Lidarr API key correct
- [ ] yt-dlp updated (`pip install --upgrade yt-dlp`)
- [ ] Disk space available
- [ ] Firewall allows connections
- [ ] Configuration saved
- [ ] Application restarted after config changes

---

## 🐛 Debug Mode (keep it OFF)

Blissful runs with **debug disabled** in normal and production use:

```python
# In Blissful.py:
app.run(host='0.0.0.0', port=7373, debug=False)
```

or via environment:

```bash
export BLISSFUL_DEBUG=false
export FLASK_DEBUG=0
```

**Warning:** The interactive debugger is unsafe in production. If you temporarily
enable it for local troubleshooting, turn it back off immediately and never expose
the service to the internet with it on. For routine issues use the log files and
`/api/health` instead.

---

## 📝 Log Files

### **Viewing Logs**

```bash
# Real-time logs:
tail -f logs/blissful.log

# Last 100 lines:
tail -n 100 logs/blissful.log

# Search logs:
grep "error" logs/blissful.log
```

### **Common Log Messages**

```
✅ "Authentication successful" - User logged in
✅ "Download completed" - Track downloaded
❌ "Connection refused" - Can't reach Lidarr
❌ "API key invalid" - Wrong API key
⚠️  "Source failed, trying next" - Normal fallback
```

---

## 🆘 Getting Help

### **Information to Provide**

When asking for help, include:

1. **Blissful version**
```bash
grep "version" Blissful.py
```

2. **Python version**
```bash
python --version
```

3. **Operating System**
```bash
# Linux/Mac
uname -a

# Windows
ver
```

4. **Error message (full)**
```
Copy complete error from logs or console
```

5. **Configuration (sanitized)**
```json
{
  "lidarr_url": "http://localhost:8686",
  "lidarr_api_key": "***REDACTED***",
  ...
}
```

6. **Steps to reproduce**
```
1. Did this
2. Then did that
3. Got this error
```

### **Where to Get Help**

- 📖 **Documentation** - Check other guides first
- 🐛 **GitHub Issues** - Report bugs
- 💬 **Discussions** - Ask questions
- 📧 **Email** - Contact developer

---

## 💡 Prevention Tips

### **Regular Maintenance**

```bash
# Weekly:
- Update yt-dlp
- Clear old downloads
- Check disk space
- Review logs

# Monthly:
- Update dependencies
- Backup configuration
- Review sources
- Clean cache
```

### **Best Practices**

✅ **Do:**
- Keep everything updated
- Monitor logs regularly
- Test after configuration changes
- Keep backups of config.json
- Document custom settings

❌ **Don't:**
- Ignore errors
- Run out of disk space
- Use outdated yt-dlp
- Change multiple settings at once
- Skip testing

---

## 🎓 Advanced Troubleshooting

### **Network Issues**

```bash
# Test DNS:
nslookup youtube.com

# Test connectivity:
ping youtube.com

# Test HTTP:
curl -I https://youtube.com

# Check proxy:
echo $http_proxy
echo $https_proxy
```

### **Permission Issues**

```bash
# Linux/Mac - Fix permissions:
sudo chown -R $USER:$USER .
chmod -R 755 .
chmod 644 config.json

# Check effective permissions:
id
groups
```

### **Database Issues**

```bash
# If using SQLite (future):
sqlite3 blissful.db ".schema"
sqlite3 blissful.db "PRAGMA integrity_check;"
```

---

## 🔮 Known Issues

### **yt-dlp Extraction Errors**

**Symptom:** "ERROR: Unable to extract..."  
**Cause:** Site changed their API  
**Solution:** Update yt-dlp

```bash
pip install --upgrade yt-dlp
```

### **Jellyfin Database Concurrency**

**Symptom:** "Database is locked"  
**Cause:** Jellyfin internal bug  
**Solution:** Just try again, it usually works the second time

### **Path Too Long (Windows)**

**Symptom:** "Path is too long"  
**Cause:** Windows 260 character limit  
**Solution:** Enable long paths or use shorter names

```powershell
# Enable long paths (Admin PowerShell):
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

---

## ✅ Still Having Issues?

If none of the above helped:

1. **Check `/api/health`** for `js_runtime_available` and `pot_provider_reachable`
2. **Collect logs** (`docker compose logs blissful blissful-pot`)
3. **Reproduce the issue** with debug still OFF
4. **Open a GitHub issue** with:
   - Error message
   - Steps to reproduce
   - System information
   - Log excerpts

We're here to help! 🤝

---

**Back to:** [Documentation Home](#!/documentation?doc=README)
