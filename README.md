# API Code Sample: NYTimes Data Loader Plugin

**Author:** Alberto Ribas  
**Context:** API integration and data loading code sample
**Stack:** Python, REST API integration, `requests`, `unittest`, mocked API responses

## What this sample demonstrates

This repository contains a small but complete API integration: a Python data loader that connects to the New York Times Article Search API, retrieves articles, transforms nested JSON responses into flat dictionaries, and yields the result in configurable batches.

The point of the sample is not the New York Times API itself. It demonstrates integration patterns that matter in enterprise automation work:

- connecting to an external REST API;
- handling API authentication through a supplied key;
- translating nested API responses into a downstream-friendly structure;
- batching results for ingestion;
- supporting incremental loading;
- exposing a dynamic schema;
- handling pagination, rate limits, and API errors;
- validating the implementation with offline unit tests.

The relevant skill is the ability to take a loosely specified API integration requirement, identify edge cases, implement the connector, document design tradeoffs, and make the result maintainable.

## Starting state

The original task provided a minimal plugin skeleton with three required methods:

- `connect()` for source setup and incremental state;
- `getDataBatch(batch_size)` for returning API results in batches;
- `getSchema()` for returning the output schema.

The required output was a list of flattened dictionaries. For example, a nested field such as:

```json
{
  "headline": {
    "main": "The main headline",
    "kicker": "..."
  }
}
```

needed to become:

```json
{
  "headline.main": "The main headline",
  "headline.kicker": "..."
}
```

The task also explicitly requested that dictionary flattening should be implemented manually, without relying on a third-party flattening library.

Bonus requirements included incremental loading and a dynamic schema derived from the flattened records.

## Target result

The finished implementation provides a working `NYTimesSource` plugin that:

1. connects to the NYTimes Article Search API;
2. sends a query and API key;
3. paginates through the API response;
4. applies rate-limit protection;
5. flattens each returned article into a single-level dictionary;
6. yields records in caller-defined batch sizes;
7. builds a dynamic schema from the keys seen in the data;
8. supports incremental loading using `pub_date` and `begin_date`;
9. includes a unit test suite using mocked API responses, so tests run offline.

## Implementation overview

### API connector

The plugin uses `requests.Session()` for connection reuse and calls the NYTimes Article Search endpoint:

```text
https://api.nytimes.com/svc/search/v2/articlesearch.json
```

The request includes:

- `api-key` for authentication;
- `q` for the search query;
- `sort=oldest` to support stable incremental loading;
- `page` for pagination;
- optional `begin_date` for incremental runs.

### Batching

`getDataBatch(batch_size)` is implemented as a generator. It accumulates flattened articles until the requested batch size is reached, then yields a list of dictionaries. If the final batch is smaller than the requested size, it is still yielded.

This keeps memory usage controlled and makes the connector suitable for downstream ingestion frameworks.

### Flattening strategy

The `flatten_dict()` function recursively flattens nested dictionaries and lists using dot notation.

Examples:

- `headline.main`
- `byline.original`
- `keywords.0.name`
- `keywords.0.value`
- `multimedia.default.url`

Lists are indexed rather than serialized. This preserves field-level access for downstream filtering, search, and schema discovery.

The function also preserves:

- `None` values;
- empty dictionaries;
- empty lists;
- primitive values.

This avoids accidental data loss during transformation.

### Dynamic schema

The schema is built dynamically by accumulating all keys seen across flattened records. This matters because API responses can be sparse: one article may contain fields that another article lacks.

`getSchema()` returns the sorted union of all observed fields after data has been consumed.

### Incremental loading

The connector supports incremental loading through `pub_date`.

When `max_inc_value` is provided, it is converted into NYTimes `begin_date` format:

```text
2026-02-14T10:03:05Z -> 20260214
2026-02-14 -> 20260214
```

The connector then requests articles from that date onward. This matches a common enterprise data-loading pattern: the framework owns state, while the connector receives the previous maximum value and translates it into the upstream API format.

