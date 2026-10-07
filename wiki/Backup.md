# Backup

The Backup page reads the full configuration hierarchy from a console and saves it as a portable JSON file.

## Workflow

1. **Select console** — SOURCE (default) or DESTINATION
2. **Choose levels** — Global, Accounts, Sites, Groups
3. **Filter scope** — Optionally filter by account/site/group name (substring match)
4. **Select elements** — 26 element types, all checked by default
5. **Start** — Discovers structure, then reads each node in sequence
6. **Save** — Writes JSON to the chosen path

## Console Selection

You can backup from either console:

| Selection | Use Case |
|-----------|----------|
| **SOURCE** (default) | Normal pre-migration backup |
| **DESTINATION** | Snapshot destination before restore (safety net) |

Selecting DESTINATION shows a confirmation dialog since it's non-standard.

## Levels

| Level | What It Captures |
|-------|-----------------|
| **Global** | Tenant-wide configuration (rare — prompts for confirmation) |
| **Accounts** | Per-account config (policy, exclusions, settings, roles, etc.) |
| **Sites** | Per-site config (most common migration scope) |
| **Groups** | Per-group config (policy, exclusions, firewall, device control) |

## Scope Filters

All filters are **substring match** (case-insensitive):

- **Account Name** — Only backup accounts whose name contains this text
- **Site Name** — Only backup sites whose name contains this text
- **Group Name** — Only backup groups whose name contains this text

Leave blank = all.

## Elements

See [[Supported Elements]] for the full list of 26 element types.

The elements section is collapsible. Use **Select All / Deselect All** for quick toggling. Click the ⓘ icon next to any element for a description.

## Progress Table

Nodes are grouped into a card per site; the account and global settings get cards of their own. Each card shows a done/total count and a small bar, groups are numbered 1, 2, 3 inside their site, and a strip on top totals the run. Click a card to fold or unfold it (**Fold all** does every card); when something failed, **Show failed only** hides everything that went through. Hover a row for its full path and the whole message.

Each node's row carries a live status:

| Status | Color | Meaning |
|--------|-------|---------|
| `waiting` | Gray | Queued, not yet started |
| `running` | Blue | Currently reading from API |
| `done` | Green | Completed, with element summary |
| `failed` | Red | Failed with error message |
| `skipped` | Dark gray | Skipped (level unchecked or cancelled) |

## Output

The backup JSON file contains an array of nodes:

```json
[
  {
    "path": "AccountName/SiteName",
    "type": "site",
    "site": { /* original site object */ },
    "policyInheritanceBroken": false,
    "data": {
      "policy": { ... },
      "exclusions": { "white_hash": [...], "path": [...], ... },
      "restrictions": [...],
      "firewall": { "config": {...}, "rules": [...] },
      ...
    }
  }
]
```

## Stop & Cancel

Click **■ Stop** to cancel a running backup. The current node finishes, then remaining nodes are marked as `cancelled`. Nodes already completed are preserved in the output file.
