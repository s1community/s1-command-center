<h1 align="center">🛡️ S1 Command Center</h1>

<p align="center">
  <strong>A professional GUI tool for SentinelOne console management, backup, restore, and migration.</strong>
</p>

<p align="center">
  <a href="https://github.com/s1community/s1-command-center/releases/latest">
    <img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Download-macOS_%26_Windows-00b894?style=for-the-badge&logo=github&logoColor=white" alt="Download"/>
  </a>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#backup--restore">Backup & Restore</a> •
  <a href="#troubleshooting">Troubleshooting</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#changelog">Changelog</a> •
  <a href="#license">License</a>
</p>

---

## Overview

**S1 Command Center** is a desktop application built for SentinelOne engineers and administrators to manage, migrate, and audit SentinelOne console configurations. It provides a visual interface for operations that typically require CLI tools or direct API calls.

Built with Python and CustomTkinter, it delivers a modern dark-themed UI with real-time progress tracking, detailed reporting, and full audit trails.

## Features

### Console Management
- **Dual Console Connections** — Connect to SOURCE and DESTINATION consoles simultaneously
- **Paste from Ticket** — One-click import of migration ticket fields into all pages
- **Auto-connect** — Automatically reconnects to saved consoles on startup
- **Reset All** — Clear all fields and start a fresh migration in one click

### Backup
- **Full Configuration Backup** — Captures policies, exclusions, blocklist, firewall rules, device control, STAR rules, tags, threat intel, settings, and more
- **26 Element Types** — Comprehensive coverage of all SentinelOne configuration elements
- **Scope Filtering** — Backup specific accounts, sites, or groups by name
- **Level Selection** — Choose to backup Global, Accounts, Sites, and/or Groups
- **Collapsible Elements** — Select exactly which elements to include
- **Live Progress Table** — Real-time status updates for each node being backed up
- **Timer & Progress Bar** — Track backup duration and completion
- **Stop Button** — Cancel a running backup at any time

### Restore
- **Smart Auto-load** — Automatically loads the latest backup file
- **Mangle Rename** — Rename accounts, sites, or groups in the backup before restoring
- **Auto Target Context** — Automatically sets the restore target on start
- **SKU Mismatch Detection** — Detects license bundle conflicts and offers to fix them automatically
- **Duplicate Detection** — Identifies existing items and skips them (exclusions, blocklist, hashes, STAR rules, filters)
- **Auto-create Sites & Groups** — Automatically creates missing sites and groups on the destination
- **Group Ranking** — Preserves group priority order after restore
- **Expired STAR Rules** — Automatically extends expired rule dates
- **Expired/Deleted Skip** — Skips expired or deleted sites and accounts
- **Live Progress Table** — Color-coded status for each node
- **Detailed Error Reporting** — Shows exact API errors for every failed item

### Reports
- **HTML Restore Report** — Professional dark-themed report with:
  - Summary statistics cards (nodes restored, skipped, errors, elements created)
  - Connection info (source/destination URLs, timestamps, duration)
  - Per-node element breakdown with colored status badges
  - **Failed Items Table** — Every individual un-restored item with name, value, and exact error
  - Errors & warnings section
  - Collapsible full operation log
- **JSON Export** — Structured data for programmatic analysis
- **Export Log** — Available after restore completes

### Operations Pages
- **Accounts & Sites** — Browse and manage console structure
- **Agents** — View and manage endpoints
- **Threats** — Monitor and respond to threats
- **Exclusions & Blocklist** — Manage allow/block lists
- **STAR Rules** — Custom detection rules management
- **Users & Roles** — RBAC management
- **Activities** — Audit log viewer
- **Deep Visibility** — Query and filter management
- **Apps & CVEs** — Application inventory and vulnerabilities
- **Threat Intel** — IOC management
- **Ranger & Rogues** — Network discovery
- **Remote Scripts** — Script library management
- **Tags** — Tag management
- **Raw API** — Direct API access for any endpoint

## Installation

### Prerequisites
- **Python 3.10+** (tested on 3.11, 3.12, 3.13)
- **macOS**, **Windows**, or **Linux**

### Setup