### Rate limiting and retry behavior

The implementation includes:

- a 12-second delay between requests for the NYTimes free-tier rate limit;
- exponential backoff for HTTP 429 responses;
- retries for server-side errors;
- explicit authentication failures for HTTP 401 and 403;
- controlled handling of pagination boundary cases.

Fatal API errors intentionally bubble up rather than being hidden, because silent data loss is more dangerous than a failed load.

## Design Decisions

- **Array flattening:** arrays are flattened using indexed keys, such as `keywords.0.name` and `keywords.0.value`. This preserves data granularity for downstream search, filtering, and schema discovery.
- **Manual flattening:** the flattening logic is implemented directly in the solution rather than delegated to a third-party library, as required by the challenge.
- **Incremental loading:** `pub_date` is translated into the NYTimes `begin_date` parameter. The surrounding ingestion framework is expected to manage the last processed value between runs.
- **Rate limiting:** the connector includes a 12-second delay between requests and exponential backoff for HTTP 429 responses.
- **Dynamic schema:** the schema is accumulated from all keys seen across flattened articles. It is only fully populated after `getDataBatch()` has been exhausted.
- **`sort=oldest`:** results are requested oldest first to support stable incremental collection. This also avoids silent pagination issues where the API may cap results unexpectedly without an explicit sort.
- **Error handling:** authentication failures and exhausted retries bubble up intentionally instead of being swallowed. In ingestion workflows, a visible failure is safer than silent data loss.

## Assumptions

- One query is used per plugin instance. Multiple queries should be handled through multiple loader configurations.
- All fields returned by the API response should be included in the flattened output.
- The plugin itself does not persist state. Incremental tracking and deduplication are assumed to be the responsibility of the caller or ingestion framework.
- The NYTimes API key is supplied through the configuration object used by the plugin.
- Fatal API errors, such as authentication failures or exhausted retries, should halt the loader rather than return incomplete data as if the run had succeeded.
- The implementation is intended as a connector/code sample, not as a full production ingestion service.

## Known Limitations

- **Date-boundary overlap:** `begin_date` only supports `YYYYMMDD` precision. Same-day articles may be re-fetched. A production implementation should deduplicate by a stable identifier such as `uri`.
- **API result cap:** the NYTimes API caps accessible pages. For very large result sets, production loading should use date-windowing to split the query into smaller time ranges.
- **Rate limit:** the free-tier limit of roughly 5 requests per minute makes full historical loads slow. A production version should make rate-limit behavior configurable and aligned with the actual API plan.
- **State management:** the plugin does not persist state internally. This is intentional for the challenge, but a production service would define clear ownership of state, checkpointing, and deduplication.
- **Schema timing:** because the schema is derived from observed data, it is only complete after data retrieval has run across the relevant result set.

## Testing approach

The test suite uses `unittest` and mocked API responses. Tests run offline and do not require a live NYTimes API key.

The tests cover:

- nested dictionary flattening;
- lists of objects;
- lists of primitives;
- preservation of `None`, empty dictionaries, and empty lists;
- batching behavior;
- empty API responses;
- first-run behavior without `begin_date`;
- incremental runs with `begin_date`;
- dynamic schema accumulation.

This made it possible to validate edge cases without depending on network access or external API availability.

## Quick Start

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Set your API key in the `config` dictionary at the bottom of `nytimes_source.py`, then run:

```bash
python nytimes_source.py
```

## Running Tests

```bash
python -m unittest test_nytimes.py -v
```

All tests run offline using mocked API responses.

## Dependencies

- `requests` HTTP client

The `requirements.txt` file contains:

```text
requests>=2.28.0,<3.0.0
```

## Why this is relevant

This sample maps directly to the type of work required in an internal automation layer:

- integrate with external APIs;
- normalize inconsistent upstream data;
- produce predictable downstream structures;
- handle errors, retries, rate limits, and pagination;
- keep transformations auditable and testable;
- document assumptions and limitations clearly;
- build something small enough to move fast, but structured enough to maintain.
