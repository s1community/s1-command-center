# API Client

The `S1API` class in `s1_api.py` wraps the SentinelOne Management Console API v2.1 with production-grade HTTP handling.

## Architecture

```
S1API
├── Transport Layer
│   ├── Connection pooling (HTTPAdapter, pool_maxsize=32)
│   ├── Unified _request() with retry logic
│   ├── 429/5xx retry with Retry-After header support
│   └── Connection error retry (4 attempts, exponential backoff)
├── Pagination
│   ├── get_all() — cursor-based, collects all pages
│   └── get_data() — single page, returns data field
├── Parallel Fan-out
│   └── get_many() — ThreadPoolExecutor for concurrent GETs
├── GraphQL
│   ├── _gql() — core GraphQL transport
│   ├── purple_query() — Purple AI natural language
│   └── uam_*() — Unified Alert Management
└── 60+ Domain Methods
    ├── Backup: get_policy, get_exclusions, get_firewall_rules, ...
    ├── Restore: set_policy, create_exclusion, create_firewall_rule, ...
    ├── Agents: get_agents, migrate_agent, initiate_scan, ...
    └── Threats, Activities, DV, Ranger, Scripts, ...
```

## Connection Pooling

The session uses `HTTPAdapter` with a pool of 32 connections:

```python
adapter = HTTPAdapter(
    pool_connections=32,
    pool_maxsize=32,
    pool_block=False,
)
session.mount("https://", adapter)
```

This reuses TCP sockets across sequential and parallel calls — critical when backup/restore makes hundreds of API calls to the same host.

## Retry Logic

All HTTP methods (GET, POST, PUT, DELETE) use a unified `_request()` with:

| Condition | Behavior |
|-----------|----------|
| **200, 201** | Success — return JSON |
| **429 (Rate Limit)** | Retry with `Retry-After` header (or 1.5× backoff) |
| **5xx (Server Error)** | Retry with exponential backoff |
| **4xx (Client Error)** | Fail immediately (no retry) |
| **Connection error** | Retry up to 4 times with 1.5×, 3×, 4.5× backoff |

## Parallel Fan-out

`get_many()` runs independent GETs concurrently:

```python
results = api.get_many([
    ("/accounts", {"limit": 5}),
    ("/system/info", None),
    ("/agents", {"countOnly": "true"}),
], max_workers=8)

for r in results:
    if r["ok"]:
        print(r["data"])
    else:
        print(r["error"])
```

Returns results in input order. Each result has: `endpoint`, `params`, `ok`, `data`, `error`, `elapsed_ms`.

Thread-safe: the pooled session handles concurrent access when `pool_maxsize ≥ max_workers`.

## GraphQL

The `_gql()` method provides shared transport for Purple AI and UAM:

```python
def _gql(self, path, query, variables=None):
    body = {"query": query}
    if variables:
        body["variables"] = variables
    resp = self._post(path, body=body)
    if resp.get("errors"):
        raise S1APIError(...)
    return resp
```

- **Purple AI**: `POST /web/api/v2.1/graphql`
- **UAM**: `POST /web/api/v2.1/unifiedalerts/graphql`

## Error Handling

All errors raise `S1APIError`:

```python
class S1APIError(Exception):
    message: str        # Human-readable error
    status_code: int    # HTTP status (0 for connection errors)
    detail: str         # API error detail
```

The GUI catches these and displays them in the output console with appropriate severity levels.
