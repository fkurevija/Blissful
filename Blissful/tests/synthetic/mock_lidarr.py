"""Tiny stand-in for Lidarr used by the synthetic compose stack."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALBUM = {
    'id': 1,
    'title': 'Synthetic Album',
    'foreignAlbumId': 'synthetic-album',
    'artist': {'artistName': 'Synthetic Artist', 'path': '/music/Synthetic Artist'},
    'statistics': {'trackCount': 1},
}
TRACK = {
    'id': 10,
    'title': 'Synthetic Track',
    'trackNumber': 1,
    'duration': 180000,
    'hasFile': False,
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/v1/system/status'):
            self._send({'version': 'synthetic', 'appName': 'Lidarr'})
        elif self.path.startswith('/api/v1/config/naming'):
            self._send({'standardTrackFormat': '{track:00} - {title}'})
        elif self.path.startswith('/api/v1/album/1'):
            self._send(ALBUM)
        elif self.path.startswith('/api/v1/track'):
            self._send([TRACK])
        else:
            self._send({'ok': True})

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8686), Handler).serve_forever()
