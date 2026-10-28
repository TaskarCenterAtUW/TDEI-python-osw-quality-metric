"""The sole application boundary for OSMnx's private APIs.

Verified with the exact OSMnx version pinned in requirements.txt (2.0.7).
When upgrading, review the helpers below and run the saved-response compatibility
tests before updating their baseline. Public OSMnx APIs remain usable elsewhere.
This module does not make network requests or configure authentication.
"""

from osmnx import _http, _overpass, settings
from osmnx.graph import _create_graph


def network_queries(polygon, custom_filter, *, timeout=None):
    """Build network queries with OSMnx's settings and polygon subdivision."""
    if timeout is None:
        query_settings = _overpass._make_overpass_settings()
    else:
        # Format request-local settings without mutating OSMnx globals shared
        # by concurrent message handlers.
        maxsize = '' if settings.overpass_memory is None else f'[maxsize:{settings.overpass_memory}]'
        query_settings = settings.overpass_settings.format(timeout=int(timeout), maxsize=maxsize)
    for coordinates in _overpass._make_overpass_polygon_coord_strs(polygon):
        yield f"{query_settings};(way{custom_filter}(poly:{coordinates!r});>;);out;"


def cached_response(cache_key):
    """Read a provider/query cache entry, respecting OSMnx's cache settings."""
    return _http._retrieve_from_cache(cache_key)


def cache_response(cache_key, data):
    """Cache a response already validated by the provider client."""
    _http._save_to_cache(cache_key, data, True)


def graph_from_responses(responses):
    """Construct the unsimplified road graph, preserving OSM direction rules."""
    return _create_graph(responses, 'all' in settings.bidirectional_network_types)
