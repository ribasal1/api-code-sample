"""
API Code Sample
NYTimes Data Loader Plugin

A data loader plugin that fetches articles from the NYT Article Search API,
flattens nested JSON responses into flat dictionaries, and yields them in
configurable batches.

Features:
    - Incremental loading via pub_date / begin_date filtering
    - Dynamic schema accumulated from all seen keys
    - Rate limiting (12s between requests + code 429 backoff)
    - Robust pagination with empirically verified API constraints
"""

import argparse
import logging
import time

import requests

log = logging.getLogger(__name__)

# NYT Article Search API constants
API_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
RATE_LIMIT_SLEEP = 12  # 5 requests/min = 1 per 12 seconds
MAX_PAGE = 100  # Pages 0-100 inclusive (empirically verified)
MAX_RETRIES = 3
BACKOFF_BASE = 30  # seconds, doubles on each retry


def flatten_dict(data, prefix="", separator="."):
    """Flatten a nested dictionary into a single-level dictionary with
    dot-separated keys.

    Rules:
        - Nested dicts: recurse with accumulated prefix
        - Lists: index each element (e.g., keywords.0.name)
        - Empty dicts: preserve as-is
        - Empty lists: preserve as-is (spec says "all elements")
        - None values: preserve (don't drop data)
        - Primitives (str, int, float, bool): keep as-is

    Args:
        data: The dictionary to flatten.
        prefix: Key prefix for recursion (internal use).
        separator: Separator between key levels (default: ".").

    Returns:
        A flat dictionary with dot-separated keys.
    """
    result = {}

    for key, value in data.items():
        full_key = f"{prefix}{separator}{key}" if prefix else key

        if isinstance(value, dict):
            if value:
                # Non-empty dict: recurse
                result.update(flatten_dict(value, prefix=full_key, separator=separator))
            else:
                # Empty dict: preserve as value
                result[full_key] = value

        elif isinstance(value, list):
            if value:
                # Non-empty list: index each element
                for i, item in enumerate(value):
                    indexed_key = f"{full_key}{separator}{i}"
                    if isinstance(item, dict):
                        # List of objects: recurse into each
                        result.update(
                            flatten_dict(item, prefix=indexed_key, separator=separator)
                        )
                    else:
                        # List of primitives
                        result[indexed_key] = item
            else:
                # Empty list: preserve as-is (spec says "all elements")
                result[full_key] = value

        else:
            # Primitive or None: keep as is
            result[full_key] = value

    return result


