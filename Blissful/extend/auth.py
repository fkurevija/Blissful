"""Opt-in API token authentication for Blissful.

The token is disabled by default. When enabled (config key ``auth_token`` or
``BLISSFUL_AUTH_TOKEN``) every ``/api/`` route except the health check requires
it. Static pages and the generated userscript stay public so the UI can load.
"""

import functools
import hmac
import logging
import os

from flask import jsonify, request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# These remain reachable without a token even when auth is enabled.
PUBLIC_PATHS = {'/api/health'}


def get_token(config_manager):
    """Return the configured token (environment wins over config.json)."""
    env_token = os.environ.get('BLISSFUL_AUTH_TOKEN', '')
    if env_token:
        return env_token
    return str(config_manager.get_setting('auth_token', '') or '')


def is_enabled(config_manager):
    return bool(get_token(config_manager))


def presented_token():
    """Read the token from standard or Blissful-specific request headers."""
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        return header[7:].strip()
    if header:
        return header.strip()
    return request.headers.get('X-Blissful-Token', '').strip()


def token_is_valid(config_manager):
    expected = get_token(config_manager)
    if not expected:
        return True
    presented = presented_token()
    if not presented:
        return False
    return hmac.compare_digest(presented, expected)


def is_same_origin_request():
    """True for requests with no Origin header or an Origin matching the host.

    The bundled UI runs on the same origin and therefore needs no token. Every
    cross-origin request (including a browser page trying to call Blissful from
    another site) must carry the token. This is what blocks drive-by config
    changes while keeping the local web UI usable.
    """
    origin = request.headers.get('Origin')
    if not origin:
        return True
    return urlparse(origin).netloc.lower() == request.host.lower()


def require_token(config_manager):
    """Decorator for an individual route; prefer install_auth() for the app."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if not token_is_valid(config_manager):
                logger.warning("Rejected unauthenticated request to %s", request.path)
                return jsonify({'success': False, 'error': 'Invalid or missing API token'}), 401
            return view(*args, **kwargs)

        return wrapper

    return decorator


def install_auth(app, config_manager):
    """Install a global gate for API routes (health remains public)."""

    @app.before_request
    def _check_api_token():
        if not request.path.startswith('/api/'):
            return None
        if request.path in PUBLIC_PATHS:
            return None
        if not is_enabled(config_manager):
            return None
        if is_same_origin_request():
            return None
        if not token_is_valid(config_manager):
            logger.warning("Rejected unauthenticated request: %s %s", request.method, request.path)
            return jsonify({'success': False, 'error': 'Invalid or missing API token'}), 401
        return None

    return app