```bash
# Clone the repository
git clone https://github.com/s1community/s1-command-center.git
cd s1-command-center

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

### Dependencies
| Package | Purpose |
|---------|---------|
| `customtkinter` | Modern dark-themed GUI framework |
| `requests` | HTTP client for SentinelOne API |
| `openpyxl` | Excel report generation |
| `Pillow` | Image handling |

## Quick Start

### 1. Connect Consoles

Launch the app and go to **Connections**. Enter your SOURCE and DESTINATION console details:

| Field | Description |
|-------|-------------|
| **Name** | Friendly name (e.g. "Production US") |
| **URL** | Console URL or short name (e.g. `usea1-021` or `https://usea1-021.sentinelone.net`) |
| **API Token** | Service User API token with appropriate permissions |

Click **Save & Connect** for each console.

> **Pro Tip:** Copy a migration ticket to your clipboard and click **Paste from Ticket** to auto-fill all fields across all pages.

### 2. Backup Source

Navigate to **Backup Source**:
1. Select which levels to backup (Accounts, Sites, Groups)
2. Optionally filter by account/site/group name
3. Choose elements to include (or leave all checked)
4. Click **▶ Start Backup**
5. Save the JSON file when prompted

### 3. Restore to Destination

Navigate to **Restore to Dest**:
1. The latest backup file loads automatically
2. Expand **Structure Operations** if you need to rename accounts/sites
3. Set restore scope and filters
4. Click **▶ Restore Now**
5. Click **Export Log** for a detailed HTML report

## Backup & Restore

### Supported Elements

| Element | Backup | Restore | Notes |
|---------|:------:|:-------:|-------|
| Policy | ✅ | ✅ | Full policy configuration |
| Exclusions | ✅ | ✅ | All types: hash, path, file type, certificate, browser |
| Blocklist | ✅ | ✅ | SHA1 and SHA256 hashes |
| Firewall Config | ✅ | ✅ | Global firewall settings |
| Firewall Rules | ✅ | ✅ | With rule ordering preserved |
| Device Control Config | ✅ | ✅ | Requires appropriate permissions |
| Device Control Rules | ✅ | ✅ | With rule ordering preserved |
| Network Quarantine | ✅ | ✅ | Config and rules |
| Tags (Firewall) | ✅ | ✅ | Firewall classification tags |
| Tags (NQ) | ✅ | ✅ | Network quarantine tags |
| Tags (Endpoint) | ✅ | ✅ | Device inventory tags |
| STAR Rules | ✅ | ✅ | Custom detection rules, auto-fixes expired dates |
| Saved Filters | ✅ | ✅ | Deep Visibility saved queries |
| Threat Intel | ✅ | ✅ | IOCs (batched, up to 5000) |
| Config Overrides | ✅ | ✅ | Configuration override settings |
| Notification Settings | ✅ | ✅ | Alert notification config |
| SSO Settings | ✅ | ✅ | Single sign-on configuration |
| SMTP Settings | ✅ | ✅ | Email server settings |
| Syslog Settings | ✅ | ✅ | Syslog forwarding config |
| AD Settings | ✅ | ✅ | Active Directory integration |
| RBAC Roles | ✅ | ✅ | Role-based access control |
| Service Users | ✅ | ✅ | API service accounts |
| Log Collection Rules | ✅ | ✅ | Log collection configuration |
| Auto-upgrade Policies | ✅ | ✅ | Agent upgrade policies |
| Gateways | ✅ | ✅ | Gateway configurations |
| Group Ranking | ✅ | ✅ | Group priority order per site |

### Error Handling

The restore process handles common issues automatically:

- **Duplicate items** → Detected and skipped (shown as "exist" in report)
- **License bundle mismatch** → Prompts to fix SKU references (e.g. Core → Complete)
- **Expired STAR rules** → Auto-extends expiration to 1 year from now
- **Expired/deleted sites** → Automatically skipped
- **Missing sites/groups** → Auto-created on destination
- **Read-only fields** → Stripped before sending to API

## Troubleshooting

### macOS — "App is not from an identified developer"

If macOS blocks the app on first launch, authorize it through System Preferences:

