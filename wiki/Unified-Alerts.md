# Unified Alerts

The Unified Alerts page provides modern multi-source alert triage via the SentinelOne Unified Alert Management (UAM) GraphQL API.

## Why Unified Alerts?

The legacy Threats page uses the REST `/threats` endpoint. Unified Alerts is the modern replacement:

| Feature | Legacy Threats | Unified Alerts |
|---------|---------------|----------------|
| API | REST `/threats` | GraphQL `/unifiedalerts/graphql` |
| Sources | EDR only | EDR + Cloud + Identity + STAR + 3rd party |
| Facets | Manual filtering | Built-in faceted counts |
| Triage | Limited | Bulk status + verdict + assign |
| Pagination | Cursor-based | Cursor-based (GraphQL edges) |
| Export | JSON only | Native CSV export |

## Features

### Alert Listing
- Filter by **Status** (NEW, IN_PROGRESS, RESOLVED)
- Filter by **Severity** (LOW, MEDIUM, HIGH, CRITICAL)
- Filter by **View** (ALL, ENDPOINT, IDENTITY, CLOUD, STAR, THIRD_PARTY)
- Configurable page size
- **Next Page** button for cursor pagination

### Facets
Click **Facets** to see distribution counts for:
- Severity breakdown
- Status breakdown
- Detection product breakdown

### Alert Detail
Enter an alert ID to access:
- **Detail** — Full alert with assets, data sources
- **Notes** — Read analyst notes
- **History** — Audit trail of all changes
- **Timeline** — Event timeline

### Triage Actions
- **→ Resolve** — Set selected alerts to RESOLVED
- **→ In Progress** — Set to IN_PROGRESS
- Works on a single alert (by ID) or all loaded alerts

### CSV Export
Click **Export CSV** to download all matching alerts as a CSV file via the server-side `alertsCsvExport` query.

## GraphQL Queries Used

| Action | GraphQL Operation |
|--------|-------------------|
| List alerts | `alerts` query |
| Get single alert | `alert` query |
| Facets | `alertGroupByCount` query |
| Notes | `alertNotes` query |
| History | `alertHistory` query |
| Timeline | `alertTimeline` query |
| Triage | `alertTriggerActions` mutation |
| CSV export | `alertsCsvExport` query |

## API Methods

All UAM methods are on the `S1API` class:

| Method | Purpose |
|--------|---------|
| `uam_list_alerts()` | Paginated alert listing |
| `uam_get_alert()` | Single alert with assets |
| `uam_facets()` | Faceted counts |
| `uam_alert_notes()` | Read notes |
| `uam_add_note()` | Create a note |
| `uam_alert_history()` | Audit trail |
| `uam_alert_timeline()` | Event timeline |
| `uam_set_status()` | Bulk status change |
| `uam_set_verdict()` | Bulk analyst verdict |
| `uam_export_csv()` | CSV export |

## Requirements

- UAM must be enabled on the tenant
- API token needs alert read/write permissions
- Works on SOURCE console (auto-selected when page opens)
