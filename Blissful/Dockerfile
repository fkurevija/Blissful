# Blissful - Lidarr Music Downloader
# Self-contained image: Deno 2.x + yt-dlp + PO-token provider are baked in,
# so YouTube and YouTube Music 403s are fixed automatically when this
# Dockerfile is used to build the image.
FROM python:3.11-slim AS base

ARG DEBIAN_FRONTEND=noninteractive

# ffmpeg: audio conversion. curl/unzip: fetch Deno (also used by the
# published-image bootstrap script). gosu: drop root after fixing volume
# ownership. passwd: create the unprivileged runtime user at build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        unzip \
        ca-certificates \
        gosu \
        passwd \
    && rm -rf /var/lib/apt/lists/*

# Deno 2.x - JavaScript runtime yt-dlp uses for YouTube's JS challenges.
ARG DENO_VERSION=2.9.8
ARG TARGETARCH
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
        amd64) deno_target="x86_64-unknown-linux-gnu" ;; \
        arm64) deno_target="aarch64-unknown-linux-gnu" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
        "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_target}.zip" \
        -o /tmp/deno.zip; \
    unzip -o -j /tmp/deno.zip deno -d /usr/local/bin/; \
    chmod 0755 /usr/local/bin/deno; \
    rm -f /tmp/deno.zip; \
    deno --version

WORKDIR /app

# Install Python dependencies (yt-dlp + bgutil PO-token provider included).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY Blissful.py ./
COPY extend/ ./extend/
COPY templates/ ./templates/
COPY static/ ./static/
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY yt-dlp.conf /app/downloads/yt-dlp.conf
RUN chmod 0755 /usr/local/bin/entrypoint.sh /app/scripts/setup-ytdlp-runtime.sh

# Unprivileged runtime user. PUID/PGID can be overridden at *runtime* by the
# entrypoint; these build args only set the image defaults.
ARG PUID=1000
ARG PGID=1000
RUN if ! getent group "${PGID}" >/dev/null 2>&1; then \
        groupadd -g "${PGID}" blissful; \
    fi; \
    if ! getent passwd "${PUID}" >/dev/null 2>&1; then \
        useradd -u "${PUID}" -g "${PGID}" -m -d /home/blissful -s /bin/sh blissful; \
    fi; \
    mkdir -p /app/config /app/downloads/pylib /app/downloads/temp; \
    chown -R "${PUID}:${PGID}" /app/config /app/downloads /home/blissful

# Mirrors the verified deployment: persistent pylib + PO-token sidecar URL.
ENV PORT=7373 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/downloads/pylib \
    YT_DLP_HOME=/app/downloads \
    DENO_PATH=/usr/local/bin/deno \
    POT_PROVIDER_URL=http://blissful-pot:4416

EXPOSE 7373

# Keep healthcheck (now also reports js_runtime_available /
# pot_provider_reachable when the runtime agent's health endpoint lands).
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:7373/api/health', timeout=5)" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "Blissful.py"]
