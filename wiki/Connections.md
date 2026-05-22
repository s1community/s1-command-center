# Connections

The Connections page manages your SOURCE and DESTINATION console credentials.

## Concepts

| Role | Purpose | Color |
|------|---------|-------|
| **SOURCE** | Console to backup/read from | 🟢 Green |
| **DESTINATION** | Console to restore/write to | 🔴 Red |

Both connections are saved to `~/.s1-command-center/contexts.json` and auto-reconnect on startup.

## Connection Fields

| Field | Required | Notes |
|-------|----------|-------|
| **Name** | Yes | Friendly name for the sidebar display |
| **URL** | Yes | Full URL (`https://usea1-021.sentinelone.net`) or short name (`usea1-021`) |
| **API Token** | Yes | Service User token from the console |

Short names are auto-expanded: `usea1-021` → `https://usea1-021.sentinelone.net`

## Actions

- **Test** — Verify credentials by calling `/my-user`
- **Save & Connect** — Store credentials and activate as SOURCE or DESTINATION
- **Delete** — Remove a saved connection
- **Context List** — Refresh the saved connections table

## Paste from Ticket

Parses clipboard text and fills **all pages** at once:

| Clipboard Key | Fills |
|---------------|-------|
| `Source console:` | SOURCE name |
| `URL:` | SOURCE url |
| `Token1:` | SOURCE token |
| `Target Console:` | DESTINATION name |
| `URL2:` | DESTINATION url |
| `Token2:` | DESTINATION token |
| `Source Site:` | Backup site filter |
| `Target Account:` | Restore account filter + mangle rename |

## Reset All

Clears **everything** across all pages:
- Connection entries and status
- Backup filters and progress
- Restore data, mangle fields, progress
- Output console

Use this to start a completely fresh migration.
