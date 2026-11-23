#!/bin/sh
# Blissful container entrypoint.
#
# Runs as root only long enough to fix ownership of the bind-mounted volumes,
# then drops privileges to PUID:PGID (default 1000:1000) with gosu (or
# su-exec). No secrets are handled here.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Volumes can hide the directories created at build time; recreate them.
mkdir -p /app/config /app/downloads /app/downloads/pylib /app/downloads/temp

if [ "$(id -u)" -eq 0 ]; then
    chown -R "${PUID}:${PGID}" /app/config /app/downloads

    if command -v gosu >/dev/null 2>&1; then
        exec gosu "${PUID}:${PGID}" "$@"
    elif command -v su-exec >/dev/null 2>&1; then
        exec su-exec "${PUID}:${PGID}" "$@"
    fi

    echo "entrypoint.sh: neither gosu nor su-exec is available; refusing to run as root" >&2
    exit 1
fi

# Already non-root (e.g. Kubernetes securityContext). Skip chown/gosu.
exec "$@"
