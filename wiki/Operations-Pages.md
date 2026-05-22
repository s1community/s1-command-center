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
| **Tags** | Tag management across all tag types |
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

## Raw API Page

Send arbitrary API requests:

1. Select method: `GET`, `POST`, `PUT`, `DELETE`
2. Enter endpoint (e.g. `/agents`, `/threats`)
3. Optionally provide a JSON body
4. Click **Send Request**

For `GET`, the JSON body is used as query parameters. For other methods, it's the request body.
