# Purple AI

The Purple AI page lets you query SentinelOne's SDL telemetry using natural language. Purple AI translates your question into a Power Query and returns a human-readable summary.

## How It Works

1. Type a question in plain English
2. Select a **View** (data domain) and **time window**
3. Click **🟣 Ask Purple AI**
4. Get back: summary text + generated Power Query + suggested follow-ups

Under the hood, this calls the undocumented GraphQL endpoint at `POST /web/api/v2.1/graphql` using the `purpleLaunchQuery` operation.

## View Selectors

| View | Data Domain |
|------|-------------|
| **EDR** | Endpoint detection — process, file, network events |
| **IDENTITY** | Identity-related telemetry |
| **CLOUD** | Cloud workload events |
| **NGFW** | Next-generation firewall events |
| **DATA_LAKE** | All ingested data sources |

## Example Questions

- "Show powershell.exe outbound connections in the last 24h, top 10"
- "Find processes that modified registry run keys yesterday"
- "List all DNS queries to suspicious domains in the past 7 days"
- "Show failed login attempts from external IPs"

## Response Fields

| Field | Description |
|-------|-------------|
| **Summary** | Brief AI-generated summary |
| **Message** | Full response text |
| **Power Query** | Generated S1QL/PQ query |
| **View Selector** | Which data domain was actually queried |
| **Time Range** | Epoch timestamps of the query window |
| **Suggested Questions** | Clickable follow-up suggestions |

## Suggested Questions

Purple AI returns up to 3 follow-up suggestions. Click any suggestion to auto-fill the question box and re-query.

## Requirements

- **Purple AI entitlement** on the tenant
- API token's role must have Purple AI permission
- Works on SOURCE console (auto-selected when page opens)

## Domain Boundary

Purple AI answers questions about **SDL telemetry** only:
- ✅ Process, network, file events
- ✅ Indicators
- ✅ Ingested third-party logs
- ❌ NOT console entities (alerts, threats, agents, sites, policies) — use the REST pages or [[Unified Alerts]] for those

## Error Handling

| Error | Cause |
|-------|-------|
| `errorType: ENTITLEMENT` | Tenant lacks Purple AI license |
| `errorType: PERMISSION` | Token's role can't use Purple AI |
| GraphQL error | Malformed query (shouldn't happen via the GUI) |