1. Click the **Apple Menu ()** in the top-left corner and select **System Settings** (or System Preferences)
2. Navigate to **Privacy & Security**
3. Scroll down to the **Security** section
4. You should see a message: *"S1 Command Center" was blocked from use because it is not from an identified developer*
5. Click **Open Anyway**
6. Enter your Mac password or use Touch ID when prompted
7. Click **Open** on the final confirmation pop-up

> After this one-time step, the app will open normally going forward.

### Connection Errors

- **"Connection refused — invalid or expired API token"** → Verify the API token is correct and not expired. Generate a new one from the console if needed.
- **"Cannot reach console"** → Check the URL is correct (e.g. `usea1-021` or full `https://usea1-021.sentinelone.net`).

### Backup Returns 0 Nodes

- Verify the SOURCE console is connected (check the sidebar indicators)
- Check your account/site name filters — they must match exactly
- Make sure the API token has sufficient permissions (Admin role recommended)

### Restore — Site Returns 404

- A previous failed restore may have created a broken/phantom site. The app will detect this and offer to use the existing default site instead.
- If issues persist, check the destination console for duplicate or expired sites.

## Architecture

```
s1-command-center/
├── main.py           # Entry point
├── app.py            # Main window, sidebar, connections page, CLI output
├── pages.py          # Backup & Restore pages, progress table, report generator
├── pages_extra.py    # Operations pages (agents, threats, exclusions, etc.)
├── s1_api.py         # SentinelOne REST API client
├── config.py         # Configuration/context manager (saved connections)
├── export_utils.py   # HTML & Excel report generation
├── requirements.txt  # Python dependencies
└── s1cc.ico          # Application icon
```

### API Client (`s1_api.py`)

The `S1API` class wraps the SentinelOne Management API v2.1 with:
- Automatic pagination for large datasets
- Retry logic with exponential backoff (skips 4xx client errors)
- Structured error handling with `S1APIError`
- Methods for all backup/restore operations

### Configuration (`config.py`)

Connections are stored in `~/.s1-command-center/contexts.json` with:
- Console name, URL, and API token
- Role assignment (source/destination)
- Automatic save on changes

## API Token Requirements

The API token needs these minimum permissions for full backup/restore:

| Permission | Required For |
|-----------|-------------|
| `Accounts.view` | Reading account structure |
| `Sites.view`, `Sites.create` | Reading/creating sites |
| `Groups.view`, `Groups.create`, `Groups.edit` | Reading/creating/reordering groups |
| `Policy.view`, `Policy.edit` | Backup/restore policies |
| `Exclusions.view`, `Exclusions.create` | Backup/restore exclusions |
| `Restrictions.view`, `Restrictions.create` | Backup/restore blocklist |
| `Firewall.view`, `Firewall.create` | Backup/restore firewall rules |
| `DeviceControl.view`, `DeviceControl.edit` | Backup/restore device control |
| `STAR.view`, `STAR.create` | Backup/restore custom rules |
| `Settings.view`, `Settings.edit` | Backup/restore settings |
| `Tags.view`, `Tags.create` | Backup/restore tags |
| `ThreatIntelligence.view`, `ThreatIntelligence.create` | Backup/restore IOCs |

> **Recommendation:** Use a Service User with **Admin** role for full access.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -am 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## Changelog

### v1.3.0 — 2026-05-22
#### New Features
- **Live DiffPanel on Restore page** — Side-by-side comparison of every backup node vs the live destination console. Shows identity (type, filterId/filterName, inherits, etc.) and per-element counts + sample names. Snapshots the destination before and after each node during restore so the operator can see exactly what changed.
- **Pinned-group preservation** — Groups with `type=pinned` on the source are now created as Pinned on the destination. Existing groups are converted via a multi-endpoint fallback chain with post-call verification.
- **Dynamic-group restoration by filter name** — Backup back-fills `filterName` on every dynamic group from the source console. Restore resolves the source filter name to the destination's matching saved-filter ID and binds the group accordingly. Per-site cache prevents repeated `/filters` lookups.
- **Resizable progress UI** — Progress table and DiffPanel sit in a draggable `PanedWindow`. Rows are numbered, paths shortened with hover-tooltips, Details column wraps, table auto-scrolls to the active row, mouse-wheel events propagate from any child widget.

