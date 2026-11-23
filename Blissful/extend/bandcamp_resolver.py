"""Bandcamp search resolver for Blissful.

Turns a free-text query into a real Bandcamp track/album URL. Search pages are
never returned as download targets. Network failures degrade to None/[].
"""

import logging
import re
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

_SEARCH_URL = 'https://bandcamp.com/search?q={query}'
_TIMEOUT = 10
_USER_AGENT = 'Mozilla/5.0 (compatible; Blissful/1.0)'
# Matches https://artist.bandcamp.com/track/slug or /album/slug (incl. www and
# protocol-relative forms after urljoin). Never matches /search pages.
_TRACK_RE = re.compile(
    r'^(?:https?:)?//(?:[A-Za-z0-9-]+\.)*bandcamp\.com/(?:track|album)/[^/?#\s]+',
    re.IGNORECASE,
)


class _LinkParser(HTMLParser):
    """Collect href attributes from an HTML document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'a':
            return
        for key, value in attrs:
            if key and key.lower() == 'href' and value:
                self.links.append(value)
                break


class BandcampResolver:
    """Resolve a Bandcamp query to a concrete track or album URL."""

    def search(self, query: str) -> list:
        """Return plausible Bandcamp track/album URLs for ``query``."""
        if query is None or not str(query).strip():
            return []

        query = str(query).strip()
        url = _SEARCH_URL.format(query=quote_plus(query))
        try:
            response = requests.get(
                url, headers={'User-Agent': _USER_AGENT}, timeout=_TIMEOUT)
            if response.status_code != 200:
                logger.debug('Bandcamp search returned HTTP %s', response.status_code)
                return []
            html = response.text
        except Exception as exc:  # robust to any network/parse failure
            logger.debug('Bandcamp search failed: %s', type(exc).__name__)
            return []

        parser = _LinkParser()
        try:
            parser.feed(html or '')
            parser.close()
        except Exception:
            pass

        results = []
        seen = set()
        for link in parser.links:
            candidate = str(link).strip()
            if not candidate:
                continue
            absolute = urljoin('https://bandcamp.com/', candidate)
            if not _TRACK_RE.match(absolute):
                continue
            parts = urlsplit(absolute)
            clean = urlunsplit((parts.scheme or 'https', parts.netloc, parts.path, '', ''))
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(clean)

        return results

    def resolve(self, query: str):
        """Return the first plausible track/album URL, or None."""
        results = self.search(query)
        return results[0] if results else None
