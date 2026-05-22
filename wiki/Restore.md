# Restore

The Restore page pushes backup data to the DESTINATION console, recreating the entire configuration hierarchy.

## Workflow

1. **Load backup** — Auto-loads the latest backup, or browse for a file
2. **Set Defaults** (optional) — Edit `isDefault`, `expiration`, `unlimitedLicenses` on accounts/sites
3. **Filter scope** — Target specific accounts, sites, or groups
4. **Mangle rename** (optional) — Rename source paths → destination paths
5. **Restore** — Resolves structure, then pushes config node by node
6. **Export report** — Professional HTML report with full detail

## Auto-load

If a backup was just completed, the file path carries over automatically. Otherwise, click **Browse** to select a JSON file.

## Set Defaults Dialog

Opens a table editor for the backup file. Editable fields per account/site/group:

| Field | Type | Purpose |
|-------|------|---------|
| `isDefault` | Checkbox | Mark as default site |
| `expiration` | Text | License expiration date |
| `unlimitedExpiration` | Checkbox | Never expire |
| `unlimitedLicenses` | Checkbox | Unlimited agent licenses |

Bulk buttons: **∞ Exp ON/OFF**, **∞ Lic ON/OFF** to set all at once.

## Mangle Rename

Renames account/site/group paths in the backup data before restoring:

| Source (from backup) | Destination (on target) |
|---------------------|------------------------|
| `OldCorp/Production` | `NewCorp/Production` |
| `OldCorp` | `NewCorp` |

The mangle is auto-filled when you use **Paste from Ticket**.

## Structure Resolution

Before restoring config, the app resolves the destination structure:

1. **Find or create accounts** — Matches by name, creates if missing
2. **Find or create sites** — Matches by name under the account
3. **Find or create groups** — Matches by name under the site
4. **Map scope IDs** — Translates source IDs → destination IDs

### Smart Handling

- **Default site override** — Detects existing default sites and prompts to rename
- **Zombie site detection** — If a site returns 404, offers to map to the default site
- **SKU mismatch** — Detects license bundle differences (e.g. Core vs Complete) and offers to fix

## Restore Order

For each node, elements are restored in this order:

1. Policy
2. Exclusions (all 5 types)
3. Blocklist
4. Firewall config → rules → reorder
5. Network quarantine config → rules
6. Device control config → rules → reorder
7. Tags (firewall, NQ, endpoint)
8. STAR rules
9. Saved filters
10. Threat intel (batched)
11. Config overrides
12. Log collection rules
13. Auto-upgrade policies
14. Settings (notifications, SSO, SMTP, syslog, AD)
15. Roles & service users
16. Group ranking

## Duplicate Detection

The restore skips items that already exist on the destination:

| Element | Detection Method |
|---------|-----------------|
| Exclusions | Match by `type` + `value` |
| Blocklist | Match by hash value |
| STAR rules | Match by rule name |
| Saved filters | Match by filter name |
| Firewall rules | Match by rule name |
| Tags | Match by tag name |

## Progress Table

Same color-coded table as Backup — see [[Backup#Progress Table]].

Each node shows a detailed summary: `policy, excl:12, block:5, fw:3, star:8, …`

## Export Report

Click **Export Log** after restore completes. Available formats:

- **HTML** — Professional dark-themed report (recommended)
- **JSON** — Structured data for automation
- **Excel** — Spreadsheet with all nodes and elements

See [[Reports]] for details.
