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
| **STAR Rules** | View, export and import custom detection rules, per scope |
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

## STAR Rules Page

**Account** and **Site** set the scope for everything this page does. Leave both blank for the tenant (global) scope; name an Account to work inside it, and add a Site to narrow further.

- **Load STAR Rules** — read the custom detection rules visible at that scope
- **Export to JSON** — save the loaded rules as raw JSON
- **Import from JSON** — create those rules at that scope. Each rule is prepared the same way a migration restore prepares it: read-only fields removed, nulls dropped, and an expiration outside the next six months pulled back into range

Scope matters most on import. An API token that is scoped to an account or a site **cannot create a rule at the tenant**; the console answers *"User …:account can not create rule with higher scope None:tenant"* and nothing is created. Name the Account (and Site) to import into. If the token can reach exactly one account, the import moves there by itself and says so; when it can reach several, only you can say which one, so the error is reported instead.

## Tags Page

Answers "the restore said it created tags — are they really there?", which a restore report cannot: the report only knows what the API accepted.

**Run Audit** (read-only) walks the tenant and every account/site matching the filters and lists what the console holds, from both APIs that back the word "tag":

- `GET /tags` — named tags for **firewall**, **network-quarantine** and **device-inventory** (Ranger)
- `GET /agents/tags`, falling back to `GET /tag-manager` — unified **endpoint tags** (Tag Manager), key/value pairs. Both are tried because a console that doesn't serve the first must not be reported as holding no tags; the summary names the route that answered.

Because `GET /tags` returns everything *visible* at a scope, including tags inherited from a parent account or the tenant, each scope's own tags are listed separately from inherited ones — tick **Show inherited tags** to see both. **Include group scopes** is off by default: groups inherit their site's tags and it costs a request per group.

| Column | Meaning |
|--------|---------|
| `scope` | Account, or account/site, that was queried |
| `level` | `global` (tenant), `account`, `site` or `group` |
| `type` | `firewall`, `network-quarantine`, `device-inventory` or `endpoint` |
| `tag` | Tag name, or `key=value` for endpoint tags |
| `owned` | `own` = belongs to this scope; `inherited` = comes from a parent |

**Diagnose endpoint tags** — *this one writes* — is for when a restore reports endpoint tags as created and the console shows none. `POST /tag-manager` answers `200` to a request body it doesn't store, so the only way to know is to write and read back. It creates a throwaway tag per candidate request format (key `s1cc-probe-…`), looks for it on every known listing route, and deletes what it finds. The console's own response body is recorded for each format, because that is what separates the last two outcomes:

- **a format that works** — creation is fine on this console; the report names the format and the route that could read it back
- **stored, but not at the requested scope** — the scope filter was ignored; look tenant-wide
- **the console claims a create that nothing can read** — the write probably worked and the tool is listing the wrong route. Search the console's own tag list for `s1cc-probe-…`: if the keys are there, this is a read problem, not a write problem — and those tags need deleting by hand, because the cleanup can only delete what it can find
- **nothing was stored and nothing was claimed** — the console accepted and discarded every shape. Check the token's `Tag Management` create permission and whether the route is enabled for the tenant

At the end you're offered a report containing each format, its outcome and the console's raw response — that file is what to send when asking someone else to look.

## Raw API Page

Send arbitrary API requests:

1. Select method: `GET`, `POST`, `PUT`, `DELETE`
2. Enter endpoint (e.g. `/agents`, `/threats`)
3. Optionally provide a JSON body
4. Click **Send Request**

For `GET`, the JSON body is used as query parameters. For other methods, it's the request body.