class NYTimesSource(object):
    """A data loader plugin for the NY Times API."""

    def __init__(self):
        self._session = None
        self._schema = set()
        self._inc_column = None
        self._max_inc_value = None

    def connect(self, inc_column=None, max_inc_value=None):
        """Connect to the source.

        Creates a requests session and stores incremental loading state.
        """
        log.debug("Incremental Column: %r", inc_column)
        log.debug("Incremental Last Value: %r", max_inc_value)

        self._inc_column = inc_column
        self._max_inc_value = max_inc_value

        if inc_column is not None and inc_column != "pub_date":
            log.warning(
                "Only 'pub_date' is supported as incremental column. "
                "Got %r - will use 'pub_date' instead.", inc_column
            )

        # Create session for connection pooling
        self._session = requests.Session()

    def disconnect(self):
        """Disconnect from the source."""
        if self._session:
            self._session.close()
            self._session = None

    def getDataBatch(self, batch_size):
        """Generator - Get data from source in batches.

        Fetches articles page by page from the NYT API, flattens each
        article, accumulates into batches of batch_size, and yields.

        :param batch_size: Number of items per batch.
        :returns: One list per batch. Each list contains flat dictionaries.
        """
        rows = []

        for article in self._fetch_articles():
            try:
                flat = flatten_dict(article)
                self._schema.update(flat.keys())
                rows.append(flat)
            except Exception as e:
                log.warning("Failed to flatten article %s: %s",
                            article.get("_id", "unknown"), e)
                continue

            if len(rows) >= batch_size:
                yield rows
                rows = []

        if rows:
            yield rows

    def _fetch_articles(self):
        """Generator - Fetch articles from all pages of the NYT API.

        Handles pagination, rate limiting, and incremental date filtering.
        """
        params = {
            "api-key": self.args.api_key,
            "q": self.args.query,
            "sort": "oldest",
        }

        # Incremental loading: add begin_date from max_inc_value
        if self._max_inc_value is not None:
            begin_date = self._format_date(self._max_inc_value)
            if begin_date:
                params["begin_date"] = begin_date

        for page in range(0, MAX_PAGE + 1):
            params["page"] = page

            docs = self._fetch_page(params)

            if not docs:
                # None or empty list - no more results
                break

            for doc in docs:
                yield doc

            # Rate limiting: sleep between requests
            if page < MAX_PAGE:
                time.sleep(RATE_LIMIT_SLEEP)

    def _format_date(self, date_str):
        """Convert a date string to NYT API format (YYYYMMDD).

        Handles formats like:
            - "2026-02-14T10:03:05Z" → "20260214"
            - "2026-02-14" → "20260214"

        Returns None if parsing fails.
        """
        if not date_str:
            return None
        try:
            # Strip time component if present, remove dashes
            date_part = date_str.split("T")[0]
            return date_part.replace("-", "")
        except (AttributeError, IndexError):
            log.warning("Could not parse date: %r", date_str)
            return None

    def getSchema(self):
        """Return the schema of the dataset.

        Schema is dynamically accumulated from all keys seen across all
        flattened articles during getDataBatch calls.

        :returns: A sorted list of column names.
        """
        return sorted(self._schema)

    def _fetch_page(self, params):
        """Fetch a single page from the NYT API with retry logic.

        Returns list of article dicts, or None if no results.
        Raises ConnectionError on auth failures, RuntimeError on persistent errors.
        """
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.get(API_URL, params=params, timeout=30)

                if resp.status_code == 429:
                    # Rate limited - back off and retry
                    wait = BACKOFF_BASE * (2 ** attempt)
                    log.warning("Rate limited (code 429). Waiting %ds before retry.", wait)
                    time.sleep(wait)
                    continue

                if resp.status_code in (401, 403):
                    raise ConnectionError(
                        f"Authentication failed (HTTP {resp.status_code}). "
                        "Check your API key."
                    )

                if resp.status_code == 400:
                    page = params.get("page", 0)
                    if page == 0:
                        # Bad request on first page - likely invalid params
                        raise ValueError(
                            "API returned 400 on first request. "
                            "Check query and date parameters."
                        )
                    # Page out of range - end of results
                    log.debug("HTTP 400 on page %s - end of results.", page)
                    return None

                if resp.status_code >= 500:
                    # Server error - retry
                    wait = BACKOFF_BASE * (2 ** attempt)
                    log.warning("Server error (%d). Waiting %ds before retry.",
                                resp.status_code, wait)
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Unexpected HTTP {resp.status_code} on page "
                        f"{params.get('page')}"
                    )

                data = resp.json()
                docs = data.get("response", {}).get("docs")

                # API returns None (not []) when no results
                if docs is None:
                    return None

                return docs

            except requests.RequestException as e:
                wait = BACKOFF_BASE * (2 ** attempt)
                log.warning("Request failed: %s. Waiting %ds before retry.", e, wait)
                time.sleep(wait)
                continue

        log.error("Failed to fetch page %s after %d retries",
                  params.get("page"), MAX_RETRIES)
        raise RuntimeError(
            f"Failed to fetch page {params.get('page')} after {MAX_RETRIES} retries"
        )


if __name__ == "__main__":
    config = {
        "api_key": "NYTIMES_API_KEY",  # Replace with your API key
        "query": "Silicon Valley",
    }
    source = NYTimesSource()

    # This looks like an argparse dependency - but the Namespace class is just # a simple way to create an object holding attributes.
    source.args = argparse.Namespace(**config)

    # First run: load articles from a specific date onwards (oldest first). # If no max_inc_value is provided, the API returns articles from 1851.
    source.connect(inc_column="pub_date", max_inc_value="2026-02-01")

    # Incremental run: uncomment below (and comment above) to simulate# a subsequent run. Uses a later date so only newer articles are fetched.# Note: begin_date is day-level precision, so articles from the same day# as max_inc_value will appear in both runs (known limitation).
    # source.connect(inc_column="pub_date", max_inc_value="2026-02-16")

    for idx, batch in enumerate(source.getDataBatch(10)):
        print(f"{idx} Batch of {len(batch)} items")
        for item in batch:
            print(f"  - {item['_id']} - {item['headline.main']}")

    print(f"\nSchema ({len(source.getSchema())} fields):")
    for field in source.getSchema():
        print(f"  {field}")

    source.disconnect()