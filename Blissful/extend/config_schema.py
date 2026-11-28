"""Declarative configuration shape validation.

The config used to be trusted verbatim on load, so a malformed
``source_priorities`` entry (a string instead of a dict) could reach
``_build_source_list()`` and fail deep inside a download. This module is the
single description of the *shape* of a config; the UI's field descriptors and
this validator are the two views of the same settings.
"""

from copy import deepcopy

SEARCHABLE_SOURCES = {'YouTube Music', 'SoundCloud', 'YouTube', 'Bandcamp',
                      'Deezer', 'Apple Music', 'Mixcloud', 'Archive.org', 'Tidal'}
METADATA_PROVIDERS = {'spotify', 'discogs', 'musicbrainz', 'acoustid'}


def normalize_config(config, defaults):
    """Return ``(config, issues)`` with obvious shape errors repaired.

    Unknown keys survive; known keys with the wrong shape fall back to their
    default. Repairing on load keeps a hand-edited config.json from breaking a
    download hours later, while leaving the richer ``_validate_config`` rules
    (secrets, naming, provider ordering) untouched on the save path.
    """
    loaded = config if isinstance(config, dict) else {}
    result = deepcopy(defaults)
    result.update(loaded)
    issues = []

    for key, default in defaults.items():
        value = result.get(key)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                issues.append(key)
                result[key] = default
        elif isinstance(default, int) and not isinstance(default, bool):
            if isinstance(value, bool) or not isinstance(value, int):
                try:
                    result[key] = int(value)
                except (TypeError, ValueError):
                    issues.append(key)
                    result[key] = default
        elif isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                try:
                    result[key] = float(value)
                except (TypeError, ValueError):
                    issues.append(key)
                    result[key] = default
        elif isinstance(default, list) and not isinstance(value, list):
            issues.append(key)
            result[key] = deepcopy(default)
        elif isinstance(default, dict) and not isinstance(value, dict):
            issues.append(key)
            result[key] = deepcopy(default)

    priorities = [entry for entry in result.get('source_priorities', [])
                  if isinstance(entry, dict)
                  and isinstance(entry.get('name'), str)
                  and isinstance(entry.get('search'), str)]
    if len(priorities) != len(result.get('source_priorities', []) or []):
        issues.append('source_priorities')
    result['source_priorities'] = priorities

    order = [item for item in result.get('metadata_provider_order', [])
             if item in METADATA_PROVIDERS]
    order = list(dict.fromkeys(order))
    if len(order) != len(result.get('metadata_provider_order', []) or []):
        issues.append('metadata_provider_order')
    result['metadata_provider_order'] = order

    depth = result.get('search_results_per_source', 3)
    if not 1 <= depth <= 10:
        result['search_results_per_source'] = max(1, min(10, int(depth)))
        issues.append('search_results_per_source')

    return result, issues


def validate_config_shape(config, defaults):
    """Only the error list, for callers that just want to report problems."""
    return normalize_config(config, defaults)[1]
