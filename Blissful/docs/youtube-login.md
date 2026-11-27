# YouTube sign-in (optional embedded browser)

Blissful can use an **optional** browser sidecar so you can sign in to YouTube
from inside the web UI instead of exporting cookies by hand. This is meant for
the "Sign in to confirm you're not a bot" gate: yt-dlp needs session cookies
from a real signed-in browser, and an OAuth form cannot supply them.

## Why there is no username/password or OAuth form

- Google sign-in is interactive (2FA, device checks, CAPTCHAs) and blocks
  automated logins.
- An OAuth/device-code flow returns an access token, **not** the YouTube web
  session cookies that yt-dlp needs for playback.
- Therefore the only reliable approach is a real browser session you interact
  with once, from which Blissful reads the cookies.

## Enable it

The sidecar is disabled by default so the base install stays small. From the
directory containing your `docker-compose.yaml`:

```bash
docker compose --profile youtube-login up -d youtube-login
```

This pulls `selenium/standalone-chrome` (about 400–600 MB on disk) and starts:

- a Chrome browser reachable from Blissful at `http://youtube-login:4444`
- **noVNC on port 7900**, mapped to the host, for the interactive window

Restart Blissful after enabling the profile so it sees `SELENIUM_URL`:

```bash
docker compose up -d blissful
```

Port 7900 must be reachable from the browser you use to open Blissful. If
Blissful is behind a reverse proxy with a different hostname, set
`YOUTUBE_NOVNC_URL` on the `blissful` service to the full noVNC URL. Blissful
appends `?autoconnect=1` so the embedded window connects immediately instead of
showing noVNC's generic Connect dialog with a password field.

## Sign in from the UI

1. Open **Sources → Download Sources** and expand the **YouTube** or
   **YouTube Music** row (click the name or the ▾ chevron).
2. Click **Login with YouTube**. A window opens with a live view of the
   browser on the server.
3. Sign in to YouTube in that window as you normally would, including 2FA.
   Use a **dedicated account** — the session lives on the server.
4. Click **Save cookies**. Blissful reads only the YouTube cookies, converts
   them to Netscape `cookies.txt` format, and stores them in the masked
   `youtube_cookies` config setting.
5. Downloads now pass those cookies to yt-dlp automatically. No restart is
   needed.

Clicking **Cancel** closes the window and discards that login attempt.

## Expiry and re-login

YouTube sessions expire. When a download is rejected with a bot challenge,
Blissful marks the session as expired; the YouTube source row then says
**"Session expired - login again."** Repeat the steps above. The status also
refreshes every two minutes while the page is open.

The browser profile is **not** persisted on disk. That is deliberate: the
cookies are already stored in Blissful's config and reused by yt-dlp, and
keeping a live browser profile on the server would add another sensitive
artifact to protect.

## Manual fallback

You do not have to enable the sidecar. The expanded YouTube row also accepts a
pasted Netscape-format `cookies.txt`, and the `YOUTUBE_COOKIES` environment
variable can supply the same value:

```bash
yt-dlp --cookies-from-browser firefox --cookies cookies.txt
```

Paste the file contents into the field (never share it). Blissful masks the
value in `/api/config` and writes it to a private file before each download.

## API endpoints

Used by the UI; handy for debugging:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/youtube/login/status` | `available`, `active`, `has_cookies`, `relogin_required` |
| `POST /api/youtube/login/start` | Open a browser session; returns `novnc_url` |
| `POST /api/youtube/login/finish` | Save YouTube cookies from the open session |
| `POST /api/youtube/login/cancel` | Close the open session without saving |

## Security notes

- The cookie file and config value are secrets. Never paste them into chat or
  commit them.
- noVNC is enabled **without a password**; expose port 7900 only on a trusted
  LAN, or put it behind your existing authentication/proxy.
- Use a dedicated Google account for the sidecar, not your primary account.

## Troubleshooting

- **"Login browser not enabled (optional profile)."** — start the sidecar with
  the command above and restart Blissful.
- **Login window shows a blank screen** — confirm noVNC responds:
  `curl -I http://<server>:7900/`.
- **noVNC asks for a password** — the sidecar was started with VNC auth
  enabled instead of `SE_VNC_NO_PASSWORD=true`. Set that variable on the
  `youtube-login` service and recreate it with `docker compose --profile
  youtube-login up -d --force-recreate youtube-login`. A password field
  *inside* the browser is for your Google/YouTube account instead.
- **"No YouTube cookies found"** — you must complete the YouTube sign-in in
  the window before clicking Save cookies.
- **Session creation error / `DevToolsActivePort`** — make sure no stale
  browser session is running; restart the sidecar with
  `docker compose --profile youtube-login restart youtube-login`.
- **Bot error returns immediately** — refresh the cookies; the account/session
  may have been invalidated by Google.
