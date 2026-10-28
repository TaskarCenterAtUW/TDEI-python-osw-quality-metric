"""Authenticated OSM network downloads from Fairway Mapper's Overpass mirror."""

import os

import requests
from src.calculators import osmnx_compat
from src.calculators.fetch_timing import FetchBudget


INTERPRETER_URL = "https://api.fairwaymapper.com/api/interpreter"


def download_seed_network(polygon, custom_filter, *, budget=None):
    """Keep OSMnx query subdivision and caching, with request-local credentials.

    The cache key includes the provider and query, never the API key. Do not
    change OSMnx's global HTTP settings: concurrent jobs and other OSMnx APIs
    must not inherit this provider's credentials.
    """
    api_key = os.environ.get("FAIRWAY_MAPPER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("FAIRWAY_MAPPER_API_KEY is required for intersection scoring")
    budget = budget if budget is not None else FetchBudget()
    budget.remaining()
    for query in osmnx_compat.network_queries(polygon, custom_filter, timeout=budget.policy.read_timeout):
        budget.remaining()
        cache_key = requests.Request("GET", INTERPRETER_URL, params={"data": query}).prepare().url
        data = osmnx_compat.cached_response(cache_key)
        if data is None:
            response = requests.post(
                INTERPRETER_URL,
                data={"data": query},
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                timeout=budget.request_timeouts(),
                allow_redirects=False,
            )
            budget.remaining()
            # Do not include response bodies or credentials in exceptions/logs.
            if response.status_code != 200:
                raise requests.HTTPError(
                    f"Fairway Mapper returned HTTP {response.status_code}", response=response,
                )
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Fairway Mapper returned invalid JSON") from None
            _validate_response(data)
            budget.remaining()
            osmnx_compat.cache_response(cache_key, data)
        else:
            _validate_response(data)
        budget.remaining()
        yield data


def _validate_response(data):
    # Overpass can return HTTP 200 with partial data after a query timeout.
    # Such responses must not silently become an incomplete graph or fallback.
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise ValueError("Fairway Mapper returned an invalid OSM response")
    if "remark" in data:
        raise ValueError("Fairway Mapper reported an incomplete or failed query")
    if any(not isinstance(element, dict) for element in data["elements"]):
        raise ValueError("Fairway Mapper returned invalid OSM elements")