#### Fixes
- **Dynamic groups silently restored as static** — `_resolve_dest_id` now overwrites an existing destination group's `filterId` when the source is dynamic and the destination is static.
- **`PUT /groups/{id}` rejects `type` field** — Restore no longer sends `type` on group updates (S1 infers it from `filterId` presence). Fixes `4000010 Validation Error :: data: type: Unknown field`.
- **Group create with `inherits=false`** — Now always creates with `inherits=true`; the per-node policy step decouples and pushes the source policy a moment later. Fixes `4000010 Policy should be delivered if it is not inherited`.
- **Config overrides rejected for missing scope** — Re-injects `data.scope` after `_clean_for_restore` strips it.
- **Unrecognised exclusion errors** — S1 API error extractor now reads `title + detail + code` from every error object. Per-item failure records keep the full message.
- **DV / saved-filter drift across consoles** — Restore matches by name against the destination's filters per site and substitutes the destination ID.

### v1.2.0 — 2026-05-08
#### New Features
- **Purple AI Page** — Natural language queries against SDL telemetry via GraphQL. Supports EDR, IDENTITY, CLOUD, NGFW, DATA_LAKE view selectors with configurable time windows and clickable suggested follow-up questions.
- **Unified Alerts Page** — Modern multi-source alert triage via UAM GraphQL API. Filter by status/severity/view, paginated listing, faceted counts, alert detail/notes/history/timeline, bulk triage (Resolve/In Progress), CSV export.
- **Connection Pooling** — `HTTPAdapter` with pool of 32 connections for better socket reuse during backup/restore.
- **429/5xx Retry** — All HTTP methods retry on rate limit (429) and server errors (5xx), honoring `Retry-After`.
- **Parallel Fan-out** — `get_many()` for concurrent independent GETs via ThreadPoolExecutor.
- **GraphQL Transport** — Shared `_gql()` method for Purple AI and Unified Alert Management.

### v1.1.2 — 2026-05-07
- DMG installer now includes an **Install & Launch** script that auto-removes the macOS quarantine flag
- Added a comprehensive **Troubleshooting** section to the README (macOS auth, connection errors, common issues)

### v1.1 — 2026-05-07
#### New Features
- **Set Defaults Dialog** — Edit `isDefault`, `expiration`, `unlimitedExpiration`, and `unlimitedLicenses` on accounts/sites/groups in the backup file before restoring
- **Default Site Override** — When restoring a site marked as default, detects existing default sites and prompts to override (with rename)
- **Smart Site Resolution** — When a site name doesn't match on the destination, detects broken/zombie sites (404), offers to map to the existing default site instead of failing
- **Live Restore Progress** — Shows step-by-step detail during resolve (`finding account…`, `looking up site…`) and element restore (`restoring star (12/566)…`)
- **Connection Validation** — Backup now verifies the console connection before starting; clear error on invalid/expired token
- **Auto-open Reports** — Exported HTML/Excel reports open automatically instead of showing a popup link

#### Fixes
- **0-node Backup Warning** — Backup with 0 nodes now shows a warning instead of a false success message
- **Shortened Error Messages** — Connection test and backup errors are truncated to prevent UI overflow
- **Site Update API** — Added `update_site` method for renaming sites and changing `isDefault` on the destination

### v1.0.1 — 2026-05-06
- Fixed sidebar width, centered window on launch
- Fixed Windows help button rendering
- Fixed paste button text
- Build improvements: xattr quarantine removal, auto-DMG creation

### v1.0.0 — 2026-05-06
- Initial release
- Full backup & restore for 26 element types
- Dual console connections with paste-from-ticket
- Mangle rename, auto-create sites/groups
- SKU mismatch detection and auto-fix
- HTML/Excel/JSON report generation
- 14 operations pages (Agents, Threats, STAR, DV, Ranger, etc.)
- macOS & Windows builds via GitHub Actions

## License

This software is provided **AS IS**, free of charge, for use by SentinelOne employees and authorized partners.

---

<p align="center">
  <strong>Built with ❤️ by Ran Jacobi</strong><br>
  <strong>SentinelOne Professional Services Team</strong>

</p>
