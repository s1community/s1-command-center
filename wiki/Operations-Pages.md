# Operations Pages

Beyond backup/restore, S1 Command Center includes 16 operations pages for day-to-day console management.

## Page List

| Page | Description |
|------|-------------|
| **Accounts & Sites** | Browse accounts → sites → groups hierarchy |
| **Agents** | List, filter, scan, abort scan, uninstall agents |
| **Threats** | View threats, timeline, and analyst notes |
| **Unified Alerts** | Modern GraphQL-based alert triage (see [[Unified Alerts]]) |
| **Purple AI** | Natural language SDL queries (see [[Purple AI]]) |
| **Exclusions & Block** | Manage exclusions and blocklist entries |
| **STAR Rules** | View and manage custom detection rules |
| **Users & Roles** | RBAC management, 2FA enrollment, token details |
| **Activities** | Audit log viewer with type filtering |
| **Deep Visibility** | DV query execution and saved filter management |
| **Apps & CVEs** | Application inventory and CVE lookup |
| **Threat Intel** | IOC indicator management |
| **Ranger & Rogues** | Network discovery and rogue device detection |
| **Remote Scripts** | Script library and bulk task management |
| **Tags** | Audit every tag a console actually holds, and diagnose endpoint tag creation |
| **Raw API** | Direct GET/POST/PUT/DELETE to any S1 endpoint |

## Common Features

All operations pages share:

- **Console selector** — Operate on SOURCE or DESTINATION
- **Export Report** — Save results as HTML, Excel, or JSON
- **CLI Output** — All actions log to the global output console
- **Async execution** — API calls run in background threads, UI stays responsive

## Agents Page

- **List Agents** — Fetch with name/site filters (up to 500)
- **Count** — Fast count-only query
- **Init Scan** — Trigger full disk scan on selected agents
- **Abort Scan** — Cancel running scans
- **Uninstall** — Queue agent removal (with confirmation)

## Threats Page

- **Load Threats** — Fetch recent threats (up to 200)
- **Timeline** — View attack timeline for a specific threat ID
- **Notes** — View analyst notes on a threat

## Tags Page

Answers "the restore said it created tags — are they really there?", which a restore report cannot: the report only knows what the API accepted.

**Run Audit** (read-only) walks the tenant and every account/site matching the filters and lists what the console holds, from both APIs that back the word "tag":

- `GET /tags` — named tags for **firewall**, **network-quarantine** and **device-inventory** (Ranger)
- `GET /agents/tags` — unified **endpoint tags** (Tag Manager), key/value pairs

Because `GET /tags` returns everything *visible* at a scope, including tags inherited from a parent account or the tenant, each scope's own tags are listed separately from inherited ones — tick **Show inherited tags** to see both. **Include group scopes** is off by default: groups inherit their site's tags and it costs a request per group.

| Column | Meaning |
|--------|---------|
| `scope` | Account, or account/site, that was queried |
| `level` | `global` (tenant), `account`, `site` or `group` |
| `type` | `firewall`, `network-quarantine`, `device-inventory` or `endpoint` |
| `tag` | Tag name, or `key=value` for endpoint tags |
| `owned` | `own` = belongs to this scope; `inherited` = comes from a parent |

**Diagnose endpoint tags** — *this one writes* — is for when a restore reports endpoint tags as created and the console shows none. `POST /tag-manager` answers `200` to a request body it doesn't store, so the only way to know is to write and read back. It creates a throwaway tag per candidate request format (key `s1cc-probe-…`), re-reads each, and deletes them again, then reports one of:

- **a format that works** — creation is fine on this console
- **stored, but not at the requested scope** — the scope filter was ignored; look tenant-wide
- **nothing was stored** — the console accepts and discards every shape, which is what an API token without `Tag Management.create` looks like. Check the token first.

Anything it fails to delete is named in the output so you can remove it by hand.

## Raw API Page

Send arbitrary API requests:

1. Select method: `GET`, `POST`, `PUT`, `DELETE`
2. Enter endpoint (e.g. `/agents`, `/threats`)
3. Optionally provide a JSON body
4. Click **Send Request**

For `GET`, the JSON body is used as query parameters. For other methods, it's the request body.
